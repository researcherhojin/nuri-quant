"""SREIncidentAgent tests (#529 Phase 2 — actor #14, canonical Layer A).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 4 actions: scan / acknowledge / resolve / list_open
- 8 detector 각각 (orphan_run / disk_full / db_lock / scheduler_heartbeat /
  actor_failure_streak / data_freshness_critical / signal_evaluation_stale /
  alpha_report_stale)
- Idempotent UNIQUE(incident_type,target,status='open') — 재detection 시 신규 row X
- resolve 후 재발 시 신규 incident_id (status 가 UNIQUE 의 일부)
- Discord publish — critical=INCIDENTS, warning=OPS, 재detection 시 publish 차단
- helper enum 검증 (log_incident / acknowledge / resolve)
- CLI smoke (scan / list_open / acknowledge / resolve)
- audit_ledger 자동 기록
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.sre_incident_agent import (
    ALPHA_REPORT_STALE_DAYS,
    DISK_CRIT_PCT,
    DISK_WARN_PCT,
    FAILURE_STREAK_CRIT,
    FAILURE_STREAK_WARN,
    FRESHNESS_FAIL_CRIT,
    FRESHNESS_FAIL_WARN,
    ORPHAN_CRIT_HOURS,
    ORPHAN_WARN_HOURS,
    SIGNAL_EVAL_CRIT_DAYS,
    SIGNAL_EVAL_WARN_DAYS,
    SREIncidentAgent,
    _human_incident_summary,
    _missed_eval_days,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import (
    acknowledge_incident,
    get_db,
    init_db,
    log_incident,
    query,
    resolve_incident,
    start_agent_run,
)
from nuri.core.timezone import KST

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sre.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch(
            "nuri.agents.base.log_agent_audit",
            side_effect=make_redirect(db_module.log_agent_audit),
        ),
        patch(
            "nuri.agents.base.start_agent_run",
            side_effect=make_redirect(db_module.start_agent_run),
        ),
        patch(
            "nuri.agents.base.finish_agent_run",
            side_effect=make_redirect(db_module.finish_agent_run),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.log_incident",
            side_effect=make_redirect(db_module.log_incident),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.db_acknowledge_incident",
            side_effect=make_redirect(db_module.acknowledge_incident),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.db_resolve_incident",
            side_effect=make_redirect(db_module.resolve_incident),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture
def no_publish():
    """Discord publish mock — 모든 테스트 default."""
    with patch("nuri.agents.actors.sre_incident_agent.SREIncidentAgent._publish_alert") as m:
        yield m


def _seed_orphan_run(db_path, actor_name: str, hours_ago: float, run_id: str = "orphan-r"):
    """agent_run_ledger 에 started + finished_at NULL row 직접 삽입 (started_at 시각 조절)."""
    start_agent_run(run_id=run_id, actor_name=actor_name, db_path=db_path)
    # started_at 을 hours_ago 시간 이전으로 강제 — datetime 모듈은 SQL 의 julianday 가 처리
    with get_db(db_path) as conn:
        conn.execute(
            """UPDATE agent_run_ledger
               SET started_at = datetime('now', ?)
               WHERE run_id = ?""",
            (f"-{int(hours_ago * 60)} minutes", run_id),
        )


def _seed_failed_runs(db_path, actor_name: str, n: int):
    """agent_run_ledger 에 finished_at 채워진 status='failed' run 을 n 개 삽입."""
    for i in range(n):
        run_id = f"fail-{actor_name}-{i}"
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO agent_run_ledger
                   (run_id, actor_name, status, started_at, finished_at, duration_ms)
                   VALUES (?, ?, 'failed', datetime('now', ?), datetime('now'), 100)""",
                (run_id, actor_name, f"-{n - i} minutes"),
            )


# ═══════════════════════════════════════════════════════
# Layer invariants
# ═══════════════════════════════════════════════════════


class TestSREIncidentAgentLayer:
    def test_actor_layer_is_a(self):
        assert SREIncidentAgent.layer == Layer.A

    def test_no_llm_dependency(self):
        assert getattr(SREIncidentAgent, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("sre-incident-agent") is SREIncidentAgent

    def test_valid_actions_exposed(self):
        assert SREIncidentAgent.VALID_ACTIONS == ("scan", "acknowledge", "resolve", "list_open")


# ═══════════════════════════════════════════════════════
# Invalid action handling
# ═══════════════════════════════════════════════════════


class TestInvalidAction:
    def test_invalid_action_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({"action": "delete"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_action_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Detector: orphan_run
# ═══════════════════════════════════════════════════════


class TestOrphanRunDetector:
    def test_no_orphan_when_recent(self, patched_db, no_publish):
        # 30분 전 시작한 row → ORPHAN_WARN_HOURS=1.0 보다 신선
        _seed_orphan_run(patched_db, actor_name="collector", hours_ago=0.5)
        actor = SREIncidentAgent()
        # 다른 detector 가 시끄럽게 fire 하지 않도록 freshness/scheduler/disk mock
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        assert result.outcome == Outcome.PASS
        orphans = [i for i in result.output["incidents"] if i["incident_type"] == "orphan_run"]
        assert orphans == []

    def test_orphan_warning_at_2h(self, patched_db, no_publish):
        _seed_orphan_run(patched_db, actor_name="collector", hours_ago=2.0)
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        orphans = [i for i in result.output["incidents"] if i["incident_type"] == "orphan_run"]
        assert len(orphans) == 1
        assert orphans[0]["severity"] == "warning"
        assert orphans[0]["target"] == "collector"
        assert orphans[0]["evidence"]["age_hours"] >= ORPHAN_WARN_HOURS

    def test_orphan_critical_at_4h(self, patched_db, no_publish):
        _seed_orphan_run(patched_db, actor_name="collector", hours_ago=4.0)
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        orphans = [i for i in result.output["incidents"] if i["incident_type"] == "orphan_run"]
        assert len(orphans) == 1
        assert orphans[0]["severity"] == "critical"
        assert orphans[0]["evidence"]["age_hours"] >= ORPHAN_CRIT_HOURS


# ═══════════════════════════════════════════════════════
# Detector: disk_full
# ═══════════════════════════════════════════════════════


class TestDiskFullDetector:
    def test_no_alert_below_warn_threshold(self, patched_db, no_publish):
        # 70% — DISK_WARN_PCT=80 보다 낮음
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=700, free=300),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            result = actor.run({"action": "scan"})
        disk = [i for i in result.output["incidents"] if i["incident_type"] == "disk_full"]
        assert disk == []

    def test_warning_at_85pct(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=850, free=150),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            result = actor.run({"action": "scan"})
        disk = [i for i in result.output["incidents"] if i["incident_type"] == "disk_full"]
        assert len(disk) == 1
        assert disk[0]["severity"] == "warning"
        assert disk[0]["target"] == "disk"
        assert disk[0]["evidence"]["percent_used"] > DISK_WARN_PCT

    def test_critical_at_95pct(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            result = actor.run({"action": "scan"})
        disk = [i for i in result.output["incidents"] if i["incident_type"] == "disk_full"]
        assert len(disk) == 1
        assert disk[0]["severity"] == "critical"
        assert disk[0]["evidence"]["percent_used"] > DISK_CRIT_PCT


# ═══════════════════════════════════════════════════════
# Detector: db_lock
# ═══════════════════════════════════════════════════════


class TestDbLockDetector:
    def test_db_ok_no_alert(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        # _detect_db_lock 은 patched query 가 정상 동작하므로 incident 없음
        db_locks = [i for i in result.output["incidents"] if i["incident_type"] == "db_lock"]
        assert db_locks == []


# ═══════════════════════════════════════════════════════
# Detector: scheduler_heartbeat
# ═══════════════════════════════════════════════════════


class TestSchedulerHeartbeatDetector:
    def test_no_alert_when_file_missing(self, patched_db, no_publish, tmp_path):
        nonexistent = tmp_path / "nonexistent_heartbeat"
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.HEARTBEAT_PATH", nonexistent),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        sch = [i for i in result.output["incidents"] if i["incident_type"] == "scheduler_heartbeat"]
        assert sch == []

    def test_warning_when_stale_45min(self, patched_db, no_publish, tmp_path):
        hb = tmp_path / "heartbeat"
        hb.write_text("ok")
        # mtime → 45분 이전
        old_ts = time.time() - 45 * 60
        import os

        os.utime(hb, (old_ts, old_ts))
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.HEARTBEAT_PATH", hb),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        sch = [i for i in result.output["incidents"] if i["incident_type"] == "scheduler_heartbeat"]
        assert len(sch) == 1
        assert sch[0]["severity"] == "warning"

    def test_critical_when_stale_2h(self, patched_db, no_publish, tmp_path):
        hb = tmp_path / "heartbeat"
        hb.write_text("ok")
        old_ts = time.time() - 120 * 60
        import os

        os.utime(hb, (old_ts, old_ts))
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.HEARTBEAT_PATH", hb),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        sch = [i for i in result.output["incidents"] if i["incident_type"] == "scheduler_heartbeat"]
        assert len(sch) == 1
        assert sch[0]["severity"] == "critical"


# ═══════════════════════════════════════════════════════
# Detector: actor_failure_streak
# ═══════════════════════════════════════════════════════


class TestActorFailureStreakDetector:
    def test_warning_at_3_consecutive_failures(self, patched_db, no_publish):
        _seed_failed_runs(patched_db, actor_name="collector", n=FAILURE_STREAK_WARN)
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        streaks = [i for i in result.output["incidents"] if i["incident_type"] == "actor_failure_streak"]
        assert len(streaks) == 1
        assert streaks[0]["severity"] == "warning"
        assert streaks[0]["target"] == "collector"

    def test_critical_at_5_consecutive_failures(self, patched_db, no_publish):
        _seed_failed_runs(patched_db, actor_name="collector", n=FAILURE_STREAK_CRIT)
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        streaks = [i for i in result.output["incidents"] if i["incident_type"] == "actor_failure_streak"]
        assert len(streaks) == 1
        assert streaks[0]["severity"] == "critical"

    def test_no_alert_when_mixed_success(self, patched_db, no_publish):
        # 1개 finished + 2개 failed → streak 미달
        with get_db(patched_db) as conn:
            conn.execute(
                """INSERT INTO agent_run_ledger
                   (run_id, actor_name, status, started_at, finished_at)
                   VALUES ('ok-1', 'collector', 'finished', datetime('now','-1 minutes'), datetime('now'))"""
            )
        _seed_failed_runs(patched_db, actor_name="collector", n=2)
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        streaks = [i for i in result.output["incidents"] if i["incident_type"] == "actor_failure_streak"]
        assert streaks == []


# ═══════════════════════════════════════════════════════
# Detector: data_freshness_critical
# ═══════════════════════════════════════════════════════


class TestDataFreshnessCriticalDetector:
    def test_no_alert_when_all_pass(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.core.freshness.check_all_freshness",
                return_value=[
                    {"key": "prices", "status": "PASS", "label": "x"},
                    {"key": "macro", "status": "PASS", "label": "y"},
                ],
            ),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        fr = [i for i in result.output["incidents"] if i["incident_type"] == "data_freshness_critical"]
        assert fr == []

    def test_warning_when_1_fail(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.core.freshness.check_all_freshness",
                return_value=[
                    {"key": "prices", "status": "FAIL", "label": "x"},
                ],
            ),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        fr = [i for i in result.output["incidents"] if i["incident_type"] == "data_freshness_critical"]
        assert len(fr) == 1
        assert fr[0]["severity"] == "warning"
        assert fr[0]["evidence"]["fail_count"] >= FRESHNESS_FAIL_WARN

    def test_critical_when_3_fails(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.core.freshness.check_all_freshness",
                return_value=[
                    {"key": "a", "status": "FAIL", "label": "A"},
                    {"key": "b", "status": "FAIL", "label": "B"},
                    {"key": "c", "status": "FAIL", "label": "C"},
                ],
            ),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        fr = [i for i in result.output["incidents"] if i["incident_type"] == "data_freshness_critical"]
        assert len(fr) == 1
        assert fr[0]["severity"] == "critical"
        assert fr[0]["evidence"]["fail_count"] >= FRESHNESS_FAIL_CRIT


# ═══════════════════════════════════════════════════════
# Detector: signal_evaluation_stale (#825)
# ═══════════════════════════════════════════════════════

# 고정 now (KST 2026-07-08 수요일 13:00, grace hour 이후) — kst_now 를 patch 하므로
# wall-clock 무관 (time-bomb seed 아님, tests/CLAUDE.md 참고). seed timestamp 는
# pipeline_events.timestamp 컨벤션(UTC, DEFAULT datetime('now')) 그대로 사용.
_EVAL_FIXED_NOW = datetime(2026, 7, 8, 13, 0, tzinfo=KST)  # 수요일


def _seed_signal_eval(db_path, ts_utc: str):
    """pipeline_events 에 signal_evaluation_run heartbeat 1행 삽입 (timestamp 명시)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (event_type, timestamp, record_count) VALUES ('signal_evaluation_run', ?, 0)",
            (ts_utc,),
        )


class TestSignalEvaluationStaleDetector:
    """#825 Gotcha-Test Pair — 'N영업일째 평가 미실행' 시나리오.

    heartbeat (signal_evaluation_run) 공백 영업일(KST 화~토) ≥ 2 → warning,
    ≥ 4 → critical. heartbeat 전무 → skip (미배포/신규 DB).
    """

    def _scan_stale(self, now=_EVAL_FIXED_NOW):
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=now),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        return [i for i in result.output["incidents"] if i["incident_type"] == "signal_evaluation_stale"]

    def test_no_alert_when_no_heartbeat_rows(self, patched_db, no_publish):
        """heartbeat 행 전무 → skip (미배포/신규 DB false positive 방지)."""
        assert self._scan_stale() == []

    def test_no_alert_when_evaluated_today(self, patched_db, no_publish):
        """당일 07:00 KST 평가 (= UTC 전날 22:00) → 공백 0 → alert 없음."""
        _seed_signal_eval(patched_db, "2026-07-07 22:00:00")
        assert self._scan_stale() == []

    def test_warning_at_2_missed_eval_days(self, patched_db, no_publish):
        """마지막 평가 토 07:00 KST → 화+수 2영업일 미실행 → warning (주말 미계상)."""
        _seed_signal_eval(patched_db, "2026-07-03 22:00:00")  # 토 2026-07-04 07:00 KST
        out = self._scan_stale()
        assert len(out) == 1
        assert out[0]["severity"] == "warning"
        assert out[0]["target"] == "signals"
        # UTC→KST 변환 lock: KST 오독 시 토요일까지 계상돼 3이 된다.
        assert out[0]["evidence"]["missed_eval_days"] == SIGNAL_EVAL_WARN_DAYS

    def test_critical_at_4plus_missed_eval_days(self, patched_db, no_publish):
        """마지막 평가 수 07:00 KST (1주 전) → 목금토화수 5영업일 미실행 → critical."""
        _seed_signal_eval(patched_db, "2026-06-30 22:00:00")  # 수 2026-07-01 07:00 KST
        out = self._scan_stale()
        assert len(out) == 1
        assert out[0]["severity"] == "critical"
        assert out[0]["evidence"]["missed_eval_days"] >= SIGNAL_EVAL_CRIT_DAYS

    def test_latest_heartbeat_wins(self, patched_db, no_publish):
        """오래된 heartbeat 가 있어도 최신 행 기준으로 판정."""
        _seed_signal_eval(patched_db, "2026-06-30 22:00:00")
        _seed_signal_eval(patched_db, "2026-07-07 22:00:00")
        assert self._scan_stale() == []


class TestMissedEvalDays:
    """_missed_eval_days 헬퍼 단위 검증 (pure function)."""

    def test_utc_timestamp_converted_to_kst(self):
        """UTC 전날 22:00 = 당일 07:00 KST → 공백 0. to_kst 변환 제거 시 1로 FAIL."""
        assert _missed_eval_days("2026-07-07 22:00:00", _EVAL_FIXED_NOW) == 0

    def test_grace_hour_excludes_today_before_noon(self):
        """오전 scan 은 당일을 미계상 — 07:00 cron 전 false positive 방지."""
        morning = datetime(2026, 7, 8, 9, 0, tzinfo=KST)  # 수 09:00 < grace 12:00
        assert _missed_eval_days("2026-07-03 22:00:00", morning) == 1  # 화요일만

    def test_weekend_not_counted(self):
        """일·월요일(평가 예정일 아님)은 공백으로 계상하지 않는다."""
        monday = datetime(2026, 7, 6, 15, 0, tzinfo=KST)  # 월 15:00
        assert _missed_eval_days("2026-07-03 22:00:00", monday) == 0

    def test_weekday_streak_counted(self):
        """평일 연속 공백은 하루 1씩 계상."""
        assert _missed_eval_days("2026-06-30 22:00:00", _EVAL_FIXED_NOW) == 5


# ═══════════════════════════════════════════════════════
# Detector: alpha_report_stale (#894)
# ═══════════════════════════════════════════════════════


def _seed_alpha_run(
    db_path,
    ts_utc: str,
    *,
    staged: bool,
    role_ok: bool = True,
    error: str | None = None,
    already_emitted: bool = False,
    raw_payload: str | None = None,
):
    """pipeline_events 에 alpha_report_run heartbeat 1행 (payload 는 scheduler 와 동일 스키마).

    `raw_payload` 는 스키마를 벗어난 payload 를 그대로 넣기 위한 탈출구 (파싱 실패 경로 검증용).
    """
    payload = raw_payload or json.dumps(
        {
            "month": ts_utc[:7],
            "role_ok": role_ok,
            "already_emitted": already_emitted,
            "staged": staged,
            "error": error,
        },
        ensure_ascii=False,
    )
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (event_type, timestamp, payload) VALUES ('alpha_report_run', ?, ?)",
            (ts_utc, payload),
        )


class TestAlphaReportStaleDetector:
    """#894 Gotcha-Test Pair — '월간 alpha 리포트가 안 나가는데 아무도 모른다'.

    핵심은 heartbeat 공백이 **아니라** 마지막 *성공 stage* 공백을 잰다는 것.
    cron 이 매일이라 `NURI_ROLE` 누락 상태에서도 heartbeat 는 매일 찍히므로,
    공백만 재는 구현으로 되돌리면 `test_role_missing_alerts_even_though_heartbeats_are_daily`
    가 FAIL 한다 — 그게 이슈가 잡으라고 한 바로 그 시나리오다.
    """

    def _scan(self, now=_EVAL_FIXED_NOW):
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=now),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        return [i for i in result.output["incidents"] if i["incident_type"] == "alpha_report_stale"]

    def test_no_alert_when_no_heartbeat_rows(self, patched_db, no_publish):
        """heartbeat 전무 → skip (미배포/신규 DB false positive 방지)."""
        assert self._scan() == []

    def test_no_alert_on_healthy_monthly_cadence(self, patched_db, no_publish):
        """정상 운영: 매일 heartbeat + 이번 달 1일 성공 stage → 오탐 0.

        acceptance '정상 월간 발화는 알림 없음'.
        """
        _seed_alpha_run(patched_db, "2026-07-01 00:00:00", staged=True)
        for day in range(2, 9):  # 이후 매일 heartbeat (이미 발화 → staged=False)
            _seed_alpha_run(patched_db, f"2026-07-{day:02d} 00:00:00", staged=False)
        assert self._scan() == []

    def test_role_missing_alerts_even_though_heartbeats_are_daily(self, patched_db, no_publish):
        """`NURI_ROLE` 누락 — heartbeat 는 매일 찍히지만 성공 stage 가 한 번도 없다.

        acceptance 'role 누락 상태를 35일 안에 #incidents 가 잡는다'. heartbeat
        공백 기준 구현으로 되돌리면 공백이 0 이라 영영 안 잡히고 이 테스트가 FAIL.
        """
        for offset in range(40):  # 2026-05-30 부터 40일치 daily heartbeat, 전부 미발화
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False, role_ok=False)
        out = self._scan()
        assert len(out) == 1
        assert out[0]["severity"] == "warning"
        assert out[0]["target"] == "alpha_report"
        e = out[0]["evidence"]
        assert e["never_staged"] is True
        assert e["days_since_staged"] >= ALPHA_REPORT_STALE_DAYS
        assert e["last_skip_reason"] == "role_missing"

    def test_stale_since_last_successful_stage(self, patched_db, no_publish):
        """예전에 성공한 적은 있으나 그 뒤 35일 넘게 미발화 → 알림."""
        _seed_alpha_run(patched_db, "2026-05-01 00:00:00", staged=True)
        _seed_alpha_run(patched_db, "2026-07-08 00:00:00", staged=False, role_ok=False)
        out = self._scan()
        assert len(out) == 1
        assert out[0]["evidence"]["never_staged"] is False
        assert out[0]["evidence"]["last_staged_at_utc"].startswith("2026-05-01")

    def test_recent_success_suppresses_alert_despite_old_failures(self, patched_db, no_publish):
        """오래된 미발화가 남아 있어도 최근 성공이 있으면 알림 없음."""
        _seed_alpha_run(patched_db, "2026-05-01 00:00:00", staged=False, role_ok=False)
        _seed_alpha_run(patched_db, "2026-07-01 00:00:00", staged=True)
        assert self._scan() == []

    def test_error_skip_reason_surfaces_the_exception(self, patched_db, no_publish):
        """예외로 못 나간 경우 evidence 가 role 누락과 구분된다 (조치가 다르다)."""
        for offset in range(40):
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False, error="boom")
        out = self._scan()
        assert out[0]["evidence"]["last_skip_reason"] == "error"
        assert out[0]["evidence"]["last_error"] == "boom"

    def test_already_emitted_skip_reason_is_distinguished(self, patched_db, no_publish):
        """이번 달 리포트가 '이미 나갔다' 고 주장하는데 35일째 성공 stage 가 없다.

        role 누락이나 예외와 조치가 다르다 — 중복 방지 키가 잘못 잡혀 매번 스스로를
        skip 하는 상태이므로, evidence 가 이걸 뭉뚱그리면 엉뚱한 곳을 보게 된다.
        """
        for offset in range(40):
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False, already_emitted=True)
        out = self._scan()
        assert out[0]["evidence"]["last_skip_reason"] == "already_emitted"
        assert out[0]["evidence"]["last_error"] is None

    def test_claims_staged_but_nothing_landed(self, patched_db, no_publish):
        """heartbeat 가 '역할 정상·예외 없음·중복 아님' 이라 말하는데 stage 는 0건.

        가장 위험한 조합이다 — 모든 지표가 초록인데 리포트만 안 나간다 (outbox 가
        None 을 돌려주는 경우). reason 이 'staged' 로 남아야 heartbeat 를 믿지 말고
        outbox 를 보라는 뜻이 전달된다.
        """
        for offset in range(40):
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False)
        out = self._scan()
        assert out[0]["evidence"]["last_skip_reason"] == "staged"

    def _scan_all(self, now=_EVAL_FIXED_NOW):
        """전체 인시던트 — detector 자체가 죽었는지 보려면 db_lock 까지 봐야 한다."""
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=now),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            return actor.run({"action": "scan"}).output["incidents"]

    def test_broken_text_payload_does_not_kill_the_detector(self, patched_db, no_publish):
        """깨진 텍스트 payload 가 섞여도 인시던트는 정상 발화한다 (#927).

        Gotcha lock: 집계 쿼리의 `json_extract` 는 malformed JSON 에 SQLite 단계에서
        `OperationalError` 를 낸다. 가드가 없으면 detector 가 통째로 죽고, scan 루프가
        그걸 `db_lock` 로 바꿔 담는다 — 즉 **'리포트가 안 나간다' 는 사실 자체가 사라진다.**
        감시자를 감시 대상이 죽이는 구조라 `json_valid()` 가드가 있어야 한다.
        """
        for offset in range(40):
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False, role_ok=False)
        _seed_alpha_run(patched_db, "2026-07-09 00:00:00", staged=False, raw_payload="{not json")

        incidents = self._scan_all()
        stale = [i for i in incidents if i["incident_type"] == "alpha_report_stale"]
        assert len(stale) == 1
        assert stale[0]["evidence"]["last_skip_reason"] == "unparseable"
        assert stale[0]["evidence"]["last_error"] is None
        # detector 가 살아 있었다는 증거 — 죽었으면 scan 루프가 db_lock 으로 감싼다
        assert not [
            i for i in incidents if i["incident_type"] == "db_lock" and i["target"] == "_detect_alpha_report_stale"
        ]

    @pytest.mark.parametrize("raw", ["null", "[]", '"x"', "5"])
    def test_non_object_json_payload_still_alerts(self, patched_db, no_publish, raw):
        """객체가 아닌 유효 JSON 도 발화를 막지 못한다 (#927).

        Gotcha lock: 이쪽은 SQLite 를 통과해서 `json.loads` 도 성공하고, `.get` 에서
        비로소 AttributeError 가 난다. 좁은 `except (JSONDecodeError, TypeError, KeyError)`
        는 이걸 못 잡아 그대로 전파됐다 — 사유 추출 실패가 인시던트를 삼키면 안 된다.
        """
        for offset in range(40):
            day = datetime(2026, 5, 30) + timedelta(days=offset)
            _seed_alpha_run(patched_db, day.strftime("%Y-%m-%d 00:00:00"), staged=False, role_ok=False)
        _seed_alpha_run(patched_db, "2026-07-09 00:00:00", staged=False, raw_payload=raw)

        out = self._scan()
        assert len(out) == 1
        assert out[0]["evidence"]["last_skip_reason"] == "unparseable"
        assert out[0]["evidence"]["last_error"] is None

    def test_summary_names_the_cause_not_just_the_type(self):
        """알림 한 줄이 cryptic 코드가 아니라 원인+조치를 담는다 (알림 가독성)."""
        line = _human_incident_summary(
            "alpha_report_stale",
            "alpha_report",
            {"days_since_staged": 41, "never_staged": True, "last_skip_reason": "role_missing"},
        )
        assert "41일째 미발화" in line
        assert "NURI_ROLE" in line


# ═══════════════════════════════════════════════════════
# Idempotent UNIQUE constraint
# ═══════════════════════════════════════════════════════


class TestIdempotentUpsert:
    def test_repeat_detection_keeps_single_open_row(self, patched_db, no_publish):
        """동일 (type, target) 의 open incident 는 1개만 — 재detection 시 last_detected_at update."""
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor.run({"action": "scan"})
            actor.run({"action": "scan"})  # 두 번째 — UPDATE 만 발생
        rows = query(
            "SELECT * FROM incidents WHERE incident_type = 'disk_full' AND status = 'open'",
            db_path=patched_db,
        )
        assert len(rows) == 1

    def test_recurrence_after_resolve_creates_new_row(self, patched_db, no_publish):
        """resolve 후 동일 (type,target) 재발 시 신규 incident_id."""
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            r1 = actor.run({"action": "scan"})
            disk1 = [i for i in r1.output["incidents"] if i["incident_type"] == "disk_full"][0]
            old_id = disk1["incident_id"]
            # resolve → 신규 row 가능
            actor.run({"action": "resolve", "incident_id": old_id})
            r2 = actor.run({"action": "scan"})
            disk2 = [i for i in r2.output["incidents"] if i["incident_type"] == "disk_full"][0]
            new_id = disk2["incident_id"]
        assert new_id != old_id
        assert disk2["is_new"] is True


# ═══════════════════════════════════════════════════════
# acknowledge / resolve / list_open actions
# ═══════════════════════════════════════════════════════


class TestAcknowledgeAction:
    def test_acknowledge_open_incident(self, patched_db, no_publish):
        incident_id = log_incident(
            incident_type="disk_full",
            severity="warning",
            target="disk",
            evidence={},
            db_path=patched_db,
        )
        actor = SREIncidentAgent()
        result = actor.run({"action": "acknowledge", "incident_id": incident_id})
        assert result.outcome == Outcome.PASS
        rows = query(
            "SELECT status FROM incidents WHERE incident_id = ?",
            (incident_id,),
            db_path=patched_db,
        )
        assert rows[0]["status"] == "acknowledged"

    def test_acknowledge_unknown_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({"action": "acknowledge", "incident_id": 999_999})
        assert result.outcome == Outcome.BLOCK

    def test_acknowledge_missing_id_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({"action": "acknowledge"})
        assert result.outcome == Outcome.BLOCK


class TestResolveAction:
    def test_resolve_open_incident(self, patched_db, no_publish):
        incident_id = log_incident(
            incident_type="orphan_run",
            severity="critical",
            target="collector",
            evidence={},
            db_path=patched_db,
        )
        actor = SREIncidentAgent()
        result = actor.run({"action": "resolve", "incident_id": incident_id})
        assert result.outcome == Outcome.PASS
        rows = query(
            "SELECT status, resolved_at FROM incidents WHERE incident_id = ?",
            (incident_id,),
            db_path=patched_db,
        )
        assert rows[0]["status"] == "resolved"
        assert rows[0]["resolved_at"] is not None

    def test_resolve_acknowledged_incident(self, patched_db, no_publish):
        incident_id = log_incident(
            incident_type="orphan_run",
            severity="critical",
            target="collector",
            evidence={},
            db_path=patched_db,
        )
        acknowledge_incident(incident_id, db_path=patched_db)
        actor = SREIncidentAgent()
        result = actor.run({"action": "resolve", "incident_id": incident_id})
        assert result.outcome == Outcome.PASS

    def test_resolve_unknown_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({"action": "resolve", "incident_id": 999_999})
        assert result.outcome == Outcome.BLOCK


class TestListOpenAction:
    def test_list_open_returns_only_open(self, patched_db, no_publish):
        i1 = log_incident("disk_full", "warning", "disk", {}, db_path=patched_db)
        i2 = log_incident("orphan_run", "critical", "collector", {}, db_path=patched_db)
        # 1개 resolve → list_open 에서 제외
        resolve_incident(i1, db_path=patched_db)
        actor = SREIncidentAgent()
        result = actor.run({"action": "list_open"})
        assert result.outcome == Outcome.PASS
        ids = [inc["incident_id"] for inc in result.output["incidents"]]
        assert i2 in ids
        assert i1 not in ids

    def test_list_open_severity_filter(self, patched_db, no_publish):
        log_incident("disk_full", "warning", "disk", {}, db_path=patched_db)
        log_incident("orphan_run", "critical", "collector", {}, db_path=patched_db)
        actor = SREIncidentAgent()
        result = actor.run({"action": "list_open", "severity": "critical"})
        assert result.outcome == Outcome.PASS
        for inc in result.output["incidents"]:
            assert inc["severity"] == "critical"

    def test_list_open_invalid_severity_blocks(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        result = actor.run({"action": "list_open", "severity": "FATAL"})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Discord publish routing
# ═══════════════════════════════════════════════════════


class TestDiscordPublishRouting:
    """PR3 Codex Round 6: critical → outbox stage_incident, warning → stage_ops."""

    def test_critical_stages_to_incidents(self, patched_db):
        with (
            patch("nuri.agents.discord.outbox.stage_incident") as mock_inc,
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor = SREIncidentAgent()
            actor.run({"action": "scan"})
        assert mock_inc.called
        kw = mock_inc.call_args.kwargs
        assert kw["actor_name"] == "sre-incident-agent"
        assert kw["priority"] == "high"

    def test_warning_stages_to_ops(self, patched_db):
        with (
            patch("nuri.agents.discord.outbox.stage_ops") as mock_ops,
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=850, free=150),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor = SREIncidentAgent()
            actor.run({"action": "scan"})
        assert mock_ops.called

    def test_repeat_detection_does_not_restage(self, patched_db):
        """재detection 시 동일 incident → stage 차단 (UNIQUE update)."""
        with (
            patch("nuri.agents.discord.outbox.stage_incident") as mock_inc,
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor = SREIncidentAgent()
            actor.run({"action": "scan"})
            first_count = mock_inc.call_count
            actor.run({"action": "scan"})
            assert mock_inc.call_count == first_count, "재detection 은 stage 안 해야 함"

    def test_publish_failure_does_not_break_scan(self, patched_db):
        """outbox stage 실패해도 scan 자체는 PASS."""
        with (
            patch(
                "nuri.agents.discord.outbox.stage_incident",
                side_effect=RuntimeError("outbox down"),
            ),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=950, free=50),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor = SREIncidentAgent()
            result = actor.run({"action": "scan"})
        assert result.outcome == Outcome.PASS


# ═══════════════════════════════════════════════════════
# helper enum 검증 (HelperLockTests)
# ═══════════════════════════════════════════════════════


class TestHelperEnumLockTests:
    def test_log_incident_invalid_type_raises(self, db_path):
        with pytest.raises(ValueError):
            log_incident(
                incident_type="bogus",
                severity="critical",
                target="x",
                evidence={},
                db_path=db_path,
            )

    def test_log_incident_invalid_severity_raises(self, db_path):
        with pytest.raises(ValueError):
            log_incident(
                incident_type="disk_full",
                severity="FATAL",
                target="disk",
                evidence={},
                db_path=db_path,
            )

    def test_log_incident_empty_target_raises(self, db_path):
        with pytest.raises(ValueError):
            log_incident(
                incident_type="disk_full",
                severity="critical",
                target="",
                evidence={},
                db_path=db_path,
            )

    def test_acknowledge_resolve_returns_false_for_unknown(self, db_path):
        assert acknowledge_incident(999_999, db_path=db_path) is False
        assert resolve_incident(999_999, db_path=db_path) is False

    def test_log_incident_idempotent_returns_same_id(self, db_path):
        id1 = log_incident("disk_full", "warning", "disk", {"k": 1}, db_path=db_path)
        id2 = log_incident("disk_full", "critical", "disk", {"k": 2}, db_path=db_path)
        assert id1 == id2
        # severity 가 update 됐는지 확인
        rows = query(
            "SELECT severity, evidence_json FROM incidents WHERE incident_id = ?",
            (id1,),
            db_path=db_path,
        )
        assert rows[0]["severity"] == "critical"


# ═══════════════════════════════════════════════════════
# Audit trail
# ═══════════════════════════════════════════════════════


class TestAuditTrail:
    def test_scan_decision_audited(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            actor.run({"action": "scan"})
        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert any(
            r["actor_name"] == "sre-incident-agent" and r["layer"] == "A" and r["outcome"] == "pass" for r in rows
        )

    def test_acknowledge_block_audited(self, patched_db, no_publish):
        actor = SREIncidentAgent()
        actor.run({"action": "acknowledge", "incident_id": 999_999})
        rows = query(
            "SELECT outcome FROM agent_audit_ledger WHERE actor_name = 'sre-incident-agent'",
            db_path=patched_db,
        )
        assert any(r["outcome"] == "block" for r in rows)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_scan_returns_0(self, patched_db, capsys):
        with (
            patch("nuri.agents.actors.sre_incident_agent.SREIncidentAgent._publish_alert"),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
        ):
            rc = main(["scan"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "incidents" in out

    def test_cli_list_open_returns_0(self, patched_db, capsys):
        rc = main(["list_open"])
        assert rc == 0

    def test_cli_acknowledge_unknown_returns_2(self, patched_db, capsys):
        rc = main(["acknowledge", "--incident-id", "999999"])
        assert rc == 2

    def test_cli_resolve_unknown_returns_2(self, patched_db, capsys):
        rc = main(["resolve", "--incident-id", "999999"])
        assert rc == 2


class TestHumanIncidentSummary:
    """#incidents 디지스트가 cryptic 코드 대신 영향 수치 한 줄을 보이는지 (alert readability)."""

    def test_scheduler_heartbeat_shows_age_and_threshold(self):
        s = _human_incident_summary("scheduler_heartbeat", "scheduler", {"age_minutes": 42.0, "warn_threshold_min": 30})
        assert "42분째" in s and "임계 30분" in s
        assert "incident_id" not in s  # 의미없는 식별자 헤드라인에서 제거

    def test_disk_full_shows_percent_and_free(self):
        s = _human_incident_summary("disk_full", "disk", {"percent_used": 96.0, "free_gb": 50.0})
        assert "96%" in s and "50GB" in s

    def test_data_freshness_lists_failed_keys(self):
        s = _human_incident_summary(
            "data_freshness_critical", "freshness", {"fail_count": 3, "fail_keys": ["stock", "macro", "news"]}
        )
        assert "3개" in s and "stock" in s

    def test_db_lock_shows_error(self):
        s = _human_incident_summary("db_lock", "db", {"error": "database is locked"})
        assert "db" in s and "database is locked" in s

    def test_orphan_run_shows_age_hours(self):
        s = _human_incident_summary("orphan_run", "stock-collector", {"age_hours": 3.5})
        assert "stock-collector" in s and "3.5h" in s and "orphan" in s

    def test_actor_failure_streak_shows_count(self):
        s = _human_incident_summary("actor_failure_streak", "consensus", {"consecutive_failures": 5})
        assert "consensus" in s and "5회 연속 실패" in s

    def test_signal_evaluation_stale_shows_missed_days_and_last_utc(self):
        s = _human_incident_summary(
            "signal_evaluation_stale",
            "signal-eval",
            {"missed_eval_days": 3, "last_evaluated_at_utc": "2026-07-04 22:00:00"},
        )
        assert "signal-eval" in s and "3영업일째" in s and "2026-07-04 22:00:00" in s

    def test_unknown_type_falls_back_gracefully(self):
        s = _human_incident_summary("brand_new_type", "x", {})
        assert "brand_new_type" in s and "x" in s
