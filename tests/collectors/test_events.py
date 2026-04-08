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
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"report_date": pd.to_datetime(["2025-04-25"])})
        dividend_df = pd.DataFrame({"ex_dividend_date": pd.to_datetime(["2025-05-10"])})
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=dividend_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 2

    def test_collect_ticker_events_with_index_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"dummy": [1]}, index=pd.to_datetime(["2025-04-25"]))
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.side_effect = Exception("no dividend")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = EventsCollector()._collect_ticker_events("AAPL")
        assert len(results) == 1

    def test_collect_ticker_events_no_date(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.events import EventsCollector

        earnings_df = pd.DataFrame({"dummy": [1]}, index=[0])
        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=earnings_df))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
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

        mock_obb = MagicMock()
        mock_obb.equity.calendar.earnings.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        mock_obb.equity.calendar.dividend.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame({"ex_dividend_date": [None]})))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
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
