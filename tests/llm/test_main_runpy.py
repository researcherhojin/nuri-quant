"""Pragma audit: runpy test for nuri/llm/report.py `if __name__ == "__main__":` block."""

from __future__ import annotations

import io
import runpy
import sys

import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path_mp(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "llm.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


class TestLLMReportMainRunpy:
    def test_main_gate_blocked_path(self, monkeypatch, db_path_mp, tmp_path):
        """Empty DB → gather_context returns low gate_score → gate_blocked=True branch.

        Behavioral verification: stdout contains "Gate 차단" message.
        """
        # Pre-empt the file write by chdir into tmp_path (main writes to
        # data/reports/{today}/llm_report.md relative to cwd — only on success).
        # On gate_blocked, no file write happens.
        monkeypatch.chdir(tmp_path)

        captured = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["report"])
        monkeypatch.setattr(sys, "stdout", captured)
        try:
            runpy.run_module("nuri.llm.report", run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise

        out = captured.getvalue()
        assert "Gate 차단" in out
