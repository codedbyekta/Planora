"""
routes/predictions.py
-----------------------
GET /predictions -> predicted Focus Score for several candidate future
time windows (not just one best hour -- that's GET /recommendations).

Delegates the actual computation to ml/predict.py, then persists the
result to the `predictions` table via crud.save_predictions so there's
a durable, per-user record of what was predicted and when (useful later
for comparing predictions against what sessions in those windows
actually validated to).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
import models
import schemas
from auth import get_current_user
from database import get_db
from ml.predict import generate_predictions

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("", response_model=list[schemas.PredictionOut])
def get_predictions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sessions = crud.get_valid_focus_sessions(db, current_user.id, limit=1000)
    predictions = generate_predictions(sessions, current_user.id)
    return crud.save_predictions(db, current_user.id, predictions)
