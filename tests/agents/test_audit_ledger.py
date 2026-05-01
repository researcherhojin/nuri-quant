"""AuditLedger tests (#529 Phase 2 — actor #10, canonical Layer A).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 4 actions: query / summarize_by_outcome / summarize_by_actor / retention_check
- query: filter + sort + limit
- summarize_by_outcome: GROUP BY outcome → totals dict
- summarize_by_actor: GROUP BY actor_name → counts dict
- retention_check 3 paths: PASS / WARN / BLOCK
- empty DB handling
- Discord publish: BLOCK → INCIDENTS, WARN → OPS (mock)
- CLI smoke
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.audit_ledger import (
    BLOCK_MULTIPLIER,
    DEFAULT_MAX_ROWS,
    DEFAULT_RETENTION_DAYS,
    AuditLedger,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_agent_audit

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "audit.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """audit-ledger 의 모든 DB 호출 redirect."""
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
            "nuri.agents.actors.audit_ledger.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _seed_audit(
    db_path,
    decision_id: str,
    actor_name: str,
    layer: str = "A",
    outcome: str = "pass",
    *,
    timestamp: str | None = None,
):
    """단일 audit row 삽입. timestamp override 시 sqlite raw INSERT 우회.

    log_agent_audit 은 timestamp DEFAULT 사용 — 과거 timestamp 가 필요하면
    별도 raw write 로 처리 (db.py 내부 sqlite3 import 만 sole importer 라
    여기는 query 만 사용 가능 → log_agent_audit 으로 시드 후 timestamp 업데이트).
    """
    log_agent_audit(
        decision_id=decision_id,
        actor_name=actor_name,
        actor_version="0.1.0",
        layer=layer,
        input_hash="hash" + decision_id,
        output='{"x":1}',
        outcome=outcome,
        db_path=db_path,
    )
    if timestamp is not None:
        # raw timestamp 업데이트 — sole importer 룰 준수 위해 query() 미사용 path X.
        # Pattern: get_db() context manager 로 안전한 conn 확보.
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE agent_audit_ledger SET timestamp = ? WHERE decision_id = ? AND actor_name = ?",
                (timestamp, decision_id, actor_name),
            )


# ═══════════════════════════════════════════════════════
# Layer A invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_a(self):
        assert AuditLedger.layer == Layer.A

    def test_no_llm_dependency(self):
        assert getattr(AuditLedger, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("audit-ledger") is AuditLedger

    def test_name_is_canonical(self):
        assert AuditLedger.name == "audit-ledger"

    def test_valid_actions(self):
        assert set(AuditLedger.VALID_ACTIONS) == {
            "query",
            "summarize_by_outcome",
            "summarize_by_actor",
            "retention_check",
        }


# ═══════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════


class TestInputValidation:
    def test_invalid_action_blocked(self, patched_db):
        result = AuditLedger().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK
        assert "invalid action" in result.output["error"]

    def test_missing_action_blocked(self, patched_db):
        result = AuditLedger().run({})
        assert result.outcome == Outcome.BLOCK

    def test_query_invalid_layer_blocked(self, patched_db):
        result = AuditLedger().run({"action": "query", "layer": "Z"})
        assert result.outcome == Outcome.BLOCK
        assert "layer" in result.output["error"]

    def test_query_invalid_outcome_blocked(self, patched_db):
        result = AuditLedger().run({"action": "query", "outcome": "yolo"})
        assert result.outcome == Outcome.BLOCK
        assert "outcome" in result.output["error"]

    def test_query_invalid_limit_blocked(self, patched_db):
        result = AuditLedger().run({"action": "query", "limit": "xx"})
        assert result.outcome == Outcome.BLOCK

    def test_summarize_by_actor_invalid_layer_blocked(self, patched_db):
        result = AuditLedger().run({"action": "summarize_by_actor", "layer": "Z"})
        assert result.outcome == Outcome.BLOCK

    def test_retention_invalid_args_blocked(self, patched_db):
        result = AuditLedger().run({"action": "retention_check", "max_rows": "bad"})
        assert result.outcome == Outcome.BLOCK

    def test_retention_zero_max_rows_blocked(self, patched_db):
        result = AuditLedger().run({"action": "retention_check", "max_rows": 0})
        assert result.outcome == Outcome.BLOCK

    def test_retention_negative_since_days_blocked(self, patched_db):
        result = AuditLedger().run({"action": "retention_check", "max_rows": 100, "since_days": -1})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# query action
# ═══════════════════════════════════════════════════════


class TestQuery:
    def test_query_empty_db(self, patched_db):
        result = AuditLedger().run({"action": "query"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 0
        assert result.output["rows"] == []

    def test_query_returns_all_when_no_filter(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall")
        _seed_audit(patched_db, "d2", "freshness-gatekeeper")
        result = AuditLedger().run({"action": "query"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 2

    def test_query_filter_by_actor(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall")
        _seed_audit(patched_db, "d2", "freshness-gatekeeper")
        _seed_audit(patched_db, "d3", "execution-firewall")
        result = AuditLedger().run({"action": "query", "actor_name": "execution-firewall"})
        assert result.output["count"] == 2
        for row in result.output["rows"]:
            assert row["actor_name"] == "execution-firewall"

    def test_query_filter_by_layer(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", layer="A")
        _seed_audit(patched_db, "d2", "regime-posterior", layer="B")
        result = AuditLedger().run({"action": "query", "layer": "A"})
        assert result.output["count"] == 1
        assert result.output["rows"][0]["layer"] == "A"

    def test_query_filter_by_outcome(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        _seed_audit(patched_db, "d2", "execution-firewall", outcome="block")
        _seed_audit(patched_db, "d3", "execution-firewall", outcome="block")
        result = AuditLedger().run({"action": "query", "outcome": "block"})
        assert result.output["count"] == 2
        for row in result.output["rows"]:
            assert row["outcome"] == "block"

    def test_query_filter_combination(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        _seed_audit(patched_db, "d2", "execution-firewall", outcome="block")
        _seed_audit(patched_db, "d3", "freshness-gatekeeper", outcome="block")
        result = AuditLedger().run(
            {
                "action": "query",
                "actor_name": "execution-firewall",
                "outcome": "block",
            }
        )
        assert result.output["count"] == 1
        assert result.output["rows"][0]["actor_name"] == "execution-firewall"
        assert result.output["rows"][0]["outcome"] == "block"

    def test_query_filter_by_since_iso(self, patched_db):
        _seed_audit(patched_db, "old", "execution-firewall", timestamp="2020-01-01 00:00:00")
        _seed_audit(patched_db, "new", "execution-firewall", timestamp="2030-01-01 00:00:00")
        result = AuditLedger().run({"action": "query", "since_iso": "2025-01-01 00:00:00"})
        assert result.output["count"] == 1
        assert result.output["rows"][0]["decision_id"] == "new"

    def test_query_limit_respected(self, patched_db):
        for i in range(5):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        result = AuditLedger().run({"action": "query", "limit": 3})
        assert result.output["count"] == 3

    def test_query_sorted_desc(self, patched_db):
        _seed_audit(patched_db, "old", "execution-firewall", timestamp="2020-01-01 00:00:00")
        _seed_audit(patched_db, "new", "execution-firewall", timestamp="2030-01-01 00:00:00")
        result = AuditLedger().run({"action": "query"})
        # Newest first
        assert result.output["rows"][0]["decision_id"] == "new"


# ═══════════════════════════════════════════════════════
# summarize_by_outcome
# ═══════════════════════════════════════════════════════


class TestSummarizeByOutcome:
    def test_empty_db_zero_totals(self, patched_db):
        result = AuditLedger().run({"action": "summarize_by_outcome"})
        assert result.outcome == Outcome.PASS
        assert result.output["totals"] == {"pass": 0, "block": 0, "warn": 0, "error": 0}
        assert result.output["total_count"] == 0

    def test_groups_by_outcome(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        _seed_audit(patched_db, "d2", "execution-firewall", outcome="pass")
        _seed_audit(patched_db, "d3", "execution-firewall", outcome="block")
        _seed_audit(patched_db, "d4", "execution-firewall", outcome="warn")
        _seed_audit(patched_db, "d5", "execution-firewall", outcome="error")
        result = AuditLedger().run({"action": "summarize_by_outcome"})
        assert result.output["totals"] == {
            "pass": 2,
            "block": 1,
            "warn": 1,
            "error": 1,
        }
        assert result.output["total_count"] == 5

    def test_filter_by_actor(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="block")
        _seed_audit(patched_db, "d2", "freshness-gatekeeper", outcome="block")
        result = AuditLedger().run({"action": "summarize_by_outcome", "actor_name": "execution-firewall"})
        assert result.output["totals"]["block"] == 1
        assert result.output["total_count"] == 1

    def test_filter_by_since_iso(self, patched_db):
        _seed_audit(
            patched_db,
            "old",
            "execution-firewall",
            outcome="pass",
            timestamp="2020-01-01 00:00:00",
        )
        _seed_audit(patched_db, "new", "execution-firewall", outcome="pass")
        result = AuditLedger().run({"action": "summarize_by_outcome", "since_iso": "2025-01-01 00:00:00"})
        assert result.output["totals"]["pass"] == 1
        assert result.output["total_count"] == 1

    def test_unset_outcome_surfaced(self, patched_db):
        """Layer B/C 시 outcome=None 인 row 가 'unset' 으로 노출됨."""
        # Layer B audit row with outcome=None
        from nuri.core.db import log_agent_audit

        log_agent_audit(
            decision_id="db",
            actor_name="regime-posterior",
            actor_version="0.1.0",
            layer="B",
            input_hash="x",
            output="{}",
            outcome=None,  # Layer B optional
            db_path=patched_db,
        )
        result = AuditLedger().run({"action": "summarize_by_outcome"})
        assert result.output.get("unset") == 1
        assert result.output["total_count"] == 1


# ═══════════════════════════════════════════════════════
# summarize_by_actor
# ═══════════════════════════════════════════════════════


class TestSummarizeByActor:
    def test_empty_db(self, patched_db):
        result = AuditLedger().run({"action": "summarize_by_actor"})
        assert result.outcome == Outcome.PASS
        assert result.output["actors"] == {}
        assert result.output["total_actors"] == 0

    def test_groups_by_actor(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        _seed_audit(patched_db, "d2", "execution-firewall", outcome="block")
        _seed_audit(patched_db, "d3", "freshness-gatekeeper", outcome="pass")
        result = AuditLedger().run({"action": "summarize_by_actor"})
        actors = result.output["actors"]
        assert "execution-firewall" in actors
        assert "freshness-gatekeeper" in actors
        assert actors["execution-firewall"]["pass"] == 1
        assert actors["execution-firewall"]["block"] == 1
        assert actors["execution-firewall"]["total"] == 2
        assert actors["freshness-gatekeeper"]["pass"] == 1
        assert actors["freshness-gatekeeper"]["total"] == 1
        assert result.output["total_actors"] == 2

    def test_filter_by_layer(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", layer="A", outcome="pass")
        _seed_audit(patched_db, "d2", "regime-posterior", layer="B", outcome="pass")
        result = AuditLedger().run({"action": "summarize_by_actor", "layer": "A"})
        assert "execution-firewall" in result.output["actors"]
        assert "regime-posterior" not in result.output["actors"]


# ═══════════════════════════════════════════════════════
# retention_check
# ═══════════════════════════════════════════════════════


class TestRetentionCheck:
    def test_empty_db_passes(self, patched_db):
        result = AuditLedger().run({"action": "retention_check"})
        assert result.outcome == Outcome.PASS
        assert result.output["total_rows"] == 0
        assert result.output["rows_older_than_n_days"] == 0
        assert "PASS" in result.output["recommendation"]

    def test_within_threshold_passes(self, patched_db):
        for i in range(3):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        result = AuditLedger().run({"action": "retention_check", "max_rows": 100})
        assert result.outcome == Outcome.PASS
        assert result.output["total_rows"] == 3
        assert result.output["max_rows"] == 100

    def test_above_max_warns(self, patched_db):
        for i in range(15):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_ops"):
            result = AuditLedger().run({"action": "retention_check", "max_rows": 10})
        assert result.outcome == Outcome.WARN
        assert result.output["total_rows"] == 15
        assert "WARN" in result.output["recommendation"]

    def test_far_above_threshold_blocks(self, patched_db):
        # max_rows=10 → block_threshold=15 → 16 rows triggers BLOCK
        for i in range(16):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_incidents"):
            result = AuditLedger().run({"action": "retention_check", "max_rows": 10})
        assert result.outcome == Outcome.BLOCK
        assert result.output["total_rows"] == 16
        assert result.output["block_threshold"] == int(10 * BLOCK_MULTIPLIER)
        assert "BLOCK" in result.output["recommendation"]

    def test_old_rows_counted(self, patched_db):
        _seed_audit(patched_db, "old", "execution-firewall", timestamp="2020-01-01 00:00:00")
        _seed_audit(patched_db, "fresh", "execution-firewall")
        result = AuditLedger().run({"action": "retention_check", "max_rows": 1000, "since_days": 30})
        assert result.output["rows_older_than_n_days"] == 1
        assert result.output["total_rows"] == 2

    def test_default_thresholds(self):
        assert DEFAULT_MAX_ROWS == 1_000_000
        assert DEFAULT_RETENTION_DAYS == 90
        assert BLOCK_MULTIPLIER == 1.5


# ═══════════════════════════════════════════════════════
# Discord publish (mock)
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    def test_block_publishes_incidents(self, patched_db):
        # max_rows=2 → block_threshold=3 → 4 rows → BLOCK
        for i in range(4):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_incidents") as m:
            result = AuditLedger().run({"action": "retention_check", "max_rows": 2})
        assert result.outcome == Outcome.BLOCK
        m.assert_called_once()

    def test_warn_publishes_ops(self, patched_db):
        for i in range(11):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_ops") as m:
            result = AuditLedger().run({"action": "retention_check", "max_rows": 10})
        assert result.outcome == Outcome.WARN
        m.assert_called_once()

    def test_pass_no_publish(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall")
        with (
            patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_incidents") as inc,
            patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_ops") as ops,
        ):
            result = AuditLedger().run({"action": "retention_check", "max_rows": 1000})
        assert result.outcome == Outcome.PASS
        inc.assert_not_called()
        ops.assert_not_called()

    def test_query_no_publish(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall")
        with (
            patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_incidents") as inc,
            patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_ops") as ops,
        ):
            AuditLedger().run({"action": "query"})
        inc.assert_not_called()
        ops.assert_not_called()

    def test_publish_failure_swallowed(self, patched_db):
        """Discord webhook 실패가 actor 결정 차단해서는 안 됨 (best-effort)."""
        for i in range(11):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch(
            "nuri.agents.discord.publisher.DiscordPublisher.publish_embed",
            side_effect=Exception("network down"),
        ):
            # 예외 raise 하지 않아야 함
            result = AuditLedger().run({"action": "retention_check", "max_rows": 10})
        assert result.outcome == Outcome.WARN

    def test_block_stages_to_incidents(self, patched_db):
        """BLOCK path → outbox stage_incident (PR3 Codex Round 6)."""
        for i in range(4):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.discord.outbox.stage_incident") as mock_stage:
            result = AuditLedger().run({"action": "retention_check", "max_rows": 2})
        assert result.outcome == Outcome.BLOCK
        mock_stage.assert_called_once()
        kw = mock_stage.call_args.kwargs
        assert kw["actor_name"] == "audit-ledger"
        assert kw["payload"]["kind"] == "audit_ledger_block"

    def test_warn_stages_to_ops(self, patched_db):
        """WARN path → outbox stage_ops (PR3 Codex Round 6)."""
        for i in range(11):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.discord.outbox.stage_ops") as mock_stage:
            result = AuditLedger().run({"action": "retention_check", "max_rows": 10})
        assert result.outcome == Outcome.WARN
        mock_stage.assert_called_once()
        assert mock_stage.call_args.kwargs["payload"]["kind"] == "audit_ledger_warn"


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCLI:
    def test_cli_query_returns_zero_on_pass(self, patched_db, capsys):
        rc = main(["query", "--limit", "5"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "count" in captured.out

    def test_cli_summarize_by_outcome(self, patched_db, capsys):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        rc = main(["summarize_by_outcome"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "totals" in captured.out

    def test_cli_summarize_by_actor(self, patched_db, capsys):
        _seed_audit(patched_db, "d1", "execution-firewall", outcome="pass")
        rc = main(["summarize_by_actor"])
        assert rc == 0

    def test_cli_retention_check_pass(self, patched_db, capsys):
        rc = main(["retention_check", "--max-rows", "1000", "--since-days", "30"])
        assert rc == 0

    def test_cli_retention_check_warn_returns_nonzero(self, patched_db):
        for i in range(11):
            _seed_audit(patched_db, f"d{i}", "execution-firewall")
        with patch("nuri.agents.actors.audit_ledger.AuditLedger._publish_ops"):
            rc = main(["retention_check", "--max-rows", "10"])
        # WARN → outcome != PASS → nonzero exit
        assert rc == 1

    def test_cli_query_with_all_optional_args(self, patched_db):
        _seed_audit(patched_db, "d1", "execution-firewall", layer="A", outcome="pass")
        rc = main(
            [
                "query",
                "--actor-name",
                "execution-firewall",
                "--layer",
                "A",
                "--outcome",
                "pass",
                "--since-iso",
                "2020-01-01 00:00:00",
                "--limit",
                "10",
            ]
        )
        assert rc == 0
