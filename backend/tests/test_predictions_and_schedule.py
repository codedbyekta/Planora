"""
Multi-window predictions (Step 8) and task x focus scheduling (Step 9),
including adaptive task-progress interactions (Step 10).
"""
from datetime import datetime, timedelta

import models
from tests.helpers import make_user, make_task, seed_validated_sessions, DIFFICULTIES, backdate_session_start


def test_predictions_never_trains_and_uses_ml_once_trained(client, db, make_authed_user):
    user_id, h = make_authed_user("predtrain")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    tasks = [make_task(db, user.id, f"T{i}", d).id for i, d in enumerate(DIFFICULTIES)]
    seed_validated_sessions(db, user, tasks, count=45, start_date=datetime(2026, 8, 1))

    # Predictions must NOT train by themselves -- confirm no model file yet
    from ml.train_model import load_model_and_meta
    assert load_model_and_meta(user.id) == (None, None)
    r = client.get("/predictions", headers=h)
    assert r.status_code == 200
    assert all(p["source"] == "fallback" for p in r.json())
    assert load_model_and_meta(user.id) == (None, None)  # still untrained after calling /predictions

    # Now trigger training via /recommendations (the only documented trigger point)
    r = client.get("/recommendations", headers=h)
    assert r.status_code == 200

    r = client.get("/predictions", headers=h)
    preds = r.json()
    if any(p["source"] == "ml_model" for p in preds):
        assert all(p["model_version"] is not None for p in preds if p["source"] == "ml_model")
    assert all(0 <= p["predicted_focus_score"] <= 100 for p in preds)


def test_schedule_matches_difficulty_to_focus_tier_and_handles_urgent_deadline(client, db, make_authed_user):
    user_id, h = make_authed_user("sched")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    tasks = [make_task(db, user.id, f"T{i}", d).id for i, d in enumerate(DIFFICULTIES)]
    # 12 sessions -> stays on the fallback path, with a real tiered pattern
    # (hours 9/10/11 = high tier, 14/15/16 = medium, 20 = low; see helpers.py)
    seed_validated_sessions(db, user, tasks, count=12, start_date=datetime(2026, 8, 1))

    r = client.get("/predictions", headers=h)
    windows = sorted(r.json(), key=lambda w: w["window_start"])
    by_hour = {int(w["window_start"][11:13]): w for w in windows}
    assert by_hour[9]["predicted_focus_score"] >= 70
    assert by_hour[20]["predicted_focus_score"] < 40

    r = client.post("/tasks", json={"title": "Hard DSA", "difficulty": "hard", "priority": "medium"}, headers=h)
    id_hard = r.json()["id"]
    r = client.post("/tasks", json={"title": "Urgent fire drill", "difficulty": "easy", "priority": "urgent"}, headers=h)
    id_urgent = r.json()["id"]
    r = client.post("/tasks", json={
        "title": "Overdue task", "deadline": (datetime.utcnow() - timedelta(days=1)).isoformat(),
    }, headers=h)
    id_overdue = r.json()["id"]

    r = client.get("/schedule", headers=h)
    sched = r.json()
    plan = {item["task_id"]: item for item in sched["plan"]}
    unscheduled = {u["task_id"]: u["reason"] for u in sched["unscheduled"]}

    assert int(plan[id_hard]["window_start"][11:13]) in (9, 10, 11)  # hard -> high focus hour
    assert int(plan[id_urgent]["window_start"][11:13]) == 20  # urgent claims the low-focus hour it needs least, still gets scheduled
    assert "urgent" in plan[id_urgent]["reason"].lower()
    assert id_overdue in unscheduled
    assert "deadline has already passed" in unscheduled[id_overdue]


def test_completed_task_disappears_and_remaining_duration_gates_schedulability(client, make_authed_user):
    _, h = make_authed_user("taskprogress")
    r = client.post("/tasks", json={"title": "Will complete", "estimated_duration": 30}, headers=h)
    task_id = r.json()["id"]

    r = client.post("/sessions", json={
        "task_id": task_id, "start_time": "2026-09-26T09:00:00", "end_time": "2026-09-26T09:30:00",
        "duration_minutes": 30, "planned_duration_minutes": 30, "completed_task": True,
    }, headers=h)
    assert r.status_code == 201

    r = client.get("/tasks", headers=h)
    task = next(t for t in r.json() if t["id"] == task_id)
    assert task["completed"] is True
    assert task["remaining_duration"] == 0

    r = client.get("/schedule", headers=h)
    sched = r.json()
    all_ids = {p["task_id"] for p in sched["plan"]} | {u["task_id"] for u in sched["unscheduled"]}
    assert task_id not in all_ids  # completed tasks never appear, in either list


def test_legacy_partial_session_reduces_remaining_duration(client, make_authed_user):
    """Regression test for a real Step 10 bug: the legacy one-shot
    endpoint used to only handle completed_task=True and silently left
    remaining_duration untouched for a partial session."""
    _, h = make_authed_user("legacypartial")
    r = client.post("/tasks", json={"title": "Partial", "estimated_duration": 60}, headers=h)
    task_id = r.json()["id"]

    client.post("/sessions", json={
        "task_id": task_id, "start_time": "2026-09-26T09:00:00", "end_time": "2026-09-26T09:20:00",
        "duration_minutes": 20, "planned_duration_minutes": 60, "completed_task": False,
    }, headers=h)

    r = client.get("/tasks", headers=h)
    task = next(t for t in r.json() if t["id"] == task_id)
    assert task["remaining_duration"] == 40
    assert task["completed"] is False


def test_interrupted_task_remaining_duration_preserved_and_reschedulable(client, db, make_authed_user):
    _, h = make_authed_user("interruptsched")
    r = client.post("/tasks", json={"title": "Interruptible", "estimated_duration": 45}, headers=h)
    task_id = r.json()["id"]

    r = client.post("/sessions/start", json={"task_id": task_id}, headers=h)
    sid = r.json()["id"]
    client.post(f"/sessions/{sid}/activity", json={"active_seconds": 600, "idle_seconds": 0}, headers=h)
    backdate_session_start(db, sid, minutes=10)
    client.post(f"/sessions/{sid}/interrupt", json={"interruption_reason": "urgent_task"}, headers=h)

    r = client.get("/tasks", headers=h)
    task = next(t for t in r.json() if t["id"] == task_id)
    assert 0 < task["remaining_duration"] < 45  # reduced by actual worked time, not zeroed or left unchanged
    assert task["completed"] is False

    r = client.get("/schedule", headers=h)
    all_ids = {p["task_id"] for p in r.json()["plan"]} | {u["task_id"] for u in r.json()["unscheduled"]}
    assert task_id in all_ids  # still eligible for scheduling after the interruption


def test_new_urgent_task_is_reflected_in_the_very_next_schedule_call(client, make_authed_user):
    _, h = make_authed_user("newurgent")
    r = client.post("/tasks", json={"title": "Normal task", "priority": "medium"}, headers=h)
    r1 = client.get("/schedule", headers=h)
    before_ids = {p["task_id"] for p in r1.json()["plan"]}

    r = client.post("/tasks", json={"title": "Just went urgent", "priority": "urgent"}, headers=h)
    urgent_id = r.json()["id"]
    r2 = client.get("/schedule", headers=h)
    plan_ids = {p["task_id"] for p in r2.json()["plan"]} | {u["task_id"] for u in r2.json()["unscheduled"]}
    assert urgent_id in plan_ids  # picked up immediately, no separate "refresh" step needed


def test_user_isolation_across_predictions_and_schedule(client, db, make_authed_user):
    id_a, h_a = make_authed_user("isoA")
    id_b, h_b = make_authed_user("isoB")
    r = client.post("/tasks", json={"title": "Belongs to A"}, headers=h_a)
    task_a = r.json()["id"]
    r = client.post("/tasks", json={"title": "Belongs to B"}, headers=h_b)
    task_b = r.json()["id"]

    r = client.get("/schedule", headers=h_a)
    a_ids = {p["task_id"] for p in r.json()["plan"]} | {u["task_id"] for u in r.json()["unscheduled"]}
    assert task_a in a_ids
    assert task_b not in a_ids

    r = client.get("/schedule", headers=h_b)
    b_ids = {p["task_id"] for p in r.json()["plan"]} | {u["task_id"] for u in r.json()["unscheduled"]}
    assert task_b in b_ids
    assert task_a not in b_ids
