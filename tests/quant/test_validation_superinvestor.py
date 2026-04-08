"""Tests for validation_superinvestor — split from test_quant_all.py."""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.quant._helpers import (  # noqa: F401
    _insert_spy_data,
    _insert_spy_data_trend,
    _seed_macro,
    _seed_portfolio,
    _seed_prices,
    _seed_spy_data,
)


class TestSuperinvestorBacktest:
    """C-2 (from test_validation.py)."""

    def test_data_readiness_check(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=db_path) is False

    def test_empty_backtest(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor(db_path=db_path)
        assert results == []


class TestSuperinvestorBacktest_Final:
    """(from test_coverage_final.py)."""

    def test_import(self):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        assert callable(backtest_superinvestor)

    def test_data_readiness_empty(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        ready = _check_data_readiness(db_path=db_path)
        assert ready is False

    def test_get_price_not_found(self, db_path):
        from nuri.quant.validation.superinvestor_backtest import _get_price_on_or_after
        result = _get_price_on_or_after("FAKE", "2026-01-01", db_path=db_path)
        assert result is None


class TestSuperinvestorBacktest_R19:
    """(from test_coverage_round19.py)."""

    def test_check_data_readiness_no_data(self, tmp_path):
        path = tmp_path / "test.db"
        init_db(path)
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_one_quarter(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_two_quarters(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-04-15", 120000, 60000000),
            )
        assert _check_data_readiness(db_path=path) is True

    def test_backtest_no_data_returns_empty(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        path = tmp_path / "test.db"
        init_db(path)
        results = backtest_superinvestor(db_path=path)
        assert results == []

    def test_generate_scorecard_empty(self):
        from nuri.quant.validation.superinvestor_backtest import generate_scorecard
        assert generate_scorecard([], 120) == []

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.superinvestor_backtest import FollowResult, generate_scorecard
        results = [
            FollowResult(investor="Buffett", ticker="AAPL", filing_date="2025-01-15",
                         change_type="NEW", entry_date="2025-01-16", entry_price=190.0,
                         exit_date="2025-05-16", exit_price=210.0,
                         return_pct=10.53, benchmark_return_pct=5.0, excess_return_pct=5.53),
            FollowResult(investor="Buffett", ticker="MSFT", filing_date="2025-01-15",
                         change_type="INCREASED", entry_date="2025-01-16", entry_price=400.0,
                         exit_date="2025-05-16", exit_price=380.0,
                         return_pct=-5.0, benchmark_return_pct=5.0, excess_return_pct=-10.0),
        ]
        scorecards = generate_scorecard(results, 120)
        assert len(scorecards) == 1
        sc = scorecards[0]
        assert sc.investor == "Buffett"
        assert sc.total_follows == 2
        assert sc.win_rate == 0.5

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out

    def test_print_scorecard_with_data(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import InvestorScorecard, print_scorecard
        sc = InvestorScorecard(
            investor="Buffett", hold_days=120, total_follows=5,
            win_rate=0.6, avg_return=8.5, avg_excess_return=3.2,
            best_ticker="AAPL", best_return=25.0,
            worst_ticker="META", worst_return=-10.0,
        )
        print_scorecard([sc])
        captured = capsys.readouterr()
        assert "Buffett" in captured.out
        assert "120일" in captured.out


class TestSuperinvestorBacktestData:
    """(from test_coverage_round12.py)."""

    def test_backtest_with_superinvestor_data(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO superinvestors "
                "(investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Buffett', '2025-08-15', 'AAPL', 900000000, 171000000000, 48.5, 'Apple Inc')")
            conn.execute(
                "INSERT OR REPLACE INTO superinvestors "
                "(investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name) "
                "VALUES ('Buffett', '2025-02-15', 'AAPL', 905000000, 165000000000, 49.0, 'Apple Inc')")
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor()
        assert isinstance(results, list)


class TestSuperinvestorBacktestIntegration:
    """(from test_coverage_round19.py)."""

    def test_backtest_with_mocked_detect_changes(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-02-15", 100000, 50000000))
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-05-15", 120000, 60000000))
        mock_changes = pd.DataFrame([{
            "ticker": "AAPL", "filing_date": "2024-05-15",
            "change_type": "INCREASED", "shares_change": 20000,
        }])
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        with patch("nuri.collectors.superinvestors.detect_changes", return_value=mock_changes), \
             patch("nuri.collectors.superinvestors.SUPERINVESTORS", {"Warren Buffett": "0000000001"}):
            results = backtest_superinvestor(investor="Warren Buffett", hold_days=30, db_path=rich_db)
        assert isinstance(results, list)
        if results:
            assert results[0].investor == "Warren Buffett"
            assert results[0].ticker == "AAPL"
