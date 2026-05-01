"""FreshnessGatekeeper actor 테스트 (#529 Phase 2 actor #2).

검증:
- Layer A enforcement (PASS/WARN/BLOCK 매핑)
- nuri.core.freshness 위임 정합성
- 모든 결정 audit_ledger 자동 기록
- LLM 의존 X
"""

from unittest.mock import patch

import pytest

from nuri.agents.actors.freshness_gatekeeper import FreshnessGatekeeper, main
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "freshness.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """base + freshness 의 db 호출을 임시 path 로 redirect."""
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
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


class TestFreshnessGatekeeperLayer:
    def test_actor_layer_is_a(self):
        assert FreshnessGatekeeper.layer == Layer.A

    def test_no_llm_dependency(self):
        assert getattr(FreshnessGatekeeper, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("freshness-gatekeeper") is FreshnessGatekeeper


class TestActionListPolicies:
    def test_list_policies_returns_keys(self, patched_db):
        actor = FreshnessGatekeeper()
        result = actor.run({"action": "list_policies"})
        assert result.outcome == Outcome.PASS
        assert "policies" in result.output
        assert isinstance(result.output["policies"], list)
        assert len(result.output["policies"]) > 0


class TestActionCheck:
    def test_check_unknown_key_blocks(self, patched_db):
        actor = FreshnessGatekeeper()
        result = actor.run({"action": "check", "key": "nonexistent_xyz"})
        assert result.outcome == Outcome.BLOCK
        assert "available" in result.output

    def test_check_missing_key_blocks(self, patched_db):
        actor = FreshnessGatekeeper()
        result = actor.run({"action": "check"})
        assert result.outcome == Outcome.BLOCK

    def test_check_pass_status_returns_pass(self, patched_db):
        """nuri.core.freshness 가 PASS 반환 시 outcome=PASS."""
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "PASS",
                "last_updated": "2026-04-30",
                "age_hours": 1.5,
                "message": "최신",
            },
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check", "key": "prices"})
            assert result.outcome == Outcome.PASS
            assert result.output["age_hours"] == 1.5

    def test_check_warn_status_returns_warn(self, patched_db):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "WARN",
                "last_updated": "2026-04-29",
                "age_hours": 50.0,
                "message": "업데이트 필요",
            },
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check", "key": "prices"})
            assert result.outcome == Outcome.WARN

    def test_check_fail_status_returns_block(self, patched_db):
        """FAIL → BLOCK (Layer A enforcement: stale data 기반 emit 차단)."""
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "FAIL",
                "last_updated": "2026-04-25",
                "age_hours": 150.0,
                "message": "오래됨",
            },
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check", "key": "prices"})
            assert result.outcome == Outcome.BLOCK
            assert result.output["age_hours"] == 150.0


class TestActionCheckAll:
    def test_check_all_worst_case_outcome(self, patched_db):
        """worst-case outcome — 한 개라도 FAIL 이면 BLOCK."""
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_all_freshness",
            return_value=[
                {"key": "a", "status": "PASS", "label": "A", "age_hours": 1, "last_updated": "x", "message": ""},
                {"key": "b", "status": "WARN", "label": "B", "age_hours": 50, "last_updated": "x", "message": ""},
                {"key": "c", "status": "FAIL", "label": "C", "age_hours": 200, "last_updated": "x", "message": ""},
            ],
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check_all"})
            assert result.outcome == Outcome.BLOCK
            assert result.output["summary"] == {"pass": 1, "warn": 1, "fail": 1, "total": 3}

    def test_check_all_warn_when_no_fail(self, patched_db):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_all_freshness",
            return_value=[
                {"key": "a", "status": "PASS", "label": "A", "age_hours": 1, "last_updated": "x", "message": ""},
                {"key": "b", "status": "WARN", "label": "B", "age_hours": 50, "last_updated": "x", "message": ""},
            ],
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check_all"})
            assert result.outcome == Outcome.WARN

    def test_check_all_pass_when_all_pass(self, patched_db):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_all_freshness",
            return_value=[
                {"key": "a", "status": "PASS", "label": "A", "age_hours": 1, "last_updated": "x", "message": ""},
                {"key": "b", "status": "PASS", "label": "B", "age_hours": 2, "last_updated": "x", "message": ""},
            ],
        ):
            actor = FreshnessGatekeeper()
            result = actor.run({"action": "check_all"})
            assert result.outcome == Outcome.PASS


class TestInvalidAction:
    def test_invalid_action_blocks(self, patched_db):
        actor = FreshnessGatekeeper()
        result = actor.run({"action": "delete"})
        assert result.outcome == Outcome.BLOCK


class TestAuditTrail:
    def test_check_decision_audited(self, patched_db):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "PASS",
                "last_updated": "x",
                "age_hours": 1.0,
                "message": "ok",
            },
        ):
            actor = FreshnessGatekeeper()
            actor.run({"action": "check", "key": "prices"})

        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["actor_name"] == "freshness-gatekeeper"
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "pass"

    def test_warn_outcome_audited(self, patched_db):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "macro_vix",
                "label": "VIX",
                "status": "WARN",
                "last_updated": "x",
                "age_hours": 30.0,
                "message": "stale",
            },
        ):
            actor = FreshnessGatekeeper()
            actor.run({"action": "check", "key": "macro_vix"})

        rows = query(
            "SELECT outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["outcome"] == "warn"


class TestCli:
    def test_cli_list_policies_returns_0(self, patched_db, capsys):
        rc = main(["list_policies"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "policies" in out

    def test_cli_check_with_pass(self, patched_db, capsys):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "PASS",
                "last_updated": "x",
                "age_hours": 1.0,
                "message": "ok",
            },
        ):
            rc = main(["check", "--key", "prices"])
        assert rc == 0

    def test_cli_check_fail_returns_2(self, patched_db, capsys):
        with patch(
            "nuri.agents.actors.freshness_gatekeeper.check_freshness",
            return_value={
                "key": "prices",
                "label": "주가",
                "status": "FAIL",
                "last_updated": "x",
                "age_hours": 200.0,
                "message": "오래됨",
            },
        ):
            rc = main(["check", "--key", "prices"])
        assert rc == 2  # BLOCK exit code
