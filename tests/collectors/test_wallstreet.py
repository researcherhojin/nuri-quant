"""Per-collector tests for wallstreet.

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


class TestWallStreetCollector:
    def test_instantiate(self):
        from nuri.collectors.wallstreet import WallStreetCollector

        c = WallStreetCollector()
        assert c.name == "wallstreet"

    def test_save_all_types(self, db_path):
        from nuri.collectors.wallstreet import WallStreetCollector

        c = WallStreetCollector()
        data = {
            "ratings": [{"ticker": "AAPL", "date": "2026-03-30", "firm": "GS",
                          "to_grade": "Buy", "from_grade": "Hold", "action": "upgrade",
                          "target_price": 230.0}],
            "earnings": [{"ticker": "AAPL", "quarter": "2026Q1",
                           "eps_actual": 2.1, "eps_estimate": 1.9, "surprise_pct": 10.5}],
            "insiders": [{"ticker": "AAPL", "date": "2026-03-20", "insider_name": "Tim Cook",
                           "position": "CEO", "transaction_type": "Sale",
                           "shares": 50000, "value": 9500000}],
            "short_data": [{"ticker": "AAPL", "short_pct_float": 0.8, "days_to_cover": 1.2}],
        }
        count = c.save(data)
        assert count > 0



class TestWallStreetDeep:
    def test_collect_and_save(self, rich_db):
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = pd.DataFrame([
            {"GradeDate": pd.Timestamp("2026-03-01"), "Firm": "GS",
             "ToGrade": "Buy", "FromGrade": "Hold", "Action": "upgrade"},
        ])
        mock_ticker.earnings_history = pd.DataFrame([
            {"Quarter": pd.Timestamp("2026-01-01"), "epsActual": 2.1,
             "epsEstimate": 1.9, "surprisePercent": 10.5},
        ])
        mock_ticker.insider_transactions = pd.DataFrame([
            {"startDate": pd.Timestamp("2026-03-20"), "insiderName": "Tim Cook",
             "position": "CEO", "transactionType": "Sale",
             "shares": 50000, "value": 9500000},
        ])
        mock_ticker.info = {"shortPercentOfFloat": 0.008, "shortRatio": 1.2}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert "ratings" in data
        count = c.save(data)
        assert count > 0

    def test_collect_empty_data(self, rich_db):
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = None
        mock_ticker.earnings_history = None
        mock_ticker.insider_transactions = None
        mock_ticker.info = {}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert isinstance(data, dict)



class TestWallStreetCollectorRatingsAndInsiders:
    def test_collect_ratings(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_info = {"shortPercentOfFloat": 0.05, "shortRatio": 2.5}
        mock_ud = pd.DataFrame({"Firm": ["GS"], "ToGrade": ["Buy"], "FromGrade": ["Hold"],
                                "Action": ["up"], "currentPriceTarget": [250.0]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_eh = pd.DataFrame({"epsActual": [1.50], "epsEstimate": [1.40], "surprisePercent": [7.14]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Sale of shares"], "Insider": ["CEO"],
                                 "Position": ["Chief Executive"], "Shares": [5000], "Value": [1000000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = mock_info
                self.upgrades_downgrades = mock_ud
                self.earnings_history = mock_eh
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        data = WallStreetCollector().collect()
        assert len(data["ratings"]) >= 1

    def test_collect_purchase_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Purchase of shares"],
                                 "Insider": ["CFO"], "Position": ["CFO"], "Shares": [1000], "Value": [200000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = {}
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["insiders"][0]["transaction_type"] == "purchase"

    def test_collect_other_transaction_type(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ins = pd.DataFrame({"Start Date": ["2025-01-20"], "Text": ["Gift of shares"],
                                 "Insider": ["Board"], "Position": ["Director"], "Shares": [500], "Value": [100000]})

        class MockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.info = {}
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = mock_ins
                self.recommendations = None

        monkeypatch.setattr(yf, "Ticker", MockTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["insiders"][0]["transaction_type"] == "other"

    def test_collect_exception_per_ticker(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.wallstreet import WallStreetCollector

        class BadTicker:
            def __init__(self, ticker):
                raise Exception("bad ticker")

        monkeypatch.setattr(yf, "Ticker", BadTicker)
        monkeypatch.setattr("nuri.collectors.wallstreet.get_tickers", lambda: ["AAPL"])
        assert WallStreetCollector().collect()["ratings"] == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector

        data = {"ratings": [{"ticker": "AAPL", "date": "2025-01-28", "firm": "GS", "to_grade": "Buy",
                              "from_grade": "Hold", "action": "up", "target_price": 250.0}],
                "earnings": [{"ticker": "AAPL", "quarter": "2025-01-28", "eps_actual": 1.5, "eps_estimate": 1.4, "surprise_pct": 7.14}],
                "insiders": [{"ticker": "AAPL", "date": "2025-01-20", "insider_name": "CEO", "position": "CEO",
                               "transaction_type": "sale", "shares": 5000, "value": 1000000}],
                "short_interest": [{"ticker": "AAPL", "short_pct_float": 5.0, "days_to_cover": 2.5}]}
        assert WallStreetCollector().save(data) >= 4

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.wallstreet import WallStreetCollector

        assert WallStreetCollector().save({"ratings": [], "earnings": [], "insiders": [], "short_interest": []}) == 0



class TestWallStreetSaveShortInterest:
    def test_save_short_no_days_to_cover(self, db_with_portfolio):
        from nuri.collectors.wallstreet import _save_short_interest

        assert _save_short_interest([{"ticker": "AAPL", "short_pct_float": 5.0}], db_path=db_with_portfolio) == 1
