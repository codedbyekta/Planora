"""
Historical-average fallback (Step 6): validated-only filtering, exact
average calculation, and the 30-session ML threshold.
"""
def _legacy_session(client, h, task_id, start_iso, end_iso, duration, planned, completed):
    r = client.post("/sessions", json={
        "task_id": task_id, "start_time": start_iso, "end_time": end_iso,
        "duration_minutes": duration, "planned_duration_minutes": planned, "completed_task": completed,
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_baseline_uses_only_validated_sessions_and_exact_average(client, make_authed_user):
    _, h = make_authed_user("baseline")
    r = client.post("/tasks", json={"title": "T", "estimated_duration": 25}, headers=h)
    task_id = r.json()["id"]

    # Two valid legacy sessions at 9am: scores 100.0 and 30.0 -> avg 65.0
    s1 = _legacy_session(client, h, task_id, "2026-09-20T09:00:00", "2026-09-20T09:25:00", 25, 25, True)
    assert s1["focus_score"] == 100.0
    s2 = _legacy_session(client, h, task_id, "2026-09-21T09:10:00", "2026-09-21T09:20:00", 10, 25, False)
    assert s2["focus_score"] == 30.0
    # One valid session at 2pm: score 4.0
    s3 = _legacy_session(client, h, task_id, "2026-09-21T14:00:00", "2026-09-21T14:02:00", 2, 25, False)
    assert s3["focus_score"] == 4.0

    r = client.get("/recommendations", headers=h)
    rec = r.json()
    assert rec["source"] == "fallback"
    assert rec["recommended_start_hour"] == 9
    assert "65.0" in rec["reason"]
    assert "3 session" in rec["reason"]

    # A PENDING session (started, never completed) must NOT move the average
    r = client.post("/sessions/start", json={"task_id": task_id}, headers=h)
    assert r.json()["validation_status"] == "pending"
    r = client.get("/recommendations", headers=h)
    assert "65.0" in r.json()["reason"]
    assert "3 session" in r.json()["reason"]

    # An INVALID session (instant, no real elapsed time) must NOT move the average either
    r = client.post("/sessions/start", json={"task_id": task_id}, headers=h)
    sid = r.json()["id"]
    client.post(f"/sessions/{sid}/complete", json={"completed_task": False}, headers=h)
    client.post(f"/sessions/{sid}/feedback",
                json={"focus_rating": 1, "engagement_rating": 1, "goal_status": "not_achieved"}, headers=h)
    r = client.get("/recommendations", headers=h)
    assert "65.0" in r.json()["reason"]
    assert "3 session" in r.json()["reason"]


def test_predictions_multi_window_and_fallback_source(client, make_authed_user):
    _, h = make_authed_user("baselinepred")
    r = client.post("/tasks", json={"title": "T"}, headers=h)
    task_id = r.json()["id"]
    _legacy_session(client, h, task_id, "2026-09-20T09:00:00", "2026-09-20T09:25:00", 25, 25, True)
    _legacy_session(client, h, task_id, "2026-09-21T14:00:00", "2026-09-21T14:25:00", 25, 25, True)

    r = client.get("/predictions", headers=h)
    assert r.status_code == 200
    preds = r.json()
    assert len(preds) >= 2
    assert all(p["source"] == "fallback" and p["model_version"] is None for p in preds)
    assert all(0 <= p["predicted_focus_score"] <= 100 for p in preds)
