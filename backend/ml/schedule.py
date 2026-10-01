"""
ml/schedule.py
---------------
Task x Focus scheduling engine (spec Section 12): takes the predicted
focus windows already produced by ml/predict.py and this user's open
tasks, and matches each task to a suitable window using predicted
focus, task difficulty, priority, and deadline TOGETHER -- never just
sorting tasks by focus score alone.

This module computes NO focus predictions itself. The caller
(routes/schedule.py) gets predictions from ml.predict.generate_predictions()
-- the exact same function GET /predictions uses -- and passes them in
here as plain dicts. No new ML, no changes to the training/prediction
pipeline in train_model.py / recommendation.py / predict.py.

GENERAL PREFERENCE (a soft tendency, not a hard rule):
    High predicted focus   -> Hard tasks
    Medium predicted focus -> Medium tasks
    Low predicted focus    -> Easy/routine tasks

OVERRIDES that can beat pure focus-matching:
    - Urgent-priority tasks get a large scoring bonus, so they tend to
      claim a slot before ordinary tier-matching happens for what's left.
    - ANY task (urgent or not) that has only one or two eligible windows
      left before its own deadline gets an even larger "last chance"
      bonus -- a looming deadline can force a less-than-ideal focus
      match rather than let the task go unscheduled or scheduled too
      late. This is deliberately based on the task's OWN remaining
      runway, not just its priority label, per "priority AND deadline
      can override normal focus matching."

HOW MATCHING WORKS (greedy score-maximization -- deliberately simple
and explainable, not a true optimal-assignment solver):
    1. Build every valid (task, window) pair. Valid means: the window
       starts before the task's deadline (if any), and the task still
       has remaining_duration > 0. A task past its deadline, or with no
       eligible window at all, simply produces no candidate pairs.
    2. Score each pair (see _score_pair / the helper functions below).
    3. Sort ALL pairs by score, descending.
    4. Walk the sorted list once: the first time a task or a window
       would be used a second time, skip that pair. Highest-scoring
       pairs get first pick -- in practice this means an urgent or
       deadline-critical task's huge bonus lets it claim its slot
       before plain difficulty/focus tier-matching decides the rest.
    5. Any task that never got a valid pair (ran out of eligible
       windows, or had none to begin with) is reported separately as
       unscheduled, with a plain-English reason.

KNOWN LIMITATION: a task whose remaining_duration is longer than one
window only gets that one window filled -- the remainder isn't
automatically carried over into a second slot in this step.
"""

from datetime import datetime, timedelta

FOCUS_HIGH_THRESHOLD = 70
FOCUS_MEDIUM_THRESHOLD = 40

_DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}
_TIER_RANK = {"low": 0, "medium": 1, "high": 2}
_PRIORITY_BONUS = {"low": 0.0, "medium": 10.0, "high": 25.0, "urgent": 60.0}


def _focus_tier(score: float) -> str:
    if score >= FOCUS_HIGH_THRESHOLD:
        return "high"
    if score >= FOCUS_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _fit_score(task_difficulty: str, focus_tier: str) -> float:
    """100 for an exact difficulty/focus-tier match, decaying for a
    mismatch by 30 points per tier of difference. A preference, not an
    exclusion -- a mismatched pair can still be scheduled if nothing
    better is competing for that window."""
    d_rank = _DIFFICULTY_RANK.get((task_difficulty or "medium").lower(), 1)
    f_rank = _TIER_RANK[focus_tier]
    return 100.0 - abs(d_rank - f_rank) * 30.0


def _remaining_minutes(task) -> float:
    return float(task.remaining_duration if task.remaining_duration is not None else task.estimated_duration)


def _eligible_windows_for_task(task, windows: list[dict]) -> list[dict]:
    """Windows that start before this task's deadline. A task with no
    deadline is eligible for every window."""
    if task.deadline is None:
        return list(windows)
    return [w for w in windows if w["window_start"] < task.deadline]


def _urgency_bonus(task, eligible_windows: list[dict]) -> float:
    """
    The fewer eligible windows remain before a task's deadline, the
    bigger this bonus. This is what lets a looming deadline override an
    otherwise-poor focus/difficulty fit -- based on the task's own
    remaining runway, not merely its priority label.
    """
    if task.deadline is None:
        return 0.0
    remaining_slots = len(eligible_windows)
    if remaining_slots <= 1:
        return 200.0  # this literally is the only chance left
    if remaining_slots == 2:
        return 60.0
    return 0.0


def _reason_for(task, window: dict, focus_tier: str, urgency_bonus: float, priority: str) -> str:
    score = window["predicted_focus_score"]
    difficulty = (task.difficulty or "medium").lower()
    focus_phrase = {
        "high": f"High predicted focus ({score}/100)",
        "medium": f"Medium predicted focus ({score}/100)",
        "low": f"Lower predicted focus ({score}/100)",
    }[focus_tier]

    fit = _fit_score(difficulty, focus_tier)
    if fit >= 100:
        match_phrase = f"matches this {difficulty} task well"
    elif fit >= 70:
        match_phrase = f"is a reasonable fit for a {difficulty} task"
    else:
        match_phrase = f"isn't an ideal fit for a {difficulty} task"

    reason = f"{focus_phrase} {match_phrase}."

    if priority == "urgent":
        reason += " Scheduled first because this task is marked urgent."
    elif urgency_bonus >= 200:
        reason += " This is the last available window before its deadline, so it was prioritized despite the fit."
    elif urgency_bonus >= 60:
        reason += " Its deadline is coming up soon, so it was prioritized over a better focus match."

    return reason


def build_schedule(tasks, predictions: list[dict], now: datetime = None) -> dict:
    """
    tasks: list of models.Task -- already scoped to ONE authenticated
           user's open (not completed) work (see
           crud.get_schedulable_tasks). Never accepts or infers a
           user_id here; the caller owns that isolation guarantee.
    predictions: the output of ml.predict.generate_predictions() for
           that SAME user.

    Returns:
        {
          "plan": [ {window_start, window_end, task_id, task_title,
                     task_difficulty, task_priority, predicted_focus_score,
                     source, model_version, reason}, ... ],  # chronological
          "unscheduled": [ {task_id, task_title, reason}, ... ]
        }
    """
    now = now or datetime.utcnow()
    windows = sorted(predictions, key=lambda w: w["window_start"])
    schedulable_tasks = [t for t in tasks if _remaining_minutes(t) > 0]

    if not windows:
        return {
            "plan": [],
            "unscheduled": [
                {
                    "task_id": t.id,
                    "task_title": t.title,
                    "reason": "No predicted focus windows available yet -- complete a few more focus sessions to unlock scheduling.",
                }
                for t in schedulable_tasks
            ],
        }

    # ---- Build every valid (task, window) candidate pair with a score ----
    candidates = []  # (score, task, window, focus_tier, urgency_bonus, priority)
    eligible_cache = {}
    for task in schedulable_tasks:
        eligible = _eligible_windows_for_task(task, windows)
        eligible_cache[task.id] = eligible
        if not eligible:
            continue

        priority = (task.priority or "medium").lower()
        priority_bonus = _PRIORITY_BONUS.get(priority, 10.0)
        urgency_bonus = _urgency_bonus(task, eligible)

        for window in eligible:
            focus_tier = _focus_tier(window["predicted_focus_score"])
            fit = _fit_score(task.difficulty, focus_tier)
            score = fit + priority_bonus + urgency_bonus
            if priority == "urgent":
                # Small chronological tie-break so an urgent task doesn't
                # end up parked in its LAST eligible slot by accident
                # when several windows score identically for it.
                score += 5.0 / (windows.index(window) + 1)
            candidates.append((score, task, window, focus_tier, urgency_bonus, priority))

    candidates.sort(key=lambda c: c[0], reverse=True)

    assigned_task_ids = set()
    assigned_window_keys = set()
    plan_by_window_start = {}

    for score, task, window, focus_tier, urgency_bonus, priority in candidates:
        window_key = window["window_start"]
        if task.id in assigned_task_ids or window_key in assigned_window_keys:
            continue
        assigned_task_ids.add(task.id)
        assigned_window_keys.add(window_key)

        remaining = _remaining_minutes(task)
        window_minutes = (window["window_end"] - window["window_start"]).total_seconds() / 60
        slot_minutes = min(remaining, window_minutes)
        slot_end = window["window_start"] + timedelta(minutes=slot_minutes)

        reason = _reason_for(task, window, focus_tier, urgency_bonus, priority)
        if remaining > window_minutes:
            reason += (
                f" (This task needs {int(remaining)} min total; only {int(slot_minutes)} min "
                f"fits in this window -- the rest will need another session.)"
            )

        plan_by_window_start[window_key] = {
            "window_start": window["window_start"],
            "window_end": slot_end,
            "task_id": task.id,
            "task_title": task.title,
            "task_difficulty": (task.difficulty or "medium").lower(),
            "task_priority": priority,
            "predicted_focus_score": window["predicted_focus_score"],
            "source": window["source"],
            "model_version": window.get("model_version"),
            "reason": reason,
        }

    plan = [plan_by_window_start[k] for k in sorted(plan_by_window_start)]

    unscheduled = []
    for task in schedulable_tasks:
        if task.id in assigned_task_ids:
            continue
        if not eligible_cache[task.id]:
            if task.deadline is not None and task.deadline < now:
                reason = "This task's deadline has already passed."
            else:
                reason = "No predicted focus window remains before this task's deadline."
        else:
            reason = (
                "No focus window was available -- all eligible windows were claimed by "
                "higher-priority or more time-critical tasks."
            )
        unscheduled.append({"task_id": task.id, "task_title": task.title, "reason": reason})

    return {"plan": plan, "unscheduled": unscheduled}
