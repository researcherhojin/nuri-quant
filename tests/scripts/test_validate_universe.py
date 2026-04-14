"""Tests for scripts/validate_universe.py — #272 Phase 2c CLI gate.

Network-free: `fetch_upstream_universes` is always mocked. Tests verify:
1. run_validation assembles checks correctly with/without fetch
2. print_table formats without crashing
3. main() returns correct exit codes (0 PASS, 1 FAIL)
4. --format json and --no-fetch flags wire through
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import yaml

from nuri.core.coverage import CoverageCheck


@pytest.fixture
def universe_cwd(tmp_path, monkeypatch):
    """Temp universe.yaml + cwd for _load_universe to find it."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "universe.yaml").write_text(
        yaml.safe_dump(
            {
                "us_core": {"tickers": ["AAPL", "MSFT"]},
                "us_sp500_extended": {"tickers": ["GOOGL"]},
                "kr_kospi200": {"tickers": ["005930.KS"]},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def db_with_data(tmp_path, monkeypatch):
    """DB with enough data to pass coverage thresholds."""
    import pandas as pd

    import nuri.core.db as db_mod
    from nuri.core.db import get_db, init_db

    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr(db_mod, "DB_PATH", db)

    # Populate prices + fundamentals for AAPL/MSFT/GOOGL (3/3 = 100% US coverage)
    with get_db(db) as conn:
        for t in ["AAPL", "MSFT", "GOOGL"]:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) "
                "VALUES (?, ?, 1, 2, 0.5, 1.5, 1000, 1.5)",
                (t, "2026-04-14"),
            )
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?, ?, 20)",
                (t, "2026-04-14"),
            )
            conn.execute(
                "INSERT INTO analyst_ratings (ticker, date, firm, action, to_grade) VALUES (?, ?, 'F', 'up', 'Buy')",
                (t, "2026-04-14"),
            )
            conn.execute(
                "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares) "
                "VALUES (?, ?, 'x', 'P', 100)",
                (t, "2026-04-14"),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct) "
                "VALUES ('Buffett', '2026-02-17', ?, 100, 1000, 1.0)",
                (t,),
            )
    return db


# ═══════════════════════════════════════════════════════
# run_validation
# ═══════════════════════════════════════════════════════


class TestRunValidation:
    def test_no_fetch_skips_upstream_checks(self, universe_cwd, db_with_data):
        """--no-fetch path: only data table checks, no universe.yaml vs upstream."""
        from scripts.validate_universe import run_validation

        checks, exit_code = run_validation(fetch=False)

        # 5 data checks, no universe.* checks
        names = [c.name for c in checks]
        assert all(n.startswith("data.") for n in names)
        assert len(checks) == 5
        assert exit_code == 0

    def test_all_checks_pass_with_complete_data(self, universe_cwd, db_with_data):
        """With full DB, all 5 data checks should PASS."""
        from scripts.validate_universe import run_validation

        checks, exit_code = run_validation(fetch=False)
        assert exit_code == 0
        assert all(c.passed for c in checks)

    def test_empty_db_yields_fail_exit_code(self, universe_cwd, tmp_path, monkeypatch):
        """Empty DB → coverage 0% → FAIL on all thresholds."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db
        from scripts.validate_universe import run_validation

        db = tmp_path / "empty.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        _, exit_code = run_validation(fetch=False)
        assert exit_code == 1

    def test_fetch_mode_includes_upstream_checks(self, universe_cwd, db_with_data):
        """fetch=True should add universe.us_sp500 + universe.kr_kospi200 checks."""
        from scripts.validate_universe import run_validation

        with patch("scripts.validate_universe.fetch_upstream_universes") as mock_fetch:
            # Return upstreams that fully match the fixture universe.yaml
            mock_fetch.return_value = (
                {"AAPL", "MSFT", "GOOGL"},  # us
                {"005930.KS"},  # kr
            )
            checks, exit_code = run_validation(fetch=True)

        names = [c.name for c in checks]
        assert "universe.us_sp500" in names
        assert "universe.kr_kospi200" in names
        assert exit_code == 0


# ═══════════════════════════════════════════════════════
# print_table — smoke (no crash)
# ═══════════════════════════════════════════════════════


class TestPrintTable:
    def test_print_table_pass_only(self, capsys):
        from scripts.validate_universe import print_table

        checks = [CoverageCheck("data.prices", 0.99, 0.95, "PASS", "537/543")]
        print_table(checks)
        out = capsys.readouterr().out
        assert "✅ PASS" in out
        assert "data.prices" in out
        assert "exit 0" in out

    def test_print_table_fail_with_detail(self, capsys):
        from scripts.validate_universe import print_table

        checks = [CoverageCheck("data.prices", 0.50, 0.95, "FAIL", "short data")]
        print_table(checks)
        out = capsys.readouterr().out
        assert "🔴 FAIL" in out
        assert "short data" in out
        assert "exit 1" in out


# ═══════════════════════════════════════════════════════
# main() CLI
# ═══════════════════════════════════════════════════════


class TestMain:
    def test_main_no_fetch_exit_zero(self, universe_cwd, db_with_data, monkeypatch):
        from scripts.validate_universe import main

        monkeypatch.setattr("sys.argv", ["validate_universe.py", "--no-fetch"])
        assert main() == 0

    def test_main_json_format_emits_valid_json(self, universe_cwd, db_with_data, monkeypatch, capsys):
        from scripts.validate_universe import main

        monkeypatch.setattr("sys.argv", ["validate_universe.py", "--no-fetch", "--format", "json"])
        rc = main()
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert rc == 0
        assert parsed["exit_code"] == 0
        assert "checks" in parsed
        assert len(parsed["checks"]) == 5

    def test_main_table_format_prints_header(self, universe_cwd, db_with_data, monkeypatch, capsys):
        from scripts.validate_universe import main

        monkeypatch.setattr("sys.argv", ["validate_universe.py", "--no-fetch"])
        main()
        out = capsys.readouterr().out
        assert "Universe + Agent Coverage Validation" in out


# ═══════════════════════════════════════════════════════
# fetch_upstream_universes — network-mocked
# ═══════════════════════════════════════════════════════


class TestFetchUpstream:
    def test_both_sources_fail_returns_empty_sets(self, capsys):
        from scripts.validate_universe import fetch_upstream_universes

        with (
            patch("nuri.collectors.universe_sync._fetch_sp500_from_wikipedia", side_effect=RuntimeError("wiki down")),
            patch("nuri.collectors.universe_sync._fetch_kospi200", side_effect=RuntimeError("krx down")),
        ):
            us, kr = fetch_upstream_universes()

        assert us == set()
        assert kr == set()
        err = capsys.readouterr().err
        assert "S&P 500 fetch 실패" in err
        assert "KOSPI 200 fetch 실패" in err

    def test_partial_success_returns_one_empty(self):
        """US succeeds, KR fails → US populated, KR empty."""
        from scripts.validate_universe import fetch_upstream_universes

        with (
            patch("nuri.collectors.universe_sync._fetch_sp500_from_wikipedia", return_value=["AAPL", "MSFT"]),
            patch("nuri.collectors.universe_sync._fetch_kospi200", side_effect=RuntimeError("krx 500")),
        ):
            us, kr = fetch_upstream_universes()

        assert us == {"AAPL", "MSFT"}
        assert kr == set()
