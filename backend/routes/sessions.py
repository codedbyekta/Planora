"""
routes/sessions.py
-------------------
LEGACY (unchanged, still backing the existing Pomodoro timer frontend):
    POST /sessions  -> save a completed session in one shot
    GET  /sessions  -> list the current user's past sessions

NEW session lifecycle (Step 12's frontend will move over to these):
    POST /sessions/start               -> begin a session
    POST /sessions/{id}/activity       -> aggregated activity heartbeat
    POST /sessions/{id}/pause          -> mark a pause
    POST /sessions/{id}/resume         -> resume after a pause
    POST /sessions/{id}/interrupt      -> end the session due to an interruption
    POST /sessions/{id}/complete       -> end the session normally
    POST /sessions/{id}/feedback       -> submit the validation form; this is
                                           the ONLY place a session becomes
                                           VALID and gets a Focus Score.

Every route below resolves the session via get_current_user + a user_id
filter (crud.get_session), so a user can never touch another user's
session -- attempting to hits a 404, not someone else's data.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import crud
import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/sessions", tags=["Focus Sessions"])


def _get_owned_session_or_404(
    db: Session, current_user: models.User, session_id: int
) -> models.FocusSession:
    db_session = crud.get_session(db, current_user.id, session_id)
    if not db_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return db_session


# ---------- LEGACY ----------

@router.post("", response_model=schemas.FocusSessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    session: schemas.FocusSessionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return crud.create_focus_session(db, current_user.id, session)


@router.get("", response_model=list[schemas.FocusSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return crud.get_focus_sessions(db, current_user.id)


# ---------- NEW SESSION LIFECYCLE ----------

@router.post("/start", response_model=schemas.FocusSessionOut, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: schemas.SessionStart,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if payload.task_id and not crud.get_task(db, current_user.id, payload.task_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return crud.start_session(db, current_user.id, payload)


@router.post("/{session_id}/activity", response_model=schemas.FocusSessionOut)
def report_activity(
    session_id: int,
    ping: schemas.SessionActivityPing,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session already ended")
    return crud.record_activity(db, db_session, ping)


@router.post("/{session_id}/pause", response_model=schemas.FocusSessionOut)
def pause_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session already ended")
    return crud.record_pause(db, db_session)


@router.post("/{session_id}/resume", response_model=schemas.FocusSessionOut)
def resume_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session already ended")
    return crud.record_resume(db, db_session)


@router.post("/{session_id}/interrupt", response_model=schemas.FocusSessionOut)
def interrupt_session(
    session_id: int,
    payload: schemas.SessionInterrupt,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session already ended")
    return crud.interrupt_session(db, db_session, payload)


@router.post("/{session_id}/complete", response_model=schemas.FocusSessionOut)
def complete_session(
    session_id: int,
    payload: schemas.SessionCompleteRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session already ended")
    return crud.complete_session(db, db_session, payload)


@router.post("/{session_id}/feedback", response_model=schemas.FocusSessionOut)
def submit_feedback(
    session_id: int,
    feedback: schemas.SessionFeedback,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_session = _get_owned_session_or_404(db, current_user, session_id)
    if db_session.end_time is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session must be completed or interrupted before feedback can be submitted",
        )
    if db_session.validation_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Feedback already submitted for this session"
        )
    return crud.submit_feedback(db, db_session, feedback)
