"""
routes/dashboard.py
--------------------
GET /dashboard -> a single summary object for the dashboard page,
so the frontend doesn't have to make 5 separate calls and stitch
them together itself.

Returns:
    today's tasks, completed/pending counts, today's total focus
    minutes, today's average focus score, today's task list, and
    deadline reminders (overdue / due today / due tomorrow).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _task_summary(t):
    return {"id": t.id, "title": t.title, "priority": t.priority, "deadline": t.deadline}


@router.get("")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    all_tasks = crud.get_tasks(db, current_user.id)
    todays_sessions = crud.get_todays_sessions(db, current_user.id)

    completed_tasks = [t for t in all_tasks if t.completed]
    pending_tasks = [t for t in all_tasks if not t.completed]

    # duration_minutes is null for a session that's still in progress
    # (started but not yet completed/interrupted) -- only count finished
    # sessions toward today's focus minutes.
    total_focus_minutes_today = sum(
        s.duration_minutes for s in todays_sessions if s.duration_minutes is not None
    )

    scored_sessions = [s for s in todays_sessions if s.focus_score is not None]
    avg_focus_score_today = (
        round(sum(s.focus_score for s in scored_sessions) / len(scored_sessions), 2)
        if scored_sessions
        else 0.0
    )

    # ---- Deadline reminders ----
    now = datetime.utcnow()
    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)

    overdue, due_today, due_tomorrow = [], [], []
    for t in pending_tasks:
        if not t.deadline:
            continue
        deadline_date = t.deadline.date()
        if deadline_date < today_date:
            overdue.append(_task_summary(t))
        elif deadline_date == today_date:
            due_today.append(_task_summary(t))
        elif deadline_date == tomorrow_date:
            due_tomorrow.append(_task_summary(t))

    return {
        "total_tasks": len(all_tasks),
        "completed_tasks": len(completed_tasks),
        "pending_tasks": len(pending_tasks),
        "todays_focus_minutes": total_focus_minutes_today,
        "todays_focus_score": avg_focus_score_today,
        "todays_task_list": [
            {"id": t.id, "title": t.title, "priority": t.priority, "completed": t.completed}
            for t in all_tasks
        ],
        "reminders": {
            "overdue": overdue,
            "due_today": due_today,
            "due_tomorrow": due_tomorrow,
        },
    }
