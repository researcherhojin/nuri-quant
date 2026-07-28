"""StateReplicatorDR actor 테스트 — #529 Phase 2 actor #15 (Layer A).

Codex Round 5 Layer A enforcement 정합성:
- input validation (action / replica_id / role / max_lag)
- audit_ledger + run_ledger 자동 기록
- LLM 의존 X (rule-based only)
- BLOCK outcome 시 state 변경 X (idempotent error path)

DR (Disaster Recovery) 핵심 invariant:
- single-writer (primary != replica)
- schema_version mismatch → out_of_sync 자동 update + BLOCK
- lag-based status (healthy < 600s < stale < 3600s ≤ unreachable)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.state_replicator_dr import (
    HEALTHY_LAG_SECONDS,
    StateReplicatorDR,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import get_schema_version, init_db, query, upsert_dr_replica


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "dr.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """state_replicator_dr + base 의 모든 DB 호출을 임시 path 로 redirect."""
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
            "nuri.agents.actors.state_replicator_dr.upsert_dr_replica",
            side_effect=make_redirect(db_module.upsert_dr_replica),
        ),
        patch(
            "nuri.agents.actors.state_replicator_dr.query",
            side_effect=make_redirect(db_module.query),
        ),
        patch(
            "nuri.agents.actors.state_replicator_dr.get_schema_version",
            side_effect=make_redirect(db_module.get_schema_version),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


# ─── Layer A invariants ──────────────────────────────────────


class TestStateReplicatorDRLayer:
    """Layer A enforcement 정합성."""

    def test_actor_layer_is_a(self):
        assert StateReplicatorDR.layer == Layer.A

    def test_actor_name_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert "state-replicator-dr" in REGISTRY.CANONICAL_15
        assert REGISTRY.get("state-replicator-dr") is StateReplicatorDR

    def test_no_llm_dependency(self):
        assert getattr(StateReplicatorDR, "_uses_llm", False) is False


# ─── snapshot action ────────────────────────────────────────


class TestSnapshotAction:
    def test_snapshot_primary(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "snapshot", "replica_id": "macmini-primary", "role": "primary"})
        assert result.outcome == Outcome.PASS
        assert result.output["role"] == "primary"
        assert result.output["status"] == "healthy"
        assert result.output["sync_lag_seconds"] == 0
        assert result.output["last_sync_schema_version"] >= 37

        rows = query("SELECT * FROM dr_replicas", db_path=patched_db)
        assert len(rows) == 1
        assert rows[0]["replica_id"] == "macmini-primary"
        assert rows[0]["role"] == "primary"
        assert rows[0]["status"] == "healthy"

    def test_snapshot_replica_no_heartbeat_unreachable(self, patched_db):
        """heartbeat 파일 없을 때 → unreachable 처리 (Docker 이전 placeholder)."""
        with patch("nuri.agents.actors.state_replicator_dr.HEARTBEAT_PATH") as mock_path:
            mock_path.exists.return_value = False
            actor = StateReplicatorDR()
            result = actor.run({"action": "snapshot", "replica_id": "mbp-replica", "role": "replica"})
        assert result.outcome == Outcome.PASS  # snapshot 자체는 성공
        assert result.output["status"] == "unreachable"
        assert result.output["sync_lag_seconds"] is None
        assert result.output["last_sync_at"] is None

    def test_snapshot_replica_fresh_heartbeat_healthy(self, patched_db, tmp_path):
        """heartbeat 파일 mtime 이 최근 (< 600s) → healthy."""
        hb = tmp_path / ".autopull_heartbeat"
        hb.touch()  # mtime = now
        with patch("nuri.agents.actors.state_replicator_dr.HEARTBEAT_PATH", hb):
            actor = StateReplicatorDR()
            result = actor.run({"action": "snapshot", "replica_id": "mbp-replica", "role": "replica"})
        assert result.outcome == Outcome.PASS
        assert result.output["status"] == "healthy"
        assert result.output["sync_lag_seconds"] is not None
        assert result.output["sync_lag_seconds"] < HEALTHY_LAG_SECONDS

    def test_snapshot_replica_stale_heartbeat(self, patched_db, tmp_path):
        """heartbeat 600 ≤ lag < 3600 → stale."""
        import os
        import time as _time

        hb = tmp_path / ".autopull_heartbeat"
        hb.touch()
        old_ts = _time.time() - 1200  # 20분 전
        os.utime(hb, (old_ts, old_ts))
        with patch("nuri.agents.actors.state_replicator_dr.HEARTBEAT_PATH", hb):
            actor = StateReplicatorDR()
            result = actor.run({"action": "snapshot", "replica_id": "mbp-replica", "role": "replica"})
        assert result.output["status"] == "stale"
        assert 600 <= result.output["sync_lag_seconds"] < 3600

    def test_snapshot_replica_unreachable_heartbeat(self, patched_db, tmp_path):
        """heartbeat lag ≥ 3600 → unreachable."""
        import os
        import time as _time

        hb = tmp_path / ".autopull_heartbeat"
        hb.touch()
        old_ts = _time.time() - 7200  # 2시간 전
        os.utime(hb, (old_ts, old_ts))
        with patch("nuri.agents.actors.state_replicator_dr.HEARTBEAT_PATH", hb):
            actor = StateReplicatorDR()
            result = actor.run({"action": "snapshot", "replica_id": "mbp-replica", "role": "replica"})
        assert result.output["status"] == "unreachable"
        assert result.output["sync_lag_seconds"] >= 3600

    def test_snapshot_missing_replica_id_blocks(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "snapshot", "role": "primary"})
        assert result.outcome == Outcome.BLOCK
        assert "replica_id" in result.output["error"]

    def test_snapshot_missing_role_blocks(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "snapshot", "replica_id": "x"})
        assert result.outcome == Outcome.BLOCK
        assert "role" in result.output["error"]

    def test_snapshot_invalid_role_blocks(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "snapshot", "replica_id": "x", "role": "tertiary"})
        assert result.outcome == Outcome.BLOCK
        rows = query("SELECT COUNT(*) AS c FROM dr_replicas", db_path=patched_db)
        assert rows[0]["c"] == 0  # state 변경 X

    def test_snapshot_idempotent_upsert(self, patched_db):
        """동일 replica_id 두 번 snapshot → row 1개 (upsert)."""
        actor = StateReplicatorDR()
        actor.run({"action": "snapshot", "replica_id": "macmini-primary", "role": "primary"})
        actor.run({"action": "snapshot", "replica_id": "macmini-primary", "role": "primary"})
        rows = query("SELECT * FROM dr_replicas", db_path=patched_db)
        assert len(rows) == 1


# ─── verify action ──────────────────────────────────────────


class TestVerifyAction:
    def test_verify_empty_returns_warn(self, patched_db):
        """replica 등록 X → WARN (snapshot 먼저 실행 안내)."""
        actor = StateReplicatorDR()
        result = actor.run({"action": "verify"})
        assert result.outcome == Outcome.WARN
        assert result.output["summary"]["total"] == 0

    def test_verify_all_healthy_passes(self, patched_db):
        actor = StateReplicatorDR()
        actor.run({"action": "snapshot", "replica_id": "macmini-primary", "role": "primary"})
        # replica 도 healthy 로 직접 등록 (heartbeat probe 우회)
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp-test",
            last_sync_at="2026-05-01 12:00:00",
            # 이 테스트의 관심사는 'replica 가 동기 상태인가' 지 특정 버전이 아니다.
            # 리터럴로 두면 migration 이 추가될 때마다 무관한 이 테스트가 깨진다 (#894 에서 실제로 깨짐).
            # 버전 자체의 lock 은 tests/core/test_agent_infra.py::test_schema_version_at_46 담당.
            last_sync_schema_version=get_schema_version(patched_db),
            sync_lag_seconds=120,
            status="healthy",
            db_path=patched_db,
        )
        result = actor.run({"action": "verify"})
        assert result.outcome == Outcome.PASS
        assert result.output["summary"]["healthy"] == 2

    def test_verify_stale_returns_warn(self, patched_db):
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 11:30:00",
            last_sync_schema_version=42,
            sync_lag_seconds=1800,
            status="stale",
            db_path=patched_db,
        )
        actor = StateReplicatorDR()
        result = actor.run({"action": "verify"})
        assert result.outcome == Outcome.WARN
        assert len(result.output["warns"]) == 1
        assert result.output["warns"][0]["status"] == "stale"

    def test_verify_unreachable_blocks(self, patched_db):
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 09:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=10800,
            status="unreachable",
            db_path=patched_db,
        )
        actor = StateReplicatorDR()
        result = actor.run({"action": "verify"})
        assert result.outcome == Outcome.BLOCK
        assert len(result.output["blocks"]) == 1
        assert result.output["blocks"][0]["status"] == "unreachable"

    def test_verify_schema_mismatch_marks_out_of_sync_and_blocks(self, patched_db):
        """primary schema_version 과 replica 가 다르면 out_of_sync 로 update + BLOCK."""
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 11:55:00",
            last_sync_schema_version=35,  # 구버전
            sync_lag_seconds=300,
            status="healthy",
            db_path=patched_db,
        )
        actor = StateReplicatorDR()
        result = actor.run({"action": "verify"})
        assert result.outcome == Outcome.BLOCK
        # row 가 out_of_sync 로 update 되었는지 확인
        rows = query(
            "SELECT status FROM dr_replicas WHERE replica_id = ?",
            ("mbp-replica",),
            db_path=patched_db,
        )
        assert rows[0]["status"] == "out_of_sync"
        # blocks 에 mismatch 정보 포함
        assert any("schema mismatch" in b["reason"] for b in result.output["blocks"])

    def test_verify_invalid_max_lag_blocks(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "verify", "max_lag_seconds": -1})
        assert result.outcome == Outcome.BLOCK

    def test_verify_max_lag_override(self, patched_db):
        """max_lag_seconds 가 전달되면 lag > max 인 healthy 도 stale 로 분류."""
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 11:55:00",
            last_sync_schema_version=42,
            sync_lag_seconds=300,
            status="healthy",
            db_path=patched_db,
        )
        actor = StateReplicatorDR()
        # max_lag=100 → 300 초가 stale 처리됨
        result = actor.run({"action": "verify", "max_lag_seconds": 100})
        assert result.outcome == Outcome.WARN


# ─── list_replicas action ───────────────────────────────────


class TestListReplicasAction:
    def test_list_replicas_empty(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "list_replicas"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 0

    def test_list_replicas_returns_all(self, patched_db):
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 11:55:00",
            last_sync_schema_version=42,
            sync_lag_seconds=300,
            status="healthy",
            db_path=patched_db,
        )
        actor = StateReplicatorDR()
        result = actor.run({"action": "list_replicas"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 2


# ─── Invalid input ──────────────────────────────────────────


class TestInvalidInput:
    def test_invalid_action_blocks(self, patched_db):
        actor = StateReplicatorDR()
        result = actor.run({"action": "delete"})
        assert result.outcome == Outcome.BLOCK
        assert "invalid action" in result.output["error"]


# ─── Audit trail ────────────────────────────────────────────


class TestAuditTrail:
    """Layer A 결정은 모두 audit_ledger 자동 기록 (Codex Round 5 mandatory)."""

    def test_snapshot_recorded_in_audit_ledger(self, patched_db):
        actor = StateReplicatorDR()
        actor.run({"action": "snapshot", "replica_id": "macmini-primary", "role": "primary"})
        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["actor_name"] == "state-replicator-dr"
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "pass"

    def test_blocked_action_recorded_with_block_outcome(self, patched_db):
        actor = StateReplicatorDR()
        actor.run({"action": "snapshot"})  # missing replica_id
        rows = query(
            "SELECT outcome, output FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["outcome"] == "block"
        assert "replica_id" in rows[0]["output"]

    def test_run_ledger_records_invocation(self, patched_db):
        actor = StateReplicatorDR()
        actor.run({"action": "list_replicas"})
        rows = query(
            "SELECT actor_name, status FROM agent_run_ledger",
            db_path=patched_db,
        )
        assert rows[0]["actor_name"] == "state-replicator-dr"
        assert rows[0]["status"] == "finished"


# ─── Helper lock-tests ──────────────────────────────────────


class TestUpsertDrReplicaLockTests:
    """upsert_dr_replica enum 검증 — Helper lock-tests (Gotcha-Test Pair §5.3.1)."""

    def test_invalid_role_rejected(self, db_path):
        with pytest.raises(ValueError, match="role must be"):
            upsert_dr_replica(
                replica_id="x",
                role="tertiary",
                hostname="h",
                last_sync_at=None,
                last_sync_schema_version=None,
                sync_lag_seconds=None,
                status="healthy",
                db_path=db_path,
            )

    def test_invalid_status_rejected(self, db_path):
        with pytest.raises(ValueError, match="status must be"):
            upsert_dr_replica(
                replica_id="x",
                role="primary",
                hostname="h",
                last_sync_at=None,
                last_sync_schema_version=None,
                sync_lag_seconds=None,
                status="unknown",
                db_path=db_path,
            )

    def test_dr_replicas_table_exists(self, db_path):
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dr_replicas'",
            db_path=db_path,
        )
        assert len(rows) == 1


# ─── Discord publish ────────────────────────────────────────


class TestDiscordPublish:
    """BLOCK outcome → INCIDENTS publish (mock, best-effort)."""

    def test_block_triggers_incidents_publish(self, patched_db):
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        upsert_dr_replica(
            replica_id="mbp-replica",
            role="replica",
            hostname="mbp",
            last_sync_at="2026-05-01 09:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=10800,
            status="unreachable",
            db_path=patched_db,
        )
        with patch("nuri.agents.actors.state_replicator_dr.StateReplicatorDR._publish_incidents") as mock_publish:
            actor = StateReplicatorDR()
            result = actor.run({"action": "verify"})
            assert result.outcome == Outcome.BLOCK
            assert mock_publish.called

    def test_pass_does_not_publish(self, patched_db):
        upsert_dr_replica(
            replica_id="macmini-primary",
            role="primary",
            hostname="macmini",
            last_sync_at="2026-05-01 12:00:00",
            last_sync_schema_version=42,
            sync_lag_seconds=0,
            status="healthy",
            db_path=patched_db,
        )
        with patch("nuri.agents.actors.state_replicator_dr.StateReplicatorDR._publish_incidents") as mock_publish:
            actor = StateReplicatorDR()
            actor.run({"action": "verify"})
            assert not mock_publish.called

    def test_publish_swallows_discord_exception(self, patched_db):
        """Discord publish 가 실패해도 actor 결과는 그대로."""
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher",
            side_effect=Exception("network down"),
        ):
            # 직접 호출해 swallow 검증
            StateReplicatorDR._publish_incidents(
                blocks=[{"replica_id": "x", "role": "replica", "reason": "test"}],
                run_id="run-test-1234",
            )
        # 예외 raise 안 되면 통과


# ─── CLI ────────────────────────────────────────────────────


class TestCli:
    def test_cli_snapshot_primary(self, patched_db, capsys):
        rc = main(
            [
                "snapshot",
                "--replica-id",
                "cli-primary",
                "--role",
                "primary",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "cli-primary" in out

    def test_cli_list_replicas(self, patched_db, capsys):
        main(["snapshot", "--replica-id", "cli-x", "--role", "primary"])
        rc = main(["list_replicas"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cli-x" in out

    def test_cli_verify_empty_returns_1(self, patched_db, capsys):
        rc = main(["verify"])
        assert rc == 1  # WARN

    def test_cli_invalid_action_returns_2(self, patched_db):
        with pytest.raises(SystemExit) as exc:
            main(["invalid_action"])
        assert exc.value.code == 2
