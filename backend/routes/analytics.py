"""
routes/analytics.py
--------------------
GET /analytics -> aggregated stats for the Analytics page charts.

All of this is computed directly from the raw focus_sessions and
tasks tables using plain Python (no ML here — this is just grouping
and averaging real data, the same thing you'd do with a GROUP BY in SQL).
The ML model (Phase 5) is a separate, smarter layer built on top of
this same raw data.

Day-of-week and hour-of-day are derived from `start_time`, which is
why FocusSession.start_time is the field we lean on throughout.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@router.get("")
def get_analytics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sessions = crud.get_focus_sessions(db, current_user.id, limit=1000)
    tasks = crud.get_tasks(db, current_user.id)

    completed_count = sum(1 for t in tasks if t.completed)
    pending_count = sum(1 for t in tasks if not t.completed)

    # ---- Daily focus time for the last 14 days ----
    today = datetime.utcnow().date()
    daily_minutes = defaultdict(int)
    for s in sessions:
        d = s.start_time.date()
        if (today - d).days < 14:
            daily_minutes[d.isoformat()] += (s.duration_minutes or 0)

    daily_focus_time = []
    for i in range(13, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        daily_focus_time.append({"date": day, "minutes": daily_minutes.get(day, 0)})

    weekly_focus_minutes = sum(d["minutes"] for d in daily_focus_time[-7:])

    # ---- Focus score trend (daily average, last 14 days) ----
    daily_scores = defaultdict(list)
    for s in sessions:
        d = s.start_time.date()
        if (today - d).days < 14 and s.focus_score is not None:
            daily_scores[d.isoformat()].append(s.focus_score)

    focus_score_trend = []
    for i in range(13, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        scores = daily_scores.get(day, [])
        avg = round(sum(scores) / len(scores), 2) if scores else None
        focus_score_trend.append({"date": day, "avg_score": avg})

    # ---- Most productive hours (average focus score grouped by hour) ----
    hour_scores = defaultdict(list)
    for s in sessions:
        if s.focus_score is not None:
            hour_scores[s.start_time.hour].append(s.focus_score)

    most_productive_hours = [
        {
            "hour": hour,
            "avg_score": round(sum(scores) / len(scores), 2),
            "session_count": len(scores),
        }
        for hour, scores in sorted(hour_scores.items())
    ]

    # ---- Productivity by day of week ----
    day_scores = defaultdict(list)
    for s in sessions:
        if s.focus_score is not None:
            day_scores[s.start_time.weekday()].append(s.focus_score)

    productivity_by_day = [
        {
            "day": DAY_NAMES[i],
            "avg_score": round(sum(day_scores[i]) / len(day_scores[i]), 2) if day_scores.get(i) else 0,
        }
        for i in range(7)
    ]

    return {
        "completed_vs_pending": {"completed": completed_count, "pending": pending_count},
        "daily_focus_time": daily_focus_time,
        "weekly_focus_minutes": weekly_focus_minutes,
        "focus_score_trend": focus_score_trend,
        "most_productive_hours": most_productive_hours,
        "productivity_by_day": productivity_by_day,
        "total_sessions": len(sessions),
    }
