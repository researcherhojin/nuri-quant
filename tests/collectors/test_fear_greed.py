"""Per-collector tests for fear_greed.

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


class TestFearGreedCollector:
    def test_instantiate(self):
        from nuri.collectors.fear_greed import FearGreedCollector

        c = FearGreedCollector()
        assert c.name == "fear_greed"

    def test_save_records(self, db_path):
        from nuri.collectors.fear_greed import FearGreedCollector

        c = FearGreedCollector()
        records = [{"indicator": "fear_greed", "date": "2026-03-30",
                     "value": 55.0, "source": "cnn_api"}]
        count = c.save(records)
        assert count == 1

    @patch("nuri.collectors.fear_greed.requests")
    def test_collect_api(self, mock_requests):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"fear_and_greed": {"score": 62.5}}
        mock_requests.get.return_value = mock_resp
        c = FearGreedCollector()
        result = c._collect_api()
        assert len(result) == 1
        assert result[0]["value"] == 62.5



class TestFearGreedCollectorAPIAndScrape:
    def test_collect_api_success(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"score": 55.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        results = FearGreedCollector().collect()
        assert len(results) == 1 and results[0]["value"] == 55.0

    def test_collect_api_value_key(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"value": 72.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect()[0]["value"] == 72.0

    def test_collect_api_no_data(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect() == []

    def test_collect_api_fail_scrape_fallback(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = '<html><text class="market-fng-gauge__dial-number-value">45</text></html>'
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        results = FearGreedCollector().collect()
        assert results[0]["value"] == 45.0

    def test_collect_both_fail(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(side_effect=Exception("all down")))
        assert FearGreedCollector().collect() == []

    def test_scrape_no_score_found(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = "<html><body>No score here</body></html>"
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        assert FearGreedCollector().collect() == []

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fear_greed import FearGreedCollector

        assert FearGreedCollector().save([{"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"}]) == 1
