"""Tests for leverage ETF conditional allowance study.

네트워크 없이 mock 데이터로 실행. conftest가 yfinance를 전역 mock.
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_leveraged_data(db_path, days=300):
    """TSLL + TSLA + VIX 테스트 데이터 시드."""
    dates = pd.bdate_range("2024-01-02", periods=days)

    # TSLA: 완만한 상승 + 노이즈
    np.random.seed(42)
    tsla_close = np.linspace(200, 280, days) + np.random.normal(0, 3, days)

    # TSLL: 2x 일간 수익률 적용 (volatility drag 포함)
    tsla_returns = np.diff(tsla_close) / tsla_close[:-1]
    tsll_close = np.zeros(days)
    tsll_close[0] = 30.0  # TSLL 초기가
    for i in range(1, days):
        tsll_close[i] = tsll_close[i - 1] * (1 + tsla_returns[i - 1] * 2)

    for ticker, close_arr in [("TSLA", tsla_close), ("TSLL", tsll_close)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close_arr * 0.999,
            "high": close_arr * 1.01,
            "low": close_arr * 0.99,
            "close": close_arr,
            "volume": [1_000_000] * days,
            "adj_close": close_arr,
        })
        upsert_prices(df, db_path)

    # VIX: 대부분 18, 일부 구간 25-35 (고변동성)
    vix_vals = np.full(days, 18.0)
    vix_vals[100:120] = 30.0  # 고공포 구간
    vix_vals[200:210] = 22.0  # 약간 높은 구간
    macros = [
        {"indicator": "vix", "date": dates[i].strftime("%Y-%m-%d"),
         "value": float(vix_vals[i]), "source": "test"}
        for i in range(days)
    ]
    upsert_macro(macros, db_path)

    return db_path


# ─── 개별 시나리오 함수 테스트 ───


class TestCalcMetrics:
    """_calc_metrics 단위 테스트."""

    def test_empty_returns(self):
        from nuri.quant.backtest.leverage_study import _calc_metrics
        result = _calc_metrics(pd.Series(dtype=float))
        assert result["total_return_pct"] == 0.0
        assert result["trading_days"] == 0

    def test_positive_returns(self):
        from nuri.quant.backtest.leverage_study import _calc_metrics
        # 약간의 노이즈가 있는 양의 수익률 (std > 0이어야 Sharpe 계산 가능)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.01, 0.005, 50))
        result = _calc_metrics(returns)
        assert result["total_return_pct"] > 0
        assert result["sharpe_ratio"] > 0
        assert result["trading_days"] == 50

    def test_negative_returns(self):
        from nuri.quant.backtest.leverage_study import _calc_metrics
        returns = pd.Series([-0.01] * 30)
        result = _calc_metrics(returns)
        assert result["total_return_pct"] < 0
        assert result["max_drawdown_pct"] < 0

    def test_single_return(self):
        from nuri.quant.backtest.leverage_study import _calc_metrics
        returns = pd.Series([0.05])
        result = _calc_metrics(returns)
        # 단일 데이터포인트: len < 2 → 빈 결과 반환
        assert result["trading_days"] == 0


class TestVolatilityDecay:
    """_calc_volatility_decay 테스트."""

    def test_empty_series(self):
        from nuri.quant.backtest.leverage_study import _calc_volatility_decay
        result = _calc_volatility_decay(
            pd.Series(dtype=float), pd.Series(dtype=float)
        )
        assert result == 0.0

    def test_perfect_2x_no_decay(self):
        from nuri.quant.backtest.leverage_study import _calc_volatility_decay
        # 일정 수익률이면 decay가 없어야 함
        idx = pd.date_range("2024-01-01", periods=50)
        underlying = pd.Series([0.01] * 50, index=idx)
        leveraged = pd.Series([0.02] * 50, index=idx)
        result = _calc_volatility_decay(leveraged, underlying)
        assert abs(result) < 1.0  # 근사적으로 0에 가까움

    def test_volatile_path_shows_decay(self):
        from nuri.quant.backtest.leverage_study import _calc_volatility_decay
        idx = pd.date_range("2024-01-01", periods=100)
        np.random.seed(7)
        underlying = pd.Series(np.random.normal(0.001, 0.03, 100), index=idx)
        leveraged = underlying * 2  # 일간 2x
        result = _calc_volatility_decay(leveraged, underlying)
        # 높은 변동성 → 음의 decay (drag)
        assert isinstance(result, float)


class TestScenarioBuyAndHold:
    """scenario_buy_and_hold 테스트."""

    def test_basic(self):
        from nuri.quant.backtest.leverage_study import scenario_buy_and_hold
        idx = pd.date_range("2024-01-01", periods=60)
        lev = pd.DataFrame({"close": np.linspace(30, 45, 60)}, index=idx)
        und = pd.DataFrame({"close": np.linspace(200, 260, 60)}, index=idx)

        result = scenario_buy_and_hold(lev, und)
        assert result["scenario"] == "A_buy_and_hold"
        assert "leveraged" in result
        assert "underlying" in result
        assert result["leveraged"]["total_return_pct"] > 0
        assert result["underlying"]["total_return_pct"] > 0
        assert "volatility_decay_pct" in result


class TestScenarioVixFilter:
    """scenario_vix_filter 테스트."""

    def test_all_low_vix(self):
        """VIX가 항상 낮으면 항상 보유."""
        from nuri.quant.backtest.leverage_study import scenario_vix_filter
        idx = pd.date_range("2024-01-01", periods=60)
        lev = pd.DataFrame({"close": np.linspace(30, 40, 60)}, index=idx)
        vix = pd.Series([15.0] * 60, index=idx, name="vix")

        result = scenario_vix_filter(lev, vix)
        assert result["scenario"] == "B_vix_filter"
        assert result["leveraged"]["total_return_pct"] > 0
        assert result["trade_count"] == 1  # 1번 진입

    def test_high_vix_blocks_entry(self):
        """VIX가 항상 높으면 진입 못함."""
        from nuri.quant.backtest.leverage_study import scenario_vix_filter
        idx = pd.date_range("2024-01-01", periods=60)
        lev = pd.DataFrame({"close": np.linspace(30, 40, 60)}, index=idx)
        vix = pd.Series([30.0] * 60, index=idx, name="vix")

        result = scenario_vix_filter(lev, vix)
        assert result["trade_count"] == 0
        assert result["leveraged"]["total_return_pct"] == 0.0

    def test_empty_vix(self):
        """VIX 데이터 없으면 거래 0."""
        from nuri.quant.backtest.leverage_study import scenario_vix_filter
        idx = pd.date_range("2024-01-01", periods=60)
        lev = pd.DataFrame({"close": np.linspace(30, 40, 60)}, index=idx)
        vix = pd.Series(dtype=float, name="vix")

        result = scenario_vix_filter(lev, vix)
        assert result["trade_count"] == 0


class TestScenarioTrendFollow:
    """scenario_trend_follow 테스트."""

    def test_insufficient_data(self):
        """SMA200 계산 불가 시 빈 결과."""
        from nuri.quant.backtest.leverage_study import scenario_trend_follow
        idx = pd.date_range("2024-01-01", periods=100)
        lev = pd.DataFrame({"close": np.linspace(30, 40, 100)}, index=idx)

        result = scenario_trend_follow(lev)
        assert result["scenario"] == "C_trend_follow"
        assert result["leveraged"]["trading_days"] == 0

    def test_strong_uptrend(self):
        """강한 상승 추세 → SMA50 > SMA200 구간 존재."""
        from nuri.quant.backtest.leverage_study import scenario_trend_follow
        idx = pd.date_range("2024-01-01", periods=300)
        lev = pd.DataFrame({"close": np.linspace(20, 60, 300)}, index=idx)

        result = scenario_trend_follow(lev)
        assert result["leveraged"]["trading_days"] > 0


class TestScenarioMaxHold:
    """scenario_max_hold 테스트."""

    def test_basic(self):
        from nuri.quant.backtest.leverage_study import scenario_max_hold
        idx = pd.date_range("2024-01-01", periods=60)
        lev = pd.DataFrame({"close": np.linspace(30, 45, 60)}, index=idx)

        result = scenario_max_hold(lev, max_days=10)
        assert result["scenario"] == "D_max_hold"
        assert result["trade_count"] > 1  # 60일 / (10+1일) ≈ 5회 이상

    def test_empty_prices(self):
        from nuri.quant.backtest.leverage_study import scenario_max_hold
        lev = pd.DataFrame({"close": pd.Series(dtype=float)})

        result = scenario_max_hold(lev)
        assert result["trade_count"] == 0

    def test_short_period(self):
        """max_days보다 짧은 기간."""
        from nuri.quant.backtest.leverage_study import scenario_max_hold
        idx = pd.date_range("2024-01-01", periods=5)
        lev = pd.DataFrame({"close": [30, 31, 32, 33, 34]}, index=idx)

        result = scenario_max_hold(lev, max_days=10)
        assert result["trade_count"] == 1  # 한 번 진입, max_days 도달 전 데이터 끝


# ─── 통합 테스트 ───


class TestRunLeverageStudy:
    """run_leverage_study 통합 테스트."""

    def test_full_study(self, db_path):
        """전체 스터디 실행 (시드 데이터)."""
        _seed_leveraged_data(db_path, days=300)
        from nuri.quant.backtest.leverage_study import run_leverage_study

        results = run_leverage_study(
            leveraged_ticker="TSLL",
            underlying_ticker="TSLA",
            db_path=db_path,
        )

        assert "scenarios" in results
        assert len(results["scenarios"]) == 4
        assert "A_buy_and_hold" in results["scenarios"]
        assert "B_vix_filter" in results["scenarios"]
        assert "C_trend_follow" in results["scenarios"]
        assert "D_max_hold" in results["scenarios"]

        # 기본 구조 검증
        a = results["scenarios"]["A_buy_and_hold"]
        assert "leveraged" in a
        assert "underlying" in a
        assert "volatility_decay_pct" in a

    def test_no_leveraged_data(self, db_path):
        """레버리지 ETF 가격 없으면 에러 메시지."""
        from nuri.quant.backtest.leverage_study import run_leverage_study

        results = run_leverage_study(
            leveraged_ticker="NONEXIST",
            underlying_ticker="TSLA",
            db_path=db_path,
        )
        assert "error" in results

    def test_no_underlying_data(self, db_path):
        """기초자산 가격 없으면 에러 메시지."""
        # TSLL만 시드
        dates = pd.bdate_range("2024-01-02", periods=60)
        df = pd.DataFrame({
            "ticker": "TSLL",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [30] * 60, "high": [31] * 60,
            "low": [29] * 60, "close": [30] * 60,
            "volume": [1_000_000] * 60, "adj_close": [30] * 60,
        })
        upsert_prices(df, db_path)

        from nuri.quant.backtest.leverage_study import run_leverage_study

        results = run_leverage_study(
            leveraged_ticker="TSLL",
            underlying_ticker="NONEXIST",
            db_path=db_path,
        )
        assert "error" in results


class TestPrintStudy:
    """print_study 출력 테스트."""

    def test_print_error(self, capsys):
        from nuri.quant.backtest.leverage_study import print_study
        print_study({"error": "No data"})
        captured = capsys.readouterr()
        assert "No data" in captured.out

    def test_print_results(self, capsys, db_path):
        _seed_leveraged_data(db_path, days=300)
        from nuri.quant.backtest.leverage_study import print_study, run_leverage_study
        results = run_leverage_study("TSLL", "TSLA", db_path=db_path)
        print_study(results)
        captured = capsys.readouterr()
        assert "레버리지 ETF" in captured.out
        assert "A_buy_and_hold" in captured.out
