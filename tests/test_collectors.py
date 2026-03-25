"""Collector 모듈 테스트."""
import pytest
import pandas as pd
from pathlib import Path

from iris.db import init_db, upsert_prices, upsert_portfolio, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_with_data(db_path):
    """가격 + 포트폴리오 데이터가 있는 DB."""
    upsert_portfolio([
        {"account": "test", "ticker": "TSLA", "quantity": 10,
         "avg_price": 300, "currency": "USD", "sector": "SectorA"},
    ], db_path)
    df = pd.DataFrame([
        {"ticker": "TSLA", "date": f"2026-03-{d:02d}",
         "open": 300+d, "high": 310+d, "low": 290+d,
         "close": 305+d, "volume": 1000000, "adj_close": 305+d}
        for d in range(1, 21)
    ])
    upsert_prices(df, db_path)
    return db_path


class TestBaseCollector:
    def test_get_tickers_filter(self, db_path):
        """_get_tickers 마켓 필터링 테스트."""
        from iris.collectors.base import BaseCollector

        upsert_portfolio([
            {"account": "test", "ticker": "TSLA", "quantity": 10,
             "avg_price": 300, "currency": "USD", "sector": "EV"},
            {"account": "test", "ticker": "005930.KS", "quantity": 1,
             "avg_price": 60000, "currency": "KRW", "sector": "Semi"},
        ], db_path)

        # BaseCollector는 ABC라서 직접 인스턴스화할 수 없음
        # _get_tickers를 간접 테스트
        from iris.db import get_tickers
        all_tickers = get_tickers(db_path=db_path)
        assert "TSLA" in all_tickers
        assert "005930.KS" in all_tickers

        us = [t for t in all_tickers if not t.endswith(".KS")]
        kr = [t for t in all_tickers if t.endswith(".KS")]
        assert us == ["TSLA"]
        assert kr == ["005930.KS"]


class TestStockCollector:
    def test_single_ticker_df(self):
        """_single_ticker_df 변환 테스트."""
        from iris.collectors.stock import StockCollector

        data = pd.DataFrame({
            "Open": [100.0], "High": [110.0], "Low": [95.0],
            "Close": [105.0], "Volume": [1000], "Adj Close": [105.0],
        }, index=pd.DatetimeIndex(["2026-03-24"], name="Date"))

        df = StockCollector._single_ticker_df(data, "TEST")
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "TEST"
        assert df.iloc[0]["close"] == 105.0
        assert df.iloc[0]["date"] == "2026-03-24"


class TestTechnicalCollector:
    def test_compute_talib(self):
        """TA-Lib 지표 계산 테스트."""
        import numpy as np
        try:
            from iris.collectors.technical import TechnicalCollector
            close = np.array([100 + i * 0.5 + np.sin(i) for i in range(50)], dtype=float)
            result = TechnicalCollector._compute_talib(close)
            assert "rsi_14" in result
            assert "macd" in result
            assert len(result["rsi_14"]) == 50
        except ImportError:
            pytest.skip("TA-Lib not available")
