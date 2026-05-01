"""파이프라인 이벤트 저널 + 신선도 + 의존성 + run_step 테스트."""

from datetime import timedelta

import pytest

from nuri.core.db import get_db, init_db
from nuri.core.events import (
    emit_event,
    get_pipeline_status,
    get_step_history,
    get_step_status,
    get_timeline,
)
from nuri.core.freshness import (
    check_all_freshness,
    check_freshness,
    get_freshness_summary,
)
from nuri.core.pipeline import check_dependencies, run_step
from nuri.core.timezone import kst_now


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


# ═══════════════════════════════════════════════════════
# emit_event + get_timeline
# ═══════════════════════════════════════════════════════


class TestEmitEvent:
    def test_emit_returns_id(self, db_path):
        """emit_event가 양수 event ID를 반환."""
        event_id = emit_event("step_started", "collect", db_path=db_path)
        assert event_id is not None and event_id > 0

    def test_emit_multiple_sequential_ids(self, db_path):
        """여러 이벤트의 ID가 순차 증가."""
        id1 = emit_event("step_started", "collect", db_path=db_path)
        id2 = emit_event("step_completed", "collect", duration_ms=100, db_path=db_path)
        assert id1 is not None and id2 is not None and id2 > id1

    def test_emit_with_payload(self, db_path):
        """payload가 JSON으로 저장/조회."""
        emit_event("step_completed", "collect", payload={"rows": 42}, db_path=db_path)
        timeline = get_timeline(limit=1, db_path=db_path)
        assert timeline[0]["payload"] == {"rows": 42}

    def test_emit_with_string_payload(self, db_path):
        """문자열 payload도 저장 가능."""
        emit_event("step_failed", "collect", payload="error message", db_path=db_path)
        timeline = get_timeline(limit=1, db_path=db_path)
        assert timeline[0]["payload"] == "error message"

    def test_emit_with_all_fields(self, db_path):
        """모든 필드가 정상 저장."""
        event_id = emit_event(
            "step_completed",
            "collect",
            payload={"summary": "ok"},
            duration_ms=1500,
            record_count=100,
            causation_id=1,
            db_path=db_path,
        )
        timeline = get_timeline(limit=1, db_path=db_path)
        evt = timeline[0]
        assert evt["id"] == event_id
        assert evt["event_type"] == "step_completed"
        assert evt["step"] == "collect"
        assert evt["duration_ms"] == 1500
        assert evt["record_count"] == 100
        assert evt["causation_id"] == 1


class TestGetTimeline:
    def test_timeline_order_desc(self, db_path):
        """타임라인이 최신순으로 정렬."""
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_completed", "collect", db_path=db_path)
        emit_event("step_started", "validate", db_path=db_path)
        timeline = get_timeline(db_path=db_path)
        assert len(timeline) == 3
        # ID 기준 내림차순 (최신이 먼저)
        assert timeline[0]["step"] == "validate"
        assert timeline[1]["step"] == "collect"
        assert timeline[1]["event_type"] == "step_completed"

    def test_timeline_limit(self, db_path):
        """limit 파라미터 작동."""
        for i in range(10):
            emit_event("step_started", "collect", db_path=db_path)
        timeline = get_timeline(limit=3, db_path=db_path)
        assert len(timeline) == 3

    def test_timeline_filter_by_step(self, db_path):
        """step 필터링 작동."""
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_started", "validate", db_path=db_path)
        emit_event("step_completed", "collect", db_path=db_path)
        timeline = get_timeline(step="collect", db_path=db_path)
        assert len(timeline) == 2
        assert all(e["step"] == "collect" for e in timeline)

    def test_timeline_empty(self, db_path):
        """이벤트 없으면 빈 리스트."""
        timeline = get_timeline(db_path=db_path)
        assert timeline == []


# ═══════════════════════════════════════════════════════
# get_step_status
# ═══════════════════════════════════════════════════════


class TestGetStepStatus:
    def test_returns_latest(self, db_path):
        """최신 이벤트의 status 반환."""
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_completed", "collect", duration_ms=500, db_path=db_path)
        status = get_step_status("collect", db_path)
        assert status["status"] == "completed"
        assert status["step"] == "collect"

    def test_unknown_when_no_events(self, db_path):
        """이벤트 없으면 unknown."""
        status = get_step_status("collect", db_path)
        assert status["status"] == "unknown"
        assert status["timestamp"] is None

    def test_running_status(self, db_path):
        """started 이벤트만 있으면 running."""
        emit_event("step_started", "collect", db_path=db_path)
        status = get_step_status("collect", db_path)
        assert status["status"] == "running"

    def test_failed_status(self, db_path):
        """failed 이벤트 반영."""
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_failed", "collect", payload={"error": "timeout"}, db_path=db_path)
        status = get_step_status("collect", db_path)
        assert status["status"] == "failed"
        assert status["payload"]["error"] == "timeout"


# ═══════════════════════════════════════════════════════
# get_pipeline_status
# ═══════════════════════════════════════════════════════


class TestGetPipelineStatus:
    def test_all_six_steps(self, db_path):
        """6개 스텝 전체 상태 반환."""
        status = get_pipeline_status(db_path)
        assert len(status) == 6
        expected_steps = {"collect", "validate", "classify", "diagnose", "recommend", "track"}
        assert set(status.keys()) == expected_steps

    def test_mixed_states(self, db_path):
        """각 스텝별 상태가 독립적."""
        emit_event("step_completed", "collect", db_path=db_path)
        emit_event("step_failed", "validate", db_path=db_path)
        status = get_pipeline_status(db_path)
        assert status["collect"]["status"] == "completed"
        assert status["validate"]["status"] == "failed"
        assert status["classify"]["status"] == "unknown"


# ═══════════════════════════════════════════════════════
# get_step_history
# ═══════════════════════════════════════════════════════


class TestGetStepHistory:
    def test_only_completed_and_failed(self, db_path):
        """완료/실패 이벤트만 포함."""
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_completed", "collect", duration_ms=100, db_path=db_path)
        emit_event("step_started", "collect", db_path=db_path)
        emit_event("step_failed", "collect", payload={"error": "err"}, db_path=db_path)
        history = get_step_history("collect", db_path=db_path)
        assert len(history) == 2
        assert all(h["event_type"] in ("step_completed", "step_failed") for h in history)

    def test_history_limit(self, db_path):
        """limit 작동."""
        for _ in range(5):
            emit_event("step_completed", "collect", db_path=db_path)
        history = get_step_history("collect", limit=2, db_path=db_path)
        assert len(history) == 2


# ═══════════════════════════════════════════════════════
# check_freshness
# ═══════════════════════════════════════════════════════


class TestCheckFreshness:
    def test_pass_status(self, db_path):
        """최근 데이터 → PASS."""
        now = kst_now()
        date_str = now.strftime("%Y-%m-%d")
        # prices 테이블에 SPY 데이터 삽입
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", date_str, 500.0),
            )
        result = check_freshness("prices", db_path)
        assert result["status"] == "PASS"
        assert result["key"] == "prices"
        assert result["age_hours"] is not None
        assert result["age_hours"] <= 24

    def test_warn_status(self, db_path):
        """warn_hours 초과 → WARN."""
        # 72시간 전 데이터 (prices warn_hours=48, fail_hours=120)
        now = kst_now()
        old_date = (now - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", old_date, 500.0),
            )
        result = check_freshness("prices", db_path)
        assert result["status"] == "WARN"

    def test_fail_status(self, db_path):
        """fail_hours 초과 → FAIL."""
        # 130시간 전 데이터 (prices fail_hours=120)
        now = kst_now()
        old_date = (now - timedelta(hours=130)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", old_date, 500.0),
            )
        result = check_freshness("prices", db_path)
        assert result["status"] == "FAIL"

    def test_fail_no_data(self, db_path):
        """데이터 없음 → FAIL."""
        result = check_freshness("prices", db_path)
        assert result["status"] == "FAIL"
        assert result["last_updated"] is None
        assert result["message"] == "데이터 없음"

    def test_consensus_freshness(self, db_path):
        """recommendations.date 기반 consensus 신선도 체크.

        Session 10 fix (PR #526): query 가 'pipeline_events.diagnose step_completed'
        를 보던 always-FAIL bug → 'recommendations.date' 로 교체. save_to_recommendations
        가 매 consensus run 마다 today date row 갱신하므로 정확한 source.
        """
        from nuri.core.db import get_db
        from nuri.core.timezone import today_kst

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES (?, 'AAPL', 'HOLD', 80.0)",
                (today_kst(),),
            )
            conn.commit()
        result = check_freshness("consensus", db_path)
        assert result["status"] == "PASS"
        assert result["key"] == "consensus"

    def test_certification_freshness_fail(self, db_path):
        """certification 이벤트 없음 → FAIL."""
        result = check_freshness("certification", db_path)
        assert result["status"] == "FAIL"


class TestCheckAllFreshness:
    def test_returns_all_policies(self, db_path):
        """모든 정책 결과 반환."""
        results = check_all_freshness(db_path)
        assert len(results) == 6
        keys = {r["key"] for r in results}
        assert keys == {"prices", "macro_vix", "macro_fear_greed", "consensus", "certification", "portfolio"}


class TestGetFreshnessSummary:
    def test_summary_counts(self, db_path):
        """pass/warn/fail 카운트 합계."""
        summary = get_freshness_summary(db_path)
        assert summary["pass"] + summary["warn"] + summary["fail"] == 6
        assert len(summary["details"]) == 6

    def test_all_fail_when_empty(self, db_path):
        """빈 DB → 전부 FAIL."""
        summary = get_freshness_summary(db_path)
        assert summary["fail"] == 6
        assert summary["pass"] == 0
        assert summary["warn"] == 0


# ═══════════════════════════════════════════════════════
# check_dependencies
# ═══════════════════════════════════════════════════════


class TestCheckDependencies:
    def test_collect_no_deps(self, db_path):
        """collect는 의존성 없음 → 항상 ready."""
        result = check_dependencies("collect", db_path)
        assert result["ready"] is True
        assert result["missing"] == []

    def test_validate_needs_collect(self, db_path):
        """validate는 collect 완료 필요."""
        result = check_dependencies("validate", db_path)
        assert result["ready"] is False
        assert "collect" in result["missing"]

    def test_validate_ready_after_collect(self, db_path):
        """collect 완료 후 validate가 ready."""
        emit_event("step_completed", "collect", db_path=db_path)
        result = check_dependencies("validate", db_path)
        assert result["ready"] is True
        assert result["missing"] == []

    def test_diagnose_needs_three(self, db_path):
        """diagnose는 collect + validate + classify 필요."""
        result = check_dependencies("diagnose", db_path)
        assert result["ready"] is False
        assert set(result["missing"]) == {"collect", "validate", "classify"}

    def test_diagnose_partially_ready(self, db_path):
        """일부 의존성만 충족 → 여전히 blocked."""
        emit_event("step_completed", "collect", db_path=db_path)
        emit_event("step_completed", "validate", db_path=db_path)
        result = check_dependencies("diagnose", db_path)
        assert result["ready"] is False
        assert result["missing"] == ["classify"]

    def test_diagnose_fully_ready(self, db_path):
        """모든 의존성 충족 → ready."""
        emit_event("step_completed", "collect", db_path=db_path)
        emit_event("step_completed", "validate", db_path=db_path)
        emit_event("step_completed", "classify", db_path=db_path)
        result = check_dependencies("diagnose", db_path)
        assert result["ready"] is True

    def test_failed_dep_not_ready(self, db_path):
        """의존성이 failed면 ready 아님."""
        emit_event("step_failed", "collect", db_path=db_path)
        result = check_dependencies("validate", db_path)
        assert result["ready"] is False
        assert "collect" in result["missing"]


# ═══════════════════════════════════════════════════════
# run_step
# ═══════════════════════════════════════════════════════


class TestRunStep:
    def test_success_path(self, db_path):
        """정상 실행 → success + 이벤트 2개 (started + completed)."""

        def my_func():
            return 42

        result = run_step("collect", my_func, db_path=db_path)
        assert result["status"] == "success"
        assert result["result"] == 42
        assert "duration_ms" in result

        # 이벤트 확인
        timeline = get_timeline(db_path=db_path)
        assert len(timeline) == 2
        assert timeline[0]["event_type"] == "step_completed"
        assert timeline[1]["event_type"] == "step_started"

    def test_success_with_int_result_records_count(self, db_path):
        """int 결과 → record_count에 기록."""

        def my_func():
            return 100

        run_step("collect", my_func, db_path=db_path)
        timeline = get_timeline(db_path=db_path)
        completed = [e for e in timeline if e["event_type"] == "step_completed"][0]
        assert completed["record_count"] == 100

    def test_failure_path(self, db_path):
        """예외 발생 → failed + 이벤트 2개 (started + failed)."""

        def failing_func():
            raise ValueError("something broke")

        result = run_step("collect", failing_func, db_path=db_path)
        assert result["status"] == "failed"
        assert "something broke" in result["error"]

        timeline = get_timeline(db_path=db_path)
        assert len(timeline) == 2
        assert timeline[0]["event_type"] == "step_failed"
        assert timeline[1]["event_type"] == "step_started"

    def test_blocked_path(self, db_path):
        """의존성 미충족 → blocked."""

        def my_func():
            return "should not run"

        result = run_step("validate", my_func, db_path=db_path)
        assert result["status"] == "blocked"
        assert "collect" in result["missing"]

        # blocked 이벤트 확인
        timeline = get_timeline(db_path=db_path)
        assert len(timeline) == 1
        assert timeline[0]["event_type"] == "step_blocked"

    def test_kwargs_passed_to_func(self, db_path):
        """kwargs가 func에 전달."""

        def my_func(x, y):
            return x + y

        result = run_step("collect", my_func, db_path=db_path, x=3, y=7)
        assert result["status"] == "success"
        assert result["result"] == 10

    def test_causation_id_links(self, db_path):
        """completed 이벤트의 causation_id가 started ID와 연결."""

        def my_func():
            return "ok"

        run_step("collect", my_func, db_path=db_path)
        timeline = get_timeline(db_path=db_path)
        completed = [e for e in timeline if e["event_type"] == "step_completed"][0]
        started = [e for e in timeline if e["event_type"] == "step_started"][0]
        assert completed["causation_id"] == started["id"]

    def test_chained_steps(self, db_path):
        """collect → validate 순서대로 실행 가능."""
        run_step("collect", lambda: 10, db_path=db_path)
        result = run_step("validate", lambda: 5, db_path=db_path)
        assert result["status"] == "success"
        assert result["result"] == 5
