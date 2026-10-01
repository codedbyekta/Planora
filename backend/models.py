"""
models.py
---------
Defines the database tables using SQLAlchemy ORM models.

Relationships:
    User
     ├── Task              (one user has many tasks)
     ├── FocusSession       (one user has many focus sessions)
     ├── ProductivityLog    (one user has many daily productivity logs)
     ├── Recommendation     (one user has many stored recommendations)
     ├── Prediction         (one user has many per-window focus predictions)
     └── ModelVersion       (one user has many trained model versions)

Every child table has a `user_id` foreign key pointing back to `users.id`.
This is how we make sure a user can only ever see their own data —
every query in crud.py filters by `user_id`. Personalized ML models are
trained and evaluated strictly per-user (see ml/train_model.py) — a
user's behavioral data is never mixed into another user's model.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships (lets us do user.tasks, user.focus_sessions, etc.)
    tasks = relationship("Task", back_populates="owner", cascade="all, delete-orphan")
    focus_sessions = relationship("FocusSession", back_populates="owner", cascade="all, delete-orphan")
    productivity_logs = relationship("ProductivityLog", back_populates="owner", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="owner", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="owner", cascade="all, delete-orphan")
    model_versions = relationship("ModelVersion", back_populates="owner", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(DateTime, nullable=True)
    priority = Column(String, default="medium")         # low / medium / high / urgent
    difficulty = Column(String, default="medium")        # easy / medium / hard
    estimated_duration = Column(Integer, default=30)     # planned minutes, set at creation
    remaining_duration = Column(Integer, nullable=True)   # minutes still left; starts equal to
                                                           # estimated_duration, decremented as
                                                           # sessions/interruptions consume it
    category = Column(String, default="Personal")        # Study / Coding / Work / Personal
    completed = Column(Boolean, default=False)            # kept for backward compatibility with
                                                           # existing routes/frontend that read it
    status = Column(String, default="pending")            # pending / in_progress / completed / blocked
                                                           # kept in sync with `completed` in crud.py
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="tasks")
    focus_sessions = relationship("FocusSession", back_populates="task")

    __table_args__ = (
        Index("ix_tasks_user_id", "user_id"),
    )


class FocusSession(Base):
    """
    Represents one work session (originally a fixed 25-min Pomodoro block;
    now a variable-length session that can be paused/interrupted).
    Only VALID sessions (validation_status="valid") are used to compute
    Focus Score aggregates and to train the personalized ML model —
    a session the user never confirmed/rated is not blindly trusted.
    """
    __tablename__ = "focus_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)   # null while a session is still in progress
    duration_minutes = Column(Integer, nullable=True)    # total session_duration (wall-clock);
                                                           # null while a session is still in progress
    active_duration = Column(Integer, nullable=True)      # minutes of detected activity
    idle_duration = Column(Integer, nullable=True)        # minutes of detected inactivity
    pause_count = Column(Integer, default=0)

    focus_rating = Column(Integer, nullable=True)         # 1-5, self-reported at session end
    engagement_rating = Column(Integer, nullable=True)    # 1-5, self-reported at session end
    goal_status = Column(String, nullable=True)           # achieved / partial / not_achieved
    task_difficulty = Column(String, nullable=True)       # snapshot of task.difficulty at session time

    interrupted = Column(Boolean, default=False)
    interruption_reason = Column(String, nullable=True)   # urgent_task / external_interruption /
                                                           # personal / other
    idle_reclassified = Column(Boolean, default=False)    # user confirmed detected idle time was
                                                           # actually deep work (reading, thinking) --
                                                           # scoring.py counts it as active, not idle,
                                                           # when this is True. Raw idle_duration is
                                                           # kept either way for transparency.

    focus_score = Column(Float, nullable=True)    # 0-100, computed once session is VALID
    validation_status = Column(String, default="pending")  # pending / valid / invalid
    completed_task = Column(Boolean, default=False)  # did the linked task get completed?
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="focus_sessions")
    task = relationship("Task", back_populates="focus_sessions")

    __table_args__ = (
        Index("ix_focus_sessions_user_id", "user_id"),
        Index("ix_focus_sessions_user_start", "user_id", "start_time"),
    )


class ProductivityLog(Base):
    """
    One row per day per user — a daily rollup used for analytics
    and weekly reports, so we don't have to recompute from raw
    sessions every time.
    """
    __tablename__ = "productivity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    date = Column(DateTime, nullable=False)
    total_focus_minutes = Column(Integer, default=0)
    tasks_completed = Column(Integer, default=0)
    average_focus_score = Column(Float, default=0.0)

    owner = relationship("User", back_populates="productivity_logs")


class Recommendation(Base):
    """
    Stores the latest generated recommendation for a user so the
    dashboard can show it without recomputing on every page load.
    """
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    recommended_start_hour = Column(Integer, nullable=True)  # e.g. 9 (=9 AM)
    recommended_end_hour = Column(Integer, nullable=True)    # e.g. 11 (=11 AM)
    reason = Column(Text, nullable=True)
    source = Column(String, default="fallback")  # "ml_model" or "fallback"
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="recommendations")


class Prediction(Base):
    """
    One row per predicted focus window (e.g. "9-10 AM -> predicted 4.6").
    Stored so we can later compare a window's predicted focus_score
    against the validated focus_score of sessions that actually ran in
    it -- that comparison is what drives the retraining monitor's MAE/RMSE
    checks (see ml/retrain_monitor.py).
    """
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    predicted_focus_score = Column(Float, nullable=False)
    source = Column(String, default="fallback")  # "ml_model" or "fallback"
    model_version = Column(Integer, nullable=True)  # which ModelVersion.model_version produced this
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="predictions")

    __table_args__ = (
        Index("ix_predictions_user_id", "user_id"),
    )


class ModelVersion(Base):
    """
    Metadata for one trained per-user model. Only the row with
    model_status="active" is used for live predictions -- a newly
    trained candidate is promoted to "active" only if it evaluates
    at least as well as the current one (see ml/retrain_monitor.py).
    Never claims Random Forest is universally best -- feature_version
    lets us track/compare different feature sets or algorithms over time.
    """
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    model_version = Column(Integer, nullable=False)   # increasing per-user version number
    trained_at = Column(DateTime, default=datetime.utcnow)
    training_sample_count = Column(Integer, nullable=False)
    validation_metric = Column(Float, nullable=True)  # MAE on held-out validated sessions
    model_status = Column(String, default="candidate")  # candidate / active / retired
    feature_version = Column(String, default="v1")

    owner = relationship("User", back_populates="model_versions")

    __table_args__ = (
        Index("ix_model_versions_user_id", "user_id"),
    )
