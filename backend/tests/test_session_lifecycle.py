"""
Session lifecycle, validation, and Focus Score (Step 5).

Covers: start/activity/pause/resume/interrupt/complete/feedback, the
legacy one-shot endpoint, the minimum-duration accidental-session
guard, idle reclassification, and "interruption is not auto-penalized".

Sessions are backdated at the DB level (helpers.backdate_session_start)
rather than using a real time.sleep(60+) to clear the 1-minute
accidental-session floor -- same real behavior, without a slow test.
"""
from tests.helpers import backdate_session_start


def test_full_happy_path_and_legacy_endpoint(client, make_authed_user, db):
    _, h = make_authed_user("lifecycle")

    r = client.post("/tasks", json={"title": "Write docs", "priority": "high", "estimated_duration": 30}, headers=h)
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]

    r = client.post("/sessions/start", json={"task_id": task_id, "planned_duration_minutes": 25}, headers=h)
    assert r.status_code == 201, r.text
    session = r.json()
    sid = session["id"]
    assert session["validation_status"] == "pending"
    assert session["end_time"] is None

    r = client.post(f"/sessions/{sid}/activity", json={"active_seconds": 600, "idle_seconds": 60}, headers=h)
    assert r.status_code == 200
    r = client.post(f"/sessions/{sid}/pause", headers=h)
    assert r.status_code == 200
    r = client.post(f"/sessions/{sid}/resume", headers=h)
    assert r.status_code == 200 and r.json()["pause_count"] == 1

    backdate_session_start(db, sid, minutes=25)
    r = client.post(f"/sessions/{sid}/complete", json={"completed_task": False}, headers=h)
    assert r.status_code == 200
    completed = r.json()
    assert completed["validation_status"] == "pending"  # still pending until feedback
    assert completed["focus_score"] is None
    assert completed["duration_minutes"] >= 24  # real elapsed time, not floored/faked

    # Can't send activity after the session ended
    r = client.post(f"/sessions/{sid}/activity", json={"active_seconds": 10, "idle_seconds": 0}, headers=h)
    assert r.status_code == 400

    r = client.post(f"/sessions/{sid}/feedback", json={
        "focus_rating": 4, "engagement_rating": 5, "goal_status": "partial", "idle_reclassified": False,
    }, headers=h)
    assert r.status_code == 200
    final = r.json()
    assert final["validation_status"] == "valid"
    assert final["focus_score"] is not None

    # Feedback can't be submitted twice
    r = client.post(f"/sessions/{sid}/feedback",
                     json={"focus_rating": 3, "engagement_rating": 3, "goal_status": "achieved"}, headers=h)
    assert r.status_code == 400

    # Legacy one-shot endpoint still works, unchanged, auto-valid
    r = client.post("/sessions", json={
        "task_id": task_id, "start_time": "2026-09-26T09:00:00", "end_time": "2026-09-26T09:25:00",
        "duration_minutes": 25, "planned_duration_minutes": 25, "completed_task": True,
    }, headers=h)
    assert r.status_code == 201, r.text
    legacy = r.json()
    assert legacy["validation_status"] == "valid"
    assert legacy["focus_score"] is not None


def test_interruption_is_not_auto_penalized(client, make_authed_user, db):
    _, h = make_authed_user("interrupt")
    r = client.post("/tasks", json={"title": "T"}, headers=h)
    task_id = r.json()["id"]

    r = client.post("/sessions/start", json={"task_id": task_id}, headers=h)
    sid = r.json()["id"]
    client.post(f"/sessions/{sid}/activity", json={"active_seconds": 300, "idle_seconds": 0}, headers=h)
    backdate_session_start(db, sid, minutes=10)
    r = client.post(f"/sessions/{sid}/interrupt", json={"interruption_reason": "urgent_task"}, headers=h)
    assert r.status_code == 200
    interrupted = r.json()
    assert interrupted["interrupted"] is True
    assert interrupted["interruption_reason"] == "urgent_task"

    # Good ratings despite the interruption -> should still validate with a
    # reasonable (not automatically zeroed/penalized) score.
    r = client.post(f"/sessions/{sid}/feedback", json={
        "focus_rating": 5, "engagement_rating": 4, "goal_status": "not_achieved",
    }, headers=h)
    assert r.status_code == 200
    result = r.json()
    assert result["validation_status"] == "valid"
    assert result["focus_score"] > 50  # not auto-penalized to a low score just for being interrupted


def test_too_short_session_is_invalid_not_valid(client, make_authed_user):
    """Regression test for a real bug caught during Step 6: an early
    implementation floored elapsed_minutes at 1, which made it
    impossible for any session to ever be short enough to fail the
    accidental-session guard. This must resolve to 'invalid'."""
    _, h = make_authed_user("tooshort")
    r = client.post("/sessions/start", json={}, headers=h)
    sid = r.json()["id"]
    r = client.post(f"/sessions/{sid}/complete", json={"completed_task": False}, headers=h)  # ~0 real minutes elapsed
    r = client.post(f"/sessions/{sid}/feedback", json={
        "focus_rating": 1, "engagement_rating": 1, "goal_status": "not_achieved",
    }, headers=h)
    assert r.json()["validation_status"] == "invalid"


def test_idle_reclassification_counts_as_active(client, make_authed_user, db):
    _, h = make_authed_user("idlereclass")
    r = client.post("/sessions/start", json={}, headers=h)
    sid = r.json()["id"]
    client.post(f"/sessions/{sid}/activity", json={"active_seconds": 300, "idle_seconds": 600}, headers=h)
    backdate_session_start(db, sid, minutes=15)
    client.post(f"/sessions/{sid}/complete", json={"completed_task": False}, headers=h)
    r_not_reclassified = client.post(f"/sessions/{sid}/feedback", json={
        "focus_rating": 3, "engagement_rating": 3, "goal_status": "partial", "idle_reclassified": False,
    }, headers=h)
    score_not_reclassified = r_not_reclassified.json()["focus_score"]

    # Second session, identical inputs, but idle time IS reclassified as deep work
    r = client.post("/sessions/start", json={}, headers=h)
    sid2 = r.json()["id"]
    client.post(f"/sessions/{sid2}/activity", json={"active_seconds": 300, "idle_seconds": 600}, headers=h)
    backdate_session_start(db, sid2, minutes=15)
    client.post(f"/sessions/{sid2}/complete", json={"completed_task": False}, headers=h)
    r_reclassified = client.post(f"/sessions/{sid2}/feedback", json={
        "focus_rating": 3, "engagement_rating": 3, "goal_status": "partial", "idle_reclassified": True,
    }, headers=h)
    score_reclassified = r_reclassified.json()["focus_score"]

    assert score_reclassified > score_not_reclassified


def test_cross_user_session_access_is_blocked(client, make_authed_user):
    _, h_a = make_authed_user("sessA")
    _, h_b = make_authed_user("sessB")
    r = client.post("/sessions/start", json={}, headers=h_a)
    sid = r.json()["id"]
    r = client.post(f"/sessions/{sid}/pause", headers=h_b)
    assert r.status_code == 404
