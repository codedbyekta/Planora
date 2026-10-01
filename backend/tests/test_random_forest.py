"""
Random Forest personalization (Step 7): feature set, per-user isolation,
MAE/RMSE/baseline comparison, model_versions bookkeeping.
"""
from datetime import datetime

import models
from tests.helpers import make_user, make_task, seed_validated_sessions, DIFFICULTIES
from ml.train_model import load_model_and_meta, FEATURE_COLUMNS, MIN_SESSIONS_TO_TRAIN
from ml.retrain_monitor import retrain_and_promote


def test_below_threshold_stays_on_fallback(client, db, make_authed_user):
    user_id, h = make_authed_user("rf_small")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    tasks = [make_task(db, user.id, f"T{i}", d).id for i, d in enumerate(DIFFICULTIES)]
    seed_validated_sessions(db, user, tasks, count=12, start_date=datetime(2026, 8, 1))

    r = client.get("/recommendations", headers=h)
    assert r.json()["source"] == "fallback"
    model, meta = load_model_and_meta(user.id)
    assert model is None and meta is None  # never trained -- below MIN_SESSIONS_TO_TRAIN


def test_training_at_threshold_produces_evaluated_model(db):
    user = make_user(db, "rf_full@example.com")
    tasks = [make_task(db, user.id, f"T{i}", d).id for i, d in enumerate(DIFFICULTIES)]
    seed_validated_sessions(db, user, tasks, count=45, start_date=datetime(2026, 8, 1))
    assert 45 >= MIN_SESSIONS_TO_TRAIN

    result = retrain_and_promote(user.id)
    assert result["meta"]["trained"] is True
    assert result["promoted"] is True  # no active model existed yet -> bootstrap promotion

    model, meta = load_model_and_meta(user.id)
    assert model is not None
    assert meta["mae"] is not None and meta["rmse"] is not None and meta["r2_score"] is not None
    assert meta["baseline_mae"] is not None
    assert isinstance(meta["beats_baseline"], bool)
    assert set(meta["feature_importances"].keys()) == set(FEATURE_COLUMNS)

    versions = db.query(models.ModelVersion).filter(models.ModelVersion.user_id == user.id).all()
    assert len(versions) == 1
    assert versions[0].model_status == "active"
    assert versions[0].training_sample_count == 45
    assert versions[0].feature_version == meta["feature_version"]


def test_isolation_guard_refuses_cross_user_training(db):
    from ml.train_model import train_and_evaluate
    user_a = make_user(db, "rf_iso_a@example.com")
    user_b = make_user(db, "rf_iso_b@example.com")
    tasks_b = [make_task(db, user_b.id, "T", "medium").id]
    seed_validated_sessions(db, user_b, tasks_b, count=45, start_date=datetime(2026, 8, 1))

    import crud
    sessions_b = crud.get_valid_focus_sessions(db, user_b.id, limit=1000)
    try:
        train_and_evaluate(sessions_b, user_a.id)  # deliberately wrong user_id
        assert False, "expected ValueError for cross-user training"
    except ValueError:
        pass

    model_a, meta_a = load_model_and_meta(user_a.id)
    assert model_a is None and meta_a is None  # user A was never touched
