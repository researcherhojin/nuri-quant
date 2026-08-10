"""collector 실행이 `collector_runs` 에 실제로 기록되는지 (#975).

**막으려는 상태**: `collector_runs` 는 도입 이래 프로덕션에 **0행**이었다. 유일한 writer
인 `CollectorOrchestrator` 가 `nuri/agents/actors/__init__.py` 에 import 만 되고
`SCHEDULES` 어디에도 없어 **한 번도 실행된 적이 없었기** 때문이다. import 가 있으니
코드 검색으로는 배선된 것처럼 보였다 — 실행 여부를 본 사람이 없었다.

대가: collector health 관측이 통째로 없었고, 2026-08-11 에 발견한 데이터 구멍 셋
(#1025 FRED 8지표 0행 · #1020 kospi/yield 0행)을 전부 손으로 DB 를 뒤져 찾았다.
이 테이블이 차 있었다면 몇 달 전에 보였을 것이다.

그래서 잠금은 **"코드가 있는가"가 아니라 "행이 쌓이는가"** 로 건다 — 이 결함의
본질이 정확히 그 차이였다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import init_db, query


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """임시 DB + `_dispatch_collector` 스텁. 실제 수집은 하지 않는다."""
    import nuri.core.db as dbm
    import nuri.scheduler as sched

    db = tmp_path / "t.db"
    init_db(db)
    monkeypatch.setattr(dbm, "DB_PATH", db)
    monkeypatch.setattr(sched, "_STAGE_OF_JOB", {}, raising=False)
    calls: list[str] = []

    def stub(name, **kw):
        calls.append(name)
        return 7  # row count

    monkeypatch.setattr(sched, "_dispatch_collector", stub)
    return type("W", (), {"db": db, "calls": calls, "sched": sched})


class TestCollectorRunIsRecorded:
    def test_a_run_writes_exactly_one_row(self, wired):
        wired.sched._run_collector("macro")
        rows = query("SELECT collector_name, status, rows_collected FROM collector_runs", db_path=wired.db)
        assert len(rows) == 1, "collector 를 돌렸는데 collector_runs 가 비어 있다 — 배선이 끊긴 상태"
        assert rows[0]["collector_name"] == "macro"
        assert rows[0]["status"] == "finished"
        assert rows[0]["rows_collected"] == 7

    def test_the_collector_still_runs_exactly_once(self, wired):
        """관측을 붙이면서 수집 횟수가 바뀌면 안 된다 — retry 는 별도 판단 사항."""
        wired.sched._run_collector("macro")
        assert wired.calls == ["macro"]
        rows = query("SELECT retry_count FROM collector_runs", db_path=wired.db)
        assert rows[0]["retry_count"] == 0, "재시도가 켜졌다 — 수집 동작 변경이라 이 PR 범위 밖"

    def test_a_failing_collector_is_recorded_and_not_retried(self, wired, monkeypatch):
        def boom(name, **kw):
            wired.calls.append(name)
            raise RuntimeError("upstream 503")

        monkeypatch.setattr(wired.sched, "_dispatch_collector", boom)
        wired.sched._run_collector("cboe")  # 예외를 삼켜야 한다 (스케줄러가 죽으면 안 됨)
        assert wired.calls == ["cboe"], "실패한 collector 를 재시도했다"
        rows = query("SELECT collector_name, status FROM collector_runs", db_path=wired.db)
        assert len(rows) == 1 and rows[0]["status"] != "finished", f"실패가 기록되지 않았다: {[dict(r) for r in rows]}"

    def test_recording_failure_never_blocks_collection(self, wired, monkeypatch):
        """관측이 본 작업을 게이트하면 안 된다 (#894).

        최초 구현은 `CollectorOrchestrator.orchestrate` 를 탔는데, `Actor.run()` 이
        실행 **전에** `agent_run_ledger` 에 쓰는 바람에 그 쓰기가 실패하면 collector 가
        아예 안 돌았다 (CI 가 `no such table: agent_run_ledger` 로 잡음). 나는 그걸
        "로그만 틀린다" 고 적어 뒀었고, 틀렸다.
        """
        import nuri.scheduler as sched

        def dead_log(**kw):
            raise RuntimeError("db down")

        monkeypatch.setattr("nuri.core.db.log_collector_run", dead_log)
        sched._run_collector("macro")
        assert wired.calls == ["macro"], "기록이 실패했다고 수집을 건너뛰었다 — 관측이 본 작업을 막았다"

    @pytest.mark.parametrize(
        ("returns", "expected_rows"),
        [(7, 7), ([1, 2, 3], 3), (None, 0), ("ok", 2)],
    )
    def test_row_count_is_derived_from_whatever_the_collector_returns(self, wired, monkeypatch, returns, expected_rows):
        """collector 마다 반환형이 제각각이다 — int / 시퀀스 / None 전부 받아야 한다."""
        monkeypatch.setattr(wired.sched, "_dispatch_collector", lambda name, **kw: returns)
        wired.sched._run_collector("macro")
        rows = query("SELECT rows_collected FROM collector_runs", db_path=wired.db)
        assert rows[0]["rows_collected"] == expected_rows

    def test_stage_wrapped_collectors_are_recorded_too(self, wired, monkeypatch):
        """스테이지 잡은 `run_step` 경로를 타는데, 그쪽도 기록돼야 한다."""
        monkeypatch.setattr(wired.sched, "_STAGE_OF_JOB", {"macro": "collect"}, raising=False)
        wired.sched._run_collector("macro")
        rows = query("SELECT collector_name FROM collector_runs", db_path=wired.db)
        assert len(rows) == 1, "run_step 경로에서는 기록이 빠졌다"


class TestHealthScanIsScheduled:
    def test_collector_health_job_is_registered(self):
        """요약 잡이 SCHEDULES 에 실제로 들어 있어야 한다 — 함수만 있으면 안 돈다."""
        from nuri.scheduler import SCHEDULES

        names = {j["name"] for j in SCHEDULES}
        assert "collector_health" in names, (
            "함수를 정의해 놓고 SCHEDULES 에 안 넣으면 #975 와 같은 상태가 된다 (코드는 있는데 한 번도 안 돎)"
        )

    @pytest.mark.parametrize(
        ("out", "expect"),
        [
            ({"collector_count": 0, "unhealthy_count": 0}, "행이 없다"),
            ({"collector_count": 5, "unhealthy_count": 2}, "unhealthy"),
            ({"collector_count": 5, "unhealthy_count": 0}, "정상"),
        ],
    )
    def test_each_health_verdict_is_logged(self, monkeypatch, caplog, out, expect):
        """세 갈래(무행/이상/정상)가 서로 다른 말을 해야 한다 — 특히 '행이 없다' 는
        배선이 끊긴 상태라 '정상' 과 절대 같이 보이면 안 된다."""
        import nuri.agents.actors.collector_orchestrator as mod
        from nuri.scheduler import _run_collector_health

        monkeypatch.setattr(
            mod,
            "CollectorOrchestrator",
            lambda: type("A", (), {"run": lambda self, p: type("R", (), {"output": out})()})(),
        )
        with caplog.at_level("INFO"):
            _run_collector_health()
        assert expect in caplog.text, f"기대 문구 '{expect}' 가 없다: {caplog.text}"

    def test_health_scan_failure_does_not_escape(self, monkeypatch, caplog):
        """요약 잡이 죽어도 스케줄러가 멈추면 안 된다."""
        import nuri.agents.actors.collector_orchestrator as mod
        from nuri.scheduler import _run_collector_health

        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(mod, "CollectorOrchestrator", boom)
        _run_collector_health()  # 예외가 새어 나오면 여기서 실패
        assert "실행 실패" in caplog.text

    def test_the_registered_callable_actually_scans(self, wired):
        """등록된 func 가 진짜 scan_health 를 부르는지 — 이름만 맞는 껍데기 배제."""
        from nuri.scheduler import SCHEDULES

        job = next(j for j in SCHEDULES if j["name"] == "collector_health")
        seen = {}

        class FakeActor:
            def run(self, payload):
                seen.update(payload)
                return type("R", (), {"output": {"collector_count": 0, "unhealthy_count": 0}})()

        import nuri.agents.actors.collector_orchestrator as mod

        orig = mod.CollectorOrchestrator
        mod.CollectorOrchestrator = FakeActor
        try:
            job["func"](*job["args"])
        finally:
            mod.CollectorOrchestrator = orig
        assert seen.get("action") == "scan_health", f"scan_health 를 부르지 않았다: {seen}"
