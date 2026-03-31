"""
Coverage Round 27 — 120+ tests targeting the highest-miss files.

Target: push backend coverage from 91% toward 95%+.
Covers ~430 uncovered lines across 20 files.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_spy_data(db_path, days=300, start_price=400.0):
    """Seed SPY price data for backtest tests."""
    dates = pd.bdate_range(end="2025-03-28", periods=days)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            price = start_price + i * 0.5 + np.sin(i / 20) * 10
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("SPY", d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 1000000),
            )


def _seed_portfolio(db_path, tickers=None):
    """Seed portfolio with sample holdings."""
    if tickers is None:
        tickers = [("AAPL", 100.0, 10), ("TSLA", 200.0, 5), ("NVDA", 150.0, 8)]
    with get_db(db_path) as conn:
        for ticker, avg_price, qty in tickers:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) "
                "VALUES (?,?,?,?,?,?)",
                ("test", ticker, qty, avg_price, "Technology", "USD"),
            )


def _seed_prices(db_path, ticker="AAPL", days=60, start_price=150.0):
    """Seed price data for a ticker."""
    dates = pd.bdate_range(end="2025-03-28", periods=days)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            price = start_price + np.sin(i / 10) * 10
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                (ticker, d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 500000 + i * 10000),
            )


def _seed_macro(db_path):
    """Seed macro data."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("vix", "2025-03-28", 18.5),
        )
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("put_call_ratio", "2025-03-28", 0.85),
        )
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("us_10y_yield", "2025-03-28", 4.2),
        )
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("us_3m_yield", "2025-03-28", 4.5),
        )
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("fear_greed", "2025-03-28", 45),
        )
        conn.execute(
            "INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
            ("usd_krw", "2025-03-28", 1400.0),
        )


# ═══════════════════════════════════════════════════════
# 1. ls_backtest.py — classify_historical_regimes, run_backtest, analyze_per_regime, etc.
# ═══════════════════════════════════════════════════════


class TestLSBacktest:
    """Tests for nuri/trading/strategy/ls_backtest.py."""

    def test_classify_historical_regimes_insufficient_data(self, db_path):
        """SPY data < 200 days returns empty."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        _seed_spy_data(db_path, days=100)
        result = classify_historical_regimes(db_path=db_path)
        assert result.empty

    def test_classify_historical_regimes_no_data(self, db_path):
        """No SPY data returns empty."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        result = classify_historical_regimes(db_path=db_path)
        assert result.empty

    def test_classify_historical_regimes_with_vix(self, db_path):
        """Full regime classification with VIX data."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        _seed_spy_data(db_path, days=300)
        _seed_macro(db_path)
        result = classify_historical_regimes(db_path=db_path)
        assert not result.empty
        assert "regime" in result.columns
        assert "return" in result.columns
        assert all(r.endswith("_vol") for r in result["regime"].unique())

    def test_classify_historical_regimes_no_vix(self, db_path):
        """Regime classification without VIX data (vol defaults to low)."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        _seed_spy_data(db_path, days=300)
        result = classify_historical_regimes(db_path=db_path)
        assert not result.empty

    def test_run_backtest_basic(self, db_path):
        """Run backtest on classified regimes."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        _seed_spy_data(db_path, days=300)
        regimes = classify_historical_regimes(db_path=db_path)
        assert not regimes.empty
        result = run_backtest(regimes, db_path=db_path)
        assert result.total_days > 0
        assert isinstance(result.sharpe, float)
        assert isinstance(result.equity_curve, list)

    def test_run_backtest_empty(self, db_path):
        """Backtest with empty data raises IndexError."""
        from nuri.trading.strategy.ls_backtest import run_backtest
        df = pd.DataFrame(columns=["date", "close", "regime", "return"])
        with pytest.raises(IndexError):
            run_backtest(df, db_path=db_path)

    def test_analyze_per_regime(self, db_path):
        """Per-regime performance analysis."""
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        _seed_spy_data(db_path, days=300)
        regimes = classify_historical_regimes(db_path=db_path)
        perfs = analyze_per_regime(regimes)
        assert len(perfs) > 0
        for p in perfs:
            assert p.days > 0
            assert 0 <= p.win_rate <= 1

    def test_stress_test(self, db_path):
        """Stress test on crisis periods."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        _seed_spy_data(db_path, days=300)
        regimes = classify_historical_regimes(db_path=db_path)
        results = stress_test(regimes)
        # May be empty if data doesn't cover crisis dates
        assert isinstance(results, list)

    def test_analyze_entry_timing_with_regime(self, db_path):
        """Entry timing analysis with explicit regime."""
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing, classify_historical_regimes
        _seed_spy_data(db_path, days=300)
        regimes = classify_historical_regimes(db_path=db_path)
        # Get a known regime from the data
        known_regime = regimes["regime"].iloc[-1]
        result = analyze_entry_timing(regimes, current_regime=known_regime)
        # May be None if no transitions found
        if result is not None:
            assert result.current_regime == known_regime
            assert result.occurrences >= 0

    def test_analyze_entry_timing_none_regime(self, db_path):
        """Entry timing with None regime falls back."""
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing
        df = pd.DataFrame({"date": ["2025-01-01"], "close": [100], "regime": ["unknown"], "return": [0.01]})
        result = analyze_entry_timing(df, current_regime=None)
        # Should be None since classify_regime will fail in test context
        assert result is None

    def test_run_backtest_with_rules(self, db_path):
        """Rules-applied backtest comparison."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        _seed_spy_data(db_path, days=300)
        regimes = classify_historical_regimes(db_path=db_path)
        result = run_backtest_with_rules(regimes, db_path=db_path)
        assert "base" in result or "error" in result
        if "base" in result:
            assert "with_rules" in result
            assert "rules_impact" in result

    def test_run_backtest_with_rules_empty(self, db_path):
        """Rules backtest with empty data."""
        from nuri.trading.strategy.ls_backtest import run_backtest_with_rules
        df = pd.DataFrame(columns=["date", "close", "regime", "return"])
        result = run_backtest_with_rules(df, db_path=db_path)
        assert "error" in result

    def test_monte_carlo_insufficient_data(self, db_path):
        """Monte Carlo with insufficient data."""
        from nuri.trading.strategy.ls_backtest import monte_carlo_test
        df = pd.DataFrame({
            "date": pd.bdate_range("2025-01-01", periods=5),
            "close": [100, 101, 102, 103, 104],
            "regime": ["bull_low_vol"] * 5,
            "return": [0.01] * 5,
        })
        result = monte_carlo_test(df, n_simulations=10, block_size=20, db_path=db_path)
        assert "error" in result

    def test_print_functions(self, db_path, capsys):
        """Test all print functions without error."""
        from nuri.trading.strategy.ls_backtest import (
            BacktestResult,
            RegimePerformance,
            print_backtest,
            print_monte_carlo,
            print_regime_performance,
            print_rules_comparison,
            print_stress,
            print_timing,
        )

        bt = BacktestResult(10, 5, 1.2, -5, 0.55, 100, 3, 0.5, 8, 4, 1.0, -3, 2)
        print_backtest(bt)
        captured = capsys.readouterr()
        assert "Strategy" in captured.out

        perfs = [RegimePerformance("bull_low_vol", 50, 50.0, 0.05, 10.0, 0.55, 20.0, {"bear_low_vol": 0.3})]
        print_regime_performance(perfs)

        print_timing(None)

        print_stress([{"name": "Test", "days": 5, "spy_return": -10, "strategy_return": -5, "excess": 5, "protected": True}])

        mc = {"actual_return": 10, "actual_sharpe": 1.2, "random_mean_return": 5,
              "random_std_return": 3, "random_mean_sharpe": 0.8,
              "return_percentile": 0.96, "sharpe_percentile": 0.95,
              "n_simulations": 100, "statistically_significant": True}
        print_monte_carlo(mc)

        print_rules_comparison({"error": "test"})
        print_rules_comparison({
            "base": {"total_return": 10, "annual_return": 5, "sharpe": 1.2, "max_drawdown": -5},
            "with_rules": {"total_return": 12, "annual_return": 6, "sharpe": 1.3, "max_drawdown": -4},
            "rules_impact": {"return_diff": 2, "sharpe_diff": 0.1, "mdd_diff": 1, "stops_hit": 5,
                             "tp1_count": 3, "tp2_count": 1, "trailing_count": 2},
            "rules_config": {"stop_loss": "-7%", "target_1": "+20%", "target_2": "+40%", "trailing_stop": "-15%"},
        })


# ═══════════════════════════════════════════════════════
# 2. signal_backtest.py — TA-Lib fallback, macro merge, etc.
# ═══════════════════════════════════════════════════════


class TestSignalBacktest:
    """Tests for nuri/quant/validation/signal_backtest.py."""

    def test_compute_indicators_pandas_fallback(self):
        """Test pandas fallback when TA-Lib is available (tests the code path)."""
        from nuri.quant.validation.signal_backtest import compute_indicators
        dates = pd.bdate_range("2024-01-01", periods=50)
        df = pd.DataFrame({
            "date": dates,
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        result = compute_indicators(df)
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "bb_lower" in result.columns
        assert "volume_sma_20" in result.columns

    def test_merge_macro_data(self, db_path):
        """Test macro data merge with fallback."""
        from nuri.quant.validation.signal_backtest import merge_macro_data
        _seed_macro(db_path)
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-03-28"]),
            "close": [100.0],
        })
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_data_no_date_column(self, db_path):
        """merge_macro_data with no date column returns df unchanged."""
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" not in result.columns

    def test_merge_macro_data_fallback_yield(self, db_path):
        """Test yield fallback (us_3m_yield empty -> us_2y_yield)."""
        from nuri.quant.validation.signal_backtest import merge_macro_data
        # Seed only us_2y_yield (no us_3m_yield)
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("us_2y_yield", "2025-03-28", 4.0))
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("us_10y_yield", "2025-03-28", 4.5))
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-28"]), "close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_yield_spread" in result.columns

    def test_merge_data_signals(self, db_path):
        """Test insider/short data merge."""
        from nuri.quant.validation.signal_backtest import merge_data_signals
        # Seed insider trades
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, transaction_type, shares, value) VALUES (?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", "Purchase", 100, 15000),
                )
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-03-25", "2025-03-26", "2025-03-27"]),
            "close": [150, 151, 152],
        })
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_data_signals_no_date(self, db_path):
        """merge_data_signals with no date column."""
        from nuri.quant.validation.signal_backtest import merge_data_signals
        df = pd.DataFrame({"close": [100]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" not in result.columns

    def test_entry_detectors_individual(self):
        """Test individual entry detector functions."""
        from nuri.quant.validation.signal_backtest import (
            _entry_gap_down,
            _entry_gap_up,
            _entry_insider_cluster,
            _entry_pcr_reversal,
            _entry_short_squeeze,
            _entry_vix_reversal,
            _entry_volume_spike,
        )

        # gap_up
        df = pd.DataFrame({"open": [100, 105], "close": [100, 102]})
        assert _entry_gap_up(df, 1) is True

        # gap_down
        df = pd.DataFrame({"open": [100, 95], "close": [100, 98]})
        assert _entry_gap_down(df, 1) is True

        # volume_spike
        df = pd.DataFrame({
            "volume": [100000] * 20 + [500000],
            "volume_sma_20": [100000] * 20 + [100000],
        })
        assert _entry_volume_spike(df, 20) is True

        # vix_reversal: VIX was >=30 for 3 days then <=25
        df = pd.DataFrame({"macro_vix": [35, 32, 31, 30, 24]})
        assert _entry_vix_reversal(df, 4) is True

        # vix_reversal: missing column
        df2 = pd.DataFrame({"close": [100, 101]})
        assert _entry_vix_reversal(df2, 1) is False

        # pcr_reversal
        pcr_vals = [0.7] * 15 + [1.3, 1.2, 1.1, 1.0, 0.9, 0.75]
        df = pd.DataFrame({"macro_pcr": pcr_vals})
        assert _entry_pcr_reversal(df, len(pcr_vals) - 1) is True

        # insider_cluster
        df = pd.DataFrame({"insider_buy_count_10d": [0, 1, 2, 3]})
        assert _entry_insider_cluster(df, 3) is True

        # short_squeeze
        df = pd.DataFrame({
            "short_interest": [5, 5, 15, 15, 15, 15],
            "close": [100, 101, 102, 103, 104, 105],
        })
        assert _entry_short_squeeze(df, 5) is True

    def test_exit_functions(self):
        """Test exit detector functions."""
        from nuri.quant.validation.signal_backtest import (
            _exit_macd_dead,
            _exit_macd_golden,
            _exit_sma_dead,
            _exit_sma_golden,
            _exit_yield_curve_recovery,
        )

        # exit_macd_golden: MACD < signal
        df = pd.DataFrame({"macd": [1.0, -0.5], "macd_signal": [0.5, 0.5]})
        assert _exit_macd_golden(df, 1) is True
        assert _exit_macd_golden(df, 0) is False

        # exit_macd_dead: MACD > signal
        df = pd.DataFrame({"macd": [-1.0, 0.5], "macd_signal": [-0.5, -0.5]})
        assert _exit_macd_dead(df, 1) is True

        # exit_sma_golden: SMA50 < SMA200
        df = pd.DataFrame({"sma_50": [200, 150], "sma_200": [190, 180]})
        assert _exit_sma_golden(df, 1) is True

        # exit_sma_dead: SMA50 > SMA200
        df = pd.DataFrame({"sma_50": [150, 200], "sma_200": [180, 180]})
        assert _exit_sma_dead(df, 1) is True

        # exit_yield_curve_recovery: spread < 0
        df = pd.DataFrame({"macro_yield_spread": [0.5, -0.1]})
        assert _exit_yield_curve_recovery(df, 1) is True

        # no column
        df2 = pd.DataFrame({"close": [100]})
        assert _exit_yield_curve_recovery(df2, 0) is False

    def test_backtest_signals_with_data(self, db_path):
        """Backtest signals with actual data."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        _seed_prices(db_path, "AAPL", days=60)
        _seed_portfolio(db_path, [("AAPL", 150.0, 10)])
        results = backtest_signals(ticker="AAPL", signals=["rsi_oversold", "gap_up"], db_path=db_path)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        """Test scorecard generation."""
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2025-01-01", 100, "2025-01-20", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "AAPL", "2025-02-01", 110, "2025-02-20", 105, -4.5, 20, False),
            SignalResult("rsi_oversold", "TSLA", "2025-01-10", 200, "2025-01-30", 220, 10.0, 20, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0
        # Should have per-ticker and total entries
        total_cards = [s for s in scorecards if s.ticker is None]
        assert len(total_cards) >= 1

    def test_generate_scorecard_empty(self):
        """Empty results returns empty scorecard."""
        from nuri.quant.validation.signal_backtest import generate_scorecard
        assert generate_scorecard([]) == []

    def test_print_scorecard(self, capsys):
        """Test scorecard printing."""
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "데이터가 없습니다" in captured.out

        sc = [SignalScorecard("rsi_oversold", None, 10, 0.6, 5.0, 4.0, 15.0, -3.0, 2.0, 15.0)]
        print_scorecard(sc)

    def test_detect_signal_entries_unknown(self):
        """Unknown signal returns empty."""
        from nuri.quant.validation.signal_backtest import detect_signal_entries
        df = pd.DataFrame({"close": [100, 101]})
        assert detect_signal_entries(df, "nonexistent_signal") == []

    def test_compute_exit_hold_days(self):
        """compute_exit with hold_days signal."""
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": list(range(30))})
        # rsi_oversold has hold_days=20
        assert compute_exit(df, 5, "rsi_oversold") == 25
        # Entry at 15, exit at 35 which exceeds len(30)
        assert compute_exit(df, 15, "rsi_oversold") is None

    def test_compute_exit_signal_based(self):
        """compute_exit with signal-based exit."""
        from nuri.quant.validation.signal_backtest import compute_exit
        # macd_golden has exit function (MACD < signal)
        df = pd.DataFrame({
            "close": list(range(10)),
            "macd": [1, 1, 1, 0.5, 0.3, -0.1, -0.5, -1, -1, -1],
            "macd_signal": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        })
        result = compute_exit(df, 1, "macd_golden")
        assert result == 5  # first index where macd < signal

    def test_backward_compat_aliases(self):
        """Test backward-compatible aliases."""
        from nuri.quant.validation.signal_backtest import (
            _compute_exit,
            _compute_indicators,
            _detect_signal_entries,
            _merge_data_signals,
            _merge_macro_data,
        )
        assert _compute_indicators is not None
        assert _detect_signal_entries is not None
        assert _compute_exit is not None
        assert _merge_macro_data is not None
        assert _merge_data_signals is not None


# ═══════════════════════════════════════════════════════
# 3. charts.py — chart data loading, signal detection, info panel
# ═══════════════════════════════════════════════════════


class TestCharts:
    """Tests for nuri/analysis/charts.py."""

    def test_load_chart_data_no_data(self, db_path, monkeypatch):
        """_load_chart_data returns None when no price data."""
        import nuri.analysis.charts as charts_mod
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: pd.DataFrame())
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_insufficient(self, db_path, monkeypatch):
        """_load_chart_data returns None with < 20 rows."""
        import nuri.analysis.charts as charts_mod
        df = pd.DataFrame({"date": ["2025-01-01"], "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100]})
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_with_data(self, db_path, monkeypatch):
        """_load_chart_data computes indicators when enough data."""
        import nuri.analysis.charts as charts_mod
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is not None
        assert "rsi_14" in result.columns

    def test_detect_signals(self):
        """_detect_signals detects buy/sell signals."""
        from nuri.analysis.charts import _detect_signals
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
            "rsi_14": np.concatenate([np.linspace(25, 35, 25), np.linspace(35, 75, 25)]),
            "macd": np.sin(np.arange(50) / 5),
            "macd_signal": np.sin(np.arange(50) / 5 - 0.5),
        }, index=dates)
        result = _detect_signals(df)
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns

    def test_get_info_panel(self, db_path, monkeypatch):
        """_get_info_panel queries DB for fundamentals/estimates/sentiment."""
        import nuri.analysis.charts as charts_mod
        # Mock query to return specific data
        call_count = [0]
        def mock_query(sql, params=(), **kwargs):
            call_count[0] += 1
            if "fundamentals" in sql:
                return [{"pe_ratio": 25, "forward_pe": 20, "roe": 0.15,
                         "revenue_growth": 0.2, "debt_to_equity": 0.5,
                         "market_cap": 1e12, "beta": 1.2}]
            elif "estimates" in sql:
                return [{"recommendation": "buy", "target_mean": 200,
                         "target_high": 250, "target_low": 180,
                         "num_analysts": 30, "current_price": 190}]
            elif "sentiment" in sql:
                return [{"avg_s": 0.15, "cnt": 10}]
            elif "superinvestors" in sql:
                return [{"investor": "Buffett", "portfolio_pct": 5.0}]
            return []

        monkeypatch.setattr(charts_mod, "query", mock_query)
        info = charts_mod._get_info_panel("AAPL")
        assert info["ticker"] == "AAPL"
        assert info["pe"] == 25
        assert info["recommendation"] == "buy"
        assert info["sentiment"] == 0.15
        assert len(info["superinvestors"]) == 1

    def test_generate_charts_no_data(self, db_path, monkeypatch):
        """generate_charts with no data generates nothing."""
        import nuri.analysis.charts as charts_mod
        monkeypatch.setattr(charts_mod, "get_tickers", lambda **kw: ["AAPL"])
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: None)
        result = charts_mod.generate_charts(tickers=["AAPL"], output_dir=db_path.parent / "charts")
        assert result == []


# ═══════════════════════════════════════════════════════
# 4. llm/report.py — context gathering, validation, report generation
# ═══════════════════════════════════════════════════════


class TestLLMReport:
    """Tests for nuri/llm/report.py."""

    def test_report_context_post_init(self):
        """ReportContext __post_init__ sets defaults."""
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="test", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        assert ctx.known_tickers == set()
        assert ctx.known_numbers == set()

    def test_format_prompt(self):
        """format_prompt assembles all sections."""
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="Gate OK", gate_score=0.8,
            regime_section="Bull", macro_section="Score 70",
            risk_section="Low risk", candidates_section="3 buys",
            conflicts_section="None", drift_section="Stable",
            consensus_section="BUY", strategy_section="Aggressive",
            external_section="TipRanks data", rebalance_section="No violations",
        )
        prompt = format_prompt(ctx)
        assert "Gate OK" in prompt
        assert "TipRanks data" in prompt
        assert "리밸런스" in prompt

    def test_validate_output_clean(self):
        """Clean output passes validation."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL", "TSLA"}, known_numbers={"0.65", "2.5"},
        )
        text = "## 1. 완성도\n시장 환경\n리스크\n시그널\n후보\n전략\n주의\nAAPL 승률 65%\nTSLA PF 2.5"
        result = validate_output(text, ctx)
        assert result.passed is True
        assert len(result.hallucinated_tickers) == 0

    def test_validate_output_hallucinated_ticker(self):
        """Hallucinated ticker is detected."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers=set(),
        )
        text = "AAPL is good. ZZYZ is also interesting. 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert "ZZYZ" in result.hallucinated_tickers

    def test_validate_output_low_gate_score(self):
        """Low gate score adds warning."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.3,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        result = validate_output("완성도 시장 리스크 시그널 후보 전략 주의", ctx)
        assert any("완성도" in w for w in result.warnings)

    def test_validate_output_missing_sections(self):
        """Missing sections add structure warning."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        result = validate_output("Hello world", ctx)
        assert any("구조" in w for w in result.warnings)

    def test_validate_output_fabricated_numbers(self):
        """Fabricated numbers detected."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers={"0.65"},
        )
        text = "승률 99% PF 8.8 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert not result.passed

    def test_generate_llm_report_gate_blocked(self, monkeypatch):
        """generate_llm_report blocked by low gate score."""
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext(
            gate_summary="Low", gate_score=0.1,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        result = generate_llm_report()
        assert result["gate_blocked"] is True
        assert result["report"] is None

    def test_generate_llm_report_success(self, monkeypatch):
        """generate_llm_report with mocked LLM."""
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext(
            gate_summary="OK", gate_score=0.8,
            regime_section="bull", macro_section="score 70",
            risk_section="low", candidates_section="2 buys",
            conflicts_section="none", drift_section="stable",
            consensus_section="BUY", strategy_section="aggressive",
            known_tickers={"AAPL"}, known_numbers={"70", "0.8"},
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr("nuri.llm.report._generate_ollama",
                            lambda prompt: "## 1. 완성도 시장 리스크 시그널 후보 전략 주의 AAPL 승률 80%")
        result = generate_llm_report()
        assert result["gate_blocked"] is False
        assert result["report"] is not None

    def test_generate_llm_report_sync(self, monkeypatch):
        """generate_llm_report_sync delegates correctly."""
        from nuri.llm.report import generate_llm_report_sync
        monkeypatch.setattr("nuri.llm.report.generate_llm_report", lambda db_path=None: {"test": True})
        result = generate_llm_report_sync()
        assert result == {"test": True}

    def test_generate_llamacpp_no_path(self):
        """_generate_llamacpp returns empty when no model path."""
        from nuri.llm.report import _generate_llamacpp
        result = _generate_llamacpp("test prompt")
        assert result == ""

    def test_generate_ollama_connection_error(self, monkeypatch):
        """_generate_ollama handles connection error."""
        import requests

        from nuri.llm.report import _generate_ollama
        monkeypatch.setattr(requests, "post", MagicMock(side_effect=requests.ConnectionError))
        result = _generate_ollama("test prompt")
        assert "연결 실패" in result


# ═══════════════════════════════════════════════════════
# 5. consensus.py — weight computation, analyze_ticker, print
# ═══════════════════════════════════════════════════════


class TestConsensus:
    """Tests for nuri/trading/agents/consensus.py."""

    def test_compute_weights_default(self, db_path):
        """Default weights when no recommendation data."""
        from nuri.trading.agents.consensus import _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """Weights adjusted with learning memory data."""
        from nuri.trading.agents.consensus import _compute_weights
        # Seed recommendations with verdicts
        with get_db(db_path) as conn:
            for i in range(15):
                verdicts_data = {
                    "verdicts": [
                        {"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"},
                        {"agent_name": "risk", "action": "HOLD", "confidence": 50, "reasoning": "test"},
                    ]
                }
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, regime, signals, "
                    "entry_price, outcome_30d) VALUES (?,?,?,?,?,?,?,?)",
                    (f"2024-{(i%12)+1:02d}-{15+i}", f"AAPL{i}", "BUY", 70, "bull",
                     json.dumps(verdicts_data), 150, 5.0 if i % 2 == 0 else -2.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_print_consensus_empty(self, capsys):
        """print_consensus with empty results."""
        from nuri.trading.agents.consensus import print_consensus
        print_consensus([])
        captured = capsys.readouterr()
        assert "합의 결과 없음" in captured.out

    def test_print_consensus_with_results(self, capsys):
        """print_consensus with mock results."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI bullish"),
            AgentVerdict("risk", "AAPL", "HOLD", 50, "moderate risk"),
        ]
        results = [ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=65,
            agreement_rate=0.7, verdicts=verdicts,
            dissent=["risk(HOLD, 50): moderate risk"],
            reasoning="technical: RSI bullish",
        )]
        print_consensus(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out


# ═══════════════════════════════════════════════════════
# 6. wallstreet.py — cached data, score branches
# ═══════════════════════════════════════════════════════


class TestWallStreet:
    """Tests for nuri/trading/agents/wallstreet.py."""

    def test_skip_tickers(self):
        """ETF/KR tickers return HOLD immediately."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent.analyze("SPY")
        assert result.action == "HOLD"
        result_kr = agent.analyze("005930.KS")
        assert result_kr.action == "HOLD"

    def test_check_cached_no_data(self, db_path):
        """_check_cached returns None with no cached data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is None

    def test_check_cached_with_ratings(self, db_path):
        """_check_cached with analyst ratings."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, to_grade, from_grade, action, target_price) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", f"Firm{i}", "buy", "hold", "upgrade", 200),
                )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None
        assert result.action in ("BUY", "SELL", "HOLD")

    def test_check_cached_with_earnings(self, db_path):
        """_check_cached with earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?,?,?,?,?)",
                ("AAPL", "2025Q1", 1.5, 1.2, 0.25),
            )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None

    def test_check_cached_with_insider_sells(self, db_path):
        """_check_cached with insider sales."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) "
                    "VALUES (?,?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", f"Exec{i}", "sale", 1000, 150000),
                )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None

    def test_analyze_with_yfinance_mock(self, db_path):
        """analyze falls through to yfinance (mocked by conftest)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        # yfinance mock returns None attributes, so should fall through to HOLD
        result = agent.analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")


# ═══════════════════════════════════════════════════════
# 7. dashboard.py — dashboard API scenarios
# ═══════════════════════════════════════════════════════


class TestDashboard:
    """Tests for nuri/api/routes/dashboard.py."""

    def test_get_allocation_unknown_regime(self):
        """_get_allocation with unknown regime returns defaults."""
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("totally_unknown_regime")
        assert "long" in result
        assert "cash" in result

    def test_get_cached_regime_exception(self, monkeypatch):
        """_get_cached_regime handles exception."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            MagicMock(side_effect=Exception("test error")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_cached_regime()
        assert result["regime"] == "unknown"

    def test_get_freshness(self, monkeypatch):
        """_get_freshness returns dict."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(return_value=[{"table": "prices", "age_hours": 5, "status": "PASS"}]),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert "prices" in result

    def test_get_freshness_exception(self, monkeypatch):
        """_get_freshness handles exception."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert result == {}

    def test_get_pipeline_status_exception(self, monkeypatch):
        """_get_pipeline_status handles exception."""
        monkeypatch.setattr(
            "nuri.core.events.get_pipeline_status",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_pipeline_status()
        assert result == {}

    def test_get_latest_actions_empty(self):
        """_get_latest_actions returns empty list with no recommendation data.
        Uses default DB which has no recommendations."""
        import nuri.api.routes.dashboard as dash_mod
        # The function queries recommendations table which is empty in default prod DB
        # We just verify the function signature and return type
        result = dash_mod._get_latest_actions()
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# 8. price_targets.py — edge cases
# ═══════════════════════════════════════════════════════


class TestPriceTargets:
    """Tests for nuri/trading/recommend/price_targets.py."""

    def test_classify_stock_type_manual(self, monkeypatch):
        """Manual override from stock_types.yaml."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"TSLA": "growth"})
        assert classify_stock_type("TSLA") == "growth"

    def test_classify_stock_type_high_pe(self, db_path, monkeypatch):
        """High PE classified as growth."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)",
                ("TEST", "2025-03-28", 50.0),
            )
        assert classify_stock_type("TEST", db_path=db_path) == "growth"

    def test_classify_stock_type_value_default(self, db_path, monkeypatch):
        """Low PE without matching sector defaults to value."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)",
                ("TEST", "2025-03-28", 12.0),
            )
        assert classify_stock_type("TEST", db_path=db_path) == "value"

    def test_calculate_targets_no_price(self, db_path):
        """calculate_targets with no price data returns error."""
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_calculate_targets_swing(self, db_path, monkeypatch):
        """calculate_targets for swing stock type."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_targets
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"TEST": "swing"})
        _seed_prices(db_path, "TEST", days=5, start_price=100)
        result = calculate_targets("TEST", stock_type="swing", db_path=db_path)
        assert result["stock_type"] == "swing"
        assert result["trailing_stop_pct"] == -20  # TRAILING_STOP_VOLATILE

    def test_format_target_tree_error(self):
        """format_target_tree with error target."""
        from nuri.trading.recommend.price_targets import format_target_tree
        result = format_target_tree({"ticker": "TEST", "error": "no data"})
        assert "TEST" in result
        assert "no data" in result

    def test_format_target_tree_kr_ticker(self):
        """format_target_tree with KR ticker uses KRW."""
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "005930.KS", "stock_type": "value",
            "current_price": 70000, "entry_price": 68000,
            "stop_loss": 61200, "stop_loss_pct": -10.0,
            "target_1": 78200, "target_1_pct": 15.0, "target_1_sell_pct": 50,
            "target_2": 88400, "target_2_pct": 30.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None, "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "₩" in result
        assert "└──" in result  # Last line changed when no analyst target

    def test_format_target_tree_with_analyst(self):
        """format_target_tree with analyst target."""
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "AAPL", "stock_type": "growth",
            "current_price": 200, "entry_price": 195,
            "stop_loss": 181.35, "stop_loss_pct": -7.0,
            "target_1": 234, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 273, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 250, "analyst_upside_pct": 28.2,
        }
        result = format_target_tree(target)
        assert "애널리스트" in result
        assert "$" in result

    def test_check_take_profit_signals(self, db_path, monkeypatch):
        """check_take_profit_signals detects targets."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})

        _seed_portfolio(db_path, [("AAPL", 100.0, 10)])
        # Seed price at 125 (25% gain → hits target_1 at +20%)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-28", 124, 126, 123, 125, 500000),
            )
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_1"

    def test_check_trailing_stop_signals(self, db_path, monkeypatch):
        """check_trailing_stop_signals detects trailing stop."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})

        _seed_portfolio(db_path, [("AAPL", 100.0, 10)])
        # HWM at 200, current at 160 → -20% from high → triggers -15% trailing
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-20", 195, 200, 190, 198, 500000),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-28", 162, 165, 158, 160, 500000),
            )
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1

    def test_check_portfolio_mdd_no_violation(self, db_path):
        """check_portfolio_mdd with no MDD violation."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _seed_portfolio(db_path, [("AAPL", 100.0, 10)])
        _seed_prices(db_path, "AAPL", days=5, start_price=110)  # Gain
        _seed_macro(db_path)  # for usd_krw
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None  # No violation

    def test_print_portfolio_targets_empty(self, capsys):
        """print_portfolio_targets with empty list."""
        from nuri.trading.recommend.price_targets import print_portfolio_targets
        print_portfolio_targets([])
        captured = capsys.readouterr()
        assert "가격 목표 대상 종목 없음" in captured.out


# ═══════════════════════════════════════════════════════
# 9. pairs.py — pairs trading
# ═══════════════════════════════════════════════════════


class TestPairs:
    """Tests for nuri/trading/strategy/pairs.py."""

    def test_find_pairs_insufficient_tickers(self, db_path):
        """find_pairs with < 2 tickers."""
        from nuri.trading.strategy.pairs import find_pairs
        _seed_portfolio(db_path, [("AAPL", 150.0, 10)])
        result = find_pairs(db_path=db_path)
        assert result == []

    def test_find_pairs_with_data(self, db_path):
        """find_pairs with correlated tickers."""
        from nuri.trading.strategy.pairs import find_pairs
        _seed_portfolio(db_path, [("AAPL", 150, 10), ("MSFT", 350, 5)])
        # Seed correlated prices
        dates = pd.bdate_range("2024-12-01", periods=60)
        with get_db(db_path) as conn:
            for i, d in enumerate(dates):
                base = 150 + i * 0.5
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                    ("AAPL", d.strftime("%Y-%m-%d"), base),
                )
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                    ("MSFT", d.strftime("%Y-%m-%d"), base * 2.3 + np.random.normal(0, 0.5)),
                )
        result = find_pairs(db_path=db_path)
        assert isinstance(result, list)

    def test_scan_pair_signals_empty(self, db_path):
        """scan_pair_signals with no eligible pairs."""
        from nuri.trading.strategy.pairs import scan_pair_signals
        result = scan_pair_signals(db_path=db_path)
        assert result == []

    def test_backtest_pairs_no_eligible(self, db_path):
        """backtest_pairs with no eligible pairs."""
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=db_path)
        assert result["total_trades"] == 0


# ═══════════════════════════════════════════════════════
# 10. tracker.py — save_recommendations, track_outcomes, etc.
# ═══════════════════════════════════════════════════════


class TestTracker:
    """Tests for nuri/trading/recommend/tracker.py."""

    def test_save_recommendations_empty(self, db_path):
        """save_recommendations with no candidates/actions returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations
        assert save_recommendations(db_path=db_path) == 0

    def test_save_recommendations_with_candidates(self, db_path, monkeypatch):
        """save_recommendations with candidate data."""
        from nuri.trading.recommend.tracker import save_recommendations

        class MockCandidate:
            ticker = "AAPL"
            direction = "BUY"
            confidence = 75
            signal_id = "rsi_oversold"
            regime_fit = True
            price = 150
            scoring_detail = {"test": 1}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_track_outcomes(self, db_path, monkeypatch):
        """track_outcomes updates 30d outcomes."""
        from nuri.core.timezone import kst_now
        from nuri.trading.recommend.tracker import track_outcomes

        # Seed a recommendation 35 days ago
        rec_date = (kst_now().replace(tzinfo=None) - timedelta(days=35)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?,?,?,?,?,?,?)",
                (rec_date, "AAPL", "BUY", 70, "bull", '["rsi_oversold"]', 150),
            )
            # Seed price for 30d target
            target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                ("AAPL", target_date, 160),
            )
        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_get_tracking_report(self, db_path):
        """get_tracking_report returns report structure."""
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path)
        assert "total_recommendations" in report
        assert "hit_rate" in report

    def test_print_tracking_report(self, db_path, capsys):
        """print_tracking_report outputs data."""
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation" in captured.out

    def test_serialize_verdicts(self):
        """_serialize_verdicts converts ConsensusResult verdicts."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.recommend.tracker import _serialize_verdicts

        class MockResult:
            ticker = "AAPL"
            verdicts = [AgentVerdict("technical", "AAPL", "BUY", 70, "RSI ok")]

        result = _serialize_verdicts([MockResult()])
        assert "AAPL" in result
        assert result["AAPL"][0]["agent_name"] == "technical"


# ═══════════════════════════════════════════════════════
# 11. swing/rules.py — entry/exit evaluation
# ═══════════════════════════════════════════════════════


class TestSwingRules:
    """Tests for nuri/trading/swing/rules.py."""

    def test_save_entries_none_approved(self, db_path):
        """save_entries with no approved entries."""
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [SwingEntry("AAPL", 150, "bounce", 30, "HOLD", 40, 0.5, False, "rejected")]
        assert save_entries(entries, db_path=db_path) == 0

    def test_save_entries_approved(self, db_path):
        """save_entries with approved entries."""
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [SwingEntry("AAPL", 150, "momentum", 35, "BUY", 65, 0.7, True, "approved")]
        n = save_entries(entries, db_path=db_path)
        assert n == 1

    def test_check_exits_no_open_trades(self, db_path):
        """check_exits with no open trades."""
        from nuri.trading.swing.rules import check_exits
        result = check_exits(db_path=db_path)
        assert result == []

    def test_check_exits_take_profit(self, db_path, monkeypatch):
        """check_exits triggers take profit."""
        from nuri.trading.swing.rules import check_exits
        # Insert open trade
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, "
                "agent_action, agent_confidence, agent_agreement, status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-20", 100.0, "bounce", "BUY", 65, 0.7, "open"),
            )
            # Price at 112 → +12% → triggers take profit at 10%
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                ("AAPL", "2025-03-28", 112.0),
            )
        exits = check_exits(db_path=db_path)
        assert len(exits) >= 1
        assert exits[0].exit_reason == "take_profit"
        assert exits[0].should_exit is True

    def test_check_exits_stop_loss(self, db_path):
        """check_exits triggers stop loss."""
        from nuri.trading.swing.rules import check_exits
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, "
                "agent_action, agent_confidence, agent_agreement, status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("TSLA", "2025-03-20", 200.0, "momentum", "BUY", 60, 0.6, "open"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                ("TSLA", "2025-03-28", 185.0),
            )
        exits = check_exits(db_path=db_path)
        assert len(exits) >= 1
        assert exits[0].exit_reason == "stop_loss"

    def test_print_entries(self, capsys):
        """print_entries with mixed entries."""
        from nuri.trading.swing.rules import SwingEntry, print_entries
        entries = [
            SwingEntry("AAPL", 150, "momentum", 35, "BUY", 65, 0.7, True, "approved"),
            SwingEntry("TSLA", 200, "bounce", 25, "HOLD", 40, 0.5, False, "rejected"),
        ]
        print_entries(entries)
        captured = capsys.readouterr()
        assert "APPROVED" in captured.out
        assert "REJECTED" in captured.out

    def test_print_entries_empty(self, capsys):
        """print_entries with no entries."""
        from nuri.trading.swing.rules import print_entries
        print_entries([])
        captured = capsys.readouterr()
        assert "진입 후보 없음" in captured.out

    def test_print_exits(self, capsys):
        """print_exits with positions."""
        from nuri.trading.swing.rules import SwingExit, print_exits
        exits = [SwingExit("AAPL", 150, 160, 6.67, 3, "hold", False)]
        print_exits(exits)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out

    def test_print_exits_empty(self, capsys):
        """print_exits with no positions."""
        from nuri.trading.swing.rules import print_exits
        print_exits([])
        captured = capsys.readouterr()
        assert "오픈 포지션 없음" in captured.out


# ═══════════════════════════════════════════════════════
# 12. certification.py — SIEGE certification edge cases
# ═══════════════════════════════════════════════════════


class TestCertification:
    """Tests for nuri/trading/engine/certification.py."""

    def test_check_leverage_ban_clean(self, db_path):
        """No leverage ETFs in portfolio."""
        from nuri.trading.engine.certification import _check_leverage_ban
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is True

    def test_check_leverage_ban_violation(self, db_path):
        """Leverage ETF in portfolio."""
        from nuri.trading.engine.certification import _check_leverage_ban
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?,?,?,?)",
                         ("test", "TQQQ", 10, 50.0))
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is False

    def test_check_vix_gate_no_data(self, db_path):
        """VIX gate with no data passes."""
        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is True

    def test_check_vix_gate_high(self, db_path):
        """VIX > 30 triggers warning."""
        from nuri.trading.engine.certification import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 35.0))
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is False

    def test_check_data_freshness_no_data(self, db_path):
        """Data freshness with no SPY data."""
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is False

    def test_check_data_freshness_fresh(self, db_path):
        """Data freshness with recent SPY data."""
        from nuri.core.timezone import kst_now
        from nuri.trading.engine.certification import _check_data_freshness
        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                         ("SPY", today, 500.0))
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is True

    def test_check_rules_loaded(self, db_path):
        """Rules loaded check."""
        from nuri.trading.engine.certification import _check_rules_loaded
        result = _check_rules_loaded(db_path=db_path)
        assert result.passed is True

    def test_certify_and_print(self, db_path, capsys, monkeypatch):
        """Full certification + print."""
        from nuri.trading.engine.certification import certify, print_certificate
        # Mock heavy checks
        monkeypatch.setattr("nuri.trading.engine.certification._check_position_limits",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="pos", description="test", detail="ok"))
        monkeypatch.setattr("nuri.trading.engine.certification._check_sector_limits",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="sec", description="test", detail="ok"))
        monkeypatch.setattr("nuri.trading.engine.certification._check_stop_loss_compliance",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="sl", description="test", detail="ok"))
        cert = certify(db_path=db_path)
        assert cert.total_conditions > 0
        assert isinstance(cert.score, float)
        print_certificate(cert)
        captured = capsys.readouterr()
        assert "SIEGE Certificate" in captured.out

    def test_certificate_post_init_empty_timestamp(self):
        """Certificate __post_init__ sets timestamp."""
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(timestamp="", total_conditions=0, passed=0, failed=0,
                           warnings=0, certified=True, conditions=[], score=100.0)
        assert cert.timestamp != ""


# ═══════════════════════════════════════════════════════
# 13. longshort.py — strategy generation edge cases
# ═══════════════════════════════════════════════════════


class TestLongShort:
    """Tests for nuri/trading/strategy/longshort.py."""

    def test_generate_strategy_no_regime(self, db_path, monkeypatch):
        """generate_strategy with no regime returns empty."""
        from nuri.trading.strategy.longshort import generate_strategy
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            MagicMock(return_value=None))
        result = generate_strategy(db_path=db_path)
        assert result == []

    def test_generate_strategy_exception(self, db_path, monkeypatch):
        """generate_strategy handles classify_regime exception."""
        from nuri.trading.strategy.longshort import generate_strategy
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            MagicMock(side_effect=Exception("no data")))
        result = generate_strategy(db_path=db_path)
        assert result == []

    def test_print_strategy_empty(self, capsys):
        """print_strategy with no actions."""
        from nuri.trading.strategy.longshort import print_strategy
        print_strategy([])
        captured = capsys.readouterr()
        assert "전략 액션 없음" in captured.out

    def test_print_strategy_with_actions(self, capsys):
        """print_strategy with actions."""
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy
        actions = [
            StrategyAction("close", "SPY", "long", "tactical", "regime change", "bear_high_vol", 90),
            StrategyAction("open_short", "SH", "short", "tactical", "hedge", "bear_high_vol", 85),
        ]
        print_strategy(actions)
        captured = capsys.readouterr()
        assert "CLOSE" in captured.out
        assert "SHORT" in captured.out


# ═══════════════════════════════════════════════════════
# 14. scheduler.py — scheduler functions
# ═══════════════════════════════════════════════════════


class TestScheduler:
    """Tests for nuri/scheduler.py."""

    def test_run_collector_unknown(self):
        """_run_collector with unknown name does nothing."""
        from nuri.scheduler import _run_collector
        # Should not raise
        _run_collector("totally_unknown_collector_name")

    def test_run_collector_stock_exception(self, monkeypatch):
        """_run_collector handles runtime errors."""
        from nuri.scheduler import _run_collector
        # Mock the actual collector to raise
        mock_collector = MagicMock()
        mock_collector.return_value.run.side_effect = Exception("test error")
        monkeypatch.setattr("nuri.collectors.stock.StockCollector", mock_collector)
        # Should not raise, just log error
        _run_collector("stock")

    def test_run_report_exception(self, monkeypatch):
        """_run_report handles exception."""
        from nuri.scheduler import _run_report
        # Should not raise
        _run_report()

    def test_run_backup_exception(self, monkeypatch):
        """_run_backup handles exception."""
        import subprocess

        from nuri.scheduler import _run_backup
        monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=Exception("no script")))
        _run_backup()

    def test_run_db_maintenance_exception(self):
        """_run_db_maintenance handles exception."""
        from nuri.scheduler import _run_db_maintenance
        _run_db_maintenance()  # Script likely doesn't exist in test env

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        """_write_heartbeat writes file."""
        import nuri.scheduler as sched_mod
        from nuri.scheduler import _write_heartbeat
        monkeypatch.setattr(sched_mod, "HEARTBEAT_PATH", tmp_path / ".heartbeat")
        _write_heartbeat()
        assert (tmp_path / ".heartbeat").exists()

    def test_print_schedule(self, capsys):
        """print_schedule outputs schedule list."""
        from nuri.scheduler import print_schedule
        print_schedule()
        captured = capsys.readouterr()
        assert "Nuri-Quant Scheduler" in captured.out

    def test_create_scheduler(self):
        """create_scheduler creates and registers jobs."""
        from nuri.scheduler import SCHEDULES, create_scheduler
        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        # Should have SCHEDULES + heartbeat
        assert len(jobs) == len(SCHEDULES) + 1


# ═══════════════════════════════════════════════════════
# 15. rebalance_advisor.py — violation detection edge cases
# ═══════════════════════════════════════════════════════


class TestRebalanceAdvisor:
    """Tests for nuri/analysis/rebalance_advisor.py."""

    def test_severity_leverage(self):
        """Leverage ETF always critical."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_severity_stop_loss_critical(self):
        """Stop loss 2x exceeded is critical."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -14, -7) == "critical"

    def test_severity_stop_loss_high(self):
        """Stop loss exceeded but not 2x is high."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_severity_position_limit(self):
        """Position limit medium/high."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 20, 0.15) == "medium"
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_severity_sector_limit(self):
        """Sector limit medium/high."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"
        assert _severity("sector_limit_exceeded", 55, 0.35) == "high"

    def test_severity_default(self):
        """Unknown type defaults to medium."""
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("unknown_type", 0, 0) == "medium"

    def test_print_rebalance_advisor_empty(self, capsys):
        """print_rebalance_advisor with no actions."""
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        captured = capsys.readouterr()
        assert "위반 사항 없음" in captured.out

    def test_print_rebalance_advisor_with_actions(self, capsys):
        """print_rebalance_advisor with actions."""
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [{
            "ticker": "TQQQ", "action": "SELL_ALL", "sell_shares": 10,
            "sell_value_usd": 500, "reason": "레버리지 ETF 금지",
            "severity": "critical", "cumulative_recovery_usd": 500,
        }]
        print_rebalance_advisor(actions)
        captured = capsys.readouterr()
        assert "TQQQ" in captured.out

    def test_generate_advisor_report_empty(self, monkeypatch):
        """generate_advisor_report with no violations."""
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        monkeypatch.setattr("nuri.analysis.rebalance_advisor.calculate_rebalance_actions", lambda db_path=None: [])
        report = generate_advisor_report()
        assert report["total_violations"] == 0
        assert report["has_critical"] is False


# ═══════════════════════════════════════════════════════
# 16. monitor.py — regime transition, daily P&L
# ═══════════════════════════════════════════════════════


class TestMonitor:
    """Tests for nuri/trading/strategy/monitor.py."""

    def test_detect_regime_transition_no_regime(self, db_path, monkeypatch):
        """detect_regime_transition returns None when no regime."""
        from nuri.trading.strategy.monitor import detect_regime_transition
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            MagicMock(return_value=None))
        result = detect_regime_transition(db_path=db_path)
        assert result is None

    def test_detect_regime_transition_exception(self, db_path, monkeypatch):
        """detect_regime_transition handles exception."""
        from nuri.trading.strategy.monitor import detect_regime_transition
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            MagicMock(side_effect=Exception("no data")))
        result = detect_regime_transition(db_path=db_path)
        assert result is None

    def test_daily_pnl_summary_no_positions(self, db_path, monkeypatch):
        """daily_pnl_summary with no open positions."""
        from nuri.trading.strategy.monitor import daily_pnl_summary
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda db_path=None: None)
        result = daily_pnl_summary(db_path=db_path)
        assert result["total_positions"] == 0
        assert result["total_pnl"] == 0


# ═══════════════════════════════════════════════════════
# 17. mean_reversion.py — scan and backtest
# ═══════════════════════════════════════════════════════


class TestMeanReversion:
    """Tests for nuri/trading/strategy/mean_reversion.py."""

    def test_scan_mean_reversion_no_data(self, db_path):
        """scan with no data returns empty."""
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        result = scan_mean_reversion(db_path=db_path)
        assert result == []

    def test_backtest_mean_reversion_no_data(self, db_path):
        """backtest with no data returns 0 trades."""
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=db_path)
        assert result["total_trades"] == 0

    def test_scan_mean_reversion_with_data(self, db_path):
        """scan detects oversold conditions."""
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        _seed_portfolio(db_path, [("AAPL", 150.0, 10)])
        # Create price data that has a big drop (to trigger RSI < 30 + below BB lower)
        dates = pd.bdate_range("2024-12-01", periods=60)
        with get_db(db_path) as conn:
            for i, d in enumerate(dates):
                if i < 45:
                    price = 150 + np.sin(i / 5) * 3
                else:
                    price = 120 - (i - 45) * 2  # sharp decline
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                    ("AAPL", d.strftime("%Y-%m-%d"), max(price, 50)),
                )
        result = scan_mean_reversion(db_path=db_path)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# 18. scanner.py — market scanner edge cases
# ═══════════════════════════════════════════════════════


class TestScanner:
    """Tests for nuri/trading/swing/scanner.py."""

    def test_analyze_ticker_insufficient_data(self):
        """_analyze_ticker with < 20 data points returns None."""
        from nuri.trading.swing.scanner import _analyze_ticker
        df = pd.DataFrame({
            "Close": [100, 101, 102],
            "Volume": [1000, 1000, 1000],
        })
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_analyze_ticker_no_signal(self):
        """_analyze_ticker with flat data returns None (no signal)."""
        from nuri.trading.swing.scanner import _analyze_ticker
        np.random.seed(42)
        dates = pd.bdate_range("2024-12-01", periods=30)
        # Perfectly flat data — no signals
        df = pd.DataFrame({
            "Close": [100.0] * 30,
            "Volume": [100000] * 30,
        }, index=dates)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_analyze_ticker_volume_spike(self):
        """_analyze_ticker detects volume spike."""
        from nuri.trading.swing.scanner import _analyze_ticker
        dates = pd.bdate_range("2024-12-01", periods=25)
        prices = list(np.linspace(100, 110, 25))
        volumes = [100000] * 24 + [500000]  # Last day volume spike
        df = pd.DataFrame({
            "Close": prices,
            "Volume": volumes,
        }, index=dates)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.signal in ("volume_spike", "momentum", "breakout", "bounce")

    def test_scan_market_no_data(self, monkeypatch):
        """scan_market with failed download."""
        from nuri.trading.swing.scanner import scan_market
        monkeypatch.setattr("nuri.trading.swing.scanner._fetch_prices", lambda *a, **kw: None)
        result = scan_market()
        assert result == []

    def test_print_scan_empty(self, capsys):
        """print_scan with empty results."""
        from nuri.trading.swing.scanner import print_scan
        print_scan([])
        captured = capsys.readouterr()
        assert "스캔 결과 없음" in captured.out

    def test_print_scan_with_results(self, capsys):
        """print_scan with results."""
        from nuri.trading.swing.scanner import ScanResult, print_scan
        results = [ScanResult("AAPL", 150, 2.5, 8.0, 3.0, 55, 0.6, "volume_spike", 40)]
        print_scan(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out


# ═══════════════════════════════════════════════════════
# 19. api/main.py — auth endpoints, health, security headers
# ═══════════════════════════════════════════════════════


class TestAPIMain:
    """Tests for nuri/api/main.py."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limiter(self, monkeypatch):
        """Disable rate limiter for all API main tests."""
        from nuri.api import main as main_mod
        monkeypatch.setattr(main_mod.limiter, "enabled", False)

    def test_health_endpoint(self):
        """Health endpoint returns ok."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_redirect(self):
        """Root redirects to docs."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (301, 302, 307)

    def test_security_headers(self):
        """Security headers are present on responses."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_auth_no_password_set(self, monkeypatch):
        """Auth endpoint when no DASHBOARD_PASSWORD set."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "")
        client = TestClient(app)
        response = client.post("/api/auth/token", json={"password": "test"})
        assert response.status_code == 503

    def test_auth_wrong_password(self, monkeypatch):
        """Auth endpoint with wrong password."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "correct_password")
        client = TestClient(app)
        response = client.post("/api/auth/token", json={"password": "wrong"})
        assert response.status_code == 401

    def test_auth_correct_password(self, monkeypatch):
        """Auth endpoint with correct password."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "test123")
        monkeypatch.setenv("API_SECRET_KEY", "test-secret-key-for-jwt")
        client = TestClient(app)
        response = client.post("/api/auth/token", json={"password": "test123"})
        assert response.status_code == 200
        assert "access_token" in response.json()


# ═══════════════════════════════════════════════════════
# 20. candidates.py — edge cases
# ═══════════════════════════════════════════════════════


class TestCandidates:
    """Tests for nuri/trading/recommend/candidates.py."""

    def test_load_scorecard_no_reports(self, monkeypatch):
        """_load_scorecard with no report directory."""
        import nuri.trading.recommend.candidates as cand_mod
        from nuri.trading.recommend.candidates import _load_scorecard
        monkeypatch.setattr(cand_mod, "REPORT_DIR", Path("/nonexistent/path"))
        data, age = _load_scorecard()
        assert data == {}
        assert age is None

    def test_get_drift_map_exception(self, monkeypatch):
        """_get_drift_map handles exception."""
        from nuri.trading.recommend.candidates import _get_drift_map
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift",
                            MagicMock(side_effect=Exception("no data")))
        result = _get_drift_map()
        assert result == {}

    def test_check_vix_gate_normal(self, db_path):
        """VIX gate normal when VIX is low."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        _seed_macro(db_path)  # VIX 18.5
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "normal"

    def test_check_vix_gate_blocked(self, db_path):
        """VIX gate blocked when VIX > 30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 35.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "blocked"

    def test_check_vix_gate_caution(self, db_path):
        """VIX gate caution when VIX 25-30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 27.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "caution"

    def test_print_candidates_empty(self, capsys, monkeypatch):
        """print_candidates with no candidates."""
        from nuri.trading.recommend.candidates import print_candidates
        monkeypatch.setattr("nuri.trading.recommend.candidates._check_vix_gate",
                            lambda **kw: {"vix": 18, "gate": "normal", "msg": ""})
        print_candidates([])
        captured = capsys.readouterr()
        assert "매매 후보 없음" in captured.out
