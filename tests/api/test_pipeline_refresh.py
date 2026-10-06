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
    yield
    # 백그라운드를 돌리지 않은 테스트가 접수 때 잡은 heavy slot 을 공유 세마포어에 남기지 않도록 (Codex #1658 r2 P2)
    with refresh._lock:
        refresh._release_permit_locked(refresh._state)


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


def test_full_slots_shed_503_at_admission_not_as_a_failed_run(monkeypatch):
    """Codex #1658 P2: 포화는 접수 시점의 503/Retry-After 로 — 202 뒤 "실패한 실행" 으로 둔갑하지 않는다."""
    from nuri.api import limits

    held = []
    while limits._heavy_slots.acquire(blocking=False):
        held.append(True)
    called = []
    monkeypatch.setattr(refresh, "_execute", lambda key: called.append(key))
    try:
        with pytest.raises(HTTPException) as error:
            refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
        assert error.value.status_code == 503
        assert error.value.headers["Retry-After"] == "5"
        assert refresh.get_refresh()["run"] is None
        assert called == []
    finally:
        for _ in held:
            limits._heavy_slots.release()


def test_slot_taken_at_admission_is_released_after_the_background_run(monkeypatch):
    from nuri.api import limits

    monkeypatch.setattr(refresh, "_execute", lambda key: 1)
    before = limits._heavy_slots._value
    run = refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
    assert limits._heavy_slots._value == before - 1, "접수 시점에 슬롯 하나를 쥔다"
    refresh._run_refresh(run["id"], ["macro"])
    assert limits._heavy_slots._value == before, "실행이 끝나면 놓는다"


def test_permit_is_released_even_if_a_new_admission_replaced_the_state_mid_run(monkeypatch):
    """Codex #1658 r3 P1: 완료를 공개한 직후 새 접수가 `_state` 를 바꿔치면 `_state` 식별로는 옛 permit 을 못 놓았다.
    finally 는 실행이 붙든 run 참조로 놓아야 한다."""
    from nuri.api import limits

    before = limits._heavy_slots._value
    run = refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})

    def execute_and_get_replaced(key):
        # 실행 도중(완료 공개 직전) 다른 접수가 상태를 가져간 상황을 재현한다
        refresh._state = {
            "id": "someone-else",
            "status": "queued",
            "started_at": refresh.kst_now().isoformat(),
            "finished_at": None,
            "jobs": [],
            "permit": False,
        }
        return 1

    monkeypatch.setattr(refresh, "_execute", execute_and_get_replaced)
    refresh._run_refresh(run["id"], ["macro"])
    assert limits._heavy_slots._value == before, "바꿔치기 뒤에도 옛 실행의 permit 은 돌아온다"


def test_job_literal_matches_the_catalog():
    assert refresh.JOB_IDS == frozenset(refresh.JOBS)


def test_abandoned_queued_run_returns_its_permit_and_unblocks_the_next_request(monkeypatch):
    """Codex #1658 r2 P1: 응답 send 가 예외로 끝나면 Starlette 가 BackgroundTasks 를 돌리지 않는다 — 접수 때
    잡은 slot 이 영영 남아 재시작 전까지 409 만 돌려주던 경로. 유예(QUEUE_GRACE_SECONDS) 뒤 회수한다."""
    from datetime import timedelta

    from nuri.api import limits
    from nuri.core.timezone import kst_now

    before = limits._heavy_slots._value
    run = refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
    assert "permit" not in run, "내부 플래그는 응답에 나가지 않는다"
    assert limits._heavy_slots._value == before - 1
    # 유예 안: 아직 queued, 두 번째 요청은 409
    with pytest.raises(HTTPException) as early:
        refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
    assert early.value.status_code == 409
    # 유예를 넘긴 뒤: abandoned 로 닫히고 slot 이 돌아온다
    later = kst_now() + timedelta(seconds=refresh.QUEUE_GRACE_SECONDS + 1)
    monkeypatch.setattr(refresh, "kst_now", lambda: later)
    state = refresh.get_refresh()["run"]
    assert state["status"] == "abandoned"
    assert [job["status"] for job in state["jobs"]] == ["skipped"]
    assert limits._heavy_slots._value == before
    # 뒤늦게 도착한 백그라운드는 아무것도 하지 않고 slot 도 두 번 놓지 않는다
    called = []
    monkeypatch.setattr(refresh, "_execute", lambda key: called.append(key))
    refresh._run_refresh(run["id"], ["macro"])
    assert called == []
    assert refresh.get_refresh()["run"]["status"] == "abandoned"
    assert limits._heavy_slots._value == before
    # 새 요청은 접수된다
    fresh = refresh.start_refresh(refresh.RefreshInput(jobs=["prices"]), BackgroundTasks(), {"sub": "test"})
    assert fresh["status"] == "queued"
    assert limits._heavy_slots._value == before - 1


def test_events_carry_job_identity_and_origin(monkeypatch):
    """Codex #1658 P2: macro 단독 갱신이 스케줄러의 collect 성공과 구분되어야 한다."""
    monkeypatch.setattr(refresh, "_execute", lambda key: 1)
    run = refresh.start_refresh(refresh.RefreshInput(jobs=["macro"]), BackgroundTasks(), {"sub": "test"})
    refresh._run_refresh(run["id"], ["macro"])
    rows = query(
        "SELECT event_type, step, payload FROM pipeline_events WHERE event_type LIKE 'refresh_job_%' ORDER BY id"
    )
    assert [r["event_type"] for r in rows] == ["refresh_job_started", "refresh_job_completed"]
    assert all(r["step"] == "collect" for r in rows)
    assert all('"origin": "dashboard_refresh"' in r["payload"] and '"job": "macro"' in r["payload"] for r in rows)
    audit = query("SELECT action, table_name, ticker FROM audit_log WHERE action = 'REFRESH'")
    assert audit and audit[-1]["table_name"] == "pipeline_refresh" and audit[-1]["ticker"] == run["id"]


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
    artifact = step["artifact"]
    assert {k: v for k, v in artifact.items() if k != "recorded_at"} == {
        "status": "available",
        "date": "2026-01-02",
        "count": 2,
    }
    assert artifact["recorded_at"].endswith("+09:00")  # #1675 기록 시각은 KST 오프셋을 달고 나간다


def test_decide_empty_unavailable_and_error_are_distinct(monkeypatch):
    from nuri.core.events import emit_event

    assert pipeline._decision_artifact() == {"status": "empty", "date": None, "count": 0, "recorded_at": None}
    emit_event("step_failed", "decide", {"error": "synthetic failure"})
    assert next(row for row in pipeline.get_pipeline_status()["steps"] if row["step"] == "decide")["status"] == "error"

    def fail(*args, **kwargs):
        raise DatabaseError("synthetic failure")

    monkeypatch.setattr(pipeline, "query", fail)
    assert pipeline._decision_artifact() == {"status": "unavailable", "date": None, "count": None, "recorded_at": None}
