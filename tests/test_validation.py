"""Phase C 검증 모듈 테스트 — in-memory SQLite로 격리."""
import pandas as pd
import numpy as np
import pytest

from nuri.db import init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def sample_prices(db_path):
    """RSI/MACD 테스트용 60일 가격 데이터.

    의도적으로 과매도(RSI<30) 구간과 골든크로스 구간을 포함.
    """
    dates = pd.bdate_range("2025-01-01", periods=60)
    # V자 패턴: 30일 하락 → 30일 상승 (RSI 과매도 반등 발생)
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


# ═══════════════════════════════════════════════════════
# C-1: 시그널 백테스트 테스트
# ═══════════════════════════════════════════════════════


class TestSignalBacktest:
    """C-1 구현 시 이 테스트들을 통과시켜야 함."""

    @pytest.mark.skip(reason="C-1 미구현")
    def test_rsi_oversold_detection(self, sample_prices):
        """V자 가격에서 RSI 과매도 반등이 감지되는지 확인."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        # TODO: db_path를 주입할 수 있도록 backtest_signals 인터페이스 확장 필요
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"])
        assert len(results) >= 1
        # RSI 과매도 반등 후 매수 → 상승기이므로 수익
        assert results[0].won is True

    @pytest.mark.skip(reason="C-1 미구현")
    def test_holding_period_exit(self, sample_prices):
        """20일 보유 후 정확한 날짜에 청산되는지 확인."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"])
        if results:
            assert results[0].holding_days == 20

    @pytest.mark.skip(reason="C-1 미구현")
    def test_scorecard_calculation(self):
        """승률, Profit Factor 계산 정확도."""
        from nuri.quant.validation.signal_backtest import (
            SignalResult, generate_scorecard,
        )
        results = [
            SignalResult("rsi_oversold", "TEST", "2025-01-01", 100, "2025-01-21", 110,
                         10.0, 20, True),
            SignalResult("rsi_oversold", "TEST", "2025-02-01", 100, "2025-02-21", 95,
                         -5.0, 20, False),
            SignalResult("rsi_oversold", "TEST", "2025-03-01", 100, "2025-03-21", 108,
                         8.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None and c.signal_id == "rsi_oversold"]
        assert len(total) == 1
        card = total[0]
        assert card.total_trades == 3
        assert abs(card.win_rate - 2 / 3) < 0.01
        assert abs(card.avg_return - (10 - 5 + 8) / 3) < 0.1
        # profit_factor = (10 + 8) / 5 = 3.6
        assert abs(card.profit_factor - 3.6) < 0.1

    @pytest.mark.skip(reason="C-1 미구현")
    def test_empty_signals(self, db_path):
        """시그널이 없는 종목은 빈 리스트 반환."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        # 데이터 없는 종목
        results = backtest_signals(ticker="NONEXIST", signals=["rsi_oversold"])
        assert results == []


# ═══════════════════════════════════════════════════════
# C-2: 슈퍼투자자 추종 테스트
# ═══════════════════════════════════════════════════════


class TestSuperinvestorBacktest:
    """C-2 구현 시 이 테스트들을 통과시켜야 함."""

    @pytest.mark.skip(reason="C-2 미구현")
    def test_data_readiness_check(self):
        """다분기 데이터 없으면 False 반환."""
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        # 현재 1분기만 있으므로 False
        assert _check_data_readiness() is False


# ═══════════════════════════════════════════════════════
# C-3: 애널리스트 검증 테스트
# ═══════════════════════════════════════════════════════


class TestAnalystBacktest:
    """C-3 구현 시 이 테스트들을 통과시켜야 함."""

    @pytest.mark.skip(reason="C-3: 데이터 누적 대기")
    def test_insufficient_data_message(self):
        """데이터 부족 시 빈 리스트 + 경고 메시지."""
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90)
        assert results == []
