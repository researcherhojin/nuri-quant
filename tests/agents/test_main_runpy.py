"""Pragma audit: runpy tests for `if __name__ == "__main__":` blocks in nuri/agents/."""

from __future__ import annotations

import io
import runpy
import sys

import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path_mp(tmp_path, monkeypatch):
    """Isolated DB with DB_PATH patched."""
    import nuri.core.db as db_mod

    path = tmp_path / "agents.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _restore_actor_registry():
    """runpy.run_module re-executes a module under `__name__ == "__main__"`,
    which re-runs `@register` decorators and overwrites the canonical class
    in ActorRegistry with a `__main__.SREIncidentAgent`-style copy. Snapshot
    + restore prevents this from polluting `tests/agents/test_sre_incident_*`
    which assert `registry.get(name) is SREIncidentAgent` on the canonical class.
    """
    from nuri.agents.base import REGISTRY

    snapshot = dict(REGISTRY._registry)
    yield
    REGISTRY._registry.clear()
    REGISTRY._registry.update(snapshot)


def _run_module_with_argv(module_name: str, monkeypatch, argv: list[str]) -> tuple[int, str]:
    """Run module via runpy, return (exit_code, stdout). Catches SystemExit."""
    captured = io.StringIO()
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "stdout", captured)
    code: int | None = 0
    try:
        runpy.run_module(module_name, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
    return code or 0, captured.getvalue()


class TestActorsMainRunpy:
    def test_decision_compiler_main_last_decision(self, monkeypatch, db_path_mp):
        """decision_compiler main last_decision: empty DB → no decision → JSON output."""
        code, out = _run_module_with_argv(
            "nuri.agents.actors.decision_compiler",
            monkeypatch,
            ["decision_compiler", "last_decision"],
        )
        # JSON output printed; on empty DB, no decision → outcome may be PASS (with empty
        # data) or WARN; both return 0 exit
        # Behavioral: stdout has JSON-shaped content (curly braces present)
        assert "{" in out and "}" in out

    def test_sre_incident_agent_main_scan(self, monkeypatch, db_path_mp):
        """sre_incident_agent main scan: empty DB → no incidents → JSON."""
        code, out = _run_module_with_argv(
            "nuri.agents.actors.sre_incident_agent",
            monkeypatch,
            ["sre_incident_agent", "scan"],
        )
        # JSON printed (PASS / WARN / BLOCK / ERROR); behavioral check
        assert "{" in out and "}" in out

    # ─── 16 actor __main__ blocks (PR #608 — coverage 104 → ~30 missed) ───

    def test_audit_ledger_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.audit_ledger",
            monkeypatch,
            ["audit_ledger", "summarize_by_outcome"],
        )
        assert "{" in out

    def test_brief_auditor_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.brief_auditor",
            monkeypatch,
            ["brief_auditor", "--hours", "1"],
        )
        # plain-text print, not JSON
        assert "audited=" in out

    def test_causal_factor_auditor_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.causal_factor_auditor",
            monkeypatch,
            ["causal_factor_auditor", "last_audit"],
        )
        assert "{" in out

    def test_channel_dispatcher_main(self, monkeypatch, db_path_mp):
        # 'ops' channel + empty outbox → claimed_n=0 (no real dispatch)
        _, out = _run_module_with_argv(
            "nuri.agents.actors.channel_dispatcher",
            monkeypatch,
            ["channel_dispatcher", "ops", "--force"],
        )
        assert "ops:" in out

    def test_collector_orchestrator_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.collector_orchestrator",
            monkeypatch,
            ["collector_orchestrator", "scan_health", "--hours", "1"],
        )
        assert "{" in out

    def test_collector_orchestrator_main_list_recent(self, monkeypatch, db_path_mp):
        # else branch in main(): list_recent action
        _, out = _run_module_with_argv(
            "nuri.agents.actors.collector_orchestrator",
            monkeypatch,
            ["collector_orchestrator", "list_recent", "--limit", "5"],
        )
        assert "{" in out

    def test_drift_sentinel_main(self, monkeypatch, db_path_mp):
        # exercise --since-iso branch (line 549) at the same time
        _, out = _run_module_with_argv(
            "nuri.agents.actors.drift_sentinel",
            monkeypatch,
            ["drift_sentinel", "list_alerts", "--since-iso", "2026-01-01T00:00:00", "--severity", "minor"],
        )
        assert "{" in out

    def test_execution_firewall_main(self, monkeypatch, db_path_mp):
        # exercise --decision-id + --severity branches (lines 444-446)
        _, out = _run_module_with_argv(
            "nuri.agents.actors.execution_firewall",
            monkeypatch,
            ["execution_firewall", "list_blocks", "--decision-id", "dec-x", "--severity", "hard"],
        )
        assert "{" in out

    def test_forward_outcome_tracker_main_scan(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.forward_outcome_tracker",
            monkeypatch,
            ["forward_outcome_tracker", "scan", "--max-decisions", "10"],
        )
        assert "{" in out

    def test_forward_outcome_tracker_main_track_one(self, monkeypatch, db_path_mp):
        # exercise track_one branch (lines 471-472) — empty DB → BLOCK/WARN ok
        _, out = _run_module_with_argv(
            "nuri.agents.actors.forward_outcome_tracker",
            monkeypatch,
            ["forward_outcome_tracker", "track_one", "--decision-id", "dec-x", "--observation-window", "7"],
        )
        assert "{" in out

    def test_forward_outcome_tracker_main_last_outcome(self, monkeypatch, db_path_mp):
        # exercise last_outcome branch with --decision-id (line 474)
        _, out = _run_module_with_argv(
            "nuri.agents.actors.forward_outcome_tracker",
            monkeypatch,
            ["forward_outcome_tracker", "last_outcome", "--decision-id", "dec-x"],
        )
        assert "{" in out

    def test_foundation_benchmark_main_list_runs(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.foundation_benchmark",
            monkeypatch,
            ["foundation_benchmark", "list_runs", "--limit", "5"],
        )
        assert "{" in out

    def test_foundation_benchmark_main_compare(self, monkeypatch, db_path_mp):
        # exercise compare branch with --benchmark-run (line 447)
        _, out = _run_module_with_argv(
            "nuri.agents.actors.foundation_benchmark",
            monkeypatch,
            ["foundation_benchmark", "compare", "--benchmark-run", "run-x"],
        )
        assert "{" in out

    def test_freshness_gatekeeper_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.freshness_gatekeeper",
            monkeypatch,
            ["freshness_gatekeeper", "list_policies"],
        )
        assert "{" in out

    def test_hypothesis_registry_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.hypothesis_registry",
            monkeypatch,
            ["hypothesis_registry", "list_open"],
        )
        assert "{" in out

    def test_outbox_watchdog_main(self, monkeypatch, db_path_mp):
        # outbox_watchdog has no CLI args; print "breaches=N health=..."
        _, out = _run_module_with_argv(
            "nuri.agents.actors.outbox_watchdog",
            monkeypatch,
            ["outbox_watchdog"],
        )
        assert "breaches=" in out

    def test_regime_posterior_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.regime_posterior",
            monkeypatch,
            ["regime_posterior", "last_posterior"],
        )
        assert "{" in out

    def test_release_rollback_manager_main(self, monkeypatch, db_path_mp):
        # `status` action only needs flag positional
        _, out = _run_module_with_argv(
            "nuri.agents.actors.release_rollback_manager",
            monkeypatch,
            ["release_rollback_manager", "status", "test_flag"],
        )
        assert "{" in out

    def test_state_replicator_dr_main(self, monkeypatch, db_path_mp):
        _, out = _run_module_with_argv(
            "nuri.agents.actors.state_replicator_dr",
            monkeypatch,
            ["state_replicator_dr", "list_replicas"],
        )
        assert "{" in out

    def test_walkforward_validator_main(self, monkeypatch, db_path_mp, tmp_path):
        """walkforward_validator pit_hash needs --csv (line 401-417 + __main__)."""
        import pandas as pd

        csv_path = tmp_path / "wf.csv"
        # 252 + 21 + 21 = 294 rows minimum for default fold spec
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=300), "x": range(300)})
        df.to_csv(csv_path, index=False)
        _, out = _run_module_with_argv(
            "nuri.agents.actors.walkforward_validator",
            monkeypatch,
            ["walkforward_validator", "pit_hash", "--csv", str(csv_path)],
        )
        assert "{" in out

    # Note: main() try/except blocks in walkforward_validator / release_rollback_manager /
    # state_replicator_dr / freshness_gatekeeper are pragma'd defensive — base.Actor.run()
    # catches all execute() exceptions and returns ERROR outcome, so these except handlers
    # only fire if start_agent_run / DB layer itself raises (unreachable from CLI test).

    def test_release_rollback_manager_main_description(self, monkeypatch, db_path_mp):
        """enable action with --description (line 165 branch)."""
        _, out = _run_module_with_argv(
            "nuri.agents.actors.release_rollback_manager",
            monkeypatch,
            [
                "release_rollback_manager",
                "enable",
                "test_flag",
                "--scope",
                "paper",
                "--description",
                "test desc",
            ],
        )
        assert "{" in out

    def test_freshness_gatekeeper_main_error(self, monkeypatch, db_path_mp):
        """check action without --key → BLOCK outcome → exit 2 (line 164-165)."""
        code, _ = _run_module_with_argv(
            "nuri.agents.actors.freshness_gatekeeper",
            monkeypatch,
            ["freshness_gatekeeper", "check"],
        )
        assert code in (1, 2)  # WARN→1, BLOCK→2

    def test_state_replicator_dr_main_error(self, monkeypatch, db_path_mp):
        """snapshot without --replica-id → ValueError caught (lines 396-398)."""
        code, _ = _run_module_with_argv(
            "nuri.agents.actors.state_replicator_dr",
            monkeypatch,
            ["state_replicator_dr", "snapshot"],
        )
        assert code == 2
