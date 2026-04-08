"""Per-collector tests for ark.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock


class TestARKCollector:
    def test_instantiate(self):
        from nuri.collectors.ark import ARKCollector

        c = ARKCollector()
        assert c.name == "ark"

    def test_save_empty(self, db_path):
        from nuri.collectors.ark import ARKCollector

        c = ARKCollector()
        assert c.save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.ark import ARKCollector

        c = ARKCollector()
        records = [{"date": "2026-03-30", "ticker": "TSLA", "direction": "Buy",
                     "shares": 50000.0, "weight": 8.5, "fund": "ARKK"}]
        count = c.save(records)
        assert count == 1



class TestARKCollectorCollectAndSave:
    def test_collect_csv_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n"
        csv_text += "01/15/2025,ARKK,Buy,AAPL,123456,Apple Inc,1000,2.5\n"
        csv_text += "01/15/2025,ARKK,Sell,NVDA,654321,NVIDIA,500,1.3\n"
        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(return_value=mock_resp))
        results = ARKCollector().collect()
        assert "AAPL" in [r["ticker"] for r in results]

    def test_collect_csv_empty_ticker(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        csv_text = "Date,Fund,Direction,Ticker,CUSIP,Name,Shares,% of ETF\n01/15/2025,ARKK,Buy,,123456,Unknown,1000,2.5\n"
        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(return_value=mock_resp))
        assert ARKCollector().collect() == []

    def test_collect_all_urls_fail(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        monkeypatch.setattr("nuri.collectors.ark.requests.get", MagicMock(side_effect=Exception("fail")))
        assert ARKCollector().collect() == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.ark import ARKCollector

        assert ARKCollector().save([{"date": "2025-01-15", "ticker": "AAPL", "direction": "Buy",
                                     "shares": 1000, "weight": 2.5, "fund": "ARKK"}]) == 1
