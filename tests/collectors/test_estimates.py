"""Per-collector tests for estimates.

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


class TestEstimatesCollector:
    def test_instantiate(self):
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c.name == "estimates"

    def test_safe_helpers(self):
        from nuri.collectors.estimates import _safe_float, _safe_int

        assert _safe_float(1.5) == 1.5
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None
        assert _safe_int(10) == 10
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None

    def test_save_records(self, db_path):
        from nuri.collectors.estimates import _upsert_estimates

        records = [{"ticker": "AAPL", "date": "2026-03-30",
                     "recommendation": "buy", "target_high": 250.0,
                     "target_low": 190.0, "target_mean": 220.0,
                     "target_median": 218.0, "num_analysts": 30,
                     "current_price": 195.0}]
        count = _upsert_estimates(records)
        assert count == 1



class TestEstimatesCollectorMockedYFinance:
    def test_collect_with_mocked_yfinance(self, rich_db, monkeypatch):
        from nuri.collectors import estimates as est_mod
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 200.0,
            "currentPrice": 200.0,
            "recommendationKey": "buy",
            "targetHighPrice": 250.0,
            "targetLowPrice": 180.0,
            "targetMeanPrice": 220.0,
            "targetMedianPrice": 215.0,
            "numberOfAnalystOpinions": 30,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        results = collector.collect()
        assert len(results) == 1
        assert results[0]["recommendation"] == "buy"
        assert results[0]["target_mean"] == 220.0

    def test_collect_empty_info(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_no_analysts(self, rich_db, monkeypatch):
        """분석가 데이터 없는 종목(VOO 같은 ETF) 스킵."""
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["VOO"])
        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": 500.0}  # 분석가 필드 없음
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_exception(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("API fail")
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_no_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        assert collector.collect() == []

    def test_collect_skips_kr_tickers(self, rich_db, monkeypatch):
        """한국 종목(.KS)은 yfinance 컨센서스 미지원 — 스킵."""
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(
            collector, "_get_tickers", lambda market=None: ["005930.KS", "000660.KS"]
        )
        assert collector.collect() == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        assert EstimatesCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        count = EstimatesCollector().save([{
            "ticker": "MSFT", "date": "2025-01-01", "recommendation": "buy",
            "target_high": 500, "target_low": 400, "target_mean": 450,
            "target_median": 445, "num_analysts": 40, "current_price": 420,
        }])
        assert count == 1

    def test_safe_float_and_int(self):
        from nuri.collectors.estimates import _safe_float, _safe_int

        assert _safe_float(3.14) == 3.14
        assert _safe_float(float("nan")) is None
        assert _safe_int(42) == 42
        assert _safe_int(float("nan")) is None



class TestEstimatesCollectorErrorHandling:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 190.0,
            "currentPrice": 190.0,
            "recommendationKey": "buy",
            "targetHighPrice": 300.0,
            "targetLowPrice": 200.0,
            "targetMeanPrice": 250.0,
            "targetMedianPrice": 248.0,
            "numberOfAnalystOpinions": 30,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = EstimatesCollector().collect()
        assert results[0]["recommendation"] == "buy"
        assert results[0]["target_mean"] == 250.0

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {}  # 빈 info
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert EstimatesCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = Exception("fail")
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert EstimatesCollector().collect() == []

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.estimates import EstimatesCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert EstimatesCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_safe_float(self):
        from nuri.collectors.estimates import _safe_float

        assert _safe_float(123.45) == 123.45
        assert _safe_float(float("nan")) is None

    def test_safe_int(self):
        from nuri.collectors.estimates import _safe_int

        assert _safe_int(30) == 30
        assert _safe_int(float("nan")) is None
