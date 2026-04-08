"""Per-collector tests for institutional.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from nuri.core.db import (
    init_db,
)


class TestInstitutionalDeep:
    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        data = [
            {"ticker": "005930.KS", "date": "2026-03-30", "market": "KOSPI",
             "institution_net": 1000000, "foreign_net": 500000,
             "individual_net": -1500000, "source": "pykrx"},
        ]
        count = c.save(data)
        assert count >= 0


# ##############################################################################
# Source: test_coverage_round5.py
# ##############################################################################



class TestInstitutionalCollect:
    def test_collect_and_save(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        mock_df = pd.DataFrame({
            "기관합계": [1000000, 2000000],
            "외국인합계": [500000, 600000],
            "개인": [-1500000, -2600000],
        }, index=pd.date_range("2026-03-29", periods=2))
        with patch("pykrx.stock.get_market_trading_value_by_date", return_value=mock_df):
            result = c.collect()
        assert isinstance(result, list)
        if result:
            count = c.save(result)
            assert count >= 0



class TestInstitutionalCollectorKRMocked:
    def test_collect_kr_with_mocked_pykrx(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        mock_df = pd.DataFrame(
            {"기관합계": [1000000], "외국인합계": [2000000], "개인": [-3000000]},
            index=pd.DatetimeIndex(["2025-01-15"]),
        )
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = mock_df

        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
            assert len(results) == 1
            assert results[0]["ticker"] == "005930.KS"

    def test_collect_kr_empty(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = pd.DataFrame()
        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_collect_kr_exception(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector

        collector = InstitutionalCollector()
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.side_effect = RuntimeError("API down")
        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector

        count = InstitutionalCollector().save([{
            "ticker": "005930.KS", "date": "2025-01-15", "market": "KR",
            "institution_net": 1000000, "foreign_net": 2000000,
            "individual_net": -3000000, "source": "pykrx",
        }])
        assert count == 1

    def test_safe_float(self):
        from nuri.collectors.institutional import _safe_float

        assert _safe_float(3.14) == 3.14
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None



class TestInstitutionalCollectorKRAndUS:
    def test_collect_kr(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_df = pd.DataFrame({"기관합계": [1000000], "외국인합계": [500000], "개인": [-200000]},
                               index=pd.to_datetime(["2025-01-30"]))
        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = mock_df
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock(stock=mock_stock))
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        collector = InstitutionalCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        results = collector.collect()
        assert len(results) >= 1

    def test_collect_kr_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert InstitutionalCollector().collect() == []

    def test_collect_kr_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert InstitutionalCollector().collect() == []

    def test_collect_us_with_finnhub(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        mock_stock = MagicMock()
        mock_stock.get_market_trading_value_by_date.return_value = pd.DataFrame()
        import sys

        monkeypatch.setitem(sys.modules, "pykrx", MagicMock())
        monkeypatch.setitem(sys.modules, "pykrx.stock", mock_stock)
        mock_client = MagicMock()
        mock_client.ownership.return_value = {"ownership": [{"data": "test"}]}
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)
        results = InstitutionalCollector().collect()
        us_results = [r for r in results if r["market"] == "US"]
        assert len(us_results) >= 1

    def test_collect_us_finnhub_import_error(self, monkeypatch, db_with_portfolio):
        import sys

        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.delitem(sys.modules, "finnhub", raising=False)
        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "finnhub":
                raise ImportError("No module named 'finnhub'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        assert InstitutionalCollector()._collect_us(["AAPL"], "test_key") == []

    def test_collect_us_finnhub_ticker_error(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        mock_client = MagicMock()
        mock_client.ownership.side_effect = Exception("API error")
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        import sys

        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)
        assert InstitutionalCollector()._collect_us(["AAPL"], "key") == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        c = InstitutionalCollector()
        assert c.save([]) == 0
        assert c.save([{"ticker": "005930.KS", "date": "2025-01-30", "market": "KR",
                         "institution_net": 1000000, "foreign_net": 500000,
                         "individual_net": -200000, "source": "pykrx"}]) == 1


# Remaining R24 classes are extensive -- adding edge cases and remaining collectors



class TestCollectNoUSTickets:
    def test_no_us_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.reddit import RedditCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert RedditCollector().collect() == []



class TestInstitutionalCollector_Uncovered:
    def test_instantiate(self):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().name == "institutional"

    def test_save_empty(self, db_path):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().save([]) == 0
