"""
ml/predict.py
--------------
Generates predicted Focus Scores for MULTIPLE candidate future time
windows (backs GET /predictions), e.g.:

    09:00-10:00 -> predicted focus 76.9
    10:00-11:00 -> predicted focus 71.2
    14:00-15:00 -> predicted focus 41.0

This is distinct from ml/recommendation.py, which picks a single best
2-hour window for GET /recommendations and /tasks/{id}/suggested-time.
Both read from the exact same feature pipeline in train_model.py
(sessions_to_dataframe, typical_feature_frame, FEATURE_COLUMNS) -- there
is no separate feature-building logic here, so the two endpoints can
never disagree about how a candidate hour's feature vector is built.

SCALE NOTE: predictions are on the same 0-100 Focus Score scale used
everywhere else in the app (scoring.py, recommendations, ModelVersion),
not the 0-5 scale from the original spec's illustrative example --
staying on one consistent scale throughout the app matters more than
matching that example number-for-number.

Only VALIDATED sessions (validation_status="valid") ever inform the
candidate hours or the "typical" feature values -- see
train_model.sessions_to_dataframe.

THIS MODULE NEVER TRAINS A MODEL. It only reads whatever model is
already cached on disk via load_model_and_meta(). Deciding when to
(re)train is ml/recommendation.py's job (triggered from GET
/recommendations) -- keeping that trigger in one place avoids two
endpoints independently deciding to retrain and racing each other, and
keeps this step scoped to prediction generation, not training policy.
A practical side effect: if a user has just crossed the 30-session mark
but hasn't hit GET /recommendations yet, GET /predictions will still
show baseline predictions until a model has actually been trained
somewhere. That's a known, temporary gap -- not a bug.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from ml.train_model import (
    MIN_SESSIONS_TO_TRAIN,
    load_model_and_meta,
    sessions_to_dataframe,
    typical_feature_frame,
)


def _valid_sessions(sessions):
    return [s for s in sessions if s.validation_status == "valid" and s.focus_score is not None]


def _next_occurrence(hour: int, now: datetime) -> datetime:
    """
    The next upcoming date/time this hour occurs at: today if that hour
    hasn't passed yet, otherwise tomorrow. Mirrors the same "is this
    hour still ahead of us today" logic routes/tasks.py already uses
    for /suggested-time, so a given hour resolves to the same kind of
    concrete slot regardless of which endpoint is asking.
    """
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _baseline_predictions(scored_sessions, now: datetime) -> list[dict]:
    """
    Historical-average predictions: this user's own mean focus_score per
    observed hour of day -- the exact same calculation
    ml/recommendation.py's fallback uses, just returned as a full spread
    across every observed hour instead of only the single best one.
    """
    if not scored_sessions:
        return []

    hour_scores = defaultdict(list)
    for s in scored_sessions:
        hour_scores[s.start_time.hour].append(s.focus_score)

    predictions = []
    for hour in sorted(hour_scores):
        avg_score = round(sum(hour_scores[hour]) / len(hour_scores[hour]), 1)
        window_start = _next_occurrence(hour, now)
        predictions.append({
            "window_start": window_start,
            "window_end": window_start + timedelta(hours=1),
            "predicted_focus_score": avg_score,
            "source": "fallback",
            "model_version": None,
        })
    return predictions


def generate_predictions(sessions, user_id: int, now: datetime = None) -> list[dict]:
    """
    Main entry point. Pure computation -- does NOT write to the
    database; the caller (routes/predictions.py) persists the result
    via crud.save_predictions. Returns a list of:
        {window_start, window_end, predicted_focus_score, source, model_version}

    Decision logic:
        < MIN_SESSIONS_TO_TRAIN validated sessions
            -> historical-average baseline, always.
        >= MIN_SESSIONS_TO_TRAIN, but no trained model exists yet, or
           the cached model's own held-out evaluation didn't beat the
           naive per-hour baseline (beats_baseline is not True)
            -> historical-average baseline (same as above) -- reaching
               the session threshold is not treated as proof the model
               is reliable.
        >= MIN_SESSIONS_TO_TRAIN AND a cached model exists AND
           beats_baseline is True
            -> personalized model predictions, one per observed hour.
    """
    now = now or datetime.utcnow()
    scored = _valid_sessions(sessions)

    if len(scored) < MIN_SESSIONS_TO_TRAIN:
        return _baseline_predictions(scored, now)

    model, meta = load_model_and_meta(user_id)
    if model is None or meta is None or not meta.get("trained") or meta.get("beats_baseline") is not True:
        return _baseline_predictions(scored, now)

    df_full = sessions_to_dataframe(scored)
    # Only predict for hours this user has actually logged validated
    # sessions in -- same "don't extrapolate to an unseen hour" rule
    # used throughout the ML pipeline.
    observed_hours = sorted(df_full["hour_of_day"].unique().tolist())

    X_pred = typical_feature_frame(df_full, observed_hours)
    predicted_scores = model.predict(X_pred)

    predictions = []
    for hour, score in zip(observed_hours, predicted_scores):
        window_start = _next_occurrence(hour, now)
        predictions.append({
            "window_start": window_start,
            "window_end": window_start + timedelta(hours=1),
            "predicted_focus_score": round(float(score), 1),
            "source": "ml_model",
            "model_version": meta.get("model_version"),
        })
    return predictions
