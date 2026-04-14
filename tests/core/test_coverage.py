"""Tests for nuri.core.coverage — pure functions, no network.

#272 Phase 2c. Covers compute_data_coverage, compute_universe_match,
compute_all_data_coverage, summary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nuri.core.coverage import (
    DATA_THRESHOLDS,
    UNIVERSE_THRESHOLD,
    US_ONLY_TABLES,
    CoverageCheck,
    _load_universe,
    compute_all_data_coverage,
    compute_data_coverage,
    compute_universe_match,
    summary,
)


@pytest.fixture
def universe_yaml(tmp_path, monkeypatch):
    """temp universe.yaml + cwd 변경."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "universe.yaml").write_text(
        yaml.safe_dump(
            {
                "us_core": {"tickers": ["AAPL", "MSFT"]},
                "us_sp500_extended": {"tickers": ["GOOGL", "NVDA"]},
                "kr_kospi200": {"tickers": ["005930.KS", "000660.KS"]},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path / "config" / "universe.yaml"


# ───────────────────────────────────────────────
# CoverageCheck dataclass
# ───────────────────────────────────────────────


class TestCoverageCheck:
    def test_passed_property(self):
        assert CoverageCheck("x", 1.0, 0.95, "PASS").passed is True
        assert CoverageCheck("x", 0.5, 0.95, "FAIL").passed is False


# ───────────────────────────────────────────────
# _load_universe
# ───────────────────────────────────────────────


class TestLoadUniverse:
    def test_loads_all_sections(self, universe_yaml):
        u = _load_universe()
        assert u["us"] == {"AAPL", "MSFT", "GOOGL", "NVDA"}
        assert u["kr"] == {"005930.KS", "000660.KS"}

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        u = _load_universe()
        assert u == {"us": set(), "kr": set()}


# ───────────────────────────────────────────────
# compute_data_coverage
# ───────────────────────────────────────────────


class TestDataCoverage:
    def test_pass_threshold(self, universe_yaml):
        # 4 US universe, mock DB has 4 → 100%
        with patch("nuri.core.coverage._table_tickers", return_value={"AAPL", "MSFT", "GOOGL", "NVDA"}):
            uni = _load_universe()
            check = compute_data_coverage("prices", 0.95, uni)
        assert check.passed is True
        assert check.actual_pct == 1.0
        assert check.name == "data.prices"

    def test_fail_below_threshold(self, universe_yaml):
        with patch("nuri.core.coverage._table_tickers", return_value={"AAPL"}):
            uni = _load_universe()
            check = compute_data_coverage("fundamentals", 0.80, uni)
        assert check.passed is False
        assert check.actual_pct == 0.25  # 1/4

    def test_kr_tickers_excluded_from_us_check(self, universe_yaml):
        # KR tickers in DB — not counted toward US universe coverage
        with patch("nuri.core.coverage._table_tickers", return_value={"005930.KS", "AAPL"}):
            uni = _load_universe()
            check = compute_data_coverage("prices", 0.95, uni)
        # AAPL matches (1/4 = 25%). 005930.KS not in us_uni.
        assert check.actual_pct == 0.25

    def test_empty_universe_returns_fail(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        check = compute_data_coverage("prices", 0.95, _load_universe())
        assert check.passed is False
        assert "universe.yaml" in check.detail

    def test_db_query_failure_returns_fail(self, universe_yaml):
        uni = _load_universe()
        with patch("nuri.core.coverage._table_tickers", side_effect=Exception("no such table: foo")):
            check = compute_data_coverage("foo", 0.5, uni)
        assert check.passed is False
        assert "조회 실패" in check.detail


# ───────────────────────────────────────────────
# compute_universe_match
# ───────────────────────────────────────────────


class TestUniverseMatch:
    def test_us_pass(self, universe_yaml):
        uni = _load_universe()
        # Wikipedia returns AAPL+MSFT+GOOGL+NVDA — same as universe → 100%
        check = compute_universe_match(
            "us_sp500",
            {"AAPL", "MSFT", "GOOGL", "NVDA"},
            uni,
            market="us",
            threshold=0.95,
        )
        assert check.passed is True
        assert check.actual_pct == 1.0

    def test_us_fail_when_extras_missing(self, universe_yaml):
        uni = _load_universe()
        # Wikipedia returns 10 tickers, only 4 in universe → 40%
        upstream = {"AAPL", "MSFT", "GOOGL", "NVDA", "X1", "X2", "X3", "X4", "X5", "X6"}
        check = compute_universe_match("us_sp500", upstream, uni, market="us", threshold=0.95)
        assert check.passed is False
        assert check.actual_pct == 0.4

    def test_empty_upstream_fails(self, universe_yaml):
        uni = _load_universe()
        check = compute_universe_match("us_sp500", set(), uni, market="us")
        assert check.passed is False
        assert "upstream fetch" in check.detail


# ───────────────────────────────────────────────
# compute_all_data_coverage + summary
# ───────────────────────────────────────────────


class TestAllDataCoverage:
    def test_returns_5_checks(self, universe_yaml):
        with patch("nuri.core.coverage._table_tickers", return_value=set()):
            checks = compute_all_data_coverage()
        assert len(checks) == 5
        names = {c.name for c in checks}
        assert "data.prices" in names
        assert "data.fundamentals" in names
        assert "data.analyst_ratings" in names
        assert "data.insider_trades" in names
        assert "data.superinvestors" in names

    def test_all_use_correct_thresholds(self, universe_yaml):
        with patch("nuri.core.coverage._table_tickers", return_value=set()):
            checks = compute_all_data_coverage()
        for c in checks:
            table_name = c.name.replace("data.", "")
            assert c.threshold == DATA_THRESHOLDS[table_name]


class TestSummary:
    def test_all_pass(self):
        checks = [
            CoverageCheck("a", 1.0, 0.95, "PASS"),
            CoverageCheck("b", 0.85, 0.80, "PASS"),
        ]
        s = summary(checks)
        assert s["pass"] == 2
        assert s["fail"] == 0
        assert s["exit_code"] == 0

    def test_one_fail_triggers_exit_1(self):
        checks = [
            CoverageCheck("a", 1.0, 0.95, "PASS"),
            CoverageCheck("b", 0.5, 0.80, "FAIL"),
        ]
        s = summary(checks)
        assert s["fail"] == 1
        assert s["exit_code"] == 1

    def test_json_serializable(self):
        import json

        checks = [CoverageCheck("a", 0.99, 0.95, "PASS", "1/2")]
        s = summary(checks)
        # Should not raise
        json.dumps(s)

    def test_check_dict_format(self):
        checks = [CoverageCheck("a", 0.99123, 0.95, "PASS", "detail")]
        s = summary(checks)
        check_dict = s["checks"][0]
        assert check_dict["name"] == "a"
        assert check_dict["actual"] == 0.9912  # rounded to 4 places
        assert check_dict["threshold"] == 0.95
        assert check_dict["status"] == "PASS"
        assert check_dict["detail"] == "detail"


# ───────────────────────────────────────────────
# UNIVERSE_THRESHOLD constant
# ───────────────────────────────────────────────


class TestConstants:
    def test_universe_threshold_is_95(self):
        assert UNIVERSE_THRESHOLD == 0.95

    def test_data_thresholds_per_spec(self):
        # Spec §2.2 기준
        assert DATA_THRESHOLDS["prices"] == 0.95
        assert DATA_THRESHOLDS["fundamentals"] == 0.80
        assert DATA_THRESHOLDS["analyst_ratings"] == 0.70
        assert DATA_THRESHOLDS["insider_trades"] == 0.50
        assert DATA_THRESHOLDS["superinvestors"] == 0.80


# ───────────────────────────────────────────────
# US_ONLY_TABLES — #288 KR "n/a (US-only)" marker
# ───────────────────────────────────────────────


class TestUsOnlyTables:
    """Tables whose data source doesn't cover KR (yfinance .KS / SEC EDGAR)."""

    def test_expected_tables_are_us_only(self):
        """Exact membership — guards against accidental additions/removals."""
        assert US_ONLY_TABLES == frozenset(
            {
                "analyst_ratings",
                "insider_trades",
                "superinvestors",
                "estimates",
                "earnings_surprises",
            }
        )

    def test_prices_and_fundamentals_not_us_only(self):
        """KR price + fundamental data IS available via yfinance/pykrx."""
        assert "prices" not in US_ONLY_TABLES
        assert "fundamentals" not in US_ONLY_TABLES

    def test_data_coverage_detail_notes_kr_unavailable(self, universe_yaml, tmp_path):
        """compute_data_coverage appends KR-unavailable note to detail for US-only tables."""
        from nuri.core.db import get_db, init_db

        db = tmp_path / "test.db"
        init_db(db)
        with get_db(db) as conn:
            for t in ["AAPL", "MSFT", "GOOGL", "NVDA"]:
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, action, to_grade) VALUES (?, ?, ?, ?, ?)",
                    (t, "2026-04-14", "Firm", "up", "Buy"),
                )

        universe = _load_universe(universe_yaml)
        check = compute_data_coverage("analyst_ratings", 0.70, universe, db_path=db)
        assert check.passed is True
        assert "KR n/a" in check.detail or "소스 미지원" in check.detail

    def test_data_coverage_non_us_only_table_omits_kr_note(self, universe_yaml, tmp_path):
        """Non-US-only tables (prices) should NOT have the KR note."""
        import pandas as pd

        from nuri.core.db import init_db, upsert_prices

        db = tmp_path / "test.db"
        init_db(db)
        df = pd.DataFrame(
            [
                {
                    "ticker": t,
                    "date": "2026-04-14",
                    "open": 1,
                    "high": 2,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 1000,
                    "adj_close": 1.5,
                }
                for t in ["AAPL", "MSFT", "GOOGL", "NVDA"]
            ]
        )
        upsert_prices(df, db_path=db)

        universe = _load_universe(universe_yaml)
        check = compute_data_coverage("prices", 0.95, universe, db_path=db)
        assert "KR n/a" not in check.detail
        assert "소스 미지원" not in check.detail
