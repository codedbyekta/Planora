"""
routes/weekly_report.py
------------------------
GET /weekly-report -> a summary of the last 7 days vs the 7 days before that.

The "AI-generated insight" here is plain Python string formatting over
real aggregated numbers - NOT a call to an LLM. This is deliberate per
the project spec: it needs to be explainable as "simple Python logic",
not a black box.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/weekly-report", tags=["Weekly Report"])

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _summarize(sessions, tasks_completed_in_range):
    scored = [s for s in sessions if s.focus_score is not None]
    total_minutes = sum(s.duration_minutes or 0 for s in sessions)

    avg_score = round(sum(s.focus_score for s in scored) / len(scored), 1) if scored else 0.0

    day_totals = {}
    hour_scores = {}
    for s in sessions:
        day = s.start_time.weekday()
        day_totals[day] = day_totals.get(day, 0) + (s.duration_minutes or 0)
        if s.focus_score is not None:
            hour_scores.setdefault(s.start_time.hour, []).append(s.focus_score)

    best_day = DAY_NAMES[max(day_totals, key=day_totals.get)] if day_totals else None
    best_hour = None
    if hour_scores:
        best_hour = max(hour_scores, key=lambda h: sum(hour_scores[h]) / len(hour_scores[h]))

    return {
        "total_focus_minutes": total_minutes,
        "tasks_completed": tasks_completed_in_range,
        "average_focus_score": avg_score,
        "best_day": best_day,
        "most_productive_hour": best_hour,
        "session_count": len(sessions),
    }


@router.get("")
def get_weekly_report(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    all_sessions = crud.get_focus_sessions(db, current_user.id, limit=2000)
    this_week_sessions = [s for s in all_sessions if s.start_time >= week_start]
    last_week_sessions = [s for s in all_sessions if prev_week_start <= s.start_time < week_start]

    all_tasks = crud.get_tasks(db, current_user.id)
    # Tasks with no explicit "completed_at" field, so we approximate using
    # the created_at falling in-range as a reasonable proxy for a student project.
    tasks_completed_this_week = sum(
        1 for t in all_tasks if t.completed and t.created_at >= week_start
    )

    this_week = _summarize(this_week_sessions, tasks_completed_this_week)
    last_week = _summarize(last_week_sessions, 0)

    minute_diff = this_week["total_focus_minutes"] - last_week["total_focus_minutes"]
    if last_week["total_focus_minutes"] > 0:
        pct_change = round((minute_diff / last_week["total_focus_minutes"]) * 100)
    else:
        pct_change = None

    # ---- Simple rule-based insight (plain Python, no LLM) ----
    if this_week["session_count"] == 0:
        insight = "No focus sessions logged this week yet. Complete a session to start building your report."
    else:
        hours = round(this_week["total_focus_minutes"] / 60, 1)
        insight = (
            f"You completed {this_week['tasks_completed']} task(s) this week and focused for "
            f"{hours} hour(s) across {this_week['session_count']} session(s)."
        )
        if this_week["best_day"]:
            insight += f" Your strongest day was {this_week['best_day']}."
        if pct_change is not None:
            if pct_change > 0:
                insight += f" That's {pct_change}% more focus time than last week."
            elif pct_change < 0:
                insight += f" That's {abs(pct_change)}% less focus time than last week."

    return {
        "this_week": this_week,
        "last_week": last_week,
        "change_vs_last_week_percent": pct_change,
        "insight": insight,
    }
