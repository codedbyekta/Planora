"""
ml/recommendation.py
---------------------
Turns a user's focus session history into a plain-English recommendation
like: "Your predicted focus is highest between 9 AM and 11 AM."

Flow:
    Historical Sessions (validated only)
        -> not enough data?          -> historical-average fallback
        -> enough data, model
           doesn't beat a naive
           per-hour average?         -> historical-average fallback
                                         (see train_model.meta["beats_baseline"])
        -> enough data AND model
           beats the baseline?       -> load personalized model ->
                                         predict focus_score for every
                                         OBSERVED hour of the day ->
                                         pick the best 2-hour window
        -> convert into a recommendation dict

RETRAINING (Step 11 -- see ml/retrain_monitor.py for the actual policy):
    This module never decides FOR ITSELF whether to retrain or whether a
    freshly retrained candidate should replace the active model --
    ml.retrain_monitor owns both of those calls. What happens here is
    just:
      - No active model yet (bootstrap): call retrain_and_promote()
        SYNCHRONOUSLY, so a user who just crossed MIN_SESSIONS_TO_TRAIN
        sees an ML-backed recommendation on this same request.
      - An active model already exists: ask should_retrain() whether
        there's a reason to. If so, hand retrain_and_promote() to
        FastAPI's BackgroundTasks (when available) so THIS request isn't
        blocked -- it keeps using the current active model/meta
        regardless of what the background retrain decides.
"""

from collections import defaultdict

import numpy as np
import pandas as pd

from ml.train_model import (
    MIN_SESSIONS_TO_TRAIN,
    FEATURE_COLUMNS,
    load_model_and_meta,
    sessions_to_dataframe,
    typical_feature_frame,
)
from ml.retrain_monitor import (
    should_retrain, retrain_and_promote, bootstrap_allowed, last_attempt_sample_count,
)


def _format_hour(hour: int) -> str:
    period = "AM" if hour < 12 else "PM"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour} {period}"


def _valid_sessions(sessions):
    return [s for s in sessions if s.validation_status == "valid" and s.focus_score is not None]


def _fallback_recommendation(sessions, note_override: str | None = None) -> dict:
    """
    Simple, transparent fallback: group VALIDATED sessions by hour of day,
    average the focus_score in each hour, and recommend the single
    best-performing hour (extended to a 2-hour window for readability).
    No ML involved - just arithmetic averages, on purpose.

    Only sessions with validation_status="valid" are counted. A session
    that's still awaiting feedback (validation_status="pending") or that
    got thrown out as too short/accidental ("invalid") never contributes
    to the average -- an unvalidated or accidental session isn't a
    trustworthy read on when the person actually focuses well.
    """
    scored = _valid_sessions(sessions)

    if not scored:
        return {
            "recommended_start_hour": None,
            "recommended_end_hour": None,
            "reason": "No completed focus sessions yet. Complete a few sessions to unlock recommendations.",
            "source": "fallback",
        }

    hour_scores = defaultdict(list)
    for s in scored:
        hour_scores[s.start_time.hour].append(s.focus_score)

    hour_averages = {h: sum(v) / len(v) for h, v in hour_scores.items()}
    best_hour = max(hour_averages, key=hour_averages.get)
    end_hour = (best_hour + 2) % 24

    if note_override:
        note = note_override
    elif len(scored) < MIN_SESSIONS_TO_TRAIN:
        note = (
            f"Based on {len(scored)} session(s) so far — this gets more accurate "
            f"the more sessions you log (we switch to a full ML model at {MIN_SESSIONS_TO_TRAIN}+)."
        )
    else:
        note = f"Based on {len(scored)} historical sessions."

    return {
        "recommended_start_hour": best_hour,
        "recommended_end_hour": end_hour,
        "reason": (
            f"Your average focus score is highest around {_format_hour(best_hour)} "
            f"(avg {round(hour_averages[best_hour], 1)}/100). {note}"
        ),
        "source": "fallback",
    }


def _ml_recommendation(db, sessions, user_id: int, background_tasks=None) -> dict:
    """
    Uses the trained personalized model to predict focus_score for every
    OBSERVED hour of the day (holding the other features at "typical"
    values for this user), then recommends the 2-hour window with the
    highest predicted score. Falls back to the plain average if no
    usable model exists (see train_model.py / ml.retrain_monitor.py).
    """
    model, meta = load_model_and_meta(user_id)
    scored_sessions = _valid_sessions(sessions)

    if model is None or meta is None:
        # Bootstrap: no active model yet for this user at all. Handled
        # synchronously (see module docstring) so this request can
        # immediately reflect the result.
        if not bootstrap_allowed(db, user_id, len(scored_sessions)):
            # A previous attempt was rejected and fewer than RETRAIN_THRESHOLD
            # new validated sessions have arrived since -- don't retrain again.
            return _fallback_recommendation(
                sessions,
                note_override="A personalized model isn't reliable enough yet, so we're using the average for now.",
            )
        result = retrain_and_promote(user_id)
        if not result["promoted"]:
            note = (
                f"A personalized model was trained on your {result['meta'].get('num_sessions', 0)} "
                f"sessions, but {result['reason']}, so we're using the average instead for now."
            )
            return _fallback_recommendation(sessions, note_override=note)
        model, meta = load_model_and_meta(user_id)
    else:
        retrain_needed, reasons = should_retrain(
            model, scored_sessions, meta, last_attempt_sample_count(db, user_id)
        )
        if retrain_needed:
            if background_tasks is not None:
                # Don't block this request -- keep serving with the
                # CURRENT active model/meta while a candidate trains and
                # is evaluated in the background. See ml/retrain_monitor.py.
                background_tasks.add_task(retrain_and_promote, user_id)
            else:
                # No BackgroundTasks available from this caller (e.g. a
                # script) -- retrain synchronously rather than silently
                # never retraining at all.
                retrain_and_promote(user_id)
                model, meta = load_model_and_meta(user_id)

    if meta.get("beats_baseline") is not True:
        # The active model didn't outperform (or hasn't yet been shown to
        # outperform) a plain per-hour average on held-out data -- crossing
        # a session threshold is never treated as proof of reliability.
        note = (
            f"A personalized model was trained on your {meta['num_sessions']} sessions "
            f"(MAE {meta.get('mae')}), but it didn't outperform a simple historical "
            f"average on held-out data yet, so we're using the average instead for now."
        )
        return _fallback_recommendation(sessions, note_override=note)

    df_full = sessions_to_dataframe(scored_sessions)

    # IMPORTANT: only predict for hours the user has actually logged sessions in.
    # A model can't meaningfully extrapolate to an hour it never saw in
    # training - restricting to observed hours keeps the recommendation honest.
    observed_hours = sorted(df_full["hour_of_day"].unique().tolist())

    X_pred = typical_feature_frame(df_full, observed_hours)
    predicted_scores = model.predict(X_pred)

    best_hour = int(observed_hours[int(np.argmax(predicted_scores))])
    end_hour = (best_hour + 2) % 24
    best_score = round(float(predicted_scores.max()), 1)

    metric_note = f" (MAE {meta['mae']} vs. baseline {meta.get('baseline_mae')})" if meta.get("mae") is not None else ""

    return {
        "recommended_start_hour": best_hour,
        "recommended_end_hour": end_hour,
        "reason": (
            f"Based on a personalized model trained on your {meta['num_sessions']} validated sessions, "
            f"your predicted focus score is highest around {_format_hour(best_hour)} "
            f"(predicted {best_score}/100){metric_note}."
        ),
        "source": "ml_model",
    }


def get_recommendation(db, sessions, user_id: int, background_tasks=None) -> dict:
    """
    Main entry point. Decides which strategy to use based on how much
    VALIDATED (validation_status="valid") session history the user has.
    background_tasks (a FastAPI BackgroundTasks instance, optional) lets
    an ongoing (non-bootstrap) retrain run without blocking this request
    -- see ml/retrain_monitor.py and _ml_recommendation above.
    """
    scored_count = len(_valid_sessions(sessions))
    if scored_count < MIN_SESSIONS_TO_TRAIN:
        return _fallback_recommendation(sessions)
    return _ml_recommendation(db, sessions, user_id, background_tasks)
