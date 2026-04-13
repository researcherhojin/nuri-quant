"""Per-collector tests for stock_kr.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import (
    init_db,
    upsert_portfolio,
)


class TestStockKRCollector:
    def test_instantiate(self):
        from nuri.collectors.stock_kr import StockKRCollector

        c = StockKRCollector()
        assert c.name == "stock_kr"


# ##############################################################################
# Source: test_collectors_phase2.py
# ##############################################################################



class TestStockKRCollectorScenarios:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame({"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
                                  index=pd.to_datetime(["2025-01-29"]))
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))
        df = StockKRCollector().collect(days=5)
        assert not df.empty

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=pd.DataFrame()))
        assert StockKRCollector().collect(days=5).empty

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(side_effect=Exception("pykrx error")))
        assert StockKRCollector().collect(days=5).empty

    def test_collect_no_kr_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock_kr import StockKRCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"}], path)
        assert StockKRCollector().collect(days=5).empty

    def test_collect_includes_indices(self, monkeypatch, db_with_portfolio):
        """KOSPI/KOSDAQ 지수가 같이 수집되는지 확인 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        # pykrx OHLCV mock
        mock_ohlcv = pd.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))

        # yfinance mock for index
        mock_index_df = pd.DataFrame(
            {"Open": [5800.0], "High": [5900.0], "Low": [5700.0], "Close": [5850.0], "Volume": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        import yfinance
        mock_download = MagicMock(return_value=mock_index_df)
        monkeypatch.setattr(yfinance, "download", mock_download)

        df = StockKRCollector().collect(days=5)
        assert not df.empty
        tickers = df["ticker"].unique().tolist()
        assert "KOSPI" in tickers
        assert "KOSDAQ" in tickers

    def test_collect_indices_empty(self, monkeypatch, db_with_portfolio):
        """yfinance가 빈 데이터 반환 시 지수 스킵 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=pd.DataFrame()))
        import yfinance
        monkeypatch.setattr(yfinance, "download", MagicMock(return_value=pd.DataFrame()))

        df = StockKRCollector().collect(days=5)
        # 개별 종목도 빈 데이터, 지수도 빈 데이터 → 전체 빈 DataFrame
        assert df.empty

    def test_collect_indices_exception(self, monkeypatch, db_with_portfolio):
        """yfinance 지수 수집 실패 시 에러 없이 스킵 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))
        import yfinance
        monkeypatch.setattr(yfinance, "download", MagicMock(side_effect=Exception("yfinance error")))

        df = StockKRCollector().collect(days=5)
        # 개별 종목은 수집되지만 지수는 스킵
        assert not df.empty
        assert "KOSPI" not in df["ticker"].unique().tolist()

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        assert StockKRCollector().save(pd.DataFrame()) == 0
