"""ReleaseRollbackManager actor 테스트 — Phase 1 dogfooding (#529 Phase 2 첫 actor).

Codex Round 5 Layer A enforcement 정합성:
- input validation (action / flag / scope / reason 강제)
- audit_ledger + run_ledger 자동 기록
- LLM 의존 X (rule-based only)
- BLOCK outcome 시 state 변경 X (idempotent error path)
"""

from unittest.mock import patch

import pytest

from nuri.agents.actors.release_rollback_manager import (
    ReleaseRollbackManager,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, is_feature_enabled, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "rollback.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """release_rollback_manager + base 의 모든 DB 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.release_rollback_manager.set_feature_flag",
            side_effect=make_redirect(db_module.set_feature_flag),
        ),
        patch(
            "nuri.agents.actors.release_rollback_manager.is_feature_enabled",
            side_effect=make_redirect(db_module.is_feature_enabled),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


class TestReleaseRollbackManagerLayer:
    """Layer A enforcement 정합성."""

    def test_actor_layer_is_a(self):
        assert ReleaseRollbackManager.layer == Layer.A

    def test_actor_name_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert "release-rollback-manager" in REGISTRY.CANONICAL_15
        assert REGISTRY.get("release-rollback-manager") is ReleaseRollbackManager

    def test_no_llm_dependency(self):
        assert getattr(ReleaseRollbackManager, "_uses_llm", False) is False


class TestEnableAction:
    def test_enable_with_paper_scope(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "enable", "flag": "cycle_engine_v1", "canary_scope": "paper"})
        assert result.outcome == Outcome.PASS
        assert result.output["enabled"] is True
        assert result.output["canary_scope"] == "paper"
        assert is_feature_enabled("cycle_engine_v1", db_path=patched_db) is True

    def test_enable_invalid_scope_blocks(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "enable", "flag": "x", "canary_scope": "beta"})
        assert result.outcome == Outcome.BLOCK
        assert "canary_scope" in result.output["error"]
        # state 변경 X 검증
        assert is_feature_enabled("x", db_path=patched_db) is False

    def test_enable_missing_scope_blocks(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "enable", "flag": "x"})
        assert result.outcome == Outcome.BLOCK


class TestRollbackAction:
    def test_rollback_disables_flag(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "enable", "flag": "test_flag", "canary_scope": "paper"})
        assert is_feature_enabled("test_flag", db_path=patched_db) is True

        result = actor.run({"action": "rollback", "flag": "test_flag", "reason": "Sharpe dropped to 0.3"})
        assert result.outcome == Outcome.PASS
        assert result.output["enabled"] is False
        assert result.output["reason"] == "Sharpe dropped to 0.3"
        assert is_feature_enabled("test_flag", db_path=patched_db) is False

    def test_rollback_without_reason_blocks(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "enable", "flag": "test_flag", "canary_scope": "full"})

        result = actor.run({"action": "rollback", "flag": "test_flag"})
        assert result.outcome == Outcome.BLOCK
        assert "reason" in result.output["error"]
        # state 변경 X 검증 (audit trail 강제 위반 시 실행 X)
        assert is_feature_enabled("test_flag", db_path=patched_db) is True


class TestStatusAction:
    def test_status_returns_current_state(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "enable", "flag": "f1", "canary_scope": "paper"})

        result = actor.run({"action": "status", "flag": "f1"})
        assert result.outcome == Outcome.PASS
        assert result.output["enabled"] is True

    def test_status_unknown_flag_returns_false(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "status", "flag": "nonexistent"})
        assert result.outcome == Outcome.PASS
        assert result.output["enabled"] is False


class TestInvalidInput:
    def test_invalid_action_blocks(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "delete", "flag": "x"})
        assert result.outcome == Outcome.BLOCK
        assert "invalid action" in result.output["error"]

    def test_missing_flag_blocks(self, patched_db):
        actor = ReleaseRollbackManager()
        result = actor.run({"action": "enable"})
        assert result.outcome == Outcome.BLOCK
        assert "flag" in result.output["error"]


class TestAuditTrail:
    """Layer A 결정은 모두 audit_ledger 자동 기록 (Codex Round 5 mandatory)."""

    def test_enable_recorded_in_audit_ledger(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "enable", "flag": "audited", "canary_scope": "paper"})

        rows = query(
            "SELECT actor_name, layer, outcome, output FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["actor_name"] == "release-rollback-manager"
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "pass"
        assert "audited" in rows[0]["output"]

    def test_rollback_recorded_in_audit_ledger(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "enable", "flag": "f", "canary_scope": "paper"})
        actor.run({"action": "rollback", "flag": "f", "reason": "test reason"})

        rows = query(
            "SELECT outcome, input_summary FROM agent_audit_ledger ORDER BY id",
            db_path=patched_db,
        )
        assert len(rows) == 2
        assert rows[0]["outcome"] == "pass"  # enable
        assert rows[1]["outcome"] == "pass"  # rollback
        assert "test reason" in rows[1]["input_summary"]

    def test_blocked_action_recorded_with_block_outcome(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "rollback", "flag": "x"})  # missing reason

        rows = query(
            "SELECT outcome, output FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["outcome"] == "block"
        assert "reason required" in rows[0]["output"]

    def test_run_ledger_records_invocation(self, patched_db):
        actor = ReleaseRollbackManager()
        actor.run({"action": "status", "flag": "x"})

        rows = query(
            "SELECT actor_name, status FROM agent_run_ledger",
            db_path=patched_db,
        )
        assert rows[0]["actor_name"] == "release-rollback-manager"
        assert rows[0]["status"] == "finished"


class TestCli:
    def test_cli_enable(self, patched_db, capsys):
        rc = main(["enable", "cli_test", "--scope", "paper", "--owner", "test"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cli_test" in out
        assert is_feature_enabled("cli_test", db_path=patched_db) is True

    def test_cli_rollback(self, patched_db, capsys):
        main(["enable", "cli_test", "--scope", "full"])
        rc = main(["rollback", "cli_test", "--reason", "cli rollback test"])
        assert rc == 0
        assert is_feature_enabled("cli_test", db_path=patched_db) is False

    def test_cli_invalid_action_returns_2(self, patched_db):
        # argparse 가 unknown action → SystemExit(2)
        with pytest.raises(SystemExit) as exc:
            main(["invalid_action", "x"])
        assert exc.value.code == 2

    def test_cli_block_returns_1(self, patched_db, capsys):
        rc = main(["rollback", "x"])  # reason 누락
        assert rc == 1  # BLOCK outcome
