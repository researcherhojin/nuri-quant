"""Tests for backoptimizer — split from test_quant_all.py."""
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


class TestOptimizer:
    """(from test_coverage_round5.py)."""

    def test_optimize_signal_import(self):
        from nuri.quant.backtest.optimizer import optimize_signal
        assert callable(optimize_signal)


class TestOptimizer_NewFeatures:
    """(from test_new_features.py)."""

    def test_optimize_signal(self, db_path):
        prices = []
        for i in range(200):
            date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
            prices.append({
                "ticker": "AAPL", "date": date,
                "open": 150 + i * 0.1, "high": 152 + i * 0.1,
                "low": 148 + i * 0.1, "close": 150 + i * 0.1,
                "volume": 1000000, "adj_close": 150 + i * 0.1,
            })
        upsert_prices(pd.DataFrame(prices), db_path)
        upsert_portfolio([
            {"account": "test", "ticker": "AAPL", "quantity": 10,
             "avg_price": 150, "currency": "USD", "sector": "Tech"},
        ], db_path)
        from nuri.quant.backtest.optimizer import optimize_signal
        results = optimize_signal("rsi_oversold", db_path=db_path)
        assert isinstance(results, list)


class TestOptimizerExtended:
    """(from test_sixty_percent.py)."""

    def test_optimize_signal(self, full_db):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("rsi_oversold", db_path=full_db)
        assert isinstance(result, (list, type(None)))

    def test_backtest_with_params(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty and len(df) > 50:
            result = _backtest_signal_with_params(df, "rsi_oversold", {"rsi_entry": 30, "rsi_exit": 70})
            assert result is None or hasattr(result, "win_rate")


class TestOptimizerAll:
    """(from test_coverage_round8.py)."""

    def test_optimize_all(self, rich_db):
        from nuri.quant.backtest.optimizer import optimize_all
        result = optimize_all()
        assert isinstance(result, pd.DataFrame)


class TestOptimizer_Push:
    """(from test_coverage_push.py)."""

    def test_opt_result(self):
        from nuri.quant.backtest.optimizer import OptResult
        r = OptResult(signal_id="rsi_oversold", params={"rsi_th": 30},
                      total_trades=50, win_rate=0.65, avg_return=3.5, profit_factor=2.1, sharpe=1.5)
        assert r.signal_id == "rsi_oversold"

    def test_optimize_all_empty(self, db_path_mp):
        from nuri.quant.backtest.optimizer import optimize_all
        results = optimize_all(db_path=db_path_mp)
        assert isinstance(results, pd.DataFrame)
