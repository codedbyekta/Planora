"""
routes/schedule.py
--------------------
GET /schedule -> "Tomorrow's Plan": matches this user's open tasks to
their predicted focus windows using difficulty, priority, and deadline
together. See ml/schedule.py for the matching algorithm itself.

This route computes NO new focus predictions -- it calls
ml.predict.generate_predictions(), the exact same function GET
/predictions uses, and hands the result straight to the scheduler. If
you just want the raw predicted windows without task assignments, use
GET /predictions instead.

Every session/task lookup is scoped to the authenticated user via
get_current_user (JWT-derived id) -- there is no way to pass or infer
another user's id here.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
import models
import schemas
from auth import get_current_user
from database import get_db
from ml.predict import generate_predictions
from ml.schedule import build_schedule

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.get("", response_model=schemas.ScheduleOut)
def get_schedule(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sessions = crud.get_valid_focus_sessions(db, current_user.id, limit=1000)
    predictions = generate_predictions(sessions, current_user.id)
    tasks = crud.get_schedulable_tasks(db, current_user.id)
    return build_schedule(tasks, predictions)
