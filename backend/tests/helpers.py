"""
tests/helpers.py
------------------
Synthetic data generation used ONLY by tests that need 30+ validated
sessions (Random Forest training, retraining/promotion, drift) -- we
obviously can't wait for real historical data to accumulate in a test
run. Sessions are inserted directly via the ORM (bypassing the API/
timers) but are scored through the SAME calculate_validated_focus_score()
production code uses, so targets stay internally consistent with the
inputs rather than being arbitrary numbers.

A deliberate, learnable pattern is injected (mornings score well,
afternoons are mediocre, evenings score poorly) purely so the Random
Forest has something real to find; this says nothing about how a real
user's data would look, and tests should not treat the resulting MAE/
beats_baseline outcome as a claim about real-world model quality.
"""
import random
from datetime import datetime, timedelta

import models
from auth import hash_password
from scoring import calculate_validated_focus_score

DIFFICULTIES = ["easy", "medium", "hard"]

TIER_BY_HOUR = {9: "high", 10: "high", 11: "high", 14: "medium", 15: "medium", 16: "medium", 20: "low"}
TIER_PROFILE = {
    "high":   dict(focus=(4, 5), engagement=(4, 5), active_ratio=(0.85, 0.98), pauses=(0, 1), goal="achieved"),
    "medium": dict(focus=(3, 4), engagement=(3, 4), active_ratio=(0.55, 0.75), pauses=(1, 3), goal="partial"),
    "low":    dict(focus=(1, 2), engagement=(1, 2), active_ratio=(0.25, 0.45), pauses=(3, 5), goal="not_achieved"),
}


def make_user(db, email, name="Test User", password="testpass123"):
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        return existing
    user = models.User(name=name, email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_task(db, user_id, title="Task", difficulty="medium"):
    task = models.Task(
        user_id=user_id, title=title, priority="medium", difficulty=difficulty,
        estimated_duration=30, remaining_duration=30, category="Work",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def seed_validated_sessions(db, user, task_ids, count, start_date, seed=7):
    """Inserts `count` VALID focus_sessions for `user`, spread one per day
    starting at `start_date`, cycling through the hour-tier pattern above."""
    rnd = random.Random(seed)
    hours = list(TIER_BY_HOUR.keys())
    for i in range(count):
        hour = hours[i % len(hours)]
        tier = TIER_BY_HOUR[hour]
        profile = TIER_PROFILE[tier]
        start_time = start_date + timedelta(days=i, hours=hour)

        duration = rnd.randint(18, 32)
        active_ratio_target = rnd.uniform(*profile["active_ratio"])
        active_minutes = round(duration * active_ratio_target)
        idle_minutes = duration - active_minutes
        pause_count = rnd.randint(*profile["pauses"])
        focus_rating = rnd.randint(*profile["focus"])
        engagement_rating = rnd.randint(*profile["engagement"])
        goal_status = profile["goal"]
        difficulty = rnd.choice(DIFFICULTIES)
        task_id = task_ids[i % len(task_ids)]

        score = calculate_validated_focus_score(
            focus_rating=focus_rating, engagement_rating=engagement_rating,
            active_duration=active_minutes, idle_duration=idle_minutes, idle_reclassified=False,
            pause_count=pause_count, goal_status=goal_status,
        )
        db.add(models.FocusSession(
            user_id=user.id, task_id=task_id, start_time=start_time,
            end_time=start_time + timedelta(minutes=duration), duration_minutes=duration,
            active_duration=active_minutes, idle_duration=idle_minutes, pause_count=pause_count,
            focus_rating=focus_rating, engagement_rating=engagement_rating, goal_status=goal_status,
            task_difficulty=difficulty, interrupted=False, idle_reclassified=False,
            focus_score=score, validation_status="valid", completed_task=(goal_status == "achieved"),
        ))
    db.commit()


def add_low_focus_sessions(db, user, task_id, count, score, start_date):
    """Adds `count` extra low-focus sessions, all around 9am, for drift tests."""
    for i in range(count):
        t = start_date + timedelta(days=i, hours=9)
        db.add(models.FocusSession(
            user_id=user.id, task_id=task_id, start_time=t, end_time=t + timedelta(minutes=25),
            duration_minutes=25, active_duration=20, idle_duration=5, pause_count=1, focus_rating=1,
            engagement_rating=1, goal_status="not_achieved", task_difficulty="medium", focus_score=score,
            validation_status="valid",
        ))
    db.commit()


def backdate_session_start(db, session_id, minutes=2):
    """Pushes a session's start_time back in time, so that when it's
    completed/interrupted "now", its elapsed duration is realistically
    >= 1 minute -- without an actual real-time test needing to sleep()
    for a minute+ to prove the same thing. Used only in tests."""
    session = db.query(models.FocusSession).filter(models.FocusSession.id == session_id).first()
    session.start_time = session.start_time - timedelta(minutes=minutes)
    db.commit()
