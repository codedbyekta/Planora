"""
ml/train_model.py
------------------
Trains a personalized model that predicts ONE user's Focus Score from
their own validated behavioral history. Strictly per-user: this module
never sees more than one user's sessions in a single training call, and
enforces that with a runtime check (see train_and_evaluate).

INPUT FEATURES (X) -- see FEATURE_COLUMNS below for the canonical order,
which recommendation.py imports directly so prediction-time feature
vectors can never silently drift out of sync with training-time ones:
    hour_of_day               - 0-23, extracted from session start_time
    day_of_week                - 0=Monday ... 6=Sunday
    task_difficulty_encoded   - easy=0 / medium=1 / hard=2 (ordinal;
                                 defaults to "medium" if a session has no
                                 task/difficulty attached)
    session_duration           - total duration_minutes of the session
    active_ratio                - active_duration / (active_duration + idle_duration).
                                 If the session's idle time was reclassified
                                 as focused deep work, it's folded into
                                 "active" first (same rule as scoring.py).
                                 Defaults to 1.0 when idle tracking wasn't
                                 available at all (e.g. legacy sessions).
    pause_count                 - how many times the session was paused
    previous_focus              - this user's own focus_score from their
                                 immediately PRECEDING validated session
                                 (chronologically). The very first session
                                 in a user's history has no "previous" one,
                                 so it's backfilled with that user's own
                                 mean focus_score rather than dropped --
                                 losing an entire training row over one
                                 missing lag value isn't worth it, and 30
                                 sessions is already a thin dataset.

TARGET (y):
    focus_score                 - the 0-100 score already calculated by
                                 scoring.calculate_validated_focus_score()
                                 for that VALIDATED session. Only sessions
                                 with validation_status="valid" are ever
                                 used here -- see sessions_to_dataframe().

WHY RANDOM FOREST (default model):
    - Handles a mix of numeric and ordinal features without manual
      encoding tricks.
    - Not very sensitive to outliers (one unusual session doesn't skew it).
    - Gives feature_importances_, which is genuinely useful to show in an
      interview ("hour_of_day and previous_focus turned out to be the
      strongest predictors for this user").
    - Simple to explain: many small decision trees voting and averaging.
    We do NOT claim Random Forest is universally the best choice -- see
    MODEL_REGISTRY below, which exists specifically so a Gradient
    Boosting / XGBoost / time-series model can be swapped in and compared
    later without touching the training/evaluation plumbing.

DON'T ASSUME 30 SESSIONS = A RELIABLE MODEL:
    Reaching MIN_SESSIONS_TO_TRAIN only means we're willing to TRY
    training a model -- it doesn't mean the result is trustworthy. After
    training, we also score a naive per-hour historical-average baseline
    on the exact same held-out test rows and compare MAE. Only if the
    trained model actually beats that baseline do we consider it usable
    (meta["beats_baseline"]); recommendation.py checks this flag and
    falls back to the plain average if the model didn't earn its keep.

WHY NOT TRAIN ON EVERY REQUEST:
    Training takes a noticeable fraction of a second and a user's
    productivity pattern doesn't meaningfully change between two page
    loads a few minutes apart. recommendation.py decides when a cached
    model is stale; we train here, save the model to disk with joblib,
    and record a ModelVersion row in Postgres for lineage/metadata.

USAGE:
    Called automatically by recommendation.py when needed, OR run
    manually for all users:
        python ml/train_model.py
"""

import os
import json
import math
from datetime import datetime

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib

import models

MIN_SESSIONS_TO_TRAIN = 30  # below this, we always use the historical-average fallback instead.
# 30 is an initial prototype safeguard (per project spec), not a universal
# statistical requirement -- it's the point at which we consider there to
# be enough per-user validated history for a personalized model to beat a
# plain average. Only VALIDATED (validation_status="valid") sessions count
# toward this threshold -- see crud.get_valid_focus_sessions.

RETRAIN_THRESHOLD = 5  # retrain once a user has this many new validated sessions since
# the cached model's meta was last written. Single source of truth --
# ml/recommendation.py imports this instead of keeping its own copy.

FEATURE_VERSION = "v2_behavioral"  # bump this whenever FEATURE_COLUMNS changes shape/meaning

FEATURE_COLUMNS = [
    "hour_of_day",
    "day_of_week",
    "task_difficulty_encoded",
    "session_duration",
    "active_ratio",
    "pause_count",
    "previous_focus",
]

_DIFFICULTY_ENCODING = {"easy": 0, "medium": 1, "hard": 2}


# ---------- MODEL REGISTRY (keeps the algorithm swappable) ----------

def _build_random_forest() -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=50, max_depth=5, random_state=42)


MODEL_REGISTRY = {
    "random_forest": _build_random_forest,
    # Future candidates go here, e.g.:
    #   "gradient_boosting": lambda: GradientBoostingRegressor(...),
    #   "xgboost": lambda: XGBRegressor(...),
    # train_and_evaluate(..., model_type="gradient_boosting") is all
    # that's needed to compare one against another -- everything below
    # (data prep, evaluation, versioning) is model-agnostic.
}
DEFAULT_MODEL_TYPE = "random_forest"


MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(MODEL_DIR, exist_ok=True)


def _model_path(user_id: int) -> str:
    return os.path.join(MODEL_DIR, f"model_user_{user_id}.pkl")


def _meta_path(user_id: int) -> str:
    return os.path.join(MODEL_DIR, f"model_user_{user_id}_meta.json")


def sessions_to_dataframe(sessions) -> pd.DataFrame:
    """
    Turn a list of FocusSession ORM objects into a clean, feature-engineered
    pandas DataFrame. Only VALIDATED sessions (validation_status="valid")
    with a real focus_score are used -- a "pending" or "invalid" session
    never enters training or the typical-value calculations used for
    prediction.
    """
    rows = []
    for s in sessions:
        if s.validation_status != "valid" or s.focus_score is None:
            continue

        active = s.active_duration or 0
        idle = s.idle_duration or 0
        if s.idle_reclassified:
            active += idle
            idle = 0
        total = active + idle
        active_ratio = (active / total) if total > 0 else 1.0

        difficulty = (s.task_difficulty or "medium").lower()
        difficulty_encoded = _DIFFICULTY_ENCODING.get(difficulty, 1)

        rows.append({
            "start_time": s.start_time,
            "hour_of_day": s.start_time.hour,
            "day_of_week": s.start_time.weekday(),
            "task_difficulty_encoded": difficulty_encoded,
            "session_duration": s.duration_minutes or 0,
            "active_ratio": active_ratio,
            "pause_count": s.pause_count or 0,
            "focus_score": s.focus_score,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # previous_focus is a LAG feature -- it only makes sense in
    # chronological order, regardless of what order `sessions` arrived in.
    df = df.sort_values("start_time").reset_index(drop=True)
    df["previous_focus"] = df["focus_score"].shift(1)
    # The first session in the user's history has no predecessor. Rather
    # than drop that row (we can't afford to lose a sample out of a
    # dataset that's only just cleared 30), backfill it with this same
    # user's own mean focus_score -- a neutral, user-specific default,
    # not a global guess.
    df["previous_focus"] = df["previous_focus"].fillna(df["focus_score"].mean())
    return df


def _next_model_version(db, user_id: int) -> int:
    latest = (
        db.query(models.ModelVersion)
        .filter(models.ModelVersion.user_id == user_id)
        .order_by(models.ModelVersion.model_version.desc())
        .first()
    )
    return (latest.model_version + 1) if latest else 1


def _split(df: pd.DataFrame, X: pd.DataFrame, y: pd.Series, time_based_split: bool, test_size: float = 0.2):
    """
    Two interchangeable splitting strategies:
      - time_based_split=False (current default): plain random 80/20
        split, same as the original prototype.
      - time_based_split=True: chronological split -- train on the
        earliest (1-test_size) fraction of sessions, test on the most
        recent test_size fraction. This is the "right" way to validate
        behavioral/time-series data (never train on the future to
        predict the past), and the plumbing for it is here now so it
        can be switched on later without restructuring anything --
        we're just not defaulting to it yet, per current instructions.
    """
    if time_based_split:
        # df is already sorted ascending by start_time (see sessions_to_dataframe)
        split_idx = max(1, int(len(df) * (1 - test_size)))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
    return X_train, X_test, y_train, y_test


def train_and_evaluate(
    sessions,
    user_id: int,
    model_type: str = DEFAULT_MODEL_TYPE,
    time_based_split: bool = False,
):
    """
    PURE computation: trains a candidate model and evaluates it. Does NOT
    touch disk or the database, and does NOT decide whether to promote
    the result -- that decision belongs to ml/retrain_monitor.py, which
    is the only thing that may currently call this. (Historically, this
    function used to also persist and immediately activate its result;
    that's exactly the "automatically replace the active model" behavior
    Step 11 requires we stop doing, so promotion/persistence were moved
    out into their own step.)

    Returns (model, meta) -- meta has no "model_version" yet (that's
    assigned at persistence time, only for whichever model actually gets
    saved) and includes a "trained": False short-circuit dict as the
    first element of the tuple (model=None) if there isn't enough data.
    """
    # --- Strict per-user isolation guard ---
    # This is a hard runtime check, not just a convention: if the caller
    # ever accidentally passes another user's sessions in here (a bug
    # elsewhere in the app), we refuse to train rather than silently
    # mixing behavioral data across users.
    for s in sessions:
        if s.user_id != user_id:
            raise ValueError(
                f"Isolation violation: session {s.id} belongs to user {s.user_id}, "
                f"not user {user_id}. Refusing to train."
            )

    df = sessions_to_dataframe(sessions)

    if len(df) < MIN_SESSIONS_TO_TRAIN:
        return None, {"trained": False, "reason": "not_enough_data", "num_sessions": len(df)}

    df = df.dropna(subset=FEATURE_COLUMNS + ["focus_score"])
    if len(df) < MIN_SESSIONS_TO_TRAIN:
        return None, {"trained": False, "reason": "not_enough_clean_data", "num_sessions": len(df)}

    X = df[FEATURE_COLUMNS]
    y = df["focus_score"]

    X_train, X_test, y_train, y_test = _split(df, X, y, time_based_split)

    build_fn = MODEL_REGISTRY.get(model_type, MODEL_REGISTRY[DEFAULT_MODEL_TYPE])
    model = build_fn()
    model.fit(X_train, y_train)

    mae = rmse = r2 = None
    baseline_mae = None
    beats_baseline = None

    if len(X_test) > 0:
        predictions = model.predict(X_test)
        mae = float(mean_absolute_error(y_test, predictions))
        rmse = float(math.sqrt(mean_squared_error(y_test, predictions)))
        r2 = float(r2_score(y_test, predictions))

        # --- Naive baseline for comparison, on the SAME held-out rows ---
        # "Per-hour average focus, from the training set only" -- exactly
        # the same idea as ml/recommendation.py's fallback, just scored
        # against test data so we can honestly say whether the trained
        # model earned its keep.
        train_hour_means = (
            X_train.assign(focus_score=y_train.values)
            .groupby("hour_of_day")["focus_score"]
            .mean()
        )
        overall_train_mean = float(y_train.mean())
        baseline_predictions = X_test["hour_of_day"].map(train_hour_means).fillna(overall_train_mean)
        baseline_mae = float(mean_absolute_error(y_test, baseline_predictions))
        beats_baseline = mae < baseline_mae

    meta = {
        "trained": True,
        "trained_at": datetime.utcnow().isoformat(),
        "num_sessions": len(df),
        "model_type": model_type,
        "feature_version": FEATURE_VERSION,
        "time_based_split": time_based_split,
        "mean_focus_score": round(float(y.mean()), 2),
        "mae": round(mae, 3) if mae is not None else None,
        "rmse": round(rmse, 3) if rmse is not None else None,
        "r2_score": round(r2, 3) if r2 is not None else None,
        "baseline_mae": round(baseline_mae, 3) if baseline_mae is not None else None,
        "beats_baseline": beats_baseline,
        "feature_importances": dict(
            zip(FEATURE_COLUMNS, [round(float(x), 3) for x in model.feature_importances_])
        ),
    }
    return model, meta


def save_as_active(user_id: int, model, meta: dict) -> None:
    """Writes a model+meta to this user's ACTIVE path on disk (the only
    path load_model_and_meta() ever reads). Called ONLY after a
    promotion decision has already said yes -- see
    ml/retrain_monitor.retrain_and_promote(). meta["model_version"] must
    already be set by the caller before this is called."""
    joblib.dump(model, _model_path(user_id))
    with open(_meta_path(user_id), "w") as f:
        json.dump(meta, f, indent=2)


def load_model_and_meta(user_id: int):
    """Returns (model, meta) if a saved model exists for this user, else (None, None)."""
    model_path = _model_path(user_id)
    meta_path = _meta_path(user_id)
    if not os.path.exists(model_path) or not os.path.exists(meta_path):
        return None, None
    model = joblib.load(model_path)
    with open(meta_path) as f:
        meta = json.load(f)
    return model, meta


def typical_feature_frame(df_full: pd.DataFrame, observed_hours: list[int]) -> pd.DataFrame:
    """
    Builds a FEATURE_COLUMNS-shaped DataFrame for PREDICTION, one row per
    candidate hour_of_day, holding every other feature at a "typical"
    value for this user (mode for categorical-ish columns, median for
    continuous ones, most-recent for the previous_focus lag feature).

    This is the ONE place a future feature vector gets constructed, and
    both ml/recommendation.py (single best window) and ml/predict.py
    (full spread of candidate windows) call it -- so a prediction can
    never silently use a different column order or a different notion
    of "typical" depending on which endpoint asked for it.
    """
    typical_day = int(df_full["day_of_week"].mode().iloc[0])
    typical_difficulty = int(df_full["task_difficulty_encoded"].mode().iloc[0])
    typical_duration = float(df_full["session_duration"].median())
    typical_active_ratio = float(df_full["active_ratio"].median())
    typical_pauses = float(df_full["pause_count"].median())
    # Most recent validated focus_score -- the most honest "previous_focus"
    # to assume for a session that hasn't happened yet.
    typical_previous_focus = float(df_full.sort_values("start_time")["focus_score"].iloc[-1])

    return pd.DataFrame(
        [
            [h, typical_day, typical_difficulty, typical_duration, typical_active_ratio,
             typical_pauses, typical_previous_focus]
            for h in observed_hours
        ],
        columns=FEATURE_COLUMNS,
    )


if __name__ == "__main__":
    # Manual run: attempts a retrain+promotion cycle for every user who has
    # enough VALIDATED sessions. Deferred (local) import of retrain_monitor
    # to avoid a circular import at module load time (retrain_monitor
    # imports FROM this module).
    from database import SessionLocal
    from ml.retrain_monitor import retrain_and_promote

    db = SessionLocal()
    users = db.query(models.User).all()
    db.close()  # retrain_and_promote opens its own session per user
    for user in users:
        result = retrain_and_promote(user.id)
        print(f"User {user.id} ({user.email}): {result}")
