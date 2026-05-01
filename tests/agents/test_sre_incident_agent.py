"""SREIncidentAgent tests (#529 Phase 2 — actor #14, canonical Layer A).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 4 actions: scan / acknowledge / resolve / list_open
- 6 detector 각각 (orphan_run / disk_full / db_lock / scheduler_heartbeat /
  actor_failure_streak / data_freshness_critical)
- Idempotent UNIQUE(incident_type,target,status='open') — 재detection 시 신규 row X
- resolve 후 재발 시 신규 incident_id (status 가 UNIQUE 의 일부)
- Discord publish — critical=INCIDENTS, warning=OPS, 재detection 시 publish 차단
- helper enum 검증 (log_incident / acknowledge / resolve)
- CLI smoke (scan / list_open / acknowledge / resolve)
- audit_ledger 자동 기록
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.sre_incident_agent import (
    DISK_CRIT_PCT,
    DISK_WARN_PCT,
    FAILURE_STREAK_CRIT,
    FAILURE_STREAK_WARN,
    FRESHNESS_FAIL_CRIT,
    FRESHNESS_FAIL_WARN,
    ORPHAN_CRIT_HOURS,
    ORPHAN_WARN_HOURS,
    SREIncidentAgent,
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
