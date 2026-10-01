"""
crud.py
-------
Database read/write functions ("CRUD" = Create, Read, Update, Delete).
Routes call these instead of writing raw queries inline, so the
query logic lives in one place.

Phase 1 only includes user-related functions. Task/session/etc.
CRUD functions get added here in later phases.
"""

from sqlalchemy.orm import Session
from datetime import datetime
import models
import schemas
from auth import hash_password
from scoring import calculate_focus_score, calculate_validated_focus_score, MIN_VALID_SESSION_MINUTES


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(models.User.email == email).first()


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    db_user = models.User(
        name=user.name,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# ---------- TASKS ----------
# Every function below takes user_id and filters by it, so a user
# can only ever read/edit/delete their OWN tasks.

def get_tasks(db: Session, user_id: int) -> list[models.Task]:
    return (
        db.query(models.Task)
        .filter(models.Task.user_id == user_id)
        .order_by(models.Task.deadline.asc().nulls_last())
        .all()
    )


def get_task(db: Session, user_id: int, task_id: int) -> models.Task | None:
    return (
        db.query(models.Task)
        .filter(models.Task.id == task_id, models.Task.user_id == user_id)
        .first()
    )


def create_task(db: Session, user_id: int, task: schemas.TaskCreate) -> models.Task:
    task_data = task.model_dump()
    # remaining_duration is server-managed (see schemas.TaskOut) -- it
    # starts equal to estimated_duration and is decremented as sessions
    # complete or get interrupted (see _end_session in this file).
    db_task = models.Task(user_id=user_id, remaining_duration=task_data["estimated_duration"], **task_data)
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def get_schedulable_tasks(db: Session, user_id: int) -> list[models.Task]:
    """
    Open (not-yet-completed) tasks for this user -- used by the Task x
    Focus scheduler (ml/schedule.py). Filtered by user_id like every
    other task query, so a user's schedule can never include another
    user's tasks.
    """
    return (
        db.query(models.Task)
        .filter(models.Task.user_id == user_id, models.Task.completed == False)  # noqa: E712
        .all()
    )


def update_task(db: Session, db_task: models.Task, task_update: schemas.TaskUpdate) -> models.Task:
    # Only overwrite fields that were actually provided in the request
    update_data = task_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.commit()
    db.refresh(db_task)
    return db_task


def delete_task(db: Session, db_task: models.Task) -> None:
    db.delete(db_task)
    db.commit()


# ---------- FOCUS SESSIONS ----------

def create_focus_session(
    db: Session, user_id: int, session: schemas.FocusSessionCreate
) -> models.FocusSession:
    """LEGACY path: unchanged behavior, backs the one-shot POST /sessions
    endpoint. Immediately scored and marked VALID, exactly as before --
    this is what "preserve existing session/timer functionality" means
    in practice while the new validation flow (below) is rolled out."""
    planned = session.planned_duration_minutes or session.duration_minutes
    score = calculate_focus_score(
        planned_duration_minutes=planned,
        actual_duration_minutes=session.duration_minutes,
        completed_task=session.completed_task,
    )

    db_session = models.FocusSession(
        user_id=user_id,
        task_id=session.task_id,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_minutes=session.duration_minutes,
        completed_task=session.completed_task,
        focus_score=score,
        validation_status="valid",
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)

    if db_session.task_id:
        # Same shared rule the new session lifecycle uses (_apply_task_progress):
        # completing the task zeroes remaining_duration; otherwise the actual
        # worked minutes are subtracted. The legacy endpoint has no separate
        # active_duration tracking, so duration_minutes IS the best available
        # "worked" signal here -- this was previously only handled for the
        # completed_task=True case, silently leaving remaining_duration
        # unchanged for a partial legacy session (a real gap, fixed here).
        _apply_task_progress(
            db, user_id, db_session.task_id,
            worked_minutes=session.duration_minutes, completed_task=session.completed_task,
        )

    return db_session


# ---------- SESSION LIFECYCLE (new session flow) ----------

def get_session(db: Session, user_id: int, session_id: int) -> models.FocusSession | None:
    return (
        db.query(models.FocusSession)
        .filter(models.FocusSession.id == session_id, models.FocusSession.user_id == user_id)
        .first()
    )


def start_session(db: Session, user_id: int, payload: schemas.SessionStart) -> models.FocusSession:
    task_difficulty = None
    if payload.task_id:
        task = get_task(db, user_id, payload.task_id)
        if task:
            task_difficulty = task.difficulty
            if task.status == "pending":
                task.status = "in_progress"
                db.commit()

    db_session = models.FocusSession(
        user_id=user_id,
        task_id=payload.task_id,
        start_time=datetime.utcnow(),
        end_time=None,
        duration_minutes=None,
        active_duration=0,
        idle_duration=0,
        pause_count=0,
        task_difficulty=task_difficulty,
        validation_status="pending",
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


def record_activity(
    db: Session, db_session: models.FocusSession, ping: schemas.SessionActivityPing
) -> models.FocusSession:
    """Applies one aggregated activity ping. Converts the reported seconds
    into whole minutes accumulated on the session -- we deliberately do NOT
    store the raw per-event stream, only the running aggregate."""
    added_active_minutes = ping.active_seconds / 60
    added_idle_minutes = ping.idle_seconds / 60

    db_session.active_duration = round((db_session.active_duration or 0) + added_active_minutes)
    db_session.idle_duration = round((db_session.idle_duration or 0) + added_idle_minutes)
    db.commit()
    db.refresh(db_session)
    return db_session


def record_pause(db: Session, db_session: models.FocusSession) -> models.FocusSession:
    db_session.pause_count = (db_session.pause_count or 0) + 1
    db.commit()
    db.refresh(db_session)
    return db_session


def record_resume(db: Session, db_session: models.FocusSession) -> models.FocusSession:
    # No state change needed beyond confirming the session is still open --
    # pause_count already captured the pause itself. Kept as a real endpoint
    # (rather than a no-op the client skips) so the pause/resume pair is
    # explicit in the API, matching the spec's endpoint list.
    return db_session


def _apply_task_progress(
    db: Session, user_id: int, task_id: int, worked_minutes: float, completed_task: bool, interrupted: bool = False
) -> None:
    """
    Shared task-progress update, used by BOTH the legacy one-shot
    `POST /sessions` endpoint and the new session lifecycle's
    _end_session() -- so a task's remaining_duration/status is kept
    consistent no matter which session flow produced the update.

    Rule (same either way): completing the task zeroes remaining_duration;
    otherwise only the actual worked minutes are subtracted (never a
    session's whole wall-clock length), so an interrupted or partial
    session still leaves an honest, reduced remaining_duration behind --
    this is what keeps GET /schedule's task list accurate without either
    endpoint needing its own copy of this logic.
    """
    db_task = get_task(db, user_id, task_id)
    if not db_task:
        return
    if completed_task:
        db_task.completed = True
        db_task.status = "completed"
        db_task.remaining_duration = 0
    else:
        current_remaining = db_task.remaining_duration if db_task.remaining_duration is not None else db_task.estimated_duration
        db_task.remaining_duration = max(0, current_remaining - worked_minutes)
        db_task.status = "in_progress" if interrupted else "pending"
    db.commit()


def _end_session(
    db: Session,
    db_session: models.FocusSession,
    *,
    interrupted: bool,
    interruption_reason: str | None,
    completed_task: bool,
) -> models.FocusSession:
    db_session.end_time = datetime.utcnow()
    elapsed_minutes = round((db_session.end_time - db_session.start_time).total_seconds() / 60)
    # NOTE: deliberately NOT floored at 1 -- a session that only lasted a few
    # seconds should be able to round down to 0 and get caught by
    # scoring.MIN_VALID_SESSION_MINUTES in submit_feedback(). Flooring this
    # at 1 would make that accidental-session guard unreachable.
    db_session.duration_minutes = elapsed_minutes
    db_session.interrupted = interrupted
    db_session.interruption_reason = interruption_reason
    db_session.completed_task = completed_task

    if db_session.task_id:
        # Preserve actual completed duration: only the real active work
        # counts against what's left on the task, not the whole wall-clock
        # window (matters most for interruptions).
        worked = db_session.active_duration or elapsed_minutes
        _apply_task_progress(
            db, db_session.user_id, db_session.task_id,
            worked_minutes=worked, completed_task=completed_task, interrupted=interrupted,
        )

    db.commit()
    db.refresh(db_session)
    return db_session


def interrupt_session(
    db: Session, db_session: models.FocusSession, payload: schemas.SessionInterrupt
) -> models.FocusSession:
    return _end_session(
        db,
        db_session,
        interrupted=True,
        interruption_reason=payload.interruption_reason,
        completed_task=False,
    )


def complete_session(
    db: Session, db_session: models.FocusSession, payload: schemas.SessionCompleteRequest
) -> models.FocusSession:
    return _end_session(
        db,
        db_session,
        interrupted=db_session.interrupted or False,
        interruption_reason=db_session.interruption_reason,
        completed_task=payload.completed_task,
    )


def submit_feedback(
    db: Session, db_session: models.FocusSession, feedback: schemas.SessionFeedback
) -> models.FocusSession:
    """
    Applies the end-of-session validation form and computes the final
    Focus Score. A session only becomes VALID here -- never before --
    and only if it cleared the minimum-duration accidental-session guard.
    """
    db_session.focus_rating = feedback.focus_rating
    db_session.engagement_rating = feedback.engagement_rating
    db_session.goal_status = feedback.goal_status
    db_session.idle_reclassified = feedback.idle_reclassified
    if feedback.interruption_reason and not db_session.interruption_reason:
        db_session.interrupted = True
        db_session.interruption_reason = feedback.interruption_reason

    too_short = (
        db_session.duration_minutes is None
        or db_session.duration_minutes < MIN_VALID_SESSION_MINUTES
    )

    if too_short:
        db_session.validation_status = "invalid"
        db_session.focus_score = None
    else:
        db_session.focus_score = calculate_validated_focus_score(
            focus_rating=feedback.focus_rating,
            engagement_rating=feedback.engagement_rating,
            active_duration=db_session.active_duration,
            idle_duration=db_session.idle_duration,
            idle_reclassified=feedback.idle_reclassified,
            pause_count=db_session.pause_count or 0,
            goal_status=feedback.goal_status,
        )
        db_session.validation_status = "valid"

    db.commit()
    db.refresh(db_session)
    return db_session


def get_focus_sessions(db: Session, user_id: int, limit: int = 200) -> list[models.FocusSession]:
    return (
        db.query(models.FocusSession)
        .filter(models.FocusSession.user_id == user_id)
        .order_by(models.FocusSession.start_time.desc())
        .limit(limit)
        .all()
    )


def get_valid_focus_sessions(db: Session, user_id: int, limit: int = 1000) -> list[models.FocusSession]:
    """
    Only VALIDATED sessions (validation_status="valid") -- the ones with a
    real, user-confirmed Focus Score. Used everywhere that feeds the
    baseline average or the ML pipeline, so a session the user never
    rated (still "pending") or that got thrown out as accidental
    ("invalid") is never silently counted toward either.
    """
    return (
        db.query(models.FocusSession)
        .filter(
            models.FocusSession.user_id == user_id,
            models.FocusSession.validation_status == "valid",
        )
        .order_by(models.FocusSession.start_time.desc())
        .limit(limit)
        .all()
    )


def get_todays_sessions(db: Session, user_id: int) -> list[models.FocusSession]:
    today = datetime.utcnow().date()
    start_of_day = datetime(today.year, today.month, today.day)
    return (
        db.query(models.FocusSession)
        .filter(
            models.FocusSession.user_id == user_id,
            models.FocusSession.start_time >= start_of_day,
        )
        .all()
    )


def get_sessions_between(
    db: Session, user_id: int, start: datetime, end: datetime
) -> list[models.FocusSession]:
    return (
        db.query(models.FocusSession)
        .filter(
            models.FocusSession.user_id == user_id,
            models.FocusSession.start_time >= start,
            models.FocusSession.start_time < end,
        )
        .all()
    )


# ---------- RECOMMENDATIONS ----------

def save_recommendation(db: Session, user_id: int, rec: dict) -> models.Recommendation:
    """Stores the latest computed recommendation so the dashboard can
    show it without recomputing on every page load."""
    db_rec = models.Recommendation(
        user_id=user_id,
        recommended_start_hour=rec.get("recommended_start_hour"),
        recommended_end_hour=rec.get("recommended_end_hour"),
        reason=rec.get("reason"),
        source=rec.get("source", "fallback"),
    )
    db.add(db_rec)
    db.commit()
    db.refresh(db_rec)
    return db_rec


def save_prediction(
    db: Session,
    user_id: int,
    *,
    window_start: datetime,
    window_end: datetime,
    predicted_focus_score: float,
    source: str,
    model_version: int | None = None,
    task_id: int | None = None,
) -> models.Prediction:
    """
    Stores one predicted focus-score window. Kept as a durable record
    (rather than overwritten each call) so a later step can compare a
    stored prediction against what a session that actually ran in that
    window validated to -- that comparison is what the retraining
    monitor's MAE/RMSE drift check needs.
    """
    db_prediction = models.Prediction(
        user_id=user_id,
        task_id=task_id,
        window_start=window_start,
        window_end=window_end,
        predicted_focus_score=predicted_focus_score,
        source=source,
        model_version=model_version,
    )
    db.add(db_prediction)
    db.commit()
    db.refresh(db_prediction)
    return db_prediction


def save_predictions(db: Session, user_id: int, predictions: list[dict]) -> list[models.Prediction]:
    """
    Batch convenience wrapper around save_prediction() for a whole set of
    candidate-window predictions at once (see ml/predict.generate_predictions).
    Each dict is expected to have window_start, window_end,
    predicted_focus_score, source, and optionally model_version/task_id.
    """
    return [
        save_prediction(
            db,
            user_id,
            window_start=p["window_start"],
            window_end=p["window_end"],
            predicted_focus_score=p["predicted_focus_score"],
            source=p["source"],
            model_version=p.get("model_version"),
            task_id=p.get("task_id"),
        )
        for p in predictions
    ]
