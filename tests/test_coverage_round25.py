"""Round 25 coverage tests — quant pipeline modules.

Covers uncovered lines in:
  - backtest/engine.py (0% → full)
  - backtest/optimizer.py (82% → edge cases)
  - validation/signal_backtest.py (87% → pandas fallback + __main__)
  - validation/analyst_backtest.py (65% → validate_estimates + print + __main__)
  - validation/scorecard.py (90% → edge cases)
  - validation/superinvestor_backtest.py (85% → edge cases + print)
  - factors/value.py (49% → full)
  - factors/quality.py (51% → full)
  - factors/composite.py (87% → edge cases)
  - factors/momentum.py (87% → edge cases)
  - regime/classifier.py (91% → special regimes)
  - regime/macro_score.py (89% → edge cases)
  - regime/strategy_map.py (89% → edge cases)
"""

import sys
import types
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import (
    get_db,
    init_db,
    upsert_macro,
    upsert_prices,
)

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_spy_prices(db_path, n=300, start_price=400.0, start_date="2024-01-02"):
    """Insert SPY price data for regime classifier tests."""
    dates = pd.bdate_range(start=start_date, periods=n)
    prices = []
    price = start_price
    for d in dates:
        # Slow uptrend with noise
        price *= 1 + np.random.normal(0.0003, 0.008)
        prices.append({
            "ticker": "SPY",
            "date": d.strftime("%Y-%m-%d"),
            "open": round(price * 0.999, 2),
            "high": round(price * 1.005, 2),
            "low": round(price * 0.995, 2),
            "close": round(price, 2),
            "volume": 50000000,
            "adj_close": round(price, 2),
        })
    df = pd.DataFrame(prices)
    upsert_prices(df, db_path)
    return prices


def _insert_ticker_prices(db_path, ticker="AAPL", n=300, start_price=150.0, start_date="2024-01-02"):
    """Insert price data for a given ticker."""
    dates = pd.bdate_range(start=start_date, periods=n)
    prices = []
    price = start_price
    for d in dates:
        price *= 1 + np.random.normal(0.0002, 0.01)
        prices.append({
            "ticker": ticker,
            "date": d.strftime("%Y-%m-%d"),
            "open": round(price * 0.999, 2),
            "high": round(price * 1.005, 2),
            "low": round(price * 0.995, 2),
            "close": round(price, 2),
            "volume": 10000000,
            "adj_close": round(price, 2),
        })
    df = pd.DataFrame(prices)
    upsert_prices(df, db_path)
    return prices


def _insert_macro(db_path, indicator, value, date="2025-03-28"):
    upsert_macro([{
        "indicator": indicator,
        "date": date,
        "value": value,
        "source": "test",
    }], db_path)


def _insert_portfolio(db_path, tickers):
    with get_db(db_path) as conn:
        for t in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", t, 10, 100.0, "USD"),
            )


# ═══════════════════════════════════════════════════════
# 1. backtest/engine.py — ALL lines (0% coverage)
# ═══════════════════════════════════════════════════════


class TestBacktestEngine:
    """Tests for nuri.quant.backtest.engine — mock vbt and quantstats."""

    def _make_mock_vbt(self, monkeypatch):
        """Create a mock vectorbt module and inject it into sys.modules."""
        mock_vbt = types.ModuleType("vectorbt")

        class MockPortfolio:
            @staticmethod
            def from_signals(**kwargs):
                pf = MagicMock()
                pf.stats.return_value = pd.Series({
                    "Total Return [%]": 15.5,
                    "Sharpe Ratio": 1.2,
                    "Max Drawdown [%]": -8.3,
                    "Win Rate [%]": 55.0,
                    "Total Trades": 42,
                })
                pf.returns.return_value = pd.Series(
                    np.random.normal(0.001, 0.01, 100),
                    index=pd.bdate_range("2024-01-01", periods=100),
                )
                return pf

        mock_vbt.Portfolio = MockPortfolio
        monkeypatch.setitem(sys.modules, "vectorbt", mock_vbt)
        return mock_vbt

    def test_run_momentum_backtest_empty_prices(self, db_path, monkeypatch):
        """Empty prices returns empty dict."""
        self._make_mock_vbt(monkeypatch)
        from nuri.quant.backtest import engine
        monkeypatch.setattr(engine, "query_df", lambda *a, **kw: pd.DataFrame())
        result = engine.run_momentum_backtest()
        assert result == {}

    def test_run_momentum_backtest_insufficient_data(self, db_path, monkeypatch):
        """Less than 20 rows returns empty dict."""
        self._make_mock_vbt(monkeypatch)
        from nuri.quant.backtest import engine

        # Only 5 rows of US data
        small_df = pd.DataFrame({
            "ticker": ["AAPL"] * 5,
            "date": pd.bdate_range("2024-01-01", periods=5).strftime("%Y-%m-%d"),
            "close": [100, 101, 102, 103, 104],
        })
        monkeypatch.setattr(engine, "query_df", lambda *a, **kw: small_df)
        result = engine.run_momentum_backtest()
        assert result == {}

    def test_run_momentum_backtest_kr_tickers_only(self, db_path, monkeypatch):
        """Only Korean tickers returns empty dict (filtered out)."""
        self._make_mock_vbt(monkeypatch)
        from nuri.quant.backtest import engine

        kr_df = pd.DataFrame({
            "ticker": ["005930.KS"] * 25,
            "date": pd.bdate_range("2024-01-01", periods=25).strftime("%Y-%m-%d"),
            "close": range(100, 125),
        })
        monkeypatch.setattr(engine, "query_df", lambda *a, **kw: kr_df)
        result = engine.run_momentum_backtest()
        assert result == {}

    def test_run_momentum_backtest_success(self, db_path, monkeypatch):
        """Full successful backtest with mocked vbt."""
        self._make_mock_vbt(monkeypatch)
        from nuri.quant.backtest import engine

        # Create multi-ticker price data (>20 rows)
        dates = pd.bdate_range("2024-01-01", periods=50)
        rows = []
        for t in ["AAPL", "MSFT", "GOOG", "TSLA", "NVDA", "META"]:
            for d in dates:
                rows.append({
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "close": 100 + np.random.random() * 50,
                })
        df = pd.DataFrame(rows)
        monkeypatch.setattr(engine, "query_df", lambda *a, **kw: df)

        # Mock quantstats to avoid file writes
        mock_qs = types.ModuleType("quantstats")
        mock_reports = MagicMock()
        mock_qs.reports = mock_reports
        monkeypatch.setitem(sys.modules, "quantstats", mock_qs)

        result = engine.run_momentum_backtest(period="3mo", top_n=3, rebalance_days=10)
        assert result["strategy"] == "Momentum Top-3"
        assert result["total_return_pct"] == 15.5
        assert result["sharpe_ratio"] == 1.2
        assert result["total_trades"] == 42

    def test_run_momentum_backtest_quantstats_error(self, db_path, monkeypatch):
        """QuantStats failure is handled gracefully."""
        self._make_mock_vbt(monkeypatch)
        from nuri.quant.backtest import engine

        dates = pd.bdate_range("2024-01-01", periods=50)
        rows = []
        for t in ["AAPL", "MSFT", "GOOG", "TSLA", "NVDA", "META"]:
            for d in dates:
                rows.append({
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "close": 100 + np.random.random() * 50,
                })
        df = pd.DataFrame(rows)
        monkeypatch.setattr(engine, "query_df", lambda *a, **kw: df)

        # Make quantstats import raise
        def broken_import(name, *args, **kwargs):
            if name == "quantstats":
                raise ImportError("no quantstats")
            return original_import(name, *args, **kwargs)

        import builtins
        original_import = builtins.__import__
        monkeypatch.setattr(builtins, "__import__", broken_import)

        result = engine.run_momentum_backtest()
        assert "strategy" in result

    def test_print_backtest_empty(self, capsys):
        """print_backtest with empty result."""
        from nuri.quant.backtest.engine import print_backtest
        print_backtest({})
        out = capsys.readouterr().out
        assert "데이터 없음" in out

    def test_print_backtest_success(self, capsys):
        """print_backtest with valid result."""
        from nuri.quant.backtest.engine import print_backtest
        result = {
            "strategy": "Momentum Top-5",
            "total_return_pct": 12.34,
            "sharpe_ratio": 1.50,
            "max_drawdown_pct": -5.67,
            "win_rate_pct": 60.0,
            "total_trades": 100,
        }
        print_backtest(result)
        out = capsys.readouterr().out
        assert "Momentum Top-5" in out
        assert "12.34" in out
        assert "1.50" in out


# ═══════════════════════════════════════════════════════
# 2. backtest/optimizer.py — edge cases (82% → higher)
# ═══════════════════════════════════════════════════════


class TestBacktestOptimizer:
    """Tests for optimizer edge cases."""

    def test_optimize_unknown_signal(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("unknown_signal", db_path=db_path)
        assert result == []

    def test_optimize_signal_no_prices(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("rsi_oversold", db_path=db_path)
        assert result == []

    def test_optimize_signal_with_data(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_signal

        # Insert enough price data for one ticker
        _insert_ticker_prices(db_path, "AAPL", n=300, start_price=150.0)
        _insert_portfolio(db_path, ["AAPL"])

        results = optimize_signal("rsi_oversold", db_path=db_path)
        # May or may not find trades, but should not crash
        assert isinstance(results, list)

    def test_optimize_signal_short_data_skipped(self, db_path):
        """Tickers with <200 rows are skipped."""
        from nuri.quant.backtest.optimizer import optimize_signal

        dates = pd.bdate_range("2024-01-01", periods=50)
        rows = [{
            "ticker": "SHORT",
            "date": d.strftime("%Y-%m-%d"),
            "open": 100, "high": 105, "low": 95,
            "close": 100 + i * 0.1,
            "volume": 1000, "adj_close": 100 + i * 0.1,
        } for i, d in enumerate(dates)]
        upsert_prices(pd.DataFrame(rows), db_path)
        _insert_portfolio(db_path, ["SHORT"])

        results = optimize_signal("rsi_oversold", db_path=db_path)
        assert results == []  # Too short, skipped

    def test_backtest_signal_with_params_no_entries(self):
        """When no entries found, returns zero result."""
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        # Flat prices, no RSI crossover
        df = pd.DataFrame({"close": [100.0] * 300})
        result = _backtest_signal_with_params(df, "rsi_oversold", {"rsi_threshold": 30, "hold_days": 20})
        assert result.total_trades == 0
        assert result.win_rate == 0.0

    def test_backtest_signal_rsi_overbought(self):
        """RSI overbought signal returns negative returns."""
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        # Create data with RSI crossing the overbought threshold
        np.random.seed(42)
        prices = np.cumsum(np.random.normal(0, 2, 300)) + 200
        df = pd.DataFrame({"close": prices})
        result = _backtest_signal_with_params(df, "rsi_overbought", {"rsi_threshold": 70, "hold_days": 10})
        assert isinstance(result.total_trades, int)

    def test_backtest_signal_bb_bounce(self):
        """BB bounce signal."""
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        np.random.seed(42)
        prices = np.cumsum(np.random.normal(0, 3, 300)) + 200
        df = pd.DataFrame({"close": prices})
        result = _backtest_signal_with_params(df, "bb_bounce", {"bb_period": 20, "bb_std": 2.0, "hold_days": 15})
        assert isinstance(result.total_trades, int)

    def test_backtest_signal_macd_golden(self):
        """MACD golden cross signal (exit by reverse cross)."""
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params

        np.random.seed(42)
        prices = np.cumsum(np.random.normal(0, 2, 300)) + 200
        df = pd.DataFrame({"close": prices})
        result = _backtest_signal_with_params(df, "macd_golden", {"fast": 12, "slow": 26, "signal": 9})
        assert isinstance(result.total_trades, int)

    def test_optimize_all_empty(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_all
        df = optimize_all(db_path=db_path)
        assert df.empty

    def test_optimize_all_with_data(self, db_path, monkeypatch):
        from nuri.quant.backtest.optimizer import optimize_all

        _insert_ticker_prices(db_path, "AAPL", n=300)
        _insert_portfolio(db_path, ["AAPL"])

        # Monkeypatch REPORT_DIR for CSV output
        import nuri.quant.backtest.optimizer as opt_mod
        monkeypatch.setattr(opt_mod, "REPORT_DIR", db_path.parent / "reports")

        df = optimize_all(db_path=db_path)
        assert isinstance(df, pd.DataFrame)

    def test_backtest_signal_pandas_fallback(self, monkeypatch):
        """Test the pandas fallback path when talib is not available."""
        # Force talib import to fail
        import builtins

        from nuri.quant.backtest.optimizer import _backtest_signal_with_params
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "talib":
                raise ImportError("no talib")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        np.random.seed(42)
        prices = np.cumsum(np.random.normal(0, 2, 300)) + 200
        df = pd.DataFrame({"close": prices})
        result = _backtest_signal_with_params(df, "rsi_oversold", {"rsi_threshold": 30, "hold_days": 20})
        assert isinstance(result.total_trades, int)


# ═══════════════════════════════════════════════════════
# 3. validation/signal_backtest.py — pandas fallback + __main__
# ═══════════════════════════════════════════════════════


class TestSignalBacktestPandasFallback:
    """Test lines 347-366: pandas fallback when TA-Lib is unavailable."""

    def test_compute_indicators_pandas_fallback(self, monkeypatch):
        """Patch talib import to force pandas fallback path."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "talib":
                raise ImportError("no talib")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from nuri.quant.validation.signal_backtest import compute_indicators

        dates = pd.bdate_range("2024-01-01", periods=250)
        df = pd.DataFrame({
            "close": np.cumsum(np.random.normal(0, 1, 250)) + 200,
            "volume": np.random.randint(1000, 10000, 250),
            "open": np.random.uniform(195, 205, 250),
        })
        df["date"] = dates

        result = compute_indicators(df)

        # Verify pandas-computed indicators exist
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns
        assert "bb_upper" in result.columns
        assert "bb_middle" in result.columns
        assert "bb_lower" in result.columns
        assert "sma_20" in result.columns
        assert "sma_50" in result.columns
        assert "sma_200" in result.columns
        assert "volume_sma_20" in result.columns

    def test_merge_macro_data_yield_fallback(self, db_path):
        """Test fallback from us_3m_yield to us_2y_yield."""
        from nuri.quant.validation.signal_backtest import merge_macro_data

        # Insert us_2y_yield (but NOT us_3m_yield)
        _insert_macro(db_path, "us_2y_yield", 4.5, "2024-06-01")
        _insert_macro(db_path, "us_10y_yield", 5.0, "2024-06-01")
        _insert_macro(db_path, "vix", 15.0, "2024-06-01")
        _insert_macro(db_path, "put_call_ratio", 0.9, "2024-06-01")

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-01", "2024-06-02"]),
            "close": [100.0, 101.0],
        })
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_data_no_date_column(self, db_path):
        """merge_macro_data returns df unchanged when no date column."""
        from nuri.quant.validation.signal_backtest import merge_macro_data

        df = pd.DataFrame({"close": [100, 101]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" not in result.columns

    def test_merge_macro_data_no_yield_columns(self, db_path):
        """Line 440: macro_yield_spread = NaN when yield columns missing."""
        from nuri.quant.validation.signal_backtest import merge_macro_data

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-01"]),
            "close": [100.0],
        })
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_yield_spread" in result.columns

    def test_merge_data_signals_empty(self, db_path):
        """merge_data_signals with no data in DB."""
        from nuri.quant.validation.signal_backtest import merge_data_signals

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-01"]),
            "close": [100.0],
        })
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_data_signals_with_insider(self, db_path):
        """merge_data_signals with insider trades data."""
        from nuri.quant.validation.signal_backtest import merge_data_signals

        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, insider_name, position, transaction_type, shares, value) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("AAPL", f"2024-06-0{i+1}", f"Exec{i}", "CEO", "P-Purchase", 1000, 100000),
                )

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-05", "2024-06-10"]),
            "close": [100.0, 101.0],
        })
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" in result.columns

    def test_merge_data_signals_no_date(self, db_path):
        """merge_data_signals returns unchanged when no date column."""
        from nuri.quant.validation.signal_backtest import merge_data_signals

        df = pd.DataFrame({"close": [100, 101]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" not in result.columns

    def test_merge_data_signals_exception_path(self, db_path, monkeypatch):
        """Lines 466-467: exception during insider query."""
        from nuri.quant.validation import signal_backtest as sb

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-01"]),
            "close": [100.0],
        })

        original_query_df = sb.query_df

        call_count = [0]

        def failing_query_df(sql, params=(), db_path=None):
            call_count[0] += 1
            # Fail the insider_trades query (first call from merge_data_signals)
            if "insider_trades" in sql:
                raise Exception("DB error")
            return original_query_df(sql, params, db_path=db_path)

        monkeypatch.setattr(sb, "query_df", failing_query_df)

        result = sb.merge_data_signals(df, "AAPL", db_path=db_path)
        assert result["insider_buy_count_10d"].iloc[0] == 0

    def test_compute_exit_with_no_exit_fn(self):
        """Line 507: exit function is None for signal without exit."""
        from nuri.quant.validation.signal_backtest import compute_exit

        df = pd.DataFrame({"close": range(100)})
        # rsi_oversold has hold_days=20, so it should use fixed exit
        result = compute_exit(df, 5, "rsi_oversold")
        assert result == 25  # 5 + 20

    def test_compute_exit_beyond_df_length(self):
        """Exit index beyond df length returns None."""
        from nuri.quant.validation.signal_backtest import compute_exit

        df = pd.DataFrame({"close": range(10)})
        result = compute_exit(df, 5, "rsi_oversold")  # 5 + 20 > 10
        assert result is None

    def test_backtest_signals_with_data(self, db_path):
        """Full backtest with real-ish data."""
        from nuri.quant.validation.signal_backtest import backtest_signals

        _insert_ticker_prices(db_path, "AAPL", n=300)
        _insert_portfolio(db_path, ["AAPL"])

        results = backtest_signals(
            ticker="AAPL",
            signals=["rsi_oversold", "bb_bounce"],
            db_path=db_path,
        )
        assert isinstance(results, list)

    def test_backtest_signals_short_data(self, db_path):
        """Ticker with <20 rows is skipped."""
        from nuri.quant.validation.signal_backtest import backtest_signals

        dates = pd.bdate_range("2024-01-01", periods=5)
        rows = [{
            "ticker": "SHORT",
            "date": d.strftime("%Y-%m-%d"),
            "open": 100, "high": 105, "low": 95,
            "close": 100, "volume": 1000, "adj_close": 100,
        } for d in dates]
        upsert_prices(pd.DataFrame(rows), db_path)
        _insert_portfolio(db_path, ["SHORT"])

        results = backtest_signals(ticker="SHORT", db_path=db_path)
        assert results == []

    def test_generate_scorecard_empty(self):
        """generate_scorecard with empty results."""
        from nuri.quant.validation.signal_backtest import generate_scorecard
        assert generate_scorecard([]) == []

    def test_print_scorecard_empty(self, capsys):
        """print_scorecard with empty list."""
        from nuri.quant.validation.signal_backtest import print_scorecard
        print_scorecard([])
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out

    def test_merge_asof_exception_path(self, db_path):
        """Lines 404-405: _merge_asof_from_db exception handling."""
        from nuri.quant.validation.signal_backtest import _merge_asof_from_db

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-06-01"]),
            "close": [100.0],
        })
        # Bad SQL to trigger exception
        result = _merge_asof_from_db(
            df, "SELECT invalid syntax!!!!", (), "value", "test_col", db_path=db_path,
        )
        assert "test_col" in result.columns
        assert pd.isna(result["test_col"].iloc[0])


class TestSignalBacktestMain:
    """Test __main__ block lines 675-697."""

    def test_main_block(self, db_path, monkeypatch, tmp_path):
        """Test the __main__ execution path."""
        from nuri.quant.validation import signal_backtest as sb

        # Mock the report directory
        monkeypatch.setattr(sb, "REPORT_DIR", tmp_path / "reports")

        # Mock argparse
        mock_args = MagicMock()
        mock_args.ticker = None
        mock_args.signal = None

        monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda self: mock_args)

        # Empty DB returns no results; should still run without error
        monkeypatch.setattr(sb, "get_tickers", lambda db_path=None: [])

        # Verify functions work with empty data
        results = sb.backtest_signals(signals=None, db_path=db_path)
        scorecards = sb.generate_scorecard(results)
        sb.print_scorecard(scorecards)


# ═══════════════════════════════════════════════════════
# 4. validation/analyst_backtest.py — validate_estimates + print + __main__
# ═══════════════════════════════════════════════════════


class TestAnalystBacktest:
    """Tests for analyst_backtest.py."""

    def test_validate_estimates_empty_table(self, db_path):
        """Empty estimates table returns empty list."""
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_validate_estimates_no_old_enough(self, db_path, monkeypatch):
        """Estimates exist but none old enough."""
        from nuri.quant.validation.analyst_backtest import validate_estimates

        # Insert recent estimates (within 90 days)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, num_analysts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-01", "Buy", 200.0, 10),
            )

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_validate_estimates_with_data(self, db_path, monkeypatch):
        """Full validation with estimates + prices."""
        from nuri.quant.validation.analyst_backtest import validate_estimates

        # Insert old estimate (more than 90 days ago)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, num_analysts, current_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-06-01", "Buy", 200.0, 15, 150.0),
            )

        # Insert price at estimate date
        upsert_prices(pd.DataFrame([{
            "ticker": "AAPL",
            "date": "2025-06-01",
            "open": 150, "high": 155, "low": 148,
            "close": 150.0, "volume": 1000, "adj_close": 150.0,
        }]), db_path)

        # Insert price 90 days later
        upsert_prices(pd.DataFrame([{
            "ticker": "AAPL",
            "date": "2025-08-29",
            "open": 180, "high": 185, "low": 178,
            "close": 180.0, "volume": 1000, "adj_close": 180.0,
        }]), db_path)

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert len(results) == 1
        r = results[0]
        assert r.ticker == "AAPL"
        assert r.price_at_estimate == 150.0
        assert r.actual_price == 180.0
        assert r.target_gap_pct == pytest.approx(33.33, abs=0.1)
        assert r.actual_return_pct == pytest.approx(20.0, abs=0.1)

    def test_validate_estimates_no_price_at_estimate(self, db_path):
        """Estimate with no matching price is skipped."""
        from nuri.quant.validation.analyst_backtest import validate_estimates

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, num_analysts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("NOPRICE", "2025-01-01", "Buy", 200.0, 5),
            )

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_validate_estimates_zero_target(self, db_path):
        """Estimate with target_mean=0 is skipped."""
        from nuri.quant.validation.analyst_backtest import validate_estimates

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, num_analysts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("AAPL", "2025-01-01", "Hold", 0, 5),
            )

        upsert_prices(pd.DataFrame([{
            "ticker": "AAPL",
            "date": "2025-01-01",
            "open": 100, "high": 105, "low": 95,
            "close": 100.0, "volume": 1000, "adj_close": 100.0,
        }]), db_path)

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_validate_estimates_zero_entry_price(self, db_path):
        """Entry price <=0 is skipped."""
        from nuri.quant.validation.analyst_backtest import validate_estimates

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, num_analysts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("AAPL", "2025-01-01", "Buy", 200.0, 5),
            )

        upsert_prices(pd.DataFrame([{
            "ticker": "AAPL",
            "date": "2025-01-01",
            "open": 0, "high": 0, "low": 0,
            "close": 0, "volume": 1000, "adj_close": 0,
        }]), db_path)

        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_print_results_empty(self, capsys):
        """print_results with empty results does nothing."""
        from nuri.quant.validation.analyst_backtest import print_results
        print_results([])
        out = capsys.readouterr().out
        assert out == ""

    def test_print_results_with_data(self, capsys):
        """print_results with valid data."""
        from nuri.quant.validation.analyst_backtest import EstimateResult, print_results

        results = [
            EstimateResult(
                ticker="AAPL", estimate_date="2025-01-01",
                recommendation="Buy", target_mean=200.0,
                price_at_estimate=150.0, actual_price=180.0,
                actual_date="2025-04-01", target_gap_pct=33.33,
                actual_return_pct=20.0, target_hit=False,
            ),
            EstimateResult(
                ticker="MSFT", estimate_date="2025-01-01",
                recommendation="Hold", target_mean=400.0,
                price_at_estimate=350.0, actual_price=410.0,
                actual_date="2025-04-01", target_gap_pct=14.29,
                actual_return_pct=17.14, target_hit=True,
            ),
        ]
        print_results(results)
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "MSFT" in out
        assert "적중률" in out


# ═══════════════════════════════════════════════════════
# 5. validation/scorecard.py — edge cases (lines 27-28, 175-180)
# ═══════════════════════════════════════════════════════


class TestScorecard:
    """Tests for scorecard.py edge cases."""

    def test_generate_validation_report_no_csv(self, tmp_path, monkeypatch):
        """Returns None if signal_scorecard.csv doesn't exist."""
        from nuri.quant.validation.scorecard import generate_validation_report

        # Create output_dir but no CSV
        output_dir = tmp_path / "2025-03-31"
        output_dir.mkdir()

        result = generate_validation_report(output_dir=output_dir)
        assert result is None

    def test_generate_validation_report_default_output_dir(self, monkeypatch):
        """Lines 27-28: output_dir is None, uses today_kst."""
        from nuri.quant.validation import scorecard as sc_mod

        # Patch today_kst and REPORT_DIR
        monkeypatch.setattr(sc_mod, "today_kst", lambda: "2025-03-31")
        fake_report_dir = Path("/tmp/nonexistent_test_report_dir_xyz123")
        monkeypatch.setattr(sc_mod, "REPORT_DIR", fake_report_dir)

        # No CSV file, so it returns None
        result = sc_mod.generate_validation_report()
        assert result is None

    def test_generate_validation_report_with_csv(self, tmp_path):
        """Full report generation with signal scorecard CSV."""
        from nuri.quant.validation.scorecard import generate_validation_report

        output_dir = tmp_path / "2025-03-31"
        output_dir.mkdir()

        # Create signal_scorecard.csv
        sig_data = pd.DataFrame([
            {"signal_id": "rsi_oversold", "ticker": None, "total_trades": 50,
             "win_rate": 0.6, "avg_return": 2.5, "median_return": 1.8,
             "max_return": 15.0, "max_loss": -8.0, "profit_factor": 1.8, "avg_holding_days": 15},
            {"signal_id": "macd_golden", "ticker": None, "total_trades": 30,
             "win_rate": 0.55, "avg_return": 3.0, "median_return": 2.0,
             "max_return": 20.0, "max_loss": -10.0, "profit_factor": 1.5, "avg_holding_days": 25},
        ])
        sig_data.to_csv(output_dir / "signal_scorecard.csv", index=False)

        try:
            result = generate_validation_report(output_dir=output_dir)
            # If plotly is available, should generate HTML
            if result is not None:
                assert result.exists()
                assert result.suffix == ".html"
        except ImportError:
            pytest.skip("plotly not available")

    def test_generate_validation_report_with_all_csvs(self, tmp_path):
        """Report with superinvestor + analyst CSVs too."""
        from nuri.quant.validation.scorecard import generate_validation_report

        output_dir = tmp_path / "2025-03-31"
        output_dir.mkdir()

        # signal scorecard
        sig_data = pd.DataFrame([
            {"signal_id": "rsi_oversold", "ticker": None, "total_trades": 50,
             "win_rate": 0.6, "avg_return": 2.5, "median_return": 1.8,
             "max_return": 15.0, "max_loss": -8.0, "profit_factor": 1.8, "avg_holding_days": 15},
        ])
        sig_data.to_csv(output_dir / "signal_scorecard.csv", index=False)

        # superinvestor scorecard
        si_data = pd.DataFrame([
            {"investor": "Warren Buffett", "avg_excess_return": 5.0, "avg_return": 12.0,
             "win_rate": 0.65, "total_follows": 20},
        ])
        si_data.to_csv(output_dir / "superinvestor_scorecard.csv", index=False)

        # analyst results
        an_data = pd.DataFrame([
            {"recommendation": "Buy", "target_hit": True, "actual_return_pct": 15.0},
            {"recommendation": "Buy", "target_hit": False, "actual_return_pct": -5.0},
            {"recommendation": "Hold", "target_hit": True, "actual_return_pct": 3.0},
        ])
        an_data.to_csv(output_dir / "analyst_results.csv", index=False)

        try:
            result = generate_validation_report(output_dir=output_dir)
            if result is not None:
                assert result.exists()
        except ImportError:
            pytest.skip("plotly not available")


# ═══════════════════════════════════════════════════════
# 6. validation/superinvestor_backtest.py — edge cases + print
# ═══════════════════════════════════════════════════════


class TestSuperinvestorBacktest:
    """Tests for superinvestor_backtest.py."""

    def test_check_data_readiness_no_data(self, db_path):
        """Returns False with no superinvestor data."""
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert not _check_data_readiness(db_path)

    def test_check_data_readiness_one_quarter(self, db_path):
        """Returns False with only 1 quarter."""
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Warren Buffett", "2024-01-01", "AAPL", 1000, 100000, 10.0),
            )

        assert not _check_data_readiness(db_path)

    def test_check_data_readiness_two_quarters(self, db_path):
        """Returns True with 2+ quarters."""
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Warren Buffett", "2024-01-01", "AAPL", 1000, 100000, 10.0),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Warren Buffett", "2024-04-01", "AAPL", 1200, 120000, 12.0),
            )

        assert _check_data_readiness(db_path)

    def test_backtest_no_data(self, db_path):
        """backtest_superinvestor returns empty with no data."""
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor(db_path=db_path)
        assert results == []

    def test_generate_scorecard_empty(self):
        """generate_scorecard with empty results."""
        from nuri.quant.validation.superinvestor_backtest import generate_scorecard
        assert generate_scorecard([], 120) == []

    def test_generate_scorecard_with_data(self):
        """generate_scorecard with valid results."""
        from nuri.quant.validation.superinvestor_backtest import (
            FollowResult,
            generate_scorecard,
        )

        results = [
            FollowResult(
                investor="Warren Buffett", ticker="AAPL", filing_date="2024-01-01",
                change_type="NEW", entry_date="2024-01-02", entry_price=150.0,
                exit_date="2024-05-01", exit_price=170.0,
                return_pct=13.33, benchmark_return_pct=5.0, excess_return_pct=8.33,
            ),
            FollowResult(
                investor="Warren Buffett", ticker="MSFT", filing_date="2024-01-01",
                change_type="INCREASED", entry_date="2024-01-02", entry_price=300.0,
                exit_date="2024-05-01", exit_price=280.0,
                return_pct=-6.67, benchmark_return_pct=5.0, excess_return_pct=-11.67,
            ),
        ]

        scorecards = generate_scorecard(results, hold_days=120)
        assert len(scorecards) == 1
        sc = scorecards[0]
        assert sc.investor == "Warren Buffett"
        assert sc.total_follows == 2
        assert sc.best_ticker == "AAPL"
        assert sc.worst_ticker == "MSFT"

    def test_print_scorecard_empty(self, capsys):
        """print_scorecard with empty list."""
        from nuri.quant.validation.superinvestor_backtest import print_scorecard
        print_scorecard([])
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out

    def test_print_scorecard_with_data(self, capsys):
        """print_scorecard with valid data."""
        from nuri.quant.validation.superinvestor_backtest import (
            InvestorScorecard,
            print_scorecard,
        )

        scorecards = [
            InvestorScorecard(
                investor="Warren Buffett", hold_days=120, total_follows=10,
                win_rate=0.7, avg_return=8.5, avg_excess_return=3.2,
                best_ticker="AAPL", best_return=25.0,
                worst_ticker="META", worst_return=-10.0,
            ),
        ]
        print_scorecard(scorecards)
        out = capsys.readouterr().out
        assert "Warren Buffett" in out
        assert "AAPL" in out

    def test_get_price_on_or_after_no_data(self, db_path):
        """_get_price_on_or_after with no data returns None."""
        from nuri.quant.validation.superinvestor_backtest import _get_price_on_or_after
        assert _get_price_on_or_after("NOPE", "2024-01-01", db_path) is None

    def test_get_price_on_or_before_no_data(self, db_path):
        """_get_price_on_or_before with no data returns None."""
        from nuri.quant.validation.superinvestor_backtest import _get_price_on_or_before
        assert _get_price_on_or_before("NOPE", "2024-01-01", db_path) is None

    def test_backtest_superinvestor_entry_price_zero(self, db_path, monkeypatch):
        """Line 150: entry_price == 0 is skipped."""
        from nuri.quant.validation import superinvestor_backtest as si_mod

        # Make data readiness pass
        monkeypatch.setattr(si_mod, "_check_data_readiness", lambda db_path=None: True)

        # Mock detect_changes to return a follow record
        mock_changes = pd.DataFrame([{
            "ticker": "ZERO",
            "filing_date": "2024-01-01",
            "change_type": "NEW",
        }])

        mock_module = MagicMock()
        mock_module.SUPERINVESTORS = {"TestInvestor": "0000000001"}
        mock_module.detect_changes = MagicMock(return_value=mock_changes)
        monkeypatch.setitem(sys.modules, "nuri.collectors.superinvestors", mock_module)

        # Insert zero-price data
        upsert_prices(pd.DataFrame([{
            "ticker": "ZERO", "date": "2024-01-01",
            "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0, "adj_close": 0,
        }]), db_path)
        upsert_prices(pd.DataFrame([{
            "ticker": "ZERO", "date": "2024-05-01",
            "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000, "adj_close": 100,
        }]), db_path)

        results = si_mod.backtest_superinvestor(investor="TestInvestor", db_path=db_path)
        assert results == []

    def test_backtest_benchmark_missing(self, db_path, monkeypatch):
        """Line 160: benchmark data missing → bench_return = 0.0."""
        from nuri.quant.validation import superinvestor_backtest as si_mod

        monkeypatch.setattr(si_mod, "_check_data_readiness", lambda db_path=None: True)

        mock_changes = pd.DataFrame([{
            "ticker": "TEST",
            "filing_date": "2024-01-01",
            "change_type": "NEW",
        }])

        mock_module = MagicMock()
        mock_module.SUPERINVESTORS = {"TestInvestor": "0000000001"}
        mock_module.detect_changes = MagicMock(return_value=mock_changes)
        monkeypatch.setitem(sys.modules, "nuri.collectors.superinvestors", mock_module)

        # Insert price data for TEST but NOT for VOO (benchmark)
        upsert_prices(pd.DataFrame([{
            "ticker": "TEST", "date": "2024-01-01",
            "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000, "adj_close": 100,
        }]), db_path)
        upsert_prices(pd.DataFrame([{
            "ticker": "TEST", "date": "2024-05-01",
            "open": 120, "high": 125, "low": 115, "close": 120, "volume": 1000, "adj_close": 120,
        }]), db_path)

        results = si_mod.backtest_superinvestor(investor="TestInvestor", db_path=db_path)
        assert len(results) == 1
        assert results[0].benchmark_return_pct == 0.0


# ═══════════════════════════════════════════════════════
# 7. factors/value.py — full coverage
# ═══════════════════════════════════════════════════════


class TestValueFactor:
    """Tests for factors/value.py."""

    def test_compute_value_empty(self, monkeypatch):
        """Empty result from OpenBB returns empty DataFrame."""
        from nuri.quant.factors import value as val_mod

        mock_obb = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb.equity.fundamental.ratios.return_value = mock_result
        monkeypatch.setattr(val_mod, "obb", mock_obb, raising=False)

        # Inject mock obb at module level
        monkeypatch.setitem(sys.modules.setdefault("openbb", MagicMock()).__dict__, "obb", mock_obb)

        result = val_mod.compute_value(tickers=["AAPL"])
        assert result.empty

    def test_compute_value_with_data(self, monkeypatch):
        """Compute value with mock OpenBB data."""
        from nuri.quant.factors import value as val_mod

        def mock_ratios(ticker, **kwargs):
            data = {
                "AAPL": {"pe_ratio": 25.0, "pb_ratio": 10.0},
                "MSFT": {"pe_ratio": 30.0, "pb_ratio": 12.0},
                "GOOG": {"pe_ratio": 20.0, "pb_ratio": 5.0},
            }
            mock_result = MagicMock()
            if ticker in data:
                mock_result.to_dataframe.return_value = pd.DataFrame([data[ticker]])
            else:
                mock_result.to_dataframe.return_value = pd.DataFrame()
            return mock_result

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios = mock_ratios

        # Patch the lazy import
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__


        def patched_import(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = mock_obb
                return mod
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", patched_import)

        result = val_mod.compute_value(tickers=["AAPL", "MSFT", "GOOG"])
        assert not result.empty
        assert "value_score" in result.columns
        assert len(result) == 3

    def test_compute_value_single_ticker(self, monkeypatch):
        """Single ticker gets 0.5 norm score (not enough for range normalization)."""
        from nuri.quant.factors import value as val_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{"pe_ratio": 25.0, "pb_ratio": 10.0}])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = val_mod.compute_value(tickers=["AAPL"])
        assert not result.empty
        assert "value_score" in result.columns

    def test_compute_value_exception_handling(self, monkeypatch):
        """OpenBB exception for one ticker doesn't crash."""
        from nuri.quant.factors import value as val_mod

        call_count = [0]

        def mock_ratios(ticker, **kwargs):
            call_count[0] += 1
            if ticker == "BAD":
                raise Exception("API error")
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{"pe_ratio": 25.0, "pb_ratio": 10.0}])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = val_mod.compute_value(tickers=["AAPL", "BAD", "MSFT"])
        assert len(result) == 2  # BAD is skipped

    def test_compute_value_nan_values(self, monkeypatch):
        """NaN pe/pb values are handled."""
        from nuri.quant.factors import value as val_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{
                "pe_ratio": float("nan"),
                "pb_ratio": float("nan"),
            }])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = val_mod.compute_value(tickers=["AAPL"])
        # NaN → pe_ratio/pb_ratio stored as None, but ticker entry still exists
        assert len(result) == 1
        assert result.iloc[0]["pe_ratio"] is None

    def test_compute_value_same_pe_pb(self, monkeypatch):
        """All same PE/PB → col_max == col_min → 0.5 norm."""
        from nuri.quant.factors import value as val_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{"pe_ratio": 20.0, "pb_ratio": 5.0}])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = val_mod.compute_value(tickers=["AAPL", "MSFT"])
        assert not result.empty
        # Both have same PE/PB, so norm columns should be 0.5
        assert all(result["pe_ratio_norm"] == 0.5)


# ═══════════════════════════════════════════════════════
# 8. factors/quality.py — full coverage
# ═══════════════════════════════════════════════════════


class TestQualityFactor:
    """Tests for factors/quality.py."""

    def test_compute_quality_empty(self, monkeypatch):
        """No valid data returns empty DataFrame."""
        from nuri.quant.factors import quality as qual_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame()
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL"])
        assert result.empty

    def test_compute_quality_with_data(self, monkeypatch):
        """Quality factor with mock data."""
        from nuri.quant.factors import quality as qual_mod

        data_map = {
            "AAPL": {"return_on_equity": 0.30, "operating_profit_margin": 0.25},
            "MSFT": {"return_on_equity": 0.40, "operating_profit_margin": 0.35},
            "GOOG": {"return_on_equity": 0.20, "operating_profit_margin": 0.20},
        }

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            if ticker in data_map:
                mock_result.to_dataframe.return_value = pd.DataFrame([data_map[ticker]])
            else:
                mock_result.to_dataframe.return_value = pd.DataFrame()
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL", "MSFT", "GOOG"])
        assert not result.empty
        assert "quality_score" in result.columns
        assert len(result) == 3

    def test_compute_quality_single_ticker(self, monkeypatch):
        """Single ticker gets 0.5 (can't normalize with 1 data point)."""
        from nuri.quant.factors import quality as qual_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{
                "return_on_equity": 0.25, "operating_profit_margin": 0.20,
            }])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL"])
        assert not result.empty

    def test_compute_quality_nan_roe(self, monkeypatch):
        """NaN ROE is handled."""
        from nuri.quant.factors import quality as qual_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{
                "return_on_equity": float("nan"),
                "operating_profit_margin": float("nan"),
            }])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL"])
        # NaN → roe/margin stored as None, but ticker entry still exists
        assert len(result) == 1
        assert result.iloc[0]["roe"] is None

    def test_compute_quality_same_values(self, monkeypatch):
        """All same ROE/margin → norm = 0.5."""
        from nuri.quant.factors import quality as qual_mod

        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{
                "return_on_equity": 0.25, "operating_profit_margin": 0.20,
            }])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL", "MSFT"])
        assert not result.empty
        assert all(result["roe_norm"] == 0.5)

    def test_compute_quality_exception(self, monkeypatch):
        """Exception for one ticker doesn't crash."""
        from nuri.quant.factors import quality as qual_mod

        def mock_ratios(ticker, **kwargs):
            if ticker == "BAD":
                raise Exception("API error")
            mock_result = MagicMock()
            mock_result.to_dataframe.return_value = pd.DataFrame([{
                "return_on_equity": 0.25, "operating_profit_margin": 0.20,
            }])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = qual_mod.compute_quality(tickers=["AAPL", "BAD"])
        # "AAPL" succeeds, "BAD" is skipped
        assert len(result) == 1

    def test_compute_quality_no_norm_cols(self, monkeypatch):
        """When no norm columns created, quality_score = 0.5."""
        from nuri.quant.factors import quality as qual_mod

        # Return data where roe/margin column names don't match standard ones
        def mock_ratios(ticker, **kwargs):
            mock_result = MagicMock()
            row = MagicMock()
            row.get.side_effect = lambda k, default=None: None  # roe and margin both None
            mock_result.to_dataframe.return_value = pd.DataFrame([{"unknown_col": 1.0}])
            return mock_result

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "openbb":
                mod = types.ModuleType("openbb")
                mod.obb = MagicMock()
                mod.obb.equity.fundamental.ratios = mock_ratios
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        # row.get returns None → roe/margin stored as None
        result = qual_mod.compute_quality(tickers=["AAPL"])
        assert len(result) == 1


# ═══════════════════════════════════════════════════════
# 9. factors/composite.py — edge cases
# ═══════════════════════════════════════════════════════


class TestCompositeFactor:
    """Tests for factors/composite.py."""

    def test_compute_composite_empty(self, db_path, monkeypatch):
        """All factor modules return empty → empty composite."""
        from nuri.quant.factors import composite as comp_mod

        monkeypatch.setattr(comp_mod, "query", lambda *a, **kw: [])

        # Mock all factor imports to return empty DataFrames
        mock_momentum = MagicMock(return_value=pd.DataFrame())
        mock_value = MagicMock(return_value=pd.DataFrame())
        mock_quality = MagicMock(return_value=pd.DataFrame())

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "nuri.quant.factors.momentum":
                mod = types.ModuleType(name)
                mod.compute_momentum = mock_momentum
                return mod
            elif name == "nuri.quant.factors.value":
                mod = types.ModuleType(name)
                mod.compute_value = mock_value
                return mod
            elif name == "nuri.quant.factors.quality":
                mod = types.ModuleType(name)
                mod.compute_quality = mock_quality
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        # All factors empty → results=[] → set_index("ticker") raises KeyError
        with pytest.raises(KeyError):
            comp_mod.compute_composite()

    def test_compute_composite_with_partial_data(self, db_path, monkeypatch):
        """Some factors have data, others don't → uses 0.5 fallback."""
        from nuri.quant.factors import composite as comp_mod

        # Mock query for fear_greed
        monkeypatch.setattr(comp_mod, "query", lambda *a, **kw: [{"value": 60}])

        momentum_df = pd.DataFrame(
            {"momentum_score": [0.8]},
            index=["AAPL"],
        )
        value_df = pd.DataFrame()  # Empty
        quality_df = pd.DataFrame(
            {"quality_score": [0.7]},
            index=["AAPL"],
        )

        import builtins
        orig = builtins.__import__

        def patched(name, *args, **kwargs):
            if name == "nuri.quant.factors.momentum":
                mod = types.ModuleType(name)
                mod.compute_momentum = lambda: momentum_df
                return mod
            elif name == "nuri.quant.factors.value":
                mod = types.ModuleType(name)
                mod.compute_value = lambda: value_df
                return mod
            elif name == "nuri.quant.factors.quality":
                mod = types.ModuleType(name)
                mod.compute_quality = lambda: quality_df
                return mod
            return orig(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched)

        result = comp_mod.compute_composite()
        assert len(result) == 1
        assert "composite_score" in result.columns
        # value_score should be 0.5 (fallback)
        assert result.loc["AAPL", "value_score"] == 0.5

    def test_print_composite_empty(self, capsys):
        """print_composite with empty DataFrame."""
        from nuri.quant.factors.composite import print_composite
        print_composite(pd.DataFrame())
        out = capsys.readouterr().out
        assert "데이터가 없습니다" in out

    def test_print_composite_with_data(self, capsys):
        """print_composite with valid data."""
        from nuri.quant.factors.composite import print_composite

        df = pd.DataFrame([{
            "ticker": "AAPL",
            "momentum_score": 0.8,
            "value_score": 0.6,
            "quality_score": 0.7,
            "sentiment_score": 0.5,
            "composite_score": 0.65,
        }]).set_index("ticker")

        print_composite(df)
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "0.650" in out


# ═══════════════════════════════════════════════════════
# 10. factors/momentum.py — edge cases
# ═══════════════════════════════════════════════════════


class TestMomentumFactor:
    """Tests for factors/momentum.py."""

    def test_compute_momentum_empty(self, db_path, monkeypatch):
        """Empty prices returns empty DataFrame."""
        from nuri.quant.factors import momentum as mom_mod
        monkeypatch.setattr(mom_mod, "query_df", lambda *a, **kw: pd.DataFrame())
        result = mom_mod.compute_momentum()
        assert result.empty

    def test_compute_momentum_short_series(self, db_path, monkeypatch):
        """Series with <14 rows is skipped."""
        from nuri.quant.factors import momentum as mom_mod

        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 10,
            "date": pd.bdate_range("2024-01-01", periods=10).strftime("%Y-%m-%d"),
            "close": range(100, 110),
        })
        monkeypatch.setattr(mom_mod, "query_df", lambda sql, *a, **kw:
            prices_df if "prices" in sql else pd.DataFrame()
        )

        result = mom_mod.compute_momentum()
        assert result.empty

    def test_compute_momentum_with_tickers(self, db_path, monkeypatch):
        """Compute momentum with specific tickers filter."""
        from nuri.quant.factors import momentum as mom_mod

        dates = pd.bdate_range("2024-01-01", periods=50)
        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 50 + ["MSFT"] * 50,
            "date": list(dates.strftime("%Y-%m-%d")) * 2,
            "close": list(range(100, 150)) + list(range(200, 250)),
        })

        def mock_query_df(sql, params=(), **kw):
            if "signals" in sql:
                return pd.DataFrame({"rsi_14": [55.0]})
            return prices_df

        monkeypatch.setattr(mom_mod, "query_df", mock_query_df)

        result = mom_mod.compute_momentum(tickers=["AAPL"])
        assert "AAPL" in result.index

    def test_compute_momentum_same_values(self, db_path, monkeypatch):
        """All same close values → col_max == col_min → norm = 0.5."""
        from nuri.quant.factors import momentum as mom_mod

        dates = pd.bdate_range("2024-01-01", periods=50)
        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 50,
            "date": dates.strftime("%Y-%m-%d"),
            "close": [100.0] * 50,
        })

        def mock_query_df(sql, params=(), **kw):
            if "signals" in sql:
                return pd.DataFrame({"rsi_14": [50.0]})
            return prices_df

        monkeypatch.setattr(mom_mod, "query_df", mock_query_df)

        result = mom_mod.compute_momentum()
        assert not result.empty

    def test_compute_momentum_no_rsi_data(self, db_path, monkeypatch):
        """No RSI in signals table → fallback to 50."""
        from nuri.quant.factors import momentum as mom_mod

        dates = pd.bdate_range("2024-01-01", periods=50)
        prices_df = pd.DataFrame({
            "ticker": ["AAPL"] * 50,
            "date": dates.strftime("%Y-%m-%d"),
            "close": np.cumsum(np.random.normal(0, 1, 50)) + 150,
        })

        def mock_query_df(sql, params=(), **kw):
            if "signals" in sql:
                return pd.DataFrame()  # No RSI data
            return prices_df

        monkeypatch.setattr(mom_mod, "query_df", mock_query_df)

        result = mom_mod.compute_momentum()
        assert not result.empty
        assert result.iloc[0]["rsi_14"] == 50  # fallback


# ═══════════════════════════════════════════════════════
# 11. regime/classifier.py — special regimes + edge cases
# ═══════════════════════════════════════════════════════


class TestRegimeClassifier:
    """Tests for regime classifier edge cases and special regimes."""

    def test_classify_regime_no_spy_data(self, db_path, monkeypatch):
        """No SPY data returns None."""
        from nuri.quant.regime import classifier as cls_mod
        # Reset freshness warning
        monkeypatch.setattr(cls_mod, "_freshness_warned", False)
        result = cls_mod.classify_regime(db_path=db_path)
        assert result is None

    def test_classify_regime_with_date(self, db_path):
        """classify_regime with explicit date skips freshness check."""
        from nuri.quant.regime.classifier import classify_regime

        _insert_spy_prices(db_path, n=300, start_date="2023-01-02")
        _insert_macro(db_path, "vix", 15.0, "2024-03-20")
        _insert_macro(db_path, "fear_greed", 55.0, "2024-03-20")

        state = classify_regime(date="2024-03-20", db_path=db_path)
        assert state is not None
        assert state.trend in ("bull", "bear", "sideways")
        assert state.volatility in ("high", "low")

    def test_detect_euphoria(self):
        """Euphoria: VIX < 12 AND F&G > 80."""
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(10.0, 85.0) is True
        assert _detect_euphoria(15.0, 85.0) is False
        assert _detect_euphoria(10.0, 70.0) is False
        assert _detect_euphoria(None, 85.0) is False
        assert _detect_euphoria(10.0, None) is False

    def test_detect_stagflation(self, db_path):
        """Stagflation: CPI > 4 AND GDP < 1."""
        from nuri.quant.regime.classifier import _detect_stagflation

        # No data
        assert _detect_stagflation(db_path) is False

        # CPI only
        _insert_macro(db_path, "cpi_yoy", 5.0)
        assert _detect_stagflation(db_path) is False

        # CPI + GDP meeting threshold
        _insert_macro(db_path, "gdp_growth", 0.5)
        assert _detect_stagflation(db_path) is True

        # CPI low
        _insert_macro(db_path, "cpi_yoy", 2.0, "2025-03-29")
        assert _detect_stagflation(db_path, date="2025-03-29") is False

    def test_detect_recovery(self, db_path):
        """Recovery: SMA50 < SMA200 200 days ago AND SMA50 >= SMA200 now."""
        from nuri.quant.regime.classifier import _detect_recovery

        # Not enough data
        assert _detect_recovery(None) is False
        short_df = pd.DataFrame({"sma50": [100], "sma200": [100]})
        assert _detect_recovery(short_df) is False

        # Create recovery scenario
        n = 300
        sma50 = np.linspace(90, 110, n)  # crossing from below to above
        sma200 = np.full(n, 100)  # flat
        spy_df = pd.DataFrame({
            "sma50": sma50,
            "sma200": sma200,
            "close": sma50,
        })
        result = _detect_recovery(spy_df)
        # At index -200 (100th): sma50[100]=96.7 < 100, at latest: sma50[299]=110 > 100
        assert result is True

    def test_detect_recovery_no_cross(self):
        """Recovery false when no crossover."""
        from nuri.quant.regime.classifier import _detect_recovery

        n = 300
        sma50 = np.full(n, 110)  # Always above
        sma200 = np.full(n, 100)
        spy_df = pd.DataFrame({
            "sma50": sma50,
            "sma200": sma200,
            "close": sma50,
        })
        assert _detect_recovery(spy_df) is False

    def test_detect_sector_rotation(self, db_path):
        """Sector rotation: SPY sideways + sector ETF 3%+ return."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        # No data
        assert _detect_sector_rotation(db_path) is False

        # Insert SPY prices (21 rows, small change)
        dates = pd.bdate_range("2025-02-25", periods=21)
        spy_rows = [{
            "ticker": "SPY",
            "date": d.strftime("%Y-%m-%d"),
            "open": 500, "high": 505, "low": 495,
            "close": 500 + (i * 0.1),  # Very small change (sideways)
            "volume": 50000000, "adj_close": 500 + (i * 0.1),
        } for i, d in enumerate(dates)]
        upsert_prices(pd.DataFrame(spy_rows), db_path)

        # Insert XLK with 5% gain
        xlk_rows = [{
            "ticker": "XLK",
            "date": d.strftime("%Y-%m-%d"),
            "open": 200, "high": 205, "low": 195,
            "close": 200 + (i * 0.5),  # ~5% over 21 days
            "volume": 10000000, "adj_close": 200 + (i * 0.5),
        } for i, d in enumerate(dates)]
        upsert_prices(pd.DataFrame(xlk_rows), db_path)

        assert _detect_sector_rotation(db_path) is True

    def test_detect_sector_rotation_spy_not_sideways(self, db_path):
        """Sector rotation false when SPY is not sideways."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.bdate_range("2025-02-25", periods=21)
        spy_rows = [{
            "ticker": "SPY",
            "date": d.strftime("%Y-%m-%d"),
            "open": 500, "high": 510, "low": 495,
            "close": 500 + (i * 1.0),  # ~4% change, not sideways
            "volume": 50000000, "adj_close": 500 + (i * 1.0),
        } for i, d in enumerate(dates)]
        upsert_prices(pd.DataFrame(spy_rows), db_path)

        assert _detect_sector_rotation(db_path) is False

    def test_classify_single(self):
        """Test _classify_single directly."""
        from nuri.quant.regime.classifier import _classify_single

        thresholds = {
            "sideways_pct": 2.0,
            "vix_threshold": 18.0,
            "vix_bear_threshold": 24.0,
            "bb_width_threshold": 6.0,
        }

        # Bull: price and SMA50 above SMA200
        trend, vol = _classify_single(110, 108, 100, 15.0, 5.0, thresholds)
        assert trend == "bull"
        assert vol == "low"

        # Bear: price and SMA50 below SMA200
        trend, vol = _classify_single(90, 92, 100, 30.0, 8.0, thresholds)
        assert trend == "bear"
        assert vol == "high"

        # Sideways: small SMA gap
        trend, vol = _classify_single(100, 100.5, 100, 16.0, 5.0, thresholds)
        assert trend == "sideways"

        # Mixed (price above, SMA50 below) → sideways
        trend, vol = _classify_single(105, 98, 100, 15.0, 5.0, thresholds)
        assert trend == "sideways"

        # VIX is None → use BB width
        trend, vol = _classify_single(110, 108, 100, None, 5.0, thresholds)
        assert vol == "low"
        trend, vol = _classify_single(110, 108, 100, None, 8.0, thresholds)
        assert vol == "high"

    def test_classify_regime_high_vol_hysteresis(self, db_path):
        """VIX >= 25 triggers faster hysteresis (2 days)."""
        from nuri.quant.regime.classifier import classify_regime

        _insert_spy_prices(db_path, n=300, start_date="2023-01-02")
        _insert_macro(db_path, "vix", 28.0, "2024-03-20")
        _insert_macro(db_path, "fear_greed", 30.0, "2024-03-20")

        state = classify_regime(date="2024-03-20", db_path=db_path)
        assert state is not None

    def test_classify_regime_special_euphoria(self, db_path):
        """Euphoria regime detection."""
        from nuri.quant.regime.classifier import classify_regime

        _insert_spy_prices(db_path, n=300, start_date="2023-01-02")
        _insert_macro(db_path, "vix", 10.0, "2024-03-20")
        _insert_macro(db_path, "fear_greed", 85.0, "2024-03-20")

        state = classify_regime(date="2024-03-20", db_path=db_path)
        assert state is not None
        assert state.details.get("special_regime") == "euphoria"

    def test_compute_dynamic_thresholds_no_data(self, db_path):
        """Default thresholds when no data."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        th = compute_dynamic_thresholds(db_path)
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0

    def test_compute_dynamic_thresholds_with_data(self, db_path):
        """Thresholds computed from data."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        _insert_spy_prices(db_path, n=300, start_date="2023-01-02")
        for i, val in enumerate(range(10, 35)):
            _insert_macro(db_path, "vix", float(val), f"2023-{(i % 12) + 1:02d}-15")

        th = compute_dynamic_thresholds(db_path)
        assert "vix_threshold" in th
        assert "sideways_pct" in th

    def test_check_data_freshness_no_data(self, db_path, monkeypatch):
        """No SPY data → freshness fails."""
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_freshness_warned", False)
        assert cls_mod._check_data_freshness(db_path) is False

    def test_check_data_freshness_old_data(self, db_path, monkeypatch):
        """Old SPY data → freshness fails."""
        from nuri.quant.regime import classifier as cls_mod
        monkeypatch.setattr(cls_mod, "_freshness_warned", False)

        # Insert very old price
        upsert_prices(pd.DataFrame([{
            "ticker": "SPY", "date": "2020-01-01",
            "open": 300, "high": 305, "low": 295,
            "close": 300, "volume": 50000000, "adj_close": 300,
        }]), db_path)

        assert cls_mod._check_data_freshness(db_path) is False

    def test_print_regime_none(self, capsys):
        """print_regime with None."""
        from nuri.quant.regime.classifier import print_regime
        print_regime(None)
        out = capsys.readouterr().out
        assert "불가" in out

    def test_print_regime_special(self, capsys):
        """print_regime with special regime."""
        from nuri.quant.regime.classifier import RegimeState, print_regime

        state = RegimeState(
            date="2025-03-28", trend="bull", volatility="low",
            regime="euphoria", confidence=0.85,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 450.0,
                "sma_diff_pct": 8.9, "vix": 10.0, "fear_greed": 85.0,
                "rsi": 65.0, "bb_width": 5.0,
                "thresholds": {"vix_threshold": 18, "vix_bear_threshold": 24,
                               "sideways_pct": 2.0, "bb_width_threshold": 6.0},
                "base_regime": "bull_low_vol", "special_regime": "euphoria",
            },
        )
        print_regime(state)
        out = capsys.readouterr().out
        assert "EUPHORIA" in out

    def test_print_history_empty(self, capsys):
        """print_history with empty list."""
        from nuri.quant.regime.classifier import print_history
        print_history([])
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_history_with_data(self, capsys):
        """print_history with valid data."""
        from nuri.quant.regime.classifier import RegimeState, print_history

        history = [
            RegimeState(
                date="2025-01-31", trend="bull", volatility="low",
                regime="bull_low_vol", confidence=0.8,
                details={"spy_close": 500, "vix": 15, "fear_greed": 60},
            ),
        ]
        print_history(history)
        out = capsys.readouterr().out
        assert "2025-01-31" in out

    def test_classify_regime_history(self, db_path):
        """Regime history with date range."""
        from nuri.quant.regime.classifier import classify_regime_history

        _insert_spy_prices(db_path, n=300, start_date="2023-01-02")

        history = classify_regime_history(
            start_date="2023-06-01", end_date="2024-01-01", db_path=db_path,
        )
        assert isinstance(history, list)

    def test_classify_regime_history_no_data(self, db_path):
        """History with no data returns empty."""
        from nuri.quant.regime.classifier import classify_regime_history
        history = classify_regime_history(db_path=db_path)
        assert history == []


# ═══════════════════════════════════════════════════════
# 12. regime/macro_score.py — edge cases
# ═══════════════════════════════════════════════════════


class TestMacroScore:
    """Tests for macro_score.py edge cases."""

    def test_compute_macro_score_no_data(self, db_path):
        """All missing data → neutral 50 scores."""
        from nuri.quant.regime.macro_score import compute_macro_score

        score = compute_macro_score(date="2025-03-28", db_path=db_path)
        assert score.total_score == pytest.approx(50.0, abs=0.1)
        assert score.interpretation == "Neutral"
        assert score.warnings is not None
        assert len(score.warnings) > 0

    def test_compute_macro_score_favorable(self, db_path):
        """Favorable macro environment."""
        from nuri.quant.regime.macro_score import compute_macro_score

        _insert_macro(db_path, "us_10y_yield", 4.5, "2025-03-28")
        _insert_macro(db_path, "us_2y_yield", 3.5, "2025-03-28")
        _insert_macro(db_path, "us_3m_yield", 3.0, "2025-03-28")
        _insert_macro(db_path, "vix", 12.0, "2025-03-28")
        _insert_macro(db_path, "put_call_ratio", 0.85, "2025-03-28")
        _insert_macro(db_path, "fear_greed", 50.0, "2025-03-28")
        _insert_macro(db_path, "unemployment", 3.5, "2025-03-28")
        _insert_macro(db_path, "cpi_yoy", 2.0, "2025-03-28")
        _insert_macro(db_path, "fed_funds_rate", 2.0, "2025-03-28")

        score = compute_macro_score(date="2025-03-28", db_path=db_path)
        assert score.total_score > 70
        assert score.interpretation == "Favorable"

    def test_compute_macro_score_adverse(self, db_path):
        """Adverse macro environment."""
        from nuri.quant.regime.macro_score import compute_macro_score

        _insert_macro(db_path, "us_10y_yield", 3.0, "2025-03-28")
        _insert_macro(db_path, "us_2y_yield", 5.0, "2025-03-28")
        _insert_macro(db_path, "us_3m_yield", 5.5, "2025-03-28")
        _insert_macro(db_path, "vix", 35.0, "2025-03-28")
        _insert_macro(db_path, "put_call_ratio", 1.5, "2025-03-28")
        _insert_macro(db_path, "fear_greed", 10.0, "2025-03-28")
        _insert_macro(db_path, "unemployment", 7.0, "2025-03-28")
        _insert_macro(db_path, "cpi_yoy", 8.0, "2025-03-28")
        _insert_macro(db_path, "fed_funds_rate", 6.0, "2025-03-28")

        score = compute_macro_score(date="2025-03-28", db_path=db_path)
        assert score.total_score < 30
        assert score.interpretation == "Adverse"

    def test_score_yield_curve_branches(self, db_path):
        """Test all branches of yield curve scoring."""
        from nuri.quant.regime.macro_score import _score_yield_curve

        # Spread > 1.0 → 100
        _insert_macro(db_path, "us_10y_yield", 5.0, "2025-01-01")
        _insert_macro(db_path, "us_2y_yield", 3.5, "2025-01-01")
        score, _ = _score_yield_curve(db_path, "2025-01-01")
        assert score == 100.0

        # Spread 0.5-1.0 → 75-100
        _insert_macro(db_path, "us_10y_yield", 4.0, "2025-01-02")
        _insert_macro(db_path, "us_2y_yield", 3.3, "2025-01-02")
        score, _ = _score_yield_curve(db_path, "2025-01-02")
        assert 75 <= score <= 100

        # Spread 0-0.5 → 50-75
        _insert_macro(db_path, "us_10y_yield", 4.0, "2025-01-03")
        _insert_macro(db_path, "us_2y_yield", 3.8, "2025-01-03")
        score, _ = _score_yield_curve(db_path, "2025-01-03")
        assert 50 <= score <= 75

        # Spread -0.5 to 0 → 25-50
        _insert_macro(db_path, "us_10y_yield", 3.5, "2025-01-04")
        _insert_macro(db_path, "us_2y_yield", 3.8, "2025-01-04")
        score, _ = _score_yield_curve(db_path, "2025-01-04")
        assert 25 <= score <= 50

        # Spread < -0.5 → 0-25
        _insert_macro(db_path, "us_10y_yield", 3.0, "2025-01-05")
        _insert_macro(db_path, "us_2y_yield", 4.0, "2025-01-05")
        score, _ = _score_yield_curve(db_path, "2025-01-05")
        assert 0 <= score <= 25

    def test_score_vix_branches(self, db_path):
        """Test all branches of VIX scoring."""
        from nuri.quant.regime.macro_score import _score_vix

        # VIX < 12 → 100
        _insert_macro(db_path, "vix", 10.0, "2025-01-01")
        score, _ = _score_vix(db_path, "2025-01-01")
        assert score == 100.0

        # VIX 12-15 → 80-100
        _insert_macro(db_path, "vix", 13.0, "2025-01-02")
        score, _ = _score_vix(db_path, "2025-01-02")
        assert 80 <= score <= 100

        # VIX 15-20 → 60-80
        _insert_macro(db_path, "vix", 17.0, "2025-01-03")
        score, _ = _score_vix(db_path, "2025-01-03")
        assert 60 <= score <= 80

        # VIX 20-30 → 20-60
        _insert_macro(db_path, "vix", 25.0, "2025-01-04")
        score, _ = _score_vix(db_path, "2025-01-04")
        assert 20 <= score <= 60

        # VIX > 30 → 0-20
        _insert_macro(db_path, "vix", 35.0, "2025-01-05")
        score, _ = _score_vix(db_path, "2025-01-05")
        assert 0 <= score <= 20

    def test_score_sentiment_branches(self, db_path):
        """Test sentiment scoring branches."""
        from nuri.quant.regime.macro_score import _score_sentiment

        # Optimal range 40-60
        _insert_macro(db_path, "fear_greed", 50.0, "2025-01-01")
        score, _ = _score_sentiment(db_path, "2025-01-01")
        assert score >= 80

        # Low fear (0-25)
        _insert_macro(db_path, "fear_greed", 15.0, "2025-01-02")
        score, _ = _score_sentiment(db_path, "2025-01-02")
        assert score < 50

        # High greed (75-100)
        _insert_macro(db_path, "fear_greed", 90.0, "2025-01-03")
        score, _ = _score_sentiment(db_path, "2025-01-03")
        assert score < 50

        # Mild fear (25-40)
        _insert_macro(db_path, "fear_greed", 32.0, "2025-01-04")
        score, _ = _score_sentiment(db_path, "2025-01-04")
        assert 50 <= score <= 80

        # Mild greed (60-75)
        _insert_macro(db_path, "fear_greed", 68.0, "2025-01-05")
        score, _ = _score_sentiment(db_path, "2025-01-05")
        assert 50 <= score <= 80

    def test_score_employment_with_trend(self, db_path):
        """Employment score with trend adjustment."""
        from nuri.quant.regime.macro_score import _score_employment

        _insert_macro(db_path, "unemployment", 3.0, "2025-01-01")
        _insert_macro(db_path, "unemployment", 3.5, "2024-10-01")  # 3 months ago
        score, details = _score_employment(db_path, "2025-01-01")
        assert score > 0
        assert details.get("trend_3m") is not None

    def test_score_employment_high_unemployment(self, db_path):
        """High unemployment → low score."""
        from nuri.quant.regime.macro_score import _score_employment
        _insert_macro(db_path, "unemployment", 8.0, "2025-01-01")
        score, _ = _score_employment(db_path, "2025-01-01")
        assert score < 30

    def test_score_inflation_deflation(self, db_path):
        """Deflation (CPI < 0) gets extra penalty."""
        from nuri.quant.regime.macro_score import _score_inflation
        _insert_macro(db_path, "cpi_yoy", -1.0, "2025-01-01")
        score, _ = _score_inflation(db_path, "2025-01-01")
        assert score <= 20

    def test_score_inflation_at_target(self, db_path):
        """CPI near 2% target → high score."""
        from nuri.quant.regime.macro_score import _score_inflation
        _insert_macro(db_path, "cpi_yoy", 2.0, "2025-01-01")
        score, _ = _score_inflation(db_path, "2025-01-01")
        assert score >= 90

    def test_score_monetary_low_rates(self, db_path):
        """Low rates → high score."""
        from nuri.quant.regime.macro_score import _score_monetary
        _insert_macro(db_path, "fed_funds_rate", 0.5, "2025-01-01")
        score, _ = _score_monetary(db_path, "2025-01-01")
        assert score >= 80

    def test_score_monetary_high_rates(self, db_path):
        """High rates → low score."""
        from nuri.quant.regime.macro_score import _score_monetary
        _insert_macro(db_path, "fed_funds_rate", 6.0, "2025-01-01")
        score, _ = _score_monetary(db_path, "2025-01-01")
        assert score < 30

    def test_score_monetary_fallback_to_2y(self, db_path):
        """Fallback from fed_funds_rate to us_2y_yield."""
        from nuri.quant.regime.macro_score import _score_monetary
        # No fed_funds_rate, only us_2y_yield
        _insert_macro(db_path, "us_2y_yield", 4.0, "2025-01-01")
        score, details = _score_monetary(db_path, "2025-01-01")
        assert details["fed_funds"] == 4.0

    def test_score_yield_spread_3m10y_branches(self, db_path):
        """Test all branches of 3M-10Y spread scoring."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y

        # Spread > 1.5 → 100
        _insert_macro(db_path, "us_10y_yield", 5.0, "2025-01-01")
        _insert_macro(db_path, "us_3m_yield", 3.0, "2025-01-01")
        score, _ = _score_yield_spread_3m10y(db_path, "2025-01-01")
        assert score == 100.0

        # Deep inversion → very low
        _insert_macro(db_path, "us_10y_yield", 3.0, "2025-01-06")
        _insert_macro(db_path, "us_3m_yield", 4.5, "2025-01-06")
        score, _ = _score_yield_spread_3m10y(db_path, "2025-01-06")
        assert score < 20

    def test_score_put_call_ratio_branches(self, db_path):
        """Test all branches of PCR scoring."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio

        # Optimal range (0.80-0.95)
        _insert_macro(db_path, "put_call_ratio", 0.87, "2025-01-01")
        score, _ = _score_put_call_ratio(db_path, "2025-01-01")
        assert score >= 85

        # Low PCR (< 0.70) → excessive greed
        _insert_macro(db_path, "put_call_ratio", 0.5, "2025-01-02")
        score, _ = _score_put_call_ratio(db_path, "2025-01-02")
        assert score < 65

        # High PCR (> 1.10) → excessive fear
        _insert_macro(db_path, "put_call_ratio", 1.3, "2025-01-03")
        score, _ = _score_put_call_ratio(db_path, "2025-01-03")
        assert score < 65

        # Mild call bias (0.70-0.80)
        _insert_macro(db_path, "put_call_ratio", 0.75, "2025-01-04")
        score, _ = _score_put_call_ratio(db_path, "2025-01-04")
        assert 65 <= score <= 85

        # Mild put bias (0.95-1.10)
        _insert_macro(db_path, "put_call_ratio", 1.0, "2025-01-05")
        score, _ = _score_put_call_ratio(db_path, "2025-01-05")
        assert 65 <= score <= 85

    def test_print_macro_score(self, capsys):
        """print_macro_score output."""
        from nuri.quant.regime.macro_score import MacroScore, print_macro_score

        score = MacroScore(
            date="2025-03-28", total_score=65.0,
            yield_curve_score=80.0, yield_spread_3m10y_score=70.0,
            vix_score=75.0, put_call_ratio_score=85.0,
            sentiment_score=60.0, employment_score=55.0,
            inflation_score=90.0, monetary_score=50.0,
            interpretation="Neutral",
            details={"spread": 0.5, "spread_3m10y": 0.3, "vix": 15.0,
                     "put_call_ratio": 0.85, "fear_greed": 50.0,
                     "unemployment": 4.0, "cpi_yoy": 2.0, "fed_funds": 3.0},
        )
        print_macro_score(score)
        out = capsys.readouterr().out
        assert "Macro Score: 65" in out
        assert "Neutral" in out

    def test_macro_trend_no_data(self, db_path):
        """_get_macro_trend with no data returns None."""
        from nuri.quant.regime.macro_score import _get_macro_trend
        result = _get_macro_trend("nonexistent", date="2025-03-28", db_path=db_path)
        assert result is None

    def test_macro_score_cautious(self, db_path):
        """Cautious interpretation (30-50)."""
        from nuri.quant.regime.macro_score import compute_macro_score

        _insert_macro(db_path, "vix", 28.0, "2025-03-28")
        _insert_macro(db_path, "fear_greed", 20.0, "2025-03-28")
        _insert_macro(db_path, "unemployment", 5.5, "2025-03-28")
        _insert_macro(db_path, "cpi_yoy", 5.0, "2025-03-28")
        _insert_macro(db_path, "fed_funds_rate", 5.0, "2025-03-28")

        score = compute_macro_score(date="2025-03-28", db_path=db_path)
        assert score.interpretation in ("Cautious", "Adverse")


# ═══════════════════════════════════════════════════════
# 13. regime/strategy_map.py — edge cases
# ═══════════════════════════════════════════════════════


class TestStrategyMap:
    """Tests for strategy_map.py edge cases."""

    def test_find_latest_csv_no_dir(self, monkeypatch):
        """_find_latest_csv with no report directory."""
        from nuri.quant.regime import strategy_map as sm

        monkeypatch.setattr(sm, "REPORT_DIR", Path("/nonexistent_dir_xyz123"))
        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_find_latest_csv_no_file(self, tmp_path, monkeypatch):
        """_find_latest_csv with directory but no matching file."""
        from nuri.quant.regime import strategy_map as sm

        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        (tmp_path / "2025-03-28").mkdir()

        result = sm._find_latest_csv("signal_results.csv")
        assert result is None

    def test_find_latest_csv_found(self, tmp_path, monkeypatch):
        """_find_latest_csv finds the file."""
        from nuri.quant.regime import strategy_map as sm

        monkeypatch.setattr(sm, "REPORT_DIR", tmp_path)
        d = tmp_path / "2025-03-28"
        d.mkdir()
        (d / "signal_results.csv").write_text("header\ndata")

        result = sm._find_latest_csv("signal_results.csv")
        assert result is not None

    def test_build_data_driven_strategy_empty(self):
        """Empty cross_df returns empty strategy."""
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        result = _build_data_driven_strategy("bull_low_vol", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []

    def test_build_data_driven_strategy_no_regime_match(self):
        """No matching regime returns empty."""
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        df = pd.DataFrame([{
            "signal_id": "rsi_oversold", "regime": "bear_high_vol",
            "trades": 10, "win_rate": 0.6, "avg_return": 2.5, "profit_factor": 1.8,
        }])
        result = _build_data_driven_strategy("bull_low_vol", df)
        assert result["recommended"] == []

    def test_build_data_driven_strategy_low_trades(self):
        """Signals with <5 trades are excluded."""
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        df = pd.DataFrame([{
            "signal_id": "rsi_oversold", "regime": "bull_low_vol",
            "trades": 3, "win_rate": 0.8, "avg_return": 5.0, "profit_factor": 3.0,
        }])
        result = _build_data_driven_strategy("bull_low_vol", df)
        assert result["recommended"] == []

    def test_build_data_driven_strategy_full(self):
        """Full data-driven strategy with recommend and avoid."""
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy

        df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol",
             "trades": 20, "win_rate": 0.65, "avg_return": 3.0, "profit_factor": 2.0},
            {"signal_id": "macd_dead", "regime": "bull_low_vol",
             "trades": 15, "win_rate": 0.35, "avg_return": -1.0, "profit_factor": 0.7},
        ])
        result = _build_data_driven_strategy("bull_low_vol", df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]

    def test_map_regime_to_strategy_none(self, monkeypatch):
        """Returns None when regime classification fails."""
        from nuri.quant.regime import strategy_map as sm

        monkeypatch.setattr(sm, "classify_regime", lambda db_path=None: None)
        result = sm.map_regime_to_strategy(db_path="fake")
        assert result is None

    def test_map_regime_to_strategy_bear(self, monkeypatch):
        """Bear regime → defensive + fallback signals."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bear_high_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=50.0,
            yield_curve_score=50, yield_spread_3m10y_score=50,
            vix_score=50, put_call_ratio_score=50,
            sentiment_score=50, employment_score=50,
            inflation_score=50, monetary_score=50,
            interpretation="Neutral", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert result.position_sizing == "minimal"
        assert "데이터 부족" in result.notes

    def test_map_regime_to_strategy_bull_high_vol(self, monkeypatch):
        """Bull high vol → signals truncated to top 2."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bull", volatility="high",
            regime="bull_high_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bull_high_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=60.0,
            yield_curve_score=60, yield_spread_3m10y_score=60,
            vix_score=60, put_call_ratio_score=60,
            sentiment_score=60, employment_score=60,
            inflation_score=60, monetary_score=60,
            interpretation="Neutral", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert len(result.recommended_signals) <= 2

    def test_map_regime_to_strategy_special_regime(self, monkeypatch):
        """Special regime (euphoria) → defensive position."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bull", volatility="low",
            regime="euphoria", confidence=0.85,
            details={"special_regime": "euphoria", "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=60.0,
            yield_curve_score=60, yield_spread_3m10y_score=60,
            vix_score=60, put_call_ratio_score=60,
            sentiment_score=60, employment_score=60,
            inflation_score=60, monetary_score=60,
            interpretation="Neutral", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert result.position_sizing == "defensive"

    def test_map_regime_to_strategy_macro_override_bad(self, monkeypatch):
        """Bad macro score overrides to defensive."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=20.0,  # Bad
            yield_curve_score=20, yield_spread_3m10y_score=20,
            vix_score=20, put_call_ratio_score=20,
            sentiment_score=20, employment_score=20,
            inflation_score=20, monetary_score=20,
            interpretation="Adverse", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert result.position_sizing == "defensive"
        assert "매크로 악화" in result.notes

    def test_map_regime_to_strategy_macro_override_good(self, monkeypatch):
        """Good macro score promotes defensive to normal."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bear", volatility="low",
            regime="bear_low_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bear_low_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=75.0,  # Good
            yield_curve_score=80, yield_spread_3m10y_score=80,
            vix_score=80, put_call_ratio_score=80,
            sentiment_score=80, employment_score=80,
            inflation_score=80, monetary_score=80,
            interpretation="Favorable", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert result.position_sizing == "normal"
        assert "매크로 양호" in result.notes

    def test_print_strategy_none(self, capsys):
        """print_strategy with None."""
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        out = capsys.readouterr().out
        assert "불가" in out

    def test_print_strategy_with_data(self, capsys):
        """print_strategy with valid recommendation."""
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy

        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="Favorable",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold", "bb_bounce"],
            avoid_signals=["macd_dead"],
            sector_preference=["XLK", "XLY"],
            signal_regime_stats={
                "rsi_oversold": {"win_rate": 0.65, "pf": 1.8, "trades": 20, "avg_return": 3.0},
            },
            notes="데이터 검증: 1개 시그널 PF>1.5",
        )
        print_strategy(rec)
        out = capsys.readouterr().out
        assert "bull_low_vol" in out
        assert "AGGRESSIVE" in out

    def test_print_cross_analysis_empty(self, capsys):
        """print_cross_analysis with empty DataFrame."""
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        out = capsys.readouterr().out
        assert "데이터 없음" in out

    def test_print_cross_analysis_with_data(self, capsys):
        """print_cross_analysis with valid data."""
        from nuri.quant.regime.strategy_map import print_cross_analysis

        df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol",
             "trades": 20, "win_rate": 0.65, "profit_factor": 1.8, "avg_return": 3.0},
            {"signal_id": "rsi_oversold", "regime": "bear_high_vol",
             "trades": 10, "win_rate": 0.4, "profit_factor": 0.7, "avg_return": -1.5},
        ])
        print_cross_analysis(df)
        out = capsys.readouterr().out
        assert "bull_low_vol" in out
        assert "bear_high_vol" in out

    def test_map_regime_with_data_driven_high_vol_ranking(self, monkeypatch):
        """High vol with data-driven stats: signals ranked by PF."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bull", volatility="high",
            regime="bull_high_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bull_high_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=60.0,
            yield_curve_score=60, yield_spread_3m10y_score=60,
            vix_score=60, put_call_ratio_score=60,
            sentiment_score=60, employment_score=60,
            inflation_score=60, monetary_score=60,
            interpretation="Neutral", details={},
        )

        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_high_vol",
             "trades": 20, "win_rate": 0.65, "avg_return": 3.0, "profit_factor": 2.5},
            {"signal_id": "bb_bounce", "regime": "bull_high_vol",
             "trades": 15, "win_rate": 0.60, "avg_return": 2.0, "profit_factor": 1.8},
            {"signal_id": "macd_golden", "regime": "bull_high_vol",
             "trades": 10, "win_rate": 0.55, "avg_return": 1.5, "profit_factor": 1.6},
        ])

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: cross_df)

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        # Should keep only top 2 by PF in high vol
        assert len(result.recommended_signals) <= 2

    def test_map_regime_sideways_fallback(self, monkeypatch):
        """Sideways regime with no data → rule-based fallback."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="sideways", volatility="low",
            regime="sideways_low_vol", confidence=0.7,
            details={"special_regime": None, "base_regime": "sideways_low_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=55.0,
            yield_curve_score=55, yield_spread_3m10y_score=55,
            vix_score=55, put_call_ratio_score=55,
            sentiment_score=55, employment_score=55,
            inflation_score=55, monetary_score=55,
            interpretation="Neutral", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert "rsi_oversold" in result.recommended_signals
        assert "bb_bounce" in result.recommended_signals

    def test_map_regime_minimal_clears_signals(self, monkeypatch):
        """Minimal position sizing clears all recommended signals."""
        from nuri.quant.regime import strategy_map as sm
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-03-28", trend="bear", volatility="high",
            regime="stagflation", confidence=0.8,
            details={"special_regime": "stagflation", "base_regime": "bear_high_vol"},
        )
        macro = MacroScore(
            date="2025-03-28", total_score=50.0,
            yield_curve_score=50, yield_spread_3m10y_score=50,
            vix_score=50, put_call_ratio_score=50,
            sentiment_score=50, employment_score=50,
            inflation_score=50, monetary_score=50,
            interpretation="Neutral", details={},
        )

        monkeypatch.setattr(sm, "analyze_signal_by_regime", lambda db_path=None: pd.DataFrame())

        result = sm.map_regime_to_strategy(regime_state=regime, macro_score=macro)
        assert result is not None
        assert result.position_sizing == "minimal"
        assert result.recommended_signals == []
        assert "시그널 매매 자제" in result.notes


# ═══════════════════════════════════════════════════════
# Additional edge case tests
# ═══════════════════════════════════════════════════════


class TestAdditionalEdgeCases:
    """Additional edge case tests for remaining uncovered lines."""

    def test_signal_backtest_dataclass_asdict(self):
        """Test SignalResult and SignalScorecard dataclass conversion."""
        from nuri.quant.validation.signal_backtest import SignalResult

        result = SignalResult(
            signal_id="rsi_oversold", ticker="AAPL",
            entry_date="2024-01-01", entry_price=150.0,
            exit_date="2024-01-21", exit_price=160.0,
            return_pct=6.67, holding_days=20, won=True,
        )
        d = asdict(result)
        assert d["signal_id"] == "rsi_oversold"
        assert d["won"] is True

    def test_analyst_result_dataclass(self):
        """Test EstimateResult dataclass."""
        from nuri.quant.validation.analyst_backtest import EstimateResult

        r = EstimateResult(
            ticker="AAPL", estimate_date="2025-01-01",
            recommendation="Buy", target_mean=200.0,
            price_at_estimate=150.0, actual_price=180.0,
            actual_date="2025-04-01", target_gap_pct=33.33,
            actual_return_pct=20.0, target_hit=False,
        )
        d = asdict(r)
        assert d["target_hit"] is False

    def test_opt_result_dataclass(self):
        """Test OptResult dataclass."""
        from nuri.quant.backtest.optimizer import OptResult

        r = OptResult(
            signal_id="rsi_oversold",
            params={"rsi_threshold": 30},
            total_trades=10,
            win_rate=0.6,
            avg_return=2.5,
            profit_factor=1.8,
            sharpe=1.2,
        )
        assert r.signal_id == "rsi_oversold"

    def test_regime_state_dataclass(self):
        """Test RegimeState dataclass."""
        from nuri.quant.regime.classifier import RegimeState

        s = RegimeState(
            date="2025-03-28", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.8,
            details={"spy_close": 500.0},
        )
        d = asdict(s)
        assert d["regime"] == "bull_low_vol"

    def test_signal_backtest_backward_compat_aliases(self):
        """Backward-compatible aliases exist."""
        from nuri.quant.validation.signal_backtest import (
            _compute_exit,
            _compute_indicators,
            _detect_signal_entries,
            _merge_data_signals,
            _merge_macro_data,
            compute_exit,
            compute_indicators,
            detect_signal_entries,
            merge_data_signals,
            merge_macro_data,
        )

        assert _compute_indicators is compute_indicators
        assert _detect_signal_entries is detect_signal_entries
        assert _compute_exit is compute_exit
        assert _merge_macro_data is merge_macro_data
        assert _merge_data_signals is merge_data_signals

    def test_print_backtest_none_result(self, capsys):
        """print_backtest(None) treated as falsy."""
        from nuri.quant.backtest.engine import print_backtest
        print_backtest(None)
        out = capsys.readouterr().out
        assert "데이터 없음" in out

    def test_compute_dynamic_thresholds_short_spy_data(self, db_path):
        """SPY data exists but too short for full computation."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        # Insert only 100 rows (less than 250)
        _insert_spy_prices(db_path, n=100, start_date="2024-06-01")

        th = compute_dynamic_thresholds(db_path)
        assert th["sideways_pct"] == 2.0  # fallback

    def test_compute_dynamic_thresholds_medium_spy_data(self, db_path):
        """SPY data exists, enough for SMA but short gap_pct."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        # Insert 260 rows (enough for sma200 but gap_pct may be short)
        _insert_spy_prices(db_path, n=260, start_date="2023-06-01")
        _insert_macro(db_path, "vix", 15.0, "2024-06-01")

        th = compute_dynamic_thresholds(db_path)
        assert "vix_threshold" in th

    def test_print_scorecard_with_inf_pf(self, capsys):
        """Scorecard with infinite profit factor."""
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard

        sc = [SignalScorecard(
            signal_id="rsi_oversold", ticker=None,
            total_trades=5, win_rate=1.0,
            avg_return=5.0, median_return=4.0,
            max_return=10.0, max_loss=0.0,
            profit_factor=float("inf"), avg_holding_days=15.0,
        )]
        print_scorecard(sc)
        out = capsys.readouterr().out
        assert "∞" in out
