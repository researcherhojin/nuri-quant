"""Per-collector tests for news.

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


class TestNewsCollectorScenarios:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["Apple beats"], "url": ["https://example.com/1"], "source": ["Reuters"]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = NewsCollector().collect()
        assert results[0]["title"] == "Apple beats"

    def test_collect_no_url(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["No link"], "url": [""], "source": ["Unknown"]},
                               index=pd.to_datetime(["2025-01-28"]))
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []

    def test_collect_date_in_column(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        news_df = pd.DataFrame({"title": ["News"], "url": ["https://example.com/1"], "source": ["Reuters"], "date": ["2025-01-28"]})
        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=news_df))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = NewsCollector().collect()
        assert results[0]["date"] == "2025-01-28"

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.return_value = MagicMock(to_dataframe=MagicMock(return_value=pd.DataFrame()))
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = Exception("API error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert NewsCollector().collect() == []



class TestNewsCollector_Uncovered:
    def test_save_empty(self, db_path):
        from nuri.collectors.news import NewsCollector

        assert NewsCollector().save([]) == 0
