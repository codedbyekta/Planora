"""
seed_data.py
------------
SAMPLE / DEMO DATA GENERATOR - for local development only.

Creates one demo user with:
    - a handful of realistic tasks (some completed, some pending, some overdue)
    - ~40 focus sessions spread over the last 3 weeks, with a deliberate
      pattern (higher focus 9-11 AM, lower focus 3-5 PM) so the ML
      recommendation engine and analytics have something meaningful
      to learn from and display.

This is intentionally NOT run automatically - you run it yourself
when you want demo data to look at:

    python seed_data.py

Demo login after seeding:
    email:    demo@planora.app
    password: demo1234
"""

import random
from datetime import datetime, timedelta

from database import SessionLocal, Base, engine
import models
import crud
import schemas

Base.metadata.create_all(bind=engine)

DEMO_EMAIL = "demo@planora.app"
DEMO_PASSWORD = "demo1234"

SAMPLE_TASKS = [
    ("Prepare DBMS notes", "Study", 60, "high", -1),      # overdue by 1 day
    ("Solve 5 LeetCode problems", "Coding", 45, "medium", 0),   # due today
    ("Read OS chapter 4", "Study", 40, "medium", 1),       # due tomorrow
    ("Push project to GitHub", "Coding", 20, "low", 2),
    ("Revise DBMS normalization", "Study", 30, "high", 3),
    ("Update resume", "Personal", 25, "medium", 4),
    ("Team standup prep", "Work", 15, "low", None),
    ("Mock interview practice", "Coding", 50, "high", 5),
]


def seed():
    db = SessionLocal()

    existing = crud.get_user_by_email(db, DEMO_EMAIL)
    if existing:
        print(f"Demo user already exists ({DEMO_EMAIL}). Skipping seed to avoid duplicates.")
        print("Delete the user from the database first if you want to reseed.")
        db.close()
        return

    user = crud.create_user(
        db, schemas.UserCreate(name="Demo Student", email=DEMO_EMAIL, password=DEMO_PASSWORD)
    )
    print(f"Created demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")

    # ---- Sample tasks ----
    now = datetime.utcnow()
    created_tasks = []
    for title, category, duration, priority, day_offset in SAMPLE_TASKS:
        deadline = (now + timedelta(days=day_offset)) if day_offset is not None else None
        task = crud.create_task(
            db,
            user.id,
            schemas.TaskCreate(
                title=title,
                description=f"Sample task: {title}",
                deadline=deadline,
                priority=priority,
                estimated_duration=duration,
                category=category,
            ),
        )
        created_tasks.append(task)
    print(f"Created {len(created_tasks)} sample tasks.")

    # ---- Sample focus sessions (last 21 days) ----
    # Deliberate pattern: mornings (9-11 AM) tend to be longer/completed
    # sessions -> higher focus_score. Afternoons (3-5 PM) are shorter/
    # more often abandoned -> lower focus_score. This gives the ML model
    # and analytics charts something real to show.
    random.seed(7)
    session_count = 0
    for days_ago in range(21, 0, -1):
        day = now - timedelta(days=days_ago)

        # Morning session (most days)
        if random.random() < 0.85:
            hour = random.choice([9, 10])
            start = day.replace(hour=hour, minute=random.choice([0, 15, 30]), second=0, microsecond=0)
            duration = random.choice([25, 25, 25, 50])  # mostly full pomodoros
            completed = random.random() < 0.8
            end = start + timedelta(minutes=duration)
            task = random.choice(created_tasks)
            crud.create_focus_session(
                db,
                user.id,
                schemas.FocusSessionCreate(
                    task_id=task.id,
                    start_time=start,
                    end_time=end,
                    duration_minutes=duration,
                    planned_duration_minutes=25,
                    completed_task=completed,
                ),
            )
            session_count += 1

        # Afternoon session (less consistent, shorter)
        if random.random() < 0.6:
            hour = random.choice([15, 16])
            start = day.replace(hour=hour, minute=random.choice([0, 20, 40]), second=0, microsecond=0)
            duration = random.choice([10, 15, 25])  # often cut short
            completed = random.random() < 0.4
            end = start + timedelta(minutes=duration)
            task = random.choice(created_tasks)
            crud.create_focus_session(
                db,
                user.id,
                schemas.FocusSessionCreate(
                    task_id=task.id,
                    start_time=start,
                    end_time=end,
                    duration_minutes=duration,
                    planned_duration_minutes=25,
                    completed_task=completed,
                ),
            )
            session_count += 1

    print(f"Created {session_count} sample focus sessions across the last 21 days.")
    print("\nDone. Log in with the demo account to explore the app, or run ml/train_model.py")
    print("to pre-train the recommendation model for this user.")

    db.close()


if __name__ == "__main__":
    seed()
