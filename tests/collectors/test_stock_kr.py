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

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        assert StockKRCollector().save(pd.DataFrame()) == 0
