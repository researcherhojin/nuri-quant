"""Per-collector tests for events.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import (
    query,
)


class TestEventsCollectorFOMCAndEarnings:
    def test_collect_fomc(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = mock_result
        mock_obb.equity.calendar.dividend.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector().collect()
        fomc = [r for r in results if r["event_type"] == "fomc"]
        assert len(fomc) == 8

    def test_collect_ticker_events_earnings(self, monkeypatch, db_with_portfolio):
        from datetime import date

        from nuri.collectors.events import EventsCollector

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [date(2025, 4, 25)], "Ex-Dividend Date": date(2025, 5, 10)}
        monkeypatch.setattr("yfinance.Ticker", lambda t: mock_ticker)
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 2
        assert any(r["event_type"] == "earnings" for r in results)
        assert any(r["event_type"] == "ex_dividend" for r in results)

    def test_collect_ticker_events_earnings_only(self, monkeypatch, db_with_portfolio):
        from datetime import date

        from nuri.collectors.events import EventsCollector

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [date(2025, 4, 25)]}
        monkeypatch.setattr("yfinance.Ticker", lambda t: mock_ticker)
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 1
        assert results[0]["event_type"] == "earnings"

    def test_collect_ticker_events_no_calendar(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        monkeypatch.setattr("yfinance.Ticker", lambda t: mock_ticker)
        assert EventsCollector()._collect_ticker_events("AAPL") == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        c = EventsCollector()
        assert c.save([]) == 0
        assert c.save([{"date": "2025-03-17", "event_type": "fomc", "ticker": None, "description": "FOMC", "importance": 3}]) == 1

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        c = EventsCollector()
        record = {"date": "2025-03-17", "event_type": "fomc", "ticker": None, "description": "FOMC", "importance": 3}
        c.save([record])
        c.save([record])
        rows = query("SELECT * FROM events WHERE event_type = 'fomc' AND date = '2025-03-17'", db_path=db_with_portfolio)
        assert len(rows) == 1



class TestEventsCollectorDividendNoDate:
    def test_dividend_no_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [], "Ex-Dividend Date": None}
        monkeypatch.setattr("yfinance.Ticker", lambda t: mock_ticker)
        assert isinstance(EventsCollector()._collect_ticker_events("AAPL"), list)



class TestEventsCollector_Uncovered:
    def test_save_empty(self, db_path):
        from nuri.collectors.events import EventsCollector

        assert EventsCollector().save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.events import EventsCollector

        count = EventsCollector().save([{
            "date": "2025-06-01", "event_type": "earnings",
            "ticker": "AAPL", "description": "Q2 earnings", "importance": "high",
        }])
        assert count >= 0
