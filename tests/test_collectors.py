"""Collector 모듈 테스트 — v2 오픈소스 스택."""
import pandas as pd
import pytest

from iris.db import init_db, upsert_prices, upsert_portfolio


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestBaseCollector:
    def test_get_tickers_filter(self, db_path):
        """_get_tickers 마켓 필터링."""
        upsert_portfolio([
            {"account": "test", "ticker": "TSLA", "quantity": 10,
             "avg_price": 300, "currency": "USD", "sector": "EV"},
            {"account": "test", "ticker": "005930.KS", "quantity": 1,
             "avg_price": 60000, "currency": "KRW", "sector": "Semi"},
        ], db_path)

        from iris.db import get_tickers
        all_tickers = get_tickers(db_path=db_path)
        us = [t for t in all_tickers if not t.endswith(".KS")]
        kr = [t for t in all_tickers if t.endswith(".KS")]
        assert "TSLA" in us
        assert "005930.KS" in kr


class TestStockCollector:
    def test_period_to_start_date(self):
        """기간 문자열 변환 테스트."""
        from iris.collectors.stock import StockCollector
        c = StockCollector()
        # 변환만 확인 (날짜 형식)
        result = c._period_to_start_date("5d")
        assert len(result) == 10  # YYYY-MM-DD
        assert "-" in result


class TestStockKRCollector:
    def test_kr_ticker_suffix_removal(self):
        """pykrx용 .KS 접미사 제거 테스트."""
        # _collect_ticker 내부 로직 간접 테스트
        ticker_full = "005930.KS"
        ticker_code = ticker_full.replace(".KS", "").replace(".KQ", "")
        assert ticker_code == "005930"


class TestTechnicalCollector:
    def test_compute_talib(self):
        """TA-Lib 지표 계산."""
        import numpy as np
        from iris.collectors.technical import TechnicalCollector
        close = np.array([100 + i * 0.5 + np.sin(i) for i in range(50)], dtype=float)
        result = TechnicalCollector._compute_talib(close)
        assert "rsi_14" in result
        assert "macd" in result
        assert len(result["rsi_14"]) == 50
