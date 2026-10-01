"""
Retraining monitor, drift detection, and model promotion (Step 11).
"""
import json
from datetime import datetime

import models
from tests.helpers import make_user, make_task, seed_validated_sessions, add_low_focus_sessions, DIFFICULTIES
from ml.train_model import load_model_and_meta, _model_path, _meta_path, RETRAIN_THRESHOLD
from ml.retrain_monitor import retrain_and_promote, check_drift, should_retrain, decide_promotion


def _bootstrap(db, email):
    user = make_user(db, email)
    tasks = [make_task(db, user.id, f"T{i}", d).id for i, d in enumerate(DIFFICULTIES)]
    seed_validated_sessions(db, user, tasks, count=45, start_date=datetime(2026, 8, 1))
    result = retrain_and_promote(user.id)
    assert result["promoted"] is True
    return user, tasks


def test_no_retrain_with_insufficient_new_data(db):
    user, _ = _bootstrap(db, "monitor_a@example.com")
    import crud
    sessions = crud.get_valid_focus_sessions(db, user.id, limit=1000)
    model, meta = load_model_and_meta(user.id)
    needed, reasons = should_retrain(model, sessions, meta)
    assert needed is False
    assert reasons == []


def test_retrain_trigger_fires_after_enough_new_sessions(db):
    user, tasks = _bootstrap(db, "monitor_b@example.com")
    seed_validated_sessions(db, user, [tasks[0]], count=RETRAIN_THRESHOLD + 1, start_date=datetime(2026, 10, 1))
    import crud
    sessions = crud.get_valid_focus_sessions(db, user.id, limit=1000)
    model, meta = load_model_and_meta(user.id)
    needed, reasons = should_retrain(model, sessions, meta)
    assert needed is True
    assert "new validated sessions accumulated" in reasons[0]


def test_worse_candidate_is_rejected_and_active_model_untouched(db):
    user, _ = _bootstrap(db, "monitor_c@example.com")
    model_path, meta_path = _model_path(user.id), _meta_path(user.id)
    with open(model_path, "rb") as f:
        original_model_bytes = f.read()

    _, meta = load_model_and_meta(user.id)
    # Force the active model to look implausibly good, so any real candidate looks worse
    json.dump(dict(meta, mae=0.001), open(meta_path, "w"))
    n_before = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user.id).count()

    result = retrain_and_promote(user.id)
    assert result["promoted"] is False

    with open(model_path, "rb") as f:
        assert f.read() == original_model_bytes  # model file on disk is untouched

    versions = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user.id).all()
    assert len(versions) == n_before + 1  # one new audit row added
    rejected = [v for v in versions if v.model_version == result["model_version"]][0]
    assert rejected.model_status == "rejected"
    active_rows = [v for v in versions if v.model_status == "active"]
    assert len(active_rows) == 1 and active_rows[0].model_version == 1  # original still active


def test_better_candidate_is_promoted_and_history_preserved(db):
    user, _ = _bootstrap(db, "monitor_d@example.com")
    _, meta = load_model_and_meta(user.id)
    # Force the active model to look terrible, so any real candidate looks better
    json.dump(dict(meta, mae=999.0), open(_meta_path(user.id), "w"))

    result = retrain_and_promote(user.id)
    assert result["promoted"] is True

    versions = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user.id).all()
    assert {v.model_version for v in versions} == {1, 2}  # nothing deleted
    assert [v.model_status for v in versions if v.model_version == 1] == ["retired"]
    assert [v.model_status for v in versions if v.model_version == 2] == ["active"]


def test_decide_promotion_rules_directly():
    active = {"mae": 5.0, "beats_baseline": True}
    assert decide_promotion({"trained": True, "mae": 3.0, "beats_baseline": True}, active)[0] is True
    assert decide_promotion({"trained": True, "mae": 6.0, "beats_baseline": True}, active)[0] is False
    assert decide_promotion({"trained": True, "mae": 5.3, "beats_baseline": True}, active)[0] is True  # within tolerance
    assert decide_promotion({"trained": True, "mae": 2.0, "beats_baseline": False}, active)[0] is False
    assert decide_promotion({"trained": False}, active)[0] is False
    assert decide_promotion({"trained": True, "mae": 3.0, "beats_baseline": True}, None)[0] is True  # bootstrap


def test_drift_requires_enough_recent_observations_not_a_single_session(db):
    user, tasks = _bootstrap(db, "monitor_e@example.com")
    _, meta = load_model_and_meta(user.id)
    import crud

    add_low_focus_sessions(db, user, tasks[0], count=1, score=1.0, start_date=datetime(2026, 11, 1))
    sessions = crud.get_valid_focus_sessions(db, user.id, limit=1000)
    drifted, _ = check_drift(sessions, meta)
    assert drifted is False  # one extreme outlier is not enough

    add_low_focus_sessions(db, user, tasks[0], count=RETRAIN_THRESHOLD, score=5.0, start_date=datetime(2026, 11, 5))
    sessions = crud.get_valid_focus_sessions(db, user.id, limit=1000)
    drifted, msg = check_drift(sessions, meta)
    assert drifted is True
    assert "lower" in msg


def test_retraining_never_touches_another_users_models(db):
    user1, _ = _bootstrap(db, "monitor_iso1@example.com")
    user2, _ = _bootstrap(db, "monitor_iso2@example.com")
    n2_before = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user2.id).count()

    retrain_and_promote(user1.id)

    n2_after = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user2.id).count()
    assert n2_before == n2_after
