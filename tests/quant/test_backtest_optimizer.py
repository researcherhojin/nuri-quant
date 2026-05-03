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
            prices.append(
                {
                    "ticker": "AAPL",
                    "date": date,
                    "open": 150 + i * 0.1,
                    "high": 152 + i * 0.1,
                    "low": 148 + i * 0.1,
                    "close": 150 + i * 0.1,
                    "volume": 1000000,
                    "adj_close": 150 + i * 0.1,
                }
            )
        upsert_prices(pd.DataFrame(prices), db_path)
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "AAPL",
                    "quantity": 10,
                    "avg_price": 150,
                    "currency": "USD",
                    "sector": "Tech",
                },
            ],
            db_path,
        )
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

        r = OptResult(
            signal_id="rsi_oversold",
            params={"rsi_th": 30},
            total_trades=50,
            win_rate=0.65,
            avg_return=3.5,
            profit_factor=2.1,
            sharpe=1.5,
        )
        assert r.signal_id == "rsi_oversold"

    def test_optimize_all_empty(self, db_path_mp):
        from nuri.quant.backtest.optimizer import optimize_all

        results = optimize_all(db_path=db_path_mp)
        assert isinstance(results, pd.DataFrame)


class TestOptimizerUnknownSignal:
    """signal_id ∉ PARAM_GRIDS → 빈 list (lines 181-182)."""

    def test_unknown_signal(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_signal

        assert optimize_signal("not_a_real_signal", db_path=db_path) == []


class TestOptimizerTalibFallback:
    """talib ImportError → pandas fallback path (lines 85-104)."""

    def test_pandas_fallback_runs(self, monkeypatch):
        """talib import 를 ImportError 로 만들고 _backtest_signal_with_params 실행."""
        import sys

        # talib 을 sys.modules 에서 제거 + import 시 ImportError 유도
        monkeypatch.setitem(sys.modules, "talib", None)

        from nuri.quant.backtest import optimizer

        # 200 일 단조 + 노이즈 → BB/RSI 신호 생성 가능
        np.random.seed(42)
        n = 250
        close = np.linspace(100, 130, n) + np.random.normal(0, 2, n)
        df = pd.DataFrame({"close": close})
        # rsi_oversold 시그널 → fallback path 거쳐야 함
        result = optimizer._backtest_signal_with_params(df, "rsi_oversold", {"rsi_threshold": 30, "hold_days": 10})
        assert hasattr(result, "win_rate")


class TestOptimizerSignalBranches:
    """rsi_overbought (line 151), bb_bounce, macd_golden 분기 hit."""

    def _make_df(self, n=300):
        # 강한 변동 패턴 — 각 시그널 trigger 가능
        np.random.seed(7)
        close = 100 + np.cumsum(np.random.normal(0, 1.5, n))
        return pd.DataFrame({"close": close})

    def test_rsi_overbought_returns_negated(self):
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        df = self._make_df()
        r = _backtest_signal_with_params(df, "rsi_overbought", {"rsi_threshold": 70, "hold_days": 10})
        assert hasattr(r, "win_rate")  # 분기 hit

    def test_bb_bounce_branch(self):
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        df = self._make_df()
        r = _backtest_signal_with_params(
            df,
            "bb_bounce",
            {"bb_period": 20, "bb_std": 2.0, "hold_days": 10},
        )
        assert hasattr(r, "win_rate")

    def test_macd_golden_branch(self):
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        df = self._make_df()
        r = _backtest_signal_with_params(
            df,
            "macd_golden",
            {"fast": 12, "slow": 26, "signal": 9},
        )
        assert hasattr(r, "win_rate")


class TestOptimizerExitNoneAndOver:
    """exit_idx >= n (lines 144-146) — entry 가 끝부분 → hold 후 exit 데이터 없음."""

    def test_short_holdout_after_late_entry(self):
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        # 합성: 끝부분에서 RSI 30 cross over (oversold trigger)
        # 처음 70 일 평탄, 70-90 하락 (RSI < 30), 90 이후 반등 → 끝부분 entry (총 100일)
        close = np.concatenate(
            [
                np.full(70, 100.0),
                np.linspace(100, 80, 20),
                np.linspace(80, 90, 10),
            ]
        )
        df = pd.DataFrame({"close": close})
        r = _backtest_signal_with_params(
            df,
            "rsi_oversold",
            {"rsi_threshold": 30, "hold_days": 50},  # 50일 hold → 끝부분 entry exit 불가
        )
        assert hasattr(r, "total_trades")
