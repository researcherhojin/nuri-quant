"""Strategy Backtest 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def backtest_data(db_path):
    """5년 SPY + SH + VIX 시뮬레이션 데이터."""
    dates = pd.bdate_range("2020-01-01", periods=1200)

    # SPY: 상승→하락→상승 패턴
    phase1 = np.linspace(300, 450, 400)  # 2020 bull
    phase2 = np.linspace(450, 350, 200)  # 2022 bear
    phase3 = np.linspace(350, 500, 600)  # 2023-25 recovery
    spy_close = np.concatenate([phase1, phase2, phase3]) + np.random.normal(0, 2, 1200)

    # SH: SPY의 대략적 역
    sh_close = 40 - (spy_close - 400) * 0.08 + np.random.normal(0, 0.5, 1200)

    for ticker, close in [("SPY", spy_close), ("SH", sh_close)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": [50000000] * 1200, "adj_close": close,
        })
        upsert_prices(df, db_path)

    # VIX: bear 구간에서 높음
    vix = np.concatenate([
        np.full(400, 15) + np.random.normal(0, 2, 400),
        np.full(200, 30) + np.random.normal(0, 3, 200),
        np.full(600, 16) + np.random.normal(0, 2, 600),
    ]).clip(10, 80)

    records = [{"indicator": "vix", "date": dates[i].strftime("%Y-%m-%d"),
                "value": float(vix[i]), "source": "test"} for i in range(1200)]
    upsert_macro(records, db_path)

    return db_path


class TestRegimeClassification:

    def test_classifies_multiple_regimes(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        regimes = df["regime"].unique()
        # 상승+하락+횡보 → 최소 2개 레짐
        non_unknown = [r for r in regimes if r != "unknown"]
        assert len(non_unknown) >= 2

    def test_bear_detected_in_decline(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        bear_days = df[df["regime"].str.contains("bear", na=False)]
        assert len(bear_days) > 50  # 200일 하락 중 최소 50일은 bear


class TestBacktest:

    def test_returns_result(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.total_days > 500
        assert -100 < result.total_return < 500
        assert result.max_drawdown <= 0

    def test_mdd_better_than_spy(self, backtest_data):
        """전략 MDD가 SPY보다 나아야 함 (방어 효과)."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.max_drawdown > result.spy_max_drawdown  # 덜 빠짐 (음수이므로 >)

    def test_equity_curve(self, backtest_data):
        """equity_curve가 올바른 구조로 생성되는지 확인."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.equity_curve is not None
        assert len(result.equity_curve) == result.total_days
        point = result.equity_curve[0]
        assert set(point.keys()) == {"date", "strategy", "spy", "drawdown"}
        last = result.equity_curve[-1]
        assert abs(last["strategy"] - result.total_return) < 0.1


class TestMonteCarlo:

    def test_runs_without_error(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=backtest_data)
        mc = monte_carlo_test(regimes, n_simulations=50, db_path=backtest_data)
        assert "actual_return" in mc
        assert "statistically_significant" in mc
        assert 0 <= mc["return_percentile"] <= 1


class TestAllocation:

    def test_allocations_sum_to_100(self):
        from nuri.trading.strategy.ls_backtest import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc["long"] + alloc["short"] + alloc["cash"]
            assert abs(total - 1.0) < 0.01, f"{regime}: {total}"
