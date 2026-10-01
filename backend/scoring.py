"""
scoring.py
----------
Two Focus Score formulas live here, on purpose:

1. calculate_focus_score() -- the ORIGINAL simple formula (duration ratio +
   task completion + a length bonus). Kept unchanged and still used by the
   legacy one-shot `POST /sessions` endpoint, so existing sessions and the
   existing frontend keep working exactly as before while the new session
   flow (Step 5+) is rolled out.

2. calculate_validated_focus_score() -- the NEW formula, used only for
   sessions that went through the full validation flow (start -> activity
   tracking -> pause/interrupt -> complete -> feedback). It combines the
   richer validated signals the spec asks for: focus rating, engagement
   rating, active/idle ratio, pause behavior, and goal outcome.

Both are intentionally simple, transparent, weighted formulas -- no ML,
no black box. The weights are documented below and sum to 100.

IMPORTANT (per project constraints):
    - Focus Score is a proxy for focus/engagement, NOT proof of
      productivity or task quality. It is never presented as such.
    - Idle time is not automatically penalized: if the session-end
      feedback confirms a detected-idle stretch was actually deep work
      (idle_reclassified=True), that time counts toward the active
      ratio instead of against it.
    - An interruption is not automatically treated as low focus: the
      duration-based signal here (active_duration) already reflects
      only the period the person actually worked, not the whole
      wall-clock window before they were pulled away.
    - Task difficulty is deliberately NOT a scoring weight here -- the
      score measures how focused the session was, independent of what
      was being worked on. Difficulty is used later by the task x focus
      recommendation engine (ml/recommendation.py), not baked into the
      per-session score itself.
"""

from typing import Optional


def calculate_focus_score(
    planned_duration_minutes: int,
    actual_duration_minutes: int,
    completed_task: bool,
) -> float:
    """
    LEGACY formula -- unchanged from the original TimeWise AI implementation.
    Used only by the backward-compatible one-shot `POST /sessions` endpoint.

    Formula (weights sum to 100):
        50%  -> how close the session ran to its planned duration
        30%  -> whether the linked task was actually completed
        20%  -> a small consistency bonus for longer sessions
    """
    if planned_duration_minutes <= 0:
        planned_duration_minutes = actual_duration_minutes or 1

    ratio = min(actual_duration_minutes / planned_duration_minutes, 1.0)
    duration_points = ratio * 50

    completion_points = 30 if completed_task else 0

    if actual_duration_minutes >= 25:
        consistency_points = 20
    elif actual_duration_minutes >= 10:
        consistency_points = 10
    else:
        consistency_points = 0

    total = duration_points + completion_points + consistency_points
    return round(max(0.0, min(total, 100.0)), 2)


# Goal outcome -> points, out of the 20 allotted below.
_GOAL_STATUS_POINTS = {
    "achieved": 20.0,
    "partial": 10.0,
    "not_achieved": 0.0,
}

# Minimum whole session duration (minutes) below which a session is
# treated as accidental and never marked VALID, regardless of feedback --
# per the "don't blindly train on accidental sessions" constraint.
MIN_VALID_SESSION_MINUTES = 1


def calculate_validated_focus_score(
    focus_rating: int,
    engagement_rating: int,
    active_duration: Optional[int],
    idle_duration: Optional[int],
    idle_reclassified: bool,
    pause_count: int,
    goal_status: str,
) -> float:
    """
    NEW formula, used once a session has gone through full validation.

    Weights (sum to 100):
        35%  -> self-reported focus + engagement ratings (1-5 each,
                averaged) -- the most direct read we have on focus itself
        25%  -> active-time ratio: active_duration / (active + idle).
                If idle_reclassified is True, the detected idle time is
                folded into "active" first -- confirmed deep work isn't
                punished just because there was no mouse/keyboard activity.
                If no idle tracking is available at all, we assume fully
                active (ratio = 1.0) rather than guessing a penalty.
        20%  -> goal outcome (achieved / partial / not_achieved)
        10%  -> pause behavior -- a mild penalty only for HEAVY pausing
                (fragmented attention), not for pausing at all. 0-2 pauses
                score full marks; a single bathroom break shouldn't hurt.
        10%  -> active-duration consistency bonus, the same idea as the
                legacy formula's "was this a real block of time" check,
                but measured on actual active time rather than wall-clock
                duration, so an interrupted session isn't penalized for
                the portion it never got to work.
    """
    # --- 1. Ratings (max 35 points) ---
    avg_rating = (focus_rating + engagement_rating) / 2  # 1-5
    rating_points = ((avg_rating - 1) / 4) * 35

    # --- 2. Active-time ratio (max 25 points) ---
    active = active_duration or 0
    idle = idle_duration or 0
    if idle_reclassified:
        active += idle
        idle = 0

    total_tracked = active + idle
    if total_tracked <= 0:
        # No idle-detection data at all (e.g. tracking unavailable) --
        # don't guess a penalty for something we couldn't measure.
        active_ratio = 1.0
    else:
        active_ratio = active / total_tracked
    active_ratio_points = active_ratio * 25

    # --- 3. Goal outcome (max 20 points) ---
    goal_points = _GOAL_STATUS_POINTS.get(goal_status, 0.0)

    # --- 4. Pause behavior (max 10 points) ---
    if pause_count <= 2:
        pause_points = 10.0
    elif pause_count <= 5:
        pause_points = 5.0
    else:
        pause_points = 0.0

    # --- 5. Active-duration consistency bonus (max 10 points) ---
    if active >= 25:
        consistency_points = 10.0
    elif active >= 10:
        consistency_points = 5.0
    else:
        consistency_points = 0.0

    total = (
        rating_points
        + active_ratio_points
        + goal_points
        + pause_points
        + consistency_points
    )
    return round(max(0.0, min(total, 100.0)), 2)
