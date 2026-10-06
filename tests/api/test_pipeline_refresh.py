"""갱신 요청과 실제 원장 관측의 회귀 테스트. 외부 수집은 대역으로 격리한다."""

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from nuri.api.routes import pipeline
from nuri.api.routes import pipeline_refresh as refresh
from nuri.core.db import DatabaseError, get_db, query


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(refresh, "_state", None)


def test_registered_refresh_route_executes_in_order_and_records_events(monkeypatch):
    from nuri.api.main import app

    calls = []
    monkeypatch.setattr(refresh, "_execute", lambda key: calls.append(key) or 3)
    with TestClient(app) as client:
        response = client.post("/api/pipeline/refresh", json={"jobs": ["technical", "prices", "prices"]})
        assert response.status_code == 202
        state = client.get("/api/pipeline/refresh").json()
    assert calls == ["prices", "technical"]
    assert state["run"]["status"] == "completed"
    assert all(job["status"] == "completed" for job in state["run"]["jobs"])
    assert query("SELECT COUNT(*) AS n FROM pipeline_events WHERE event_type='step_completed'")[0]["n"] == 2
    assert query("SELECT COUNT(*) AS n FROM decisions")[0]["n"] == 0


def test_duplicate_request_is_rejected_before_background_work():
    refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
    with pytest.raises(HTTPException) as error:
        refresh.start_refresh(refresh.RefreshInput(jobs=["prices"]), BackgroundTasks(), {"sub": "test"})
    assert error.value.status_code == 409


def test_failure_skips_downstream_and_preserves_failed_lifecycle(monkeypatch):
    def fail(key):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(refresh, "_execute", fail)
    tasks = BackgroundTasks()
    run = refresh.start_refresh(refresh.RefreshInput(jobs=["prices", "technical"]), tasks, {"sub": "test"})
    refresh._run_refresh(run["id"], ["prices", "technical"])
    state = refresh.get_refresh()["run"]
    assert state["status"] == "failed"
    assert [job["status"] for job in state["jobs"]] == ["failed", "skipped"]
    assert query("SELECT COUNT(*) AS n FROM pipeline_events WHERE event_type='step_failed'")[0]["n"] == 1


def test_slot_is_held_for_actual_background_execution(monkeypatch):
    from nuri.api import limits

    held = []
    while limits._heavy_slots.acquire(blocking=False):
        held.append(True)
    called = []
    monkeypatch.setattr(refresh, "_execute", lambda key: called.append(key))
    try:
        run = refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
        refresh._run_refresh(run["id"], ["macro"])
        assert refresh.get_refresh()["run"]["status"] == "failed"
        assert called == []
    finally:
        for _ in held:
            limits._heavy_slots.release()


def test_invalid_jobs_and_auth_are_enforced(monkeypatch):
    from nuri.api import auth
    from nuri.api.main import app

    with TestClient(app) as client:
        for jobs in ([], ["decide"], ["consensus"], ["track"]):
            assert client.post("/api/pipeline/refresh", json={"jobs": jobs}).status_code == 422
        monkeypatch.setattr(auth, "_AUTH_ENABLED", True)
        assert client.post("/api/pipeline/refresh", json={"jobs": ["macro"]}).status_code in (401, 403)


def test_decide_reports_latest_ledger_date_without_inventing_execution():
    with get_db() as conn:
        for day, ticker in [("2026-01-01", "DEMO"), ("2026-01-02", "DEMO"), ("2026-01-02", "EXAMPLE")]:
            conn.execute("INSERT INTO decisions (date,ticker,action) VALUES (?,?,?)", (day, ticker, "HOLD"))
    step = next(row for row in pipeline.get_pipeline_status()["steps"] if row["step"] == "decide")
    assert step["status"] == "idle"
    assert step["last_updated"] is None
    assert step["execution_mode"] == "inline_with_consensus"
    assert step["artifact"] == {"status": "available", "date": "2026-01-02", "count": 2}


def test_decide_empty_unavailable_and_error_are_distinct(monkeypatch):
    from nuri.core.events import emit_event

    assert pipeline._decision_artifact() == {"status": "empty", "date": None, "count": 0}
    emit_event("step_failed", "decide", {"error": "synthetic failure"})
    assert next(row for row in pipeline.get_pipeline_status()["steps"] if row["step"] == "decide")["status"] == "error"

    def fail(*args, **kwargs):
        raise DatabaseError("synthetic failure")

    monkeypatch.setattr(pipeline, "query", fail)
    assert pipeline._decision_artifact() == {"status": "unavailable", "date": None, "count": None}
