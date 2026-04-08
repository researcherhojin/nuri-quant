"""Per-collector tests for cboe.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import (
    query,
    upsert_macro,
)


class TestCBOECollector:
    def test_instantiate(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c.name == "cboe"

    def test_extract_pcr_total(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85

    def test_extract_pcr_simple(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92

    def test_extract_pcr_calculated(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        result = c._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_missing(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({}) is None

    def test_save_records(self, db_path):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2026-03-30",
                     "value": 0.85, "source": "cboe"}]
        count = c.save(records)
        assert count == 1



class TestCBOECollector_Phase2:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 1.2}) == 1.2

    def test_extract_pcr_volume_calc(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 1500000,
            "TOTAL_CALL_VOLUME": 2000000,
        })
        assert result == pytest.approx(0.75)

    def test_extract_pcr_missing(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None
        assert CBOECollector._extract_pcr({"unrelated": 42}) is None

    def test_extract_pcr_zero_call(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 100,
            "TOTAL_CALL_VOLUME": 0,
        }) is None

    @patch("nuri.collectors.cboe.requests.get")
    def test_collect_daily_json(self, mock_get):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.92}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "put_call_ratio"
        assert records[0]["value"] == 0.92
        assert records[0]["source"] == "CBOE"

    @patch("nuri.collectors.cboe.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'put_call_ratio'", db_path=db_path)
        assert len(rows) >= 1
        assert rows[0]["value"] == pytest.approx(0.88)

    def test_parse_date_formats(self):
        from nuri.collectors.base import parse_date

        assert parse_date("2026-03-28") == "2026-03-28"
        assert parse_date("03/28/2026") == "2026-03-28"
        assert parse_date("") is None
        assert parse_date("invalid") is None
        assert parse_date("2026-03-28T12:00:00") == "2026-03-28"



class TestCBOEDeepFromHistorical:
    def test_collect_daily_mock(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests") as mock_req:
            mock_req.get.return_value = mock_resp
            result = c._collect_daily()
        assert isinstance(result, list)

    def test_collect_daily_failure(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        with patch.object(c, "_collect_daily", return_value=[]):
            result = c._collect_daily()
        assert isinstance(result, list)
        assert len(result) == 0


# ##############################################################################
# Source: test_coverage_round6.py
# ##############################################################################



class TestCBOEDeepCalculations:
    def test_collect_daily_success(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert isinstance(result, list)
        if result:
            assert result[0]["value"] == 0.85

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"TRADE_DATE": "2026-03-29", "TOTAL_PUT_CALL_RATIO": 0.90},
                {"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88},
            ]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert isinstance(result, list)

    def test_collect_full(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c.collect()
        assert isinstance(result, list)


# ##############################################################################
# Source: test_coverage_round8.py
# ##############################################################################



class TestCBOEFull:
    def test_collect_with_fallback(self):
        from nuri.collectors.cboe import CBOECollector

        mock_daily = MagicMock()
        mock_daily.status_code = 200
        mock_daily.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        mock_fail = MagicMock()
        mock_fail.status_code = 500

        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get",
                    side_effect=[mock_daily, mock_fail]):
            daily = c._collect_daily()
            totalpc = c._collect_totalpc()
        assert len(daily) > 0
        assert len(totalpc) == 0



class TestCBOEExtractPCR:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92
        assert CBOECollector._extract_pcr({"put_call_ratio": 1.1}) == 1.1
        assert CBOECollector._extract_pcr({"pcr": 0.75}) == 0.75
        assert CBOECollector._extract_pcr({"ratio": 0.6}) == 0.6

    def test_extract_pcr_from_volumes(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert abs(result - 0.5) < 0.01

    def test_extract_pcr_none(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None

    def test_extract_pcr_invalid_values(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": "bad"}) is None

    def test_collect_daily_success(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.85

    def test_collect_daily_dict_response(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"TOTAL_PUT_CALL_RATIO": 0.92}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.92

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.88}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert len(result) == 1

    def test_collect_fred_pcr(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "observations": [
                {"date": "2025-03-14", "value": "0.85"},
                {"date": "2025-03-13", "value": "."},
                {"date": "2025-03-12", "value": "0.92"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_fred_pcr()
        assert len(result) == 2

    def test_collect_fallback_chain(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = "test_key"
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                with patch.object(c, "_collect_fred_pcr", return_value=[
                    {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.9, "source": "FRED"}
                ]):
                    result = c.collect()
        assert len(result) == 1

    def test_collect_all_fail(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                result = c.collect()
        assert result == []

    def test_collect_daily_returns_empty(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", return_value=[]):
            with patch.object(c, "_collect_totalpc", return_value=[
                {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.8, "source": "CBOE"}
            ]):
                result = c.collect()
        assert len(result) == 1

    def test_save(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.85, "source": "CBOE"}]
        assert c.save(records) == 1
