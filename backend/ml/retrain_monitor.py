"""
ml/retrain_monitor.py
----------------------
Decides WHEN a user's model should be retrained, and whether a freshly
retrained candidate actually deserves to replace the currently active
model. This is the one place that owns both decisions -- ml/predict.py
and ml/recommendation.py never make either decision themselves.

MONITORING (should we even bother retraining?):
    Retraining is considered only once at least RETRAIN_THRESHOLD new
    VALIDATED sessions have accumulated since the active model's own
    training snapshot (meta["num_sessions"]) -- the same count-based
    staleness check already used since Step 7/8, now centralized here.
    We do NOT retrain on every session, and crossing this threshold is
    not a guarantee the result will be used -- see promotion, below.

    Two additional DIAGNOSTIC checks run only once the volume trigger has
    already fired (there's no point running them on a handful of
    sessions), and are recorded as extra reasons/context on the retrain
    event rather than separate triggers with their own thresholds -- once
    there's enough new data to justify training a candidate at all, these
    just explain WHY (drift, degradation, or plain routine accumulation):

      - DRIFT: has this user's recent validated focus behavior shifted
        meaningfully from what the active model was trained on? Compares
        the mean focus_score of the newest N validated sessions (N = the
        new-session count) against the training set's own mean
        (meta["mean_focus_score"]). A single unusual session can never
        trigger this by itself -- it only runs once >= RETRAIN_THRESHOLD
        new sessions exist, and even then the comparison is an average
        over all of them, not any one point.
      - PERFORMANCE DEGRADATION: replays the CURRENTLY ACTIVE model
        against those same new sessions' real feature vectors and
        compares its error (MAE) against the MAE it posted during its
        own training-time evaluation.

PROMOTION (does the new candidate actually replace the old one?):
    A new model NEVER automatically replaces the active one. It's
    promoted only if:
      1. It trained successfully and beat the naive per-hour baseline on
         its own held-out data (meta["beats_baseline"] is True) -- same
         bar as first-time training in Step 7.
      2. There is no active model yet (bootstrap case), OR its MAE is
         better than or within PROMOTION_STABILITY_TOLERANCE of the
         currently active model's MAE ("better or acceptably stable").
    Otherwise the candidate is still recorded (see audit history, below)
    with model_status="rejected", and the active model is left completely
    untouched.

AUDIT HISTORY:
    Every training attempt -- promoted or not -- gets its own
    ModelVersion row. An old "active" row is flipped to "retired" only at
    the moment a new candidate is actually promoted; nothing is ever
    deleted. This is "preserve previous model_versions" in practice: the
    full lineage of what was tried and why is queryable later.

BACKGROUND EXECUTION:
    retrain_and_promote() does real work (training + evaluation) and is
    meant to be handed to FastAPI's BackgroundTasks by the caller
    (ml/recommendation.py / routes/recommendations.py) so an ordinary
    GET /recommendations request is never blocked by a retrain -- the
    request being served right now just keeps using whatever's currently
    active. The ONE exception is bootstrap (no active model exists yet):
    ml/recommendation.py still calls this synchronously in that case,
    exactly as Step 7/8 did, so a user crossing the 30-session threshold
    sees ML-backed recommendations on that same request instead of
    waiting on a background job with no visible result yet.

    No Celery/Redis or other new infrastructure -- FastAPI's built-in
    BackgroundTasks is enough for a prototype at this scale, and this
    function opens its OWN database session rather than reusing the
    request's (which may already be closed by the time a background task
    actually runs).
"""

from datetime import datetime

from database import SessionLocal
import models
import crud
from ml.train_model import (
    RETRAIN_THRESHOLD,
    FEATURE_COLUMNS,
    train_and_evaluate,
    save_as_active,
    load_model_and_meta,
    sessions_to_dataframe,
)

MIN_RECENT_FOR_DRIFT = RETRAIN_THRESHOLD  # reuse the same "enough new evidence" bar
DRIFT_MEAN_SHIFT_THRESHOLD = 15.0  # focus_score points, on the 0-100 scale
PERFORMANCE_DEGRADATION_FACTOR = 1.5  # recent MAE > 1.5x training-time MAE gets flagged
PROMOTION_STABILITY_TOLERANCE = 0.5  # candidate MAE can be this much worse and still be "stable enough"


def _new_session_count(valid_sessions, meta: dict) -> int:
    return len(valid_sessions) - meta.get("num_sessions", 0)


def last_attempt_sample_count(db, user_id: int) -> int | None:
    """
    Validated-session count at this user's most recent training ATTEMPT
    (any status: active, retired or rejected), read from model_versions.
    Without this, a rejected candidate would leave the active model's own
    snapshot unchanged, so "new sessions since training" would stay above
    the threshold forever and every request would retrain again. Anchoring
    the volume trigger to the last attempt means a rejection is followed by
    another RETRAIN_THRESHOLD genuinely new sessions before the next try.
    """
    latest = (
        db.query(models.ModelVersion)
        .filter(models.ModelVersion.user_id == user_id)
        .order_by(models.ModelVersion.model_version.desc())
        .first()
    )
    return latest.training_sample_count if latest else None


def bootstrap_allowed(db, user_id: int, valid_count: int) -> bool:
    """No active model yet: train if never attempted, or if a prior attempt
    was rejected and RETRAIN_THRESHOLD new validated sessions have arrived."""
    last = last_attempt_sample_count(db, user_id)
    return last is None or (valid_count - last) >= RETRAIN_THRESHOLD


def _recent_sessions(valid_sessions, n: int):
    """The n most recently started validated sessions (chronological tail)."""
    return sorted(valid_sessions, key=lambda s: s.start_time)[-n:] if n > 0 else []


def check_drift(valid_sessions, meta: dict) -> tuple[bool, str | None]:
    new_count = _new_session_count(valid_sessions, meta)
    historical_mean = meta.get("mean_focus_score")
    if new_count < MIN_RECENT_FOR_DRIFT or historical_mean is None:
        return False, None

    recent = _recent_sessions(valid_sessions, new_count)
    recent_mean = sum(s.focus_score for s in recent) / len(recent)
    shift = recent_mean - historical_mean
    if abs(shift) >= DRIFT_MEAN_SHIFT_THRESHOLD:
        direction = "higher" if shift > 0 else "lower"
        return True, (
            f"recent average focus ({round(recent_mean, 1)}) over the last {new_count} validated "
            f"sessions is notably {direction} than this model's training-time average ({historical_mean})"
        )
    return False, None


def check_performance_degradation(model, valid_sessions, meta: dict) -> tuple[bool, str | None]:
    from sklearn.metrics import mean_absolute_error

    new_count = _new_session_count(valid_sessions, meta)
    training_mae = meta.get("mae")
    if new_count < MIN_RECENT_FOR_DRIFT or training_mae is None or model is None:
        return False, None

    recent = _recent_sessions(valid_sessions, new_count)
    df = sessions_to_dataframe(recent)
    if df.empty:
        return False, None
    df = df.dropna(subset=FEATURE_COLUMNS + ["focus_score"])
    if df.empty:
        return False, None

    predictions = model.predict(df[FEATURE_COLUMNS])
    recent_mae = float(mean_absolute_error(df["focus_score"], predictions))
    if training_mae > 0 and recent_mae > training_mae * PERFORMANCE_DEGRADATION_FACTOR:
        return True, (
            f"the active model's error on its {new_count} most recent sessions "
            f"(MAE {round(recent_mae, 2)}) is notably worse than its training-time MAE ({training_mae})"
        )
    return False, None


def should_retrain(
    model, valid_sessions, meta: dict, last_attempt_count: int | None = None
) -> tuple[bool, list[str]]:
    """Returns (should_retrain, reasons). reasons is non-empty iff should_retrain is True.
    last_attempt_count (see last_attempt_sample_count) anchors the volume
    trigger to the most recent attempt, so a rejected candidate is not
    retried until enough NEW evidence has accumulated after it."""
    new_count = _new_session_count(valid_sessions, meta)
    since_attempt = len(valid_sessions) - max(meta.get("num_sessions", 0), last_attempt_count or 0)
    reasons = []
    if since_attempt >= RETRAIN_THRESHOLD and new_count >= RETRAIN_THRESHOLD:
        reasons.append(f"{new_count} new validated sessions accumulated since the active model was trained")

        drifted, drift_reason = check_drift(valid_sessions, meta)
        if drifted:
            reasons.append(f"drift detected: {drift_reason}")

        degraded, perf_reason = check_performance_degradation(model, valid_sessions, meta)
        if degraded:
            reasons.append(f"performance degradation detected: {perf_reason}")

    return (len(reasons) > 0), reasons


def _next_model_version(db, user_id: int) -> int:
    latest = (
        db.query(models.ModelVersion)
        .filter(models.ModelVersion.user_id == user_id)
        .order_by(models.ModelVersion.model_version.desc())
        .first()
    )
    return (latest.model_version + 1) if latest else 1


def decide_promotion(candidate_meta: dict, active_meta: dict | None) -> tuple[bool, str]:
    if not candidate_meta.get("trained"):
        return False, "candidate failed to train (insufficient clean data)"
    if candidate_meta.get("beats_baseline") is not True:
        return False, "candidate did not beat the naive historical-average baseline on held-out data"
    if active_meta is None:
        return True, "no active model exists yet -- promoting the first successfully trained model"

    candidate_mae = candidate_meta.get("mae")
    active_mae = active_meta.get("mae")
    if candidate_mae is None or active_mae is None:
        return False, "missing MAE for one side of the comparison -- keeping the current active model"

    if candidate_mae <= active_mae + PROMOTION_STABILITY_TOLERANCE:
        return True, f"candidate MAE {candidate_mae} is better than or acceptably close to active MAE {active_mae}"
    return False, f"candidate MAE {candidate_mae} is worse than active MAE {active_mae} beyond the stability tolerance"


def retrain_and_promote(user_id: int) -> dict:
    """
    Full retrain-evaluate-promote cycle for ONE user. Opens its own DB
    session (safe to call from a FastAPI BackgroundTask, after the
    original request's session may already be closed, or from a plain
    script). Sessions are fetched strictly by user_id -- never touches
    any other user's data.
    """
    db = SessionLocal()
    try:
        sessions = crud.get_valid_focus_sessions(db, user_id, limit=1000)
        _, active_meta = load_model_and_meta(user_id)
        candidate_model, candidate_meta = train_and_evaluate(sessions, user_id)

        promote, reason = decide_promotion(candidate_meta, active_meta)
        model_version = _next_model_version(db, user_id)
        candidate_meta["model_version"] = model_version
        candidate_meta["promotion_reason"] = reason

        if promote:
            db.query(models.ModelVersion).filter(
                models.ModelVersion.user_id == user_id, models.ModelVersion.model_status == "active"
            ).update({"model_status": "retired"})
            save_as_active(user_id, candidate_model, candidate_meta)
            status = "active"
        else:
            status = "rejected"

        db.add(models.ModelVersion(
            user_id=user_id,
            model_version=model_version,
            trained_at=datetime.utcnow(),
            training_sample_count=candidate_meta.get("num_sessions", 0),
            validation_metric=candidate_meta.get("mae"),
            model_status=status,
            feature_version=candidate_meta.get("feature_version", "unknown"),
        ))
        db.commit()

        return {"promoted": promote, "reason": reason, "model_version": model_version, "meta": candidate_meta}
    finally:
        db.close()
