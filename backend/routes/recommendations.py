"""
routes/recommendations.py
--------------------------
GET /recommendations -> the user's current best-time-to-work recommendation.

Delegates all the actual logic to ml/recommendation.py. This route's
only job is: fetch the user's sessions, call the engine, save the
result for the dashboard, and return it.
"""

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

import crud
import models
from auth import get_current_user
from database import get_db
from ml.recommendation import get_recommendation

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


@router.get("")
def get_recommendations(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sessions = crud.get_valid_focus_sessions(db, current_user.id, limit=1000)
    rec = get_recommendation(db, sessions, current_user.id, background_tasks)
    crud.save_recommendation(db, current_user.id, rec)
    return rec
