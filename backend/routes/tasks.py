"""
routes/tasks.py
----------------
GET    /tasks        -> list all of the current user's tasks
POST   /tasks        -> create a new task
PUT    /tasks/{id}   -> update a task (partial update)
DELETE /tasks/{id}   -> delete a task

Every route depends on get_current_user, so an unauthenticated
request is rejected with 401 before it ever touches the database.
Every query in crud.py is filtered by user_id, so a user can never
read or modify another user's tasks (attempting to do so returns 404,
not the other user's data).
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

import crud
import models
import schemas
from auth import get_current_user
from database import get_db
from ml.recommendation import get_recommendation

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=list[schemas.TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return crud.get_tasks(db, current_user.id)


@router.post("", response_model=schemas.TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    task: schemas.TaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return crud.create_task(db, current_user.id, task)


@router.put("/{task_id}", response_model=schemas.TaskOut)
def update_task(
    task_id: int,
    task_update: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_task = crud.get_task(db, current_user.id, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return crud.update_task(db, db_task, task_update)


@router.get("/{task_id}/suggested-time")
def suggest_time_for_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Personalized schedule recommendation for one specific task.
    Reuses the same recommendation engine as /recommendations - the
    only new logic here is turning "best hour" into an actual calendar
    slot (today or tomorrow) sized to the task's estimated_duration.
    """
    db_task = crud.get_task(db, current_user.id, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    sessions = crud.get_valid_focus_sessions(db, current_user.id, limit=1000)
    rec = get_recommendation(db, sessions, current_user.id, background_tasks)

    if rec["recommended_start_hour"] is None:
        return {
            "task_id": task_id,
            "suggested_start": None,
            "suggested_end": None,
            "reason": rec["reason"],
        }

    now = datetime.utcnow()
    best_hour = rec["recommended_start_hour"]

    # If that hour has already passed today, suggest tomorrow instead.
    target_date = now.date() if now.hour < best_hour else (now + timedelta(days=1)).date()
    suggested_start = datetime(target_date.year, target_date.month, target_date.day, best_hour, 0)
    suggested_end = suggested_start + timedelta(minutes=db_task.estimated_duration)

    day_label = "Today" if target_date == now.date() else "Tomorrow"

    return {
        "task_id": task_id,
        "suggested_start": suggested_start.isoformat(),
        "suggested_end": suggested_end.isoformat(),
        "day_label": day_label,
        "reason": rec["reason"],
        "source": rec["source"],
    }


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_task = crud.get_task(db, current_user.id, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    crud.delete_task(db, db_task)
    return None
