"""Evidence inventory exercises real SQL against an isolated database."""

from datetime import date

import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.validation.research_readiness import inventory


def test_inventory_cutoff_coverage_and_immutability(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    with get_db(db_path=db_path) as conn:
        for ticker, day in (
            ("TESTAA", "2026-01-01"),
            ("TESTAA", "2026-01-02"),
            ("TESTBB", "2026-02-02"),
            ("TESTCC", "2026-01-01"),
        ):
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, 100)", (ticker, day))
        for ident, status, day in (
            ("measured", "emitted", "2026-01-01"),
            ("missing", "emitted", "2026-01-01"),
            ("blocked", "blocked", "2026-01-01"),
            ("future", "emitted", "2026-02-02"),
        ):
            conn.execute(
                """INSERT INTO agent_decisions
                   (decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status)
                   VALUES (?, 'TESTAA', ?, 'BUY', 50, '{}', '{}', ?)""",
                (ident, day, status),
            )
        conn.execute(
            """INSERT INTO decision_outcomes
               (decision_id, observation_window, tracked_as_of_date, realized_return, alpha, hypothesis_validation)
               VALUES ('measured', 30, '2026-01-31', 0.1, 0.02, 'pass')"""
        )
        conn.execute(
            """INSERT INTO decision_outcomes
               (decision_id, observation_window, tracked_as_of_date, realized_return, hypothesis_validation)
               VALUES ('missing', 30, '2026-02-02', 0.1, 'pass')"""
        )
    before = db_path.read_bytes()
    result = inventory(db_path=db_path, as_of=date(2026, 1, 31), window=30, min_bars=2)
    assert db_path.read_bytes() == before
    assert result["prices"] == {"symbols": 2, "symbols_with_required_bars": 1, "latest_bar_date": "2026-01-02"}
    assert result["decisions"] == {
        "all_statuses": 3,
        "emitted": 2,
        "calendar_elapsed": 2,
        "elapsed_without_outcome_row": 1,
        "elapsed_with_return": 1,
        "elapsed_with_alpha": 1,
    }
    assert "TESTAA" not in str(result)


def test_empty_inventory(tmp_path):
    db_path = tmp_path / "empty.db"
    init_db(db_path)
    result = inventory(db_path=db_path, as_of=date(2026, 1, 31), window=7, min_bars=2)
    assert result["prices"]["latest_bar_date"] is None
    assert result["decisions"]["calendar_elapsed"] == 0


@pytest.mark.parametrize(("window", "min_bars"), [(1, 2), (30, 0)])
def test_invalid_requirements_do_not_create_database(tmp_path, window, min_bars):
    db_path = tmp_path / "absent.db"
    with pytest.raises(ValueError):
        inventory(db_path=db_path, as_of=date(2026, 1, 31), window=window, min_bars=min_bars)
    assert not db_path.exists()


def test_cli_outputs_inventory_for_explicit_database(tmp_path, monkeypatch, capsys):
    import json
    import runpy
    import sys

    db_path = tmp_path / "cli.db"
    init_db(db_path)
    before = db_path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["research_readiness", "--db", str(db_path), "--as-of", "2026-01-31", "--window", "7", "--min-bars", "2"],
    )
    runpy.run_module("nuri.quant.validation.research_readiness", run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "research_evidence_inventory"
    assert result["as_of"] == "2026-01-31"
    assert result["min_bars"] == 2
    assert result["window_calendar_days"] == 7
    assert result["prices"]["symbols"] == 0
    assert db_path.read_bytes() == before
