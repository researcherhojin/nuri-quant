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
