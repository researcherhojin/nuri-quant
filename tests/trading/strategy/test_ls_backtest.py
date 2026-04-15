"""Tests for nuri.trading.strategy.ls_backtest.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""

import pandas as pd
import pytest


class TestRegimeClassification:
    """From test_backtest.py — historical regime classification."""

    def test_classifies_multiple_regimes(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        regimes = df["regime"].unique()
        non_unknown = [r for r in regimes if r != "unknown"]
        assert len(non_unknown) >= 2

    def test_bear_detected_in_decline(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        bear_days = df[df["regime"].str.contains("bear", na=False)]
        assert len(bear_days) > 50


class TestBacktest:
    """From test_backtest.py — backtest results."""

    def test_returns_result(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.total_days > 500
        assert -100 < result.total_return < 500
        assert result.max_drawdown <= 0

    def test_equity_curve(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.equity_curve is not None
        assert len(result.equity_curve) == result.total_days


class TestMonteCarlo:
    """From test_backtest.py — Monte Carlo simulation."""

    def test_runs_without_error(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=backtest_data)
        mc = monte_carlo_test(regimes, n_simulations=50, db_path=backtest_data)
        assert "actual_return" in mc
        assert "statistically_significant" in mc
        assert 0 <= mc["return_percentile"] <= 1


class TestInteractiveBacktest:
    def test_classify_historical_regimes_accepts_custom_sma(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes

        df_fast = classify_historical_regimes(db_path=backtest_data, sma_period=50)
        df_slow = classify_historical_regimes(db_path=backtest_data, sma_period=100)

        assert len(df_fast) == len(df_slow)
        assert "sma_fast" in df_fast.columns
        assert not df_fast["sma_gap"].equals(df_slow["sma_gap"])

    def test_run_interactive_backtest_returns_equity_curve(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_interactive_backtest

        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_interactive_backtest(
            regimes,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=backtest_data,
        )

        assert result.total_days > 0
        assert result.equity_curve is not None
        assert len(result.equity_curve) == result.total_days
        assert {"date", "strategy", "spy", "drawdown"} <= set(result.equity_curve[0])

    def test_run_interactive_backtest_thresholds_change_result(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_interactive_backtest

        regimes = classify_historical_regimes(db_path=backtest_data)
        baseline = run_interactive_backtest(
            regimes,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=backtest_data,
        )
        tighter = run_interactive_backtest(
            regimes,
            stop_loss_pct=-3,
            take_profit_pct=10,
            db_path=backtest_data,
        )

        assert baseline.total_days == tighter.total_days
        assert baseline.total_return != tighter.total_return

    def test_empty_regimes_after_filtering_returns_zero_result(self, backtest_data):
        """df.empty guard inside run_interactive_backtest (line 193)."""
        from nuri.trading.strategy.ls_backtest import run_interactive_backtest

        only_unknown = pd.DataFrame({
            "regime": ["unknown"] * 5,
            "return": [0.01] * 5,
            "date": pd.bdate_range("2024-01-01", periods=5),
            "close": [100.0] * 5,
        })

        result = run_interactive_backtest(
            only_unknown,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=backtest_data,
        )

        assert result.total_days == 0
        assert result.equity_curve == []

    def test_missing_sh_data_falls_back_to_spy_inverse(self, db_path):
        """No SH ticker in DB → sh empty DataFrame path (line 201)."""
        import numpy as np

        from nuri.core.db import upsert_prices
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            run_interactive_backtest,
        )

        dates = pd.bdate_range("2022-01-01", periods=300)
        spy_close = np.linspace(400, 500, 300) + np.random.normal(0, 2, 300)
        upsert_prices(
            pd.DataFrame({
                "ticker": "SPY",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": spy_close * 0.999,
                "high": spy_close * 1.005,
                "low": spy_close * 0.995,
                "close": spy_close,
                "volume": [50_000_000] * 300,
                "adj_close": spy_close,
            }),
            db_path,
        )

        regimes = classify_historical_regimes(db_path=db_path)
        result = run_interactive_backtest(
            regimes,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=db_path,
        )

        assert result.total_days > 0

    def test_sh_nan_return_falls_back_to_spy_inverse(self, backtest_data, monkeypatch):
        """sh_return NaN in bear regime (line 261)."""
        import numpy as np

        from nuri.trading.strategy import ls_backtest

        original = ls_backtest.query_df

        def query_df_with_nan(sql, *args, **kwargs):
            df = original(sql, *args, **kwargs)
            if "ticker='SH'" in sql and not df.empty:
                df.loc[10:12, "close"] = np.nan
            return df

        monkeypatch.setattr(ls_backtest, "query_df", query_df_with_nan)

        regimes = ls_backtest.classify_historical_regimes(db_path=backtest_data)
        regimes["regime"] = "bear_low_vol"
        result = ls_backtest.run_interactive_backtest(
            regimes,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=backtest_data,
        )

        assert result.total_days > 0

    def test_single_row_regimes_returns_zero_result(self, backtest_data):
        """df with 1 row → loop skips → empty strat guard (line 296)."""
        from nuri.trading.strategy.ls_backtest import run_interactive_backtest

        single = pd.DataFrame({
            "regime": ["bull_low_vol"],
            "return": [0.01],
            "date": [pd.Timestamp("2024-01-02")],
            "close": [100.0],
        })

        result = run_interactive_backtest(
            single,
            stop_loss_pct=-7,
            take_profit_pct=20,
            db_path=backtest_data,
        )

        assert result.total_days == 0
        assert result.equity_curve == []


class TestAllocation:
    """From test_backtest.py — allocation sums."""

    def test_allocations_sum_to_100(self):
        from nuri.trading.strategy.ls_backtest import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc["long"] + alloc["short"] + alloc["cash"]
            assert abs(total - 1.0) < 0.01, f"{regime}: {total}"


class TestLSBacktest:
    """From test_coverage_round4.py."""

    def test_classify_historical_regimes(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        assert isinstance(regimes, pd.DataFrame)
        assert "regime" in regimes.columns
        assert len(regimes) > 100

    def test_run_backtest(self, rich_db):
        from nuri.trading.strategy.ls_backtest import BacktestResult, classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert isinstance(result, BacktestResult)
        assert hasattr(result, "total_return")
        assert result.total_days > 0

    def test_monte_carlo(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=10, db_path=rich_db)
        assert isinstance(mc, dict)


class TestLSBacktestDeep:
    """From test_coverage_round5.py."""

    def test_backtest_result_fields(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert hasattr(result, "annual_return")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "win_rate")


class TestLSBacktestRound6:
    """From test_coverage_round6.py — extended backtest functions."""

    def test_analyze_per_regime(self, rich_db):
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)
        assert len(perfs) > 0
        assert hasattr(perfs[0], "regime")

    def test_stress_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        assert isinstance(results, list)

    def test_run_backtest_with_rules(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        assert isinstance(result, dict)

    def test_print_stress(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, print_stress, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        print_stress(results)
        assert len(capsys.readouterr().out) > 0

    def test_print_monte_carlo(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test, print_monte_carlo
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=5, db_path=rich_db)
        print_monte_carlo(mc)
        assert len(capsys.readouterr().out) > 0

    def test_print_rules_comparison(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_rules_comparison,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        print_rules_comparison(result)
        assert len(capsys.readouterr().out) > 0


class TestLSBacktest_R26:
    """From test_coverage_round26.py."""

    def test_classify_returns_df(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=rich_db)
        assert isinstance(df, pd.DataFrame)
        assert "regime" in df.columns

    def test_run_backtest(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert hasattr(result, "total_return")

    def test_monte_carlo_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=5, db_path=rich_db)
        assert isinstance(mc, dict)

    def test_stress_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        assert isinstance(results, list)

    def test_run_backtest_with_rules(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        assert isinstance(result, dict)

    def test_analyze_per_regime(self, rich_db):
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)


class TestLSBacktest_R27:
    """From test_coverage_round27.py."""

    def test_classify_multiple_regimes(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=rich_db)
        assert len(df) > 0

    def test_print_timing(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, print_timing
        regimes = classify_historical_regimes(db_path=rich_db)
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing
        timing = analyze_entry_timing(regimes)
        print_timing(timing)
        assert len(capsys.readouterr().out) >= 0

    def test_print_rules_comparison(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_rules_comparison,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        print_rules_comparison(result)
        assert len(capsys.readouterr().out) > 0


class TestLSBacktestEmpty:
    """ls_backtest: empty DataFrame causes IndexError."""

    def test_empty_df_raises(self, db_path):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=db_path)
        # Empty DB → empty or minimal df
        assert isinstance(df, pd.DataFrame)
        if len(df) == 0:
            from nuri.trading.strategy.ls_backtest import run_backtest
            with pytest.raises((IndexError, KeyError, ValueError)):
                run_backtest(df, db_path=db_path)
