"""Per-collector tests for fred_calendar.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch

from nuri.core.db import (
    query,
)


class TestFREDCalendarCollector:
    def test_fallback_calendar(self):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""
        records = collector.collect(days_ahead=365)
        assert isinstance(records, list)
        for r in records:
            assert r["event_type"] == "economic"

    @patch("nuri.collectors.fred_calendar.requests.get")
    def test_collect_fred_api(self, mock_get):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "release_dates": [
                {"release_id": 10, "date": "2026-04-14"},
                {"release_id": 50, "date": "2026-04-03"},
                {"release_id": 999, "date": "2026-04-10"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = FREDCalendarCollector()
        collector.api_key = "test_key"
        records = collector.collect()
        assert len(records) == 2
        descriptions = {r["description"] for r in records}
        assert "FRED: CPI" in descriptions

    def test_negative_days_ahead_defaults(self):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        collector = FREDCalendarCollector()
        collector.api_key = ""
        records = collector.collect(days_ahead=-5)
        assert isinstance(records, list)


# ##############################################################################
# Source: test_coverage_round3.py
# ##############################################################################


class TestFREDCalendarCollectorAPIAndFallback:
    def test_collect_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        c.api_key = ""
        assert isinstance(c.collect(days_ahead=365), list)

    def test_collect_invalid_days(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        c.api_key = ""
        assert isinstance(c.collect(days_ahead=-1), list)

    def test_collect_fred_api_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "release_dates": [
                {"release_id": 10, "date": "2026-04-15"},
                {"release_id": 50, "date": "2026-04-18"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get", MagicMock(return_value=mock_resp))
        c = FREDCalendarCollector()
        c.api_key = "test_key"
        results = c._collect_fred_api(days_ahead=30)
        assert len(results) == 2

    def test_collect_fred_api_failure_fallback(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        monkeypatch.setattr("nuri.collectors.fred_calendar.requests.get", MagicMock(side_effect=Exception("FRED down")))
        c = FREDCalendarCollector()
        c.api_key = "test_key"
        assert isinstance(c.collect(days_ahead=365), list)

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        assert c.save([]) == 0
        assert (
            c.save(
                [
                    {
                        "date": "2026-04-15",
                        "event_type": "economic",
                        "ticker": None,
                        "description": "FRED: CPI",
                        "importance": 3,
                    }
                ]
            )
            == 1
        )

    def test_save_deduplicates(self, db_with_portfolio):
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        record = {
            "date": "2026-04-15",
            "event_type": "economic",
            "ticker": None,
            "description": "FRED: CPI",
            "importance": 3,
        }
        c.save([record])
        c.save([record])
        rows = query("SELECT * FROM events WHERE description = 'FRED: CPI'", db_path=db_with_portfolio)
        assert len(rows) == 1

    def test_save_is_atomic_rollback_on_insert_failure(self, db_with_portfolio):
        import pytest

        from nuri.collectors.fred_calendar import FREDCalendarCollector

        c = FREDCalendarCollector()
        original = {
            "date": "2026-04-15",
            "event_type": "economic",
            "ticker": None,
            "description": "FRED: CPI",
            "importance": 3,
        }
        assert c.save([original]) == 1

        # importance 키 누락 → DELETE 후 INSERT 단계에서 실패해야 하며, 단일 트랜잭션 롤백으로 기존 행 보존
        broken = {"date": "2026-04-15", "event_type": "economic", "ticker": None, "description": "FRED: CPI"}
        with pytest.raises(Exception):
            c.save([broken])

        rows = query("SELECT * FROM events WHERE description = 'FRED: CPI'", db_path=db_with_portfolio)
        assert len(rows) == 1
        assert rows[0]["importance"] == 3

    def test_fallback_warns_when_past_2026(self, monkeypatch, caplog):
        from datetime import datetime

        from nuri.collectors.fred_calendar import FREDCalendarCollector
        from nuri.core.timezone import KST

        monkeypatch.setattr(
            "nuri.collectors.fred_calendar.kst_now",
            lambda: datetime(2027, 1, 15, 9, 0, tzinfo=KST),
        )
        c = FREDCalendarCollector()
        c.api_key = ""
        with caplog.at_level("WARNING", logger="nuri.collectors.fred_calendar"):
            records = c.collect(days_ahead=14)
        assert records == []
        assert any("폴백 만료" in rec.message for rec in caplog.records)


# ##############################################################################
# Source: test_coverage_round24.py -- edge cases
# ##############################################################################
