"""Per-collector tests for stock.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.base import MAX_FAILURE_RATE, BaseCollector, CollectionFailureError
from nuri.core.db import (
    get_db,
    init_db,
    query,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)


class TestStockCollector:
    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        result = c._period_to_start_date("5d")
        assert len(result) == 10
        assert "-" in result



class TestStockCollectorTickerCollection:
    def test_collect_ticker_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000], "adj_close": [194.0]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and not df.empty

    def test_collect_ticker_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("provider error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_no_adj_close(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and "adj_close" in df.columns

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock import StockCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert StockCollector().collect(period="5d").empty

    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        result = StockCollector._period_to_start_date("1mo")
        assert len(result) == 10

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        assert StockCollector().save(pd.DataFrame()) == 0



class TestStockCollectorEdgeCases:
    def test_collect_full_flow(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "open": [190.0], "high": [195.0],
                                "low": [189.0], "close": [194.0], "volume": [50000000], "adj_close": [194.0]})
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert not StockCollector().collect(period="5d").empty
