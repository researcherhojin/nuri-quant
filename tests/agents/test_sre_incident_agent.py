"""SREIncidentAgent tests (#529 Phase 2 — actor #14, canonical Layer A).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 4 actions: scan / acknowledge / resolve / list_open
- detector 각각 (orphan_run / disk_full / db_lock / scheduler_heartbeat /
  actor_failure_streak / data_freshness_critical / signal_evaluation_stale /
  alpha_report_stale / frontend_build_stale)
- Idempotent UNIQUE(incident_type,target,status='open') — 재detection 시 신규 row X
- resolve 후 재발 시 신규 incident_id (status 가 UNIQUE 의 일부)
- Discord publish — critical=INCIDENTS, warning=OPS, 재detection 시 publish 차단
- helper enum 검증 (log_incident / acknowledge / resolve)
- CLI smoke (scan / list_open / acknowledge / resolve)
- audit_ledger 자동 기록
"""

from __future__ import annotations

import json
import os
import subprocess
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
    FRONTEND_BUILD_STALE_MIN,
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


# ═══════════════════════════════════════════════════════
# 자동 해소 (#944)
# ═══════════════════════════════════════════════════════


def _seed_open_incident(db_path, incident_type: str, target: str, *, hours_ago: float):
    """open incident 1건 + last_detected_at 백데이트."""
    log_incident(
        incident_type=incident_type,
        severity="warning",
        target=target,
        evidence={"seeded": True},
        db_path=db_path,
    )
    with get_db(db_path) as conn:
        conn.execute(
            """UPDATE incidents SET last_detected_at = datetime('now', ?)
                WHERE incident_type = ? AND target = ? AND status = 'open'""",
            (f"-{int(hours_ago * 60)} minutes", incident_type, target),
        )


def _open_rows(db_path):
    return [
        dict(r)
        for r in query("SELECT incident_type, target, status FROM incidents WHERE status='open'", db_path=db_path)
    ]


class TestIncidentAutoResolve:
    """열기만 하고 닫지 않으면 dedupe 가 재발 알림을 영원히 흡수한다 (#944)."""

    def _scan_all(self, now=_EVAL_FIXED_NOW):
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=now),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            return actor.run({"action": "scan"}).output

    def test_undetected_incident_past_grace_is_resolved(self, patched_db, no_publish):
        """조건이 사라졌고 grace 도 지났으면 닫힌다."""
        _seed_open_incident(patched_db, "orphan_run", "ghost-actor", hours_ago=48)
        out = self._scan_all()
        assert any(r["target"] == "ghost-actor" for r in out["auto_resolved"])
        assert not [r for r in _open_rows(patched_db) if r["target"] == "ghost-actor"]

    def test_within_grace_is_kept(self, patched_db, no_publish):
        """Gotcha lock: grace 안이면 안 닫는다 — 간헐 조건의 열고-닫기 폭풍 방지."""
        _seed_open_incident(patched_db, "orphan_run", "flappy-actor", hours_ago=0.5)
        out = self._scan_all()
        assert not out["auto_resolved"]
        assert [r for r in _open_rows(patched_db) if r["target"] == "flappy-actor"]

    def test_dead_detector_does_not_resolve_its_types(self, patched_db, no_publish):
        """Gotcha lock: **안 보이는 것과 사라진 것은 다르다.**

        detector 가 죽어 조용해진 걸 '해소됨' 으로 읽으면, 고장난 감시자가 진짜
        incident 를 닫아버린다 — 감시 자체가 거짓말이 되는 경로다.
        """
        _seed_open_incident(patched_db, "orphan_run", "ghost-actor", hours_ago=48)
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=_EVAL_FIXED_NOW),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
            patch.object(
                SREIncidentAgent, "_detect_orphan_runs", autospec=True, side_effect=RuntimeError("detector down")
            ),
        ):
            out = actor.run({"action": "scan"}).output

        assert not [r for r in out["auto_resolved"] if r["incident_type"] == "orphan_run"]
        assert [r for r in _open_rows(patched_db) if r["target"] == "ghost-actor"]

    def test_every_detector_is_mapped(self):
        """map 누락 = 그 타입이 detector 사망 중에도 닫힌다 — 조용한 구멍."""
        from nuri.agents.actors.sre_incident_agent import _DETECTOR_INCIDENT_TYPES

        detectors = {n for n in dir(SREIncidentAgent) if n.startswith("_detect_")}
        assert detectors, "detector 스윕이 아무것도 못 찾았다 — 캐너리"
        assert detectors == set(_DETECTOR_INCIDENT_TYPES), (
            f"매핑 누락/잉여: {detectors ^ set(_DETECTOR_INCIDENT_TYPES)}"
        )

    def test_still_detected_incident_is_not_resolved(self, patched_db, no_publish):
        """Gotcha lock: 이번 스캔에서 감지된 인시던트는 오래됐어도 닫지 않는다.

        통상 경로에서는 `_record_incident` 가 재감지 시 `last_detected_at` 을 갱신해
        grace 쿼리가 먼저 걸러낸다. 그래서 `_auto_resolve` 를 직접 불러 계약을 검증한다
        — 갱신 경로가 바뀌어도(로그 실패, 쿼리 변경) **발화 중인 장애가 조용히 resolved
        로 사라지지 않아야** 한다.
        """
        _seed_open_incident(patched_db, "orphan_run", "stuck-actor", hours_ago=48)
        detected = [{"incident_type": "orphan_run", "target": "stuck-actor"}]

        resolved, _errors = SREIncidentAgent()._auto_resolve(detected, failed_detectors=set())

        assert not [r for r in resolved if r["target"] == "stuck-actor"]
        assert [r for r in _open_rows(patched_db) if r["target"] == "stuck-actor"]


# ═══════════════════════════════════════════════════════
# health_check.sh 흡수 detector 3종 (#939)
# ═══════════════════════════════════════════════════════


class TestAbsorbedHealthChecks:
    """`health_check.sh` 의 고유 검사를 알림 경로가 있는 detector 로 이식 (#939).

    그 스크립트는 `echo` 만 하고 DB/Discord 쓰기가 0건이라, 시간마다 로그만 쌓였다.
    게다가 plist 주석은 "SRE-Incident-Agent 가 이 로그를 watch 한다" 고 적어뒀는데
    그런 코드는 없었다 — 광고된 배선이 허구였다. 여기 옮겨야 `log_incident` +
    Discord publish 를 탄다.
    """

    def _detect(self, name: str, **patches):
        actor = SREIncidentAgent()
        ctx = MagicMock(run_id="test-run")
        with patch.object(SREIncidentAgent, "_publish_alert"):
            return getattr(actor, name)(ctx)

    def test_schema_drift_expected_version_comes_from_code(self, patched_db, no_publish):
        """기대값은 `_MIGRATIONS` 에서 도출 — 상수를 박으면 이후 마이그레이션을 못 잡는다.

        `health_check.sh` 는 `>= 40` 하드코딩이라 41~49 누락을 통과시켰다.
        """
        from nuri.core.db_migrations import _MIGRATIONS

        expected = max(v for v, _, _ in _MIGRATIONS)
        # schema_version 테이블을 실제로 되돌려 detector 가 읽는 경로 그대로 검증한다.
        with get_db(patched_db) as conn:
            conn.execute("DELETE FROM schema_version WHERE version > ?", (expected - 3,))
        out = self._detect("_detect_schema_version_drift")
        assert len(out) == 1
        e = out[0]["evidence"]
        assert e["expected_version"] == expected and e["missing_migrations"] == 3
        assert out[0]["severity"] == "critical"

    def test_schema_drift_silent_when_current(self, patched_db, no_publish):
        assert self._detect("_detect_schema_version_drift") == []

    def test_missing_table_is_reported(self, patched_db, no_publish):
        with patch(
            "nuri.agents.actors.sre_incident_agent.REQUIRED_TABLES",
            ("incidents", "definitely_not_a_table"),
        ):
            out = self._detect("_detect_required_tables_missing")
        assert len(out) == 1
        assert out[0]["evidence"]["missing"] == ["definitely_not_a_table"]
        assert out[0]["severity"] == "critical"

    def test_all_required_tables_present_is_silent(self, patched_db, no_publish):
        """init_db() 가 만든 스키마는 필수 테이블을 전부 갖춰야 한다."""
        assert self._detect("_detect_required_tables_missing") == []

    @pytest.mark.parametrize(
        ("hostname", "expect_incident", "role"),
        [
            ("Ehbebeui-Macmini", False, "primary"),
            ("Ehbebeui-MacBookPro", True, "replica"),
            ("some-random-host", True, "unknown"),
        ],
    )
    def test_writer_role(self, patched_db, no_publish, hostname, expect_incident, role):
        """writer actor 가 primary 밖에서 돌면 원장이 갈라진다 (§3.11 단일 원장)."""
        with patch("nuri.agents.actors.sre_incident_agent.socket.gethostname", return_value=hostname):
            out = self._detect("_detect_writer_role")
        assert bool(out) is expect_incident
        if expect_incident:
            assert out[0]["evidence"]["role"] == role
            assert out[0]["severity"] == "warning"


# ═══════════════════════════════════════════════════════
# Detector: frontend_build_stale (#1463)
# ═══════════════════════════════════════════════════════


def _git(cwd, *args: str, when: int | None = None) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{when} +0000"
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture()
def prod_frontend(tmp_path):
    """primary 머신 흉내: frontend/ 커밋 하나를 가진 레포 + detector 경로를 그리로 돌린다.

    반환값은 (frontend_dir, commit_epoch). `set_build(epoch)` 로 BUILD_ID mtime 을 놓는다.
    """
    repo = tmp_path / "repo"
    fe = repo / "frontend"
    (fe / "app").mkdir(parents=True)
    (fe / "app" / "page.tsx").write_text("export default () => null;\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    commit_epoch = int(time.time()) - 3 * 3600  # 3h 전 커밋
    _git(repo, "commit", "-m", "seed", when=commit_epoch)

    def set_build(epoch: float):
        (fe / ".next").mkdir(exist_ok=True)
        bid = fe / ".next" / "BUILD_ID"
        bid.write_text("build-x")
        os.utime(bid, (epoch, epoch))
        return bid

    def commit(when: int) -> str:
        """frontend/ 에 커밋 하나 더 (커밋 시각 고정). 반환: sha."""
        (fe / "app" / "page.tsx").write_text(f"export default () => {when};\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "touch", when=when)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

    with (
        patch("nuri.agents.actors.sre_incident_agent._machine_role", return_value="primary"),
        patch("nuri.agents.actors.sre_incident_agent.REPO_ROOT", repo),
        patch("nuri.agents.actors.sre_incident_agent.FRONTEND_DIR", fe),
    ):
        yield type(
            "P",
            (),
            {
                "fe": fe,
                "repo": repo,
                "commit_epoch": commit_epoch,
                "set_build": staticmethod(set_build),
                "commit": staticmethod(commit),
            },
        )


class TestFrontendBuildStaleDetector:
    """#1463 Gotcha-Test Pair — '프로덕션 프론트 빌드가 계속 실패하는데 아무도 모른다'.

    핵심은 mtime 비교만이 아니라 `build_frontend.sh` 의 마커 둘을 읽는 것이다. 그 스크립트는
    같은 커밋을 재시도하지 않으므로(`.next.failed`), 마커를 안 보면 계속 실패하는 빌드는 mtime
    드리프트로만 보이고 — 그마저 이전 빌드가 복원돼 있어 "낡음" 으로 뭉뚱그려진다. 실패는
    실패라고 말해야 조치(`--retry`)가 나온다.
    """

    def _scan(self):
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        return result.output["incidents"]

    def _mine(self, incidents):
        return [i for i in incidents if i["incident_type"] == "frontend_build_stale"]

    def test_current_build_is_silent(self, patched_db, no_publish, prod_frontend):
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        assert self._mine(self._scan()) == []

    def test_recent_commit_not_yet_built_is_normal(self, patched_db, no_publish, prod_frontend):
        """autopull 이 5분마다 따라잡는다 — 방금 온 커밋이 아직 안 빌드된 건 사고가 아니다."""
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        prod_frontend.commit(int(time.time()) - 10 * 60)  # 10분 전 커밋, 빌드보다 새롭다
        assert self._mine(self._scan()) == []

    def test_small_gap_that_persists_past_threshold_warns(self, patched_db, no_publish, prod_frontend):
        """잠금(Codex P1) — 낡음은 **미빌드 지속 시간**이지 커밋−빌드 간격이 아니다.

        빌드 T, 커밋 T+1분, 그 뒤 3시간 동안 마커 없는 실패(npm 부재·락 경합)가 반복되면 간격은
        영원히 1분이다. 간격 기준 구현으로 되돌리면 이 테스트가 FAIL 한다.
        """
        prod_frontend.set_build(prod_frontend.commit_epoch - 60)  # 3h 전 커밋보다 1분 오래된 빌드
        out = self._mine(self._scan())
        assert len(out) == 1
        assert out[0]["severity"] == "warning" and out[0]["target"] == "frontend_build"
        e = out[0]["evidence"]
        assert e["reason"] == "stale" and e["build_missing"] is False
        assert e["unbuilt_minutes"] > FRONTEND_BUILD_STALE_MIN
        assert e["code_commit"] and e["code_committed_at_utc"] and e["build_id_mtime_utc"]

    def test_build_in_progress_is_not_judged(self, patched_db, no_publish, prod_frontend):
        """빌드 중에는 .next 가 .next.bak 으로 비켜나 BUILD_ID 가 없다 — 락 pid 가 살아 있으면 skip."""
        lock = prod_frontend.fe / ".next.lock"
        lock.mkdir()
        holder = subprocess.Popen(["sleep", "30"])
        try:
            (lock / "pid").write_text(str(holder.pid))
            assert self._mine(self._scan()) == []
        finally:
            holder.kill()

    def test_dead_lock_holder_does_not_hide_a_missing_build(self, patched_db, no_publish, prod_frontend):
        lock = prod_frontend.fe / ".next.lock"
        lock.mkdir()
        dead = subprocess.Popen(["true"])
        dead.wait()
        (lock / "pid").write_text(str(dead.pid))
        out = self._mine(self._scan())
        assert len(out) == 1 and out[0]["evidence"]["build_missing"] is True

    def test_failed_marker_for_an_older_commit_is_not_a_failure_yet(self, patched_db, no_publish, prod_frontend):
        """새 커밋이 왔고 다음 주기가 마커를 지우고 재시도한다 — 옛 sha 마커는 실패가 아니다."""
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        (prod_frontend.fe / ".next.failed").write_text("0000000000000000000000000000000000000000\n")
        prod_frontend.commit(int(time.time()) - 5 * 60)
        assert self._mine(self._scan()) == []

    def test_failed_marker_beats_a_fresh_pending_marker(self, patched_db, no_publish, prod_frontend):
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        sha = prod_frontend.commit(int(time.time()) - 5 * 60)
        (prod_frontend.fe / ".next.failed").write_text(sha + "\n")
        (prod_frontend.fe / ".next.restart_pending").touch()
        out = self._mine(self._scan())
        assert len(out) == 1 and out[0]["evidence"]["reason"] == "build_failed"

    def test_missing_build_on_primary_warns(self, patched_db, no_publish, prod_frontend):
        """BUILD_ID 자체가 없다 — 재부팅 뒤 빈 대시보드가 뜨는 상태."""
        out = self._mine(self._scan())
        assert len(out) == 1
        assert out[0]["evidence"]["reason"] == "stale" and out[0]["evidence"]["build_missing"] is True

    def test_failed_marker_wins_even_when_build_looks_current(self, patched_db, no_publish, prod_frontend):
        """잠금 — 실패 후 이전 빌드가 복원돼 mtime 만 보면 '낡음' 이거나, 복원본이 최근이면
        아예 조용하다. 마커를 안 읽는 구현으로 되돌리면 이 테스트가 FAIL 한다."""
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=prod_frontend.repo, capture_output=True, text=True
        ).stdout.strip()
        (prod_frontend.fe / ".next.failed").write_text(sha + "\n")
        out = self._mine(self._scan())
        assert len(out) == 1
        e = out[0]["evidence"]
        assert e["reason"] == "build_failed"
        assert e["failed_commit"] == sha

    def test_fresh_restart_pending_marker_is_not_yet_an_incident(self, patched_db, no_publish, prod_frontend):
        """방금 빌드하고 재기동 중일 수 있다 — 한 주기 안의 마커는 정상."""
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        (prod_frontend.fe / ".next.restart_pending").touch()
        assert self._mine(self._scan()) == []

    def test_restart_pending_past_threshold_warns(self, patched_db, no_publish, prod_frontend):
        prod_frontend.set_build(prod_frontend.commit_epoch + 60)
        mark = prod_frontend.fe / ".next.restart_pending"
        mark.touch()
        old = time.time() - (FRONTEND_BUILD_STALE_MIN + 5) * 60
        os.utime(mark, (old, old))
        out = self._mine(self._scan())
        assert len(out) == 1 and out[0]["evidence"]["reason"] == "restart_failed"

    def test_replica_and_unknown_hosts_are_ignored(self, patched_db, no_publish, prod_frontend):
        """dev 머신의 .next 는 의미가 없다 — primary 밖에서는 발화하지 않는다."""
        for role in ("replica", "unknown"):
            with patch("nuri.agents.actors.sre_incident_agent._machine_role", return_value=role):
                assert self._mine(self._scan()) == [], role

    def test_no_frontend_dir_is_skipped(self, patched_db, no_publish, prod_frontend):
        with patch("nuri.agents.actors.sre_incident_agent.FRONTEND_DIR", prod_frontend.repo / "nope"):
            assert self._mine(self._scan()) == []

    def test_git_failure_surfaces_as_detector_failure_not_silence(self, patched_db, no_publish, prod_frontend):
        """git 이 죽으면 '감시가 안 된다' 가 남아야 한다 — 조용한 skip 이면 사고와 구분이 안 된다."""
        # 존재하는 디렉터리지만 git 레포가 아니다 — 없는 경로면 cwd 오류라 `check=` 와 무관하게
        # 죽어서, git 의 비정상 종료를 삼키는 회귀(check=False)를 못 잡는다.
        plain = prod_frontend.repo.parent / "plain-dir"
        plain.mkdir()
        with patch("nuri.agents.actors.sre_incident_agent.REPO_ROOT", plain):
            incidents = self._scan()
        assert self._mine(incidents) == []
        failures = [
            i for i in incidents if i["incident_type"] == "db_lock" and i["target"] == "_detect_frontend_build_stale"
        ]
        assert len(failures) == 1

    def test_resolves_once_build_catches_up(self, patched_db, no_publish, prod_frontend):
        """조건이 풀리면 기존 `_auto_resolve` 가 닫는다 — 열기만 하는 detector 는 재발 알림을 삼킨다."""
        bid = prod_frontend.set_build(prod_frontend.commit_epoch - 60)
        assert len(self._mine(self._scan())) == 1
        with get_db(patched_db) as conn:
            conn.execute(
                "UPDATE incidents SET last_detected_at = datetime('now', '-48 hours') WHERE incident_type = 'frontend_build_stale'"
            )
        os.utime(bid, None)  # 빌드가 따라잡음
        actor = SREIncidentAgent()
        with (
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            out = actor.run({"action": "scan"}).output
        assert [r for r in out["auto_resolved"] if r["incident_type"] == "frontend_build_stale"]

    @pytest.mark.parametrize(
        ("evidence", "needle"),
        [
            ({"reason": "build_failed", "failed_commit": "deadbeefcafe"}, "deadbeef"),
            ({"reason": "restart_failed"}, "재기동"),
            ({"reason": "stale", "build_missing": True}, "BUILD_ID"),
            (
                {
                    "reason": "stale",
                    "build_missing": False,
                    "unbuilt_minutes": 540.0,
                    "code_committed_at_utc": "2026-09-08 04:43:20",
                    "build_id_mtime_utc": "2026-08-29 20:58:00",
                },
                "540분",
            ),
        ],
    )
    def test_human_summary_names_the_cause(self, evidence, needle):
        text = _human_incident_summary("frontend_build_stale", "frontend_build", evidence)
        assert needle in text and "frontend_build_stale on" not in text

    def test_outbox_has_meta_for_the_kind(self):
        """#ops 디지스트가 cryptic 타입명 대신 의미+조치를 보이게 (alert readability)."""
        from nuri.agents.discord.outbox import _SRE_KIND_META

        meta = _SRE_KIND_META["sre_frontend_build_stale"]
        assert "--retry" in meta["action"]


# ═══════════════════════════════════════════════════════
# #1466 — 같은 (type, target) 을 두 번 resolve 할 수 있어야 한다
# ═══════════════════════════════════════════════════════


class TestIncidentCanBeResolvedTwice:
    """#1466 Gotcha-Test Pair — 'SRE 스캔이 38시간째 UNIQUE 충돌로 죽는데 아무도 모른다'.

    `UNIQUE(incident_type, target, status)` 는 resolved 에도 걸려 두 번째 해소가 첫 번째와
    충돌했다. 2026-09-06 16:01 부터 `_auto_resolve` 가 매시간 그 지점에서 스캔 전체를 죽였다.
    migration 63 이 유일성을 open 행 한정 partial index 로 바꾼다 — 그 마이그레이션을 빼면
    `test_second_resolution_of_the_same_incident_succeeds` 가 IntegrityError 로 FAIL 한다.
    """

    def test_second_resolution_of_the_same_incident_succeeds(self, db_path):
        """open → resolve → 재발(open) → resolve. 두 번째 resolve 가 프로덕션에서 죽던 줄이다."""
        first = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 1}, db_path=db_path)
        assert resolve_incident(first, db_path=db_path) is True
        second = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 2}, db_path=db_path)
        assert second != first, "재발이 새 행이어야 두 번째 resolve 가 의미가 있다"
        assert resolve_incident(second, db_path=db_path) is True
        rows = query(
            "SELECT status FROM incidents WHERE incident_type='scheduler_heartbeat' AND target='scheduler'",
            db_path=db_path,
        )
        assert [r["status"] for r in rows] == ["resolved", "resolved"]

    def test_open_uniqueness_is_still_enforced(self, db_path):
        """불변식은 그대로다 — open 은 (type,target) 당 하나. 이게 없으면 dedupe 가 무너진다."""
        from nuri.core.db import DatabaseError  # IntegrityError 의 상위 — sqlite3 직접 import 금지

        log_incident("disk_full", "warning", "disk", {}, db_path=db_path)
        with get_db(db_path) as conn, pytest.raises(DatabaseError):
            conn.execute(
                "INSERT INTO incidents (incident_type, severity, target, status, evidence_json) "
                "VALUES ('disk_full', 'warning', 'disk', 'open', '{}')"
            )

    def test_schema_has_partial_index_not_table_unique(self, db_path):
        """구조 잠금 — 테이블 UNIQUE 가 되살아나면 위 동작 테스트보다 먼저 여기서 이름을 댄다."""
        table_sql = query("SELECT sql FROM sqlite_master WHERE name='incidents'", db_path=db_path)[0]["sql"]
        assert "UNIQUE" not in table_sql, "테이블 UNIQUE(type,target,status) 가 돌아왔다 — #1466 재발"
        idx = query(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_incidents_open_unique'",
            db_path=db_path,
        )
        assert idx and "WHERE status = 'open'" in idx[0]["sql"]

    def test_auto_resolve_closes_a_recurrence_whose_first_episode_was_already_resolved(self, patched_db, no_publish):
        """프로덕션 상태 재현 — #7 resolved + #8 open(3h 지남) → 스캔이 PASS 하고 #8 이 닫힌다."""
        first = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 1}, db_path=patched_db)
        resolve_incident(first, db_path=patched_db)
        _seed_open_incident(patched_db, "scheduler_heartbeat", "scheduler", hours_ago=48)
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=_EVAL_FIXED_NOW),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            result = actor.run({"action": "scan"})
        assert result.outcome == Outcome.PASS
        assert any(r["target"] == "scheduler" for r in result.output["auto_resolved"])
        assert result.output["resolve_errors"] == []
        assert not [r for r in _open_rows(patched_db) if r["target"] == "scheduler"]

    def test_a_failing_resolve_does_not_kill_the_scan(self, patched_db, no_publish):
        """원장 정리 한 행의 실패가 detector 전부를 멈추면 안 된다 (#894 유형). 삼키지도 않는다."""
        _seed_open_incident(patched_db, "orphan_run", "ghost-actor", hours_ago=48)
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=_EVAL_FIXED_NOW),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
            patch(
                "nuri.agents.actors.sre_incident_agent.db_resolve_incident",
                side_effect=RuntimeError("UNIQUE constraint failed: incidents.incident_type"),
            ),
        ):
            result = actor.run({"action": "scan"})
        assert result.outcome == Outcome.PASS
        errs = result.output["resolve_errors"]
        assert len(errs) == 1 and errs[0]["target"] == "ghost-actor" and "UNIQUE" in errs[0]["error"]
        assert result.output["summary"]["resolve_errors"] == 1
        assert result.output["auto_resolved"] == []

    def test_a_failing_candidate_query_does_not_kill_the_scan(self, patched_db, no_publish):
        """후보 조회 자체가 죽어도(락·fd 고갈) detector 결과는 살아남는다 — 조회 실패는 output 에 남긴다."""
        real_query = __import__("nuri.core.db", fromlist=["query"]).query

        def flaky(sql, *a, **kw):
            if "FROM incidents" in sql and "last_detected_at) <" in sql:
                raise RuntimeError("database is locked")
            kw.setdefault("db_path", patched_db)
            return real_query(sql, *a, **kw)

        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=_EVAL_FIXED_NOW),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
            patch("nuri.agents.actors.sre_incident_agent.query", side_effect=flaky),
        ):
            result = actor.run({"action": "scan"})
        assert result.outcome == Outcome.PASS
        assert "incidents" in result.output and result.output["auto_resolved"] == []
        errs = result.output["resolve_errors"]
        assert len(errs) == 1 and "locked" in errs[0]["error"] and errs[0]["incident_id"] is None

    def test_upgrade_from_v62_preserves_rows_and_unblocks_the_second_resolve(self, tmp_path):
        """업그레이드 경로 — 프로덕션 모양(v62 + resolved·open·acknowledged 같은 키)의 DB 에 63 을
        적용한다. 신규 DB 테스트만으로는 `INSERT … SELECT` 컬럼 매핑 오류가 안 잡힌다 (Codex P2)."""
        from nuri.core.db import connection as conn_mod
        from nuri.core.db_migrations import _MIGRATIONS

        path = tmp_path / "v62.db"
        with patch.object(conn_mod, "_MIGRATIONS", [m for m in _MIGRATIONS if m[0] <= 62]):
            init_db(path)
        assert query("SELECT MAX(version) v FROM schema_version", db_path=path)[0]["v"] == 62
        first = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 1}, db_path=path)
        assert resolve_incident(first, db_path=path)
        second = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 2}, db_path=path)
        third = log_incident("disk_full", "warning", "disk", {"n": 3}, db_path=path)
        assert acknowledge_incident(third, db_path=path)
        with get_db(path) as conn:  # v62 는 두 번째 resolve 를 거부한다 — 프로덕션 오류 재현
            with pytest.raises(Exception, match="UNIQUE"):
                conn.execute("UPDATE incidents SET status='resolved' WHERE incident_id = ?", (second,))
        before = query(
            "SELECT incident_id, incident_type, target, status, evidence_json FROM incidents ORDER BY incident_id",
            db_path=path,
        )

        init_db(path)  # → 63

        after = query(
            "SELECT incident_id, incident_type, target, status, evidence_json FROM incidents ORDER BY incident_id",
            db_path=path,
        )
        assert [dict(r) for r in after] == [dict(r) for r in before], "재생성이 행/컬럼을 바꿨다"
        assert query("SELECT MAX(version) v FROM schema_version", db_path=path)[0]["v"] == 63
        assert resolve_incident(second, db_path=path) is True, "프로덕션에서 죽던 두 번째 resolve"
        fourth = log_incident("scheduler_heartbeat", "critical", "scheduler", {"n": 4}, db_path=path)
        assert fourth > third, "AUTOINCREMENT 가 재생성 뒤에도 이어진다"


# ═══════════════════════════════════════════════════════
# #1467 — 감시 자체의 실패는 실제 인시던트다
# ═══════════════════════════════════════════════════════


class TestScanFailuresAreRealIncidents:
    """detector 예외와 원장 정리 실패를 DB row + Discord 로 (#1467).

    예전엔 output JSON 의 합성 항목(`is_new=False`)뿐이라 DB 미기록·미발행 — 감시가 죽어도 아무도
    모르는 형태였고 #1466 이 그 침묵 속에서 38시간을 갔다.
    """

    def _scan(self, **extra_patches):
        actor = SREIncidentAgent()
        with (
            patch("nuri.agents.actors.sre_incident_agent.kst_now", return_value=_EVAL_FIXED_NOW),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                return_value=MagicMock(total=1000, used=100, free=900),
            ),
        ):
            return actor.run({"action": "scan"})

    def test_detector_failure_is_written_and_published(self, patched_db, no_publish):
        with patch.object(SREIncidentAgent, "_detect_orphan_runs", autospec=True, side_effect=RuntimeError("boom")):
            result = self._scan()
        assert result.outcome == Outcome.PASS
        rows = [r for r in _open_rows(patched_db) if r["target"] == "_detect_orphan_runs"]
        assert rows and rows[0]["incident_type"] == "db_lock", "감시 실패가 DB 에 없다 — 예전의 침묵"
        # 이 머신의 writer_role 같은 다른 인시던트도 publish 되므로 대상으로 거른다
        mine = [c for c in no_publish.call_args_list if c.args[3] == "_detect_orphan_runs"]
        assert len(mine) == 1 and mine[0].args[1] == "db_lock" and mine[0].args[2] == "warning", (
            "warning 은 #ops 로 나가야 한다"
        )

    def test_second_failure_does_not_republish(self, patched_db, no_publish):
        """dedupe — 같은 detector 가 매시간 죽어도 알림은 한 번, row 는 하나."""
        with patch.object(SREIncidentAgent, "_detect_orphan_runs", autospec=True, side_effect=RuntimeError("boom")):
            self._scan()
            self._scan()
        assert len([r for r in _open_rows(patched_db) if r["target"] == "_detect_orphan_runs"]) == 1
        assert len([c for c in no_publish.call_args_list if c.args[3] == "_detect_orphan_runs"]) == 1

    def test_recovered_detector_is_auto_resolved(self, patched_db, no_publish):
        with patch.object(SREIncidentAgent, "_detect_orphan_runs", autospec=True, side_effect=RuntimeError("boom")):
            self._scan()
        with get_db(patched_db) as conn:
            conn.execute(
                "UPDATE incidents SET last_detected_at = datetime('now', '-48 hours') WHERE target = '_detect_orphan_runs'"
            )
        out = self._scan().output
        assert any(r["target"] == "_detect_orphan_runs" for r in out["auto_resolved"])
        assert not [r for r in _open_rows(patched_db) if r["target"] == "_detect_orphan_runs"]

    def test_resolve_failure_becomes_an_incident_too(self, patched_db, no_publish):
        _seed_open_incident(patched_db, "orphan_run", "ghost-actor", hours_ago=48)
        with patch(
            "nuri.agents.actors.sre_incident_agent.db_resolve_incident",
            side_effect=RuntimeError("UNIQUE constraint failed"),
        ):
            result = self._scan()
        assert result.outcome == Outcome.PASS
        rows = [r for r in _open_rows(patched_db) if r["target"] == "_auto_resolve"]
        assert rows and rows[0]["incident_type"] == "db_lock"
        assert any(
            i["target"] == "_auto_resolve" and "UNIQUE" in i["evidence"]["error"] for i in result.output["incidents"]
        )

    def test_recording_failure_falls_back_to_a_synthetic_entry(self, patched_db, no_publish):
        """DB 가 진짜 죽었으면 기록도 못 한다 — 그래도 스캔은 PASS 하고 output 에는 남는다."""
        with (
            patch.object(SREIncidentAgent, "_detect_orphan_runs", autospec=True, side_effect=RuntimeError("boom")),
            patch("nuri.agents.actors.sre_incident_agent.log_incident", side_effect=RuntimeError("disk I/O error")),
        ):
            result = self._scan()
        assert result.outcome == Outcome.PASS
        synth = [i for i in result.output["incidents"] if i["target"] == "_detect_orphan_runs"]
        assert len(synth) == 1 and synth[0]["is_new"] is False
        assert "disk I/O error" in synth[0]["evidence"]["record_error"]
