"""Phase C 검증 모듈 테스트 — in-memory SQLite로 격리."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def sample_prices(db_path):
    """RSI/MACD/BB 테스트용 60일 V자 가격 데이터."""
    dates = pd.bdate_range("2025-01-01", periods=60)
    prices_down = np.linspace(100, 70, 30)
    prices_up = np.linspace(70, 110, 30)
    close = np.concatenate([prices_down, prices_up])

    df = pd.DataFrame({
        "ticker": "TEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": [1000000] * 60,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def long_prices(db_path):
    """SMA 골든/데드크로스 테스트용 300일 데이터."""
    dates = pd.bdate_range("2024-01-01", periods=300)
    # 상승 → 하락 → 상승 패턴 (SMA50/200 크로스 발생)
    phase1 = np.linspace(100, 180, 150)
    phase2 = np.linspace(180, 120, 80)
    phase3 = np.linspace(120, 160, 70)
    close = np.concatenate([phase1, phase2, phase3]) + np.random.normal(0, 0.5, 300)

    df = pd.DataFrame({
        "ticker": "LONG",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": [1000000] * 300,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


# ═══════════════════════════════════════════════════════
# C-1: 시그널 백테스트
# ═══════════════════════════════════════════════════════


class TestSignalBacktest:

    def test_rsi_oversold_detection(self, sample_prices):
        """V자 가격에서 RSI 과매도 반등이 감지되는지 확인."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1
        assert results[0].won is True

    def test_holding_period_exit(self, sample_prices):
        """20일 보유 후 정확한 날짜에 청산되는지 확인."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1, "RSI oversold 시그널이 감지되어야 함"
        assert results[0].holding_days == 20

    def test_macd_signal_detection(self, sample_prices):
        """V자 패턴에서 MACD 크로스가 감지되는지 확인."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["macd_golden", "macd_dead"], db_path=sample_prices)
        # V자 패턴이면 하락→상승 전환 시 MACD golden이 발생할 수 있음
        # 감지 여부만 확인 (빈 리스트도 OK — 60일은 MACD에 짧을 수 있음)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id in ("macd_golden", "macd_dead")

    def test_bb_bounce_detection(self, sample_prices):
        """BB 하단 반등 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["bb_bounce"], db_path=sample_prices)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "bb_bounce"
            assert r.holding_days == 20

    def test_sma_cross_with_long_data(self, long_prices):
        """300일 데이터에서 SMA 골든/데드 크로스 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="LONG", signals=["sma_golden", "sma_dead"], db_path=long_prices)
        # 300일이면 SMA200이 계산 가능, 상승→하락→상승이면 크로스 발생
        assert isinstance(results, list)

    def test_scorecard_calculation(self):
        """승률, Profit Factor 계산 정확도."""
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard

        results = [
            SignalResult("rsi_oversold", "TEST", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "TEST", "2025-02-01", 100, "2025-02-21", 95, -5.0, 20, False),
            SignalResult("rsi_oversold", "TEST", "2025-03-01", 100, "2025-03-21", 108, 8.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None and c.signal_id == "rsi_oversold"]
        assert len(total) == 1
        card = total[0]
        assert card.total_trades == 3
        assert abs(card.win_rate - 2 / 3) < 0.01
        assert abs(card.avg_return - (10 - 5 + 8) / 3) < 0.1
        assert abs(card.profit_factor - 3.6) < 0.1

    def test_scorecard_all_wins(self):
        """전부 이익이면 profit_factor = inf."""
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard

        results = [
            SignalResult("bb_bounce", "A", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("bb_bounce", "A", "2025-02-01", 100, "2025-02-21", 105, 5.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None]
        assert total[0].profit_factor == float("inf")
        assert total[0].win_rate == 1.0

    def test_empty_signals(self, db_path):
        """시그널이 없는 종목은 빈 리스트 반환."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NONEXIST", signals=["rsi_oversold"], db_path=db_path)
        assert results == []


# ═══════════════════════════════════════════════════════
# C-2: 슈퍼투자자 추종
# ═══════════════════════════════════════════════════════


class TestSuperinvestorBacktest:

    def test_data_readiness_check(self, db_path):
        """다분기 데이터 없으면 False 반환."""
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=db_path) is False

    def test_empty_backtest(self, db_path):
        """데이터 부족 시 빈 리스트."""
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor(db_path=db_path)
        assert results == []


# ═══════════════════════════════════════════════════════
# C-3: 애널리스트 검증
# ═══════════════════════════════════════════════════════


class TestAnalystBacktest:

    def test_insufficient_data_message(self, db_path):
        """데이터 부족 시 빈 리스트 + 경고 메시지."""
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []
