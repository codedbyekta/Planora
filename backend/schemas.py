"""
schemas.py
----------
Pydantic models used to validate incoming request data and
shape outgoing response data. These are separate from the
SQLAlchemy models in models.py:

    models.py   -> what's stored in the database
    schemas.py  -> what the API accepts / returns over HTTP

This separation means we never accidentally expose fields like
`hashed_password` in an API response.
"""

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import datetime
from typing import Optional, Literal


# ---------- USER ----------

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- TASK ----------

TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskDifficulty = Literal["easy", "medium", "hard"]


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: TaskPriority = "medium"
    difficulty: TaskDifficulty = "medium"
    estimated_duration: int = 30
    category: str = "Personal"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: Optional[TaskPriority] = None
    difficulty: Optional[TaskDifficulty] = None
    estimated_duration: Optional[int] = None
    category: Optional[str] = None
    completed: Optional[bool] = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str]
    deadline: Optional[datetime]
    priority: str
    difficulty: str
    estimated_duration: int
    remaining_duration: Optional[int]  # server-managed only, not settable via the API --
                                        # decremented as sessions complete/get interrupted
    status: str
    category: str
    completed: bool
    created_at: datetime


# ---------- FOCUS SESSION ----------

class FocusSessionCreate(BaseModel):
    """
    LEGACY one-shot schema. Still used by the backward-compatible
    `POST /sessions` endpoint (existing frontend Pomodoro timer).
    New session flow uses the schemas below instead.
    """
    task_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    planned_duration_minutes: Optional[int] = None  # what the timer was set to (e.g. 25)
    completed_task: bool = False


class FocusSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[int]
    start_time: datetime
    end_time: Optional[datetime]
    duration_minutes: Optional[int]
    active_duration: Optional[int]
    idle_duration: Optional[int]
    pause_count: int
    focus_rating: Optional[int]
    engagement_rating: Optional[int]
    goal_status: Optional[str]
    task_difficulty: Optional[str]
    interrupted: bool
    interruption_reason: Optional[str]
    idle_reclassified: bool
    focus_score: Optional[float]
    validation_status: str
    completed_task: bool
    created_at: datetime


# ---------- SESSION LIFECYCLE (new session flow) ----------

InterruptionReason = Literal["urgent_task", "external_interruption", "personal", "other"]
GoalStatus = Literal["achieved", "partial", "not_achieved"]


class SessionStart(BaseModel):
    task_id: Optional[int] = None
    planned_duration_minutes: Optional[int] = None


class SessionActivityPing(BaseModel):
    """
    A periodic, aggregated client-side activity report -- NOT raw
    mouse/keyboard events. The client batches its own local detection
    (mouse/keyboard/click/scroll/visibility) into these two numbers
    every so often (e.g. every 30-60s) and sends the delta.
    """
    active_seconds: int = 0
    idle_seconds: int = 0


class SessionInterrupt(BaseModel):
    interruption_reason: InterruptionReason


class SessionCompleteRequest(BaseModel):
    completed_task: bool = False


class SessionFeedback(BaseModel):
    """
    The end-of-session validation form. A session only becomes VALID
    once this is submitted (and the session met a minimum real duration --
    see scoring.MIN_VALID_SESSION_MINUTES).
    """
    focus_rating: int = Field(ge=1, le=5)
    engagement_rating: int = Field(ge=1, le=5)
    goal_status: GoalStatus
    idle_reclassified: bool = False  # "was the idle period intentional/deep work?"
    interruption_reason: Optional[InterruptionReason] = None  # can confirm/override here
    # if the interrupt endpoint wasn't called for some reason


# ---------- RECOMMENDATION ----------

class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recommended_start_hour: Optional[int]
    recommended_end_hour: Optional[int]
    reason: Optional[str]
    source: str


# ---------- PREDICTION ----------

class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    window_start: datetime
    window_end: datetime
    predicted_focus_score: float
    source: str
    model_version: Optional[int] = None


# ---------- SCHEDULE (Task x Focus recommendation engine) ----------

class ScheduleItemOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    window_start: datetime
    window_end: datetime
    task_id: int
    task_title: str
    task_difficulty: str
    task_priority: str
    predicted_focus_score: float
    source: str
    model_version: Optional[int] = None
    reason: str


class UnscheduledTaskOut(BaseModel):
    task_id: int
    task_title: str
    reason: str


class ScheduleOut(BaseModel):
    plan: list[ScheduleItemOut]
    unscheduled: list[UnscheduledTaskOut]
