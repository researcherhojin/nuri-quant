"""파이프라인 DAG 는 관측하되 차단하지 않는다 (#921).

`nuri/core/pipeline.py` 의 DAG 는 오래 죽어 있었다 — `run_step` 의 호출자가
자기 테스트뿐이었고, 선언된 6-step 어휘(collect/validate/classify/diagnose/
recommend/track)는 2026-04-09 수동 실행 때 두 행씩 남기고 그 뒤로 아무도 쓰지
않았다. 스케줄러는 48개 cron 잡을 서로 무관하게 돌렸다.

되살리면서 두 가지를 반드시 지켜야 했다:

1. **차단 금지.** 의존성 미충족이 잡 실행을 막으면, DB 한 번 삐끗하거나 크론
   순서가 바뀌었을 때 파이프라인이 조용히 선다. 스케줄러는 `warn_only=True` 로
   부르고 경고 이벤트만 남긴다 ([[feedback_observability_must_not_gate]]).
2. **실패를 성공으로 기록하지 않기.** `_run_collector` 는 예외를 삼켜 로깅한다.
   그 바깥에서 감싸면 `run_step` 이 항상 성공을 보므로, `reraise=True` 로
   step_failed 를 남긴 뒤 원래 예외를 그대로 올려보낸다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.core.db import init_db
from nuri.core.events import PIPELINE_STEPS, emit_event, get_step_status
from nuri.core.pipeline import STEP_DEPENDENCIES, check_dependencies, run_step


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "pipe.db"
    init_db(path)
    return path


class TestVocabularyIsShared:
    def test_dag_and_event_steps_use_the_same_names(self):
        """두 어휘가 갈라지면 스케줄러가 남긴 이벤트를 DAG 가 못 읽는다.

        Gotcha-Test Pair: 한쪽만 이름을 바꾸면 FAIL — 그 불일치가 #921 의 본질이다.
        """
        assert set(STEP_DEPENDENCIES) == set(PIPELINE_STEPS), (
            f"STEP_DEPENDENCIES={sorted(STEP_DEPENDENCIES)} != PIPELINE_STEPS={sorted(PIPELINE_STEPS)}"
        )

    def test_every_dependency_names_a_real_stage(self):
        for step, deps in STEP_DEPENDENCIES.items():
            for d in deps:
                assert d in STEP_DEPENDENCIES, f"{step} 이 존재하지 않는 스테이지 {d} 에 의존"


class TestStatusIgnoresDomainEvents:
    def test_a_later_domain_event_does_not_overwrite_stage_status(self, db_path):
        """`step` 컬럼은 lifecycle 이벤트와 도메인 이벤트가 공유한다.

        프로덕션에서 holdings_monitor 가 step="track" 으로 자기 이벤트를 남기고
        있었고, 예전 `get_step_status` 는 가장 최근 행을 그대로 status 로 돌려줘
        "holdings_monitor_run" 을 상태로 보고했다 — completed 가 아니므로 이걸
        의존성으로 삼는 스테이지는 영영 ready 가 될 수 없었다.

        Gotcha-Test Pair: event_type 필터를 빼면 FAIL.
        """
        run_step("collect", lambda: 1, db_path=db_path)
        emit_event("holdings_monitor_run", "collect", db_path=db_path)

        assert get_step_status("collect", db_path)["status"] == "completed"
        assert check_dependencies("analyze", db_path)["ready"] is True

    def test_unknown_when_only_domain_events_exist(self, db_path):
        """lifecycle 이벤트가 하나도 없으면 상태는 unknown 이지 도메인 이벤트 이름이 아니다."""
        emit_event("holdings_monitor_run", "track", db_path=db_path)
        assert get_step_status("track", db_path)["status"] == "unknown"


class TestWarnOnlyNeverBlocks:
    def test_missing_dependency_blocks_by_default(self, db_path):
        """기존 계약 보존 — warn_only 를 안 주면 예전처럼 막는다."""
        assert run_step("analyze", lambda: 1, db_path=db_path)["status"] == "blocked"

    def test_warn_only_runs_anyway_and_reports_the_gap(self, db_path):
        """의존성이 안 맞아도 실행한다. 경고는 결과와 이벤트 양쪽에 남는다.

        Gotcha-Test Pair: warn_only 분기를 없애면 status 가 blocked 로 바뀌어 FAIL.
        """
        result = run_step("analyze", lambda: 42, db_path=db_path, warn_only=True)

        assert result["status"] == "success", "관측 모드가 실행을 막았다"
        assert result["result"] == 42
        assert result["dependency_warning"] == ["collect"]
        assert get_step_status("analyze", db_path)["status"] == "completed"

    def test_warning_is_recorded_as_an_event(self, db_path):
        from nuri.core.db import query

        run_step("analyze", lambda: 1, db_path=db_path, warn_only=True)
        rows = query(
            "SELECT step FROM pipeline_events WHERE event_type = ?",
            ("step_dependency_warning",),
            db_path=db_path,
        )
        assert [r["step"] for r in rows] == ["analyze"]


class TestFailureIsNotRecordedAsSuccess:
    def test_reraise_preserves_the_original_exception(self, db_path):
        """호출자가 자기 로깅을 갖고 있을 때 예외 타입/메시지가 그대로 올라와야 한다."""

        def boom():
            raise ValueError("원본")

        with pytest.raises(ValueError, match="원본"):
            run_step("collect", boom, db_path=db_path, warn_only=True, reraise=True)
        assert get_step_status("collect", db_path)["status"] == "failed"

    def test_without_reraise_the_failure_is_returned(self, db_path):
        def boom():
            raise ValueError("원본")

        result = run_step("collect", boom, db_path=db_path)
        assert result["status"] == "failed"
        assert get_step_status("collect", db_path)["status"] == "failed"


class TestSchedulerWiring:
    def test_staged_job_emits_lifecycle_events(self, db_path, monkeypatch):
        """스테이지에 속한 잡은 run_step 을 거친다.

        Gotcha-Test Pair: `_run_collector` 의 배선을 되돌리면 상태가 unknown 이라 FAIL.
        """
        import nuri.core.db as dbm

        monkeypatch.setattr(dbm, "DB_PATH", db_path)
        import nuri.scheduler as sch

        with patch.object(sch, "_dispatch_collector", return_value=None):
            sch._run_collector("consensus")
        assert get_step_status("consensus", db_path)["status"] == "completed"

    def test_unstaged_job_emits_nothing(self, db_path, monkeypatch):
        """브리프·디스패처 같은 운영 잡은 스테이지가 아니다 — 가짜 상태를 만들지 않는다."""
        import nuri.core.db as dbm

        monkeypatch.setattr(dbm, "DB_PATH", db_path)
        import nuri.scheduler as sch

        with patch.object(sch, "_dispatch_collector", return_value=None):
            sch._run_collector("dispatcher_brief")
        assert get_step_status("dispatcher_brief", db_path)["status"] == "unknown"

    def test_job_failure_is_logged_and_recorded_but_not_raised(self, db_path, monkeypatch):
        """기존 계약 보존: 잡 실패는 스케줄러를 죽이지 않는다. 단 step_failed 는 남는다."""
        import nuri.core.db as dbm

        monkeypatch.setattr(dbm, "DB_PATH", db_path)
        import nuri.scheduler as sch

        with patch.object(sch, "_dispatch_collector", side_effect=ValueError("boom")):
            sch._run_collector("stock")  # raise 하지 않아야 한다
        assert get_step_status("collect", db_path)["status"] == "failed"

    def test_every_mapped_job_name_is_reachable_from_schedules(self):
        """매핑에 있는 잡 이름이 실제 SCHEDULES 의 collector 인자와 일치하는가.

        오타나 이름 변경으로 매핑이 조용히 죽는 것을 막는다 — 그러면 그 스테이지는
        영영 이벤트를 안 남기고, 대시보드는 idle 로 보인다.
        """
        import nuri.scheduler as sch

        scheduled = {j["args"][0] for j in sch.SCHEDULES if j.get("func") is sch._run_collector and j.get("args")}
        orphan = sorted(set(sch._STAGE_OF_JOB) - scheduled)
        assert not orphan, f"_STAGE_OF_JOB 에 있으나 SCHEDULES 에 없는 잡: {orphan}"


class TestTelemetryFailureDoesNotGate:
    """이벤트 기록이 실패해도 감싼 함수는 실행된다.

    CI 가 실제로 이 구멍을 잡았다 (#921 첫 커밋): `pipeline_events` 테이블이 없는
    환경에서 `emit_event` 가 OperationalError 를 던졌고, 그게 `run_step` 밖으로
    나가 **collector 가 아예 호출되지 않았다** — mock 이 0회 호출로 FAIL.
    warn_only 로 "차단하지 않는다" 를 만들어 놓고 텔레메트리 자체를 게이트로
    만든 셈이다. 로컬은 DB 에 테이블이 있어서 통과했다.
    """

    def test_wrapped_function_runs_even_if_every_emit_fails(self, db_path):
        """Gotcha-Test Pair: `_safe_emit` 을 `emit_event` 로 되돌리면 FAIL."""
        from nuri.core.db import OperationalError

        ran = []
        with patch(
            "nuri.core.pipeline.emit_event",
            side_effect=OperationalError("no such table: pipeline_events"),
        ):
            result = run_step("analyze", lambda: ran.append(1), db_path=db_path, warn_only=True)

        assert ran == [1], "이벤트 기록 실패가 본 작업을 막았다"
        assert result["status"] == "success"

    def test_reraise_still_works_when_emit_fails(self, db_path):
        """텔레메트리가 죽어도 진짜 실패는 여전히 호출자에게 전달된다."""
        from nuri.core.db import OperationalError

        def boom():
            raise ValueError("진짜 실패")

        with patch("nuri.core.pipeline.emit_event", side_effect=OperationalError("no such table")):
            with pytest.raises(ValueError, match="진짜 실패"):
                run_step("collect", boom, db_path=db_path, warn_only=True, reraise=True)
