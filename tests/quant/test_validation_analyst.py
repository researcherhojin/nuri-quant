"""Tests for validation_analyst — split from test_quant_all.py."""

from datetime import datetime, timedelta
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


class TestAnalystBacktest:
    """C-3 (from test_validation.py)."""

    def test_insufficient_data_message(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []


class TestAnalystBacktest_Extra:
    """(from test_coverage_extra.py)."""

    def test_validate_estimates(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(db_path=db_path)
        assert isinstance(results, list)

    def test_estimate_result_class(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult

        r = EstimateResult(
            ticker="AAPL",
            estimate_date="2026-01-01",
            recommendation="Buy",
            target_mean=200.0,
            price_at_estimate=180.0,
            actual_price=195.0,
            actual_date="2026-04-01",
            target_gap_pct=11.1,
            actual_return_pct=8.3,
            target_hit=False,
        )
        assert r.target_hit is False
        assert r.ticker == "AAPL"


class TestAnalystBacktestData:
    """(from test_coverage_round12.py)."""

    def test_with_estimates_data(self, rich_db):
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO estimates "
                "(ticker, date, recommendation, target_high, target_low, "
                "target_mean, target_median, num_analysts, current_price) "
                "VALUES ('AAPL', '2025-06-01', 'buy', 250, 180, 220, 215, 30, 190)"
            )
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates()
        assert isinstance(results, list)


class TestAnalystBacktestBranches:
    """Cover branches: oldest msg, target_mean None/0, no price_at, no price_after, full hit."""

    def _seed_estimate(self, db_path, ticker, date, target_mean=200.0, recommendation="buy"):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO estimates "
                "(ticker, date, recommendation, target_high, target_low, "
                "target_mean, target_median, num_analysts, current_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticker,
                    date,
                    recommendation,
                    target_mean and target_mean * 1.1,
                    target_mean and target_mean * 0.9,
                    target_mean,
                    target_mean,
                    10,
                    100,
                ),
            )

    def _seed_price(self, db_path, ticker, date, close):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date, close, close, close, close, 1000),
            )

    def test_oldest_estimate_warning_branch(self, db_path, caplog):
        """Estimates 있지만 너무 최근이라 검증 불가 → 경고 메시지 (lines 62-72)."""
        # 최근 (오늘) estimate — min_elapsed=90 보다 짧음
        recent_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "AAA", recent_date)
        from nuri.quant.validation.analyst_backtest import validate_estimates

        with caplog.at_level("WARNING"):
            results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []
        assert any("검증 가능 시점" in r.message for r in caplog.records)

    def test_skip_when_target_mean_zero(self, db_path):
        """target_mean=0 → continue (line 86)."""
        old = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "AAA", old, target_mean=0)
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_skip_when_no_price_at_estimate(self, db_path):
        """price_at 없음 → continue (line 94)."""
        old = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "BBB", old, target_mean=200.0)
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_skip_when_price_at_estimate_zero(self, db_path):
        """price_at_estimate <= 0 → continue (line 97)."""
        old = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "CCC", old, target_mean=200.0)
        self._seed_price(db_path, "CCC", old, 0.0)
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_skip_when_no_price_after(self, db_path, monkeypatch):
        """price_after 없음 → continue (line 106). 두 번째 query 만 빈 결과 반환하도록 patch."""
        from nuri.core.db import query as real_query
        from nuri.quant.validation import analyst_backtest as ab_mod

        old = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "DDD", old, target_mean=200.0)
        self._seed_price(db_path, "DDD", old, 100.0)

        call_count = {"n": 0}

        def stub_query(sql, params=None, db_path=None):
            # 1st: estimates lookup (allow real)
            # 2nd: price_at lookup (allow real)
            # 3rd: price_after lookup → return empty
            call_count["n"] += 1
            if call_count["n"] == 3:
                return []
            return real_query(sql, params, db_path=db_path)

        monkeypatch.setattr(ab_mod, "query", stub_query)
        results = ab_mod.validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_full_validation_target_hit(self, db_path):
        """Full happy path: target hit (line 113 True) + result append (lines 115-126)."""
        old = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        after_date = (datetime.strptime(old, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
        self._seed_estimate(db_path, "EEE", old, target_mean=110.0)
        self._seed_price(db_path, "EEE", old, 100.0)
        self._seed_price(db_path, "EEE", after_date, 120.0)  # 110 target hit
        from nuri.quant.validation.analyst_backtest import validate_estimates

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert len(results) == 1
        r = results[0]
        assert r.ticker == "EEE"
        assert r.target_hit is True
        assert r.actual_price == 120.0


class TestPrintResults:
    def test_empty_silent(self, capsys):
        from nuri.quant.validation.analyst_backtest import print_results

        print_results([])
        out = capsys.readouterr().out
        assert out == ""

    def test_print_with_data(self, capsys):
        from nuri.quant.validation.analyst_backtest import EstimateResult, print_results

        rs = [
            EstimateResult(
                ticker="AAA",
                estimate_date="2026-01-01",
                recommendation="buy",
                target_mean=200.0,
                price_at_estimate=180.0,
                actual_price=210.0,
                actual_date="2026-04-01",
                target_gap_pct=11.1,
                actual_return_pct=16.7,
                target_hit=True,
            ),
            EstimateResult(
                ticker="BBB",
                estimate_date="2026-01-01",
                recommendation="hold",
                target_mean=100.0,
                price_at_estimate=110.0,
                actual_price=95.0,
                actual_date="2026-04-01",
                target_gap_pct=-9.1,
                actual_return_pct=-13.6,
                target_hit=False,
            ),
        ]
        print_results(rs)
        out = capsys.readouterr().out
        assert "AAA" in out
        assert "적중률" in out
