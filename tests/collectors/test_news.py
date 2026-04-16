"""Per-collector tests for news.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock

import pandas as pd


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


class TestYfinanceFallback:
    """yfinance 직접 폴백 경로 (#274). Flat vs nested payload + KST 변환 regression lock-in."""

    def test_fallback_parses_nested_payload(self, monkeypatch, db_with_portfolio):
        """신형 yfinance: {id, content: {...}} 구조 파싱."""
        import sys

        from nuri.collectors.news import NewsCollector

        # OpenBB primary 강제 실패시킴 → fallback 유도
        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = ImportError("OBBject_CompanyNews not found")
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        nested = [
            {
                "id": "abc123",
                "content": {
                    "title": "AAPL beats earnings",
                    "canonicalUrl": {"url": "https://example.com/nested/1"},
                    "provider": {"displayName": "Yahoo Finance"},
                    "pubDate": "2026-04-16T15:30:00Z",  # UTC → KST 2026-04-17
                },
            }
        ]

        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.news = nested
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = NewsCollector().collect()
        assert len(results) >= 1
        first = next(r for r in results if r["url"] == "https://example.com/nested/1")
        assert first["title"] == "AAPL beats earnings"
        assert first["source"] == "Yahoo Finance"
        assert first["date"] == "2026-04-17"  # UTC 15:30 → KST 00:30 다음날

    def test_fallback_parses_flat_payload(self, monkeypatch, db_with_portfolio):
        """구형 yfinance: {title, link, publisher, providerPublishTime: epoch} 구조 파싱."""
        import sys
        from datetime import datetime, timezone

        from nuri.collectors.news import NewsCollector
        from nuri.core.timezone import KST

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = ImportError("OBBject_CompanyNews not found")
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        # UTC 2026-04-16 14:00:00 → KST 2026-04-16 23:00 (같은 날)
        epoch_same_day = int(datetime(2026, 4, 16, 14, 0, 0, tzinfo=timezone.utc).timestamp())
        # UTC 2026-04-16 15:30:00 → KST 2026-04-17 00:30 (다음 날)
        epoch_next_day = int(datetime(2026, 4, 16, 15, 30, 0, tzinfo=timezone.utc).timestamp())

        flat = [
            {"title": "Flat same-day", "link": "https://ex.com/flat/1", "publisher": "WSJ", "providerPublishTime": epoch_same_day},
            {"title": "Flat next-day", "link": "https://ex.com/flat/2", "publisher": "WSJ", "providerPublishTime": epoch_next_day},
        ]

        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.news = flat
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = NewsCollector().collect()
        by_url = {r["url"]: r for r in results}

        assert "https://ex.com/flat/1" in by_url
        assert by_url["https://ex.com/flat/1"]["date"] == "2026-04-16"
        assert by_url["https://ex.com/flat/1"]["source"] == "WSJ"
        assert by_url["https://ex.com/flat/2"]["date"] == "2026-04-17"

        # 변환 결과가 프로젝트 KST helper 와 동치임을 확인
        expected = datetime.fromtimestamp(epoch_next_day, tz=KST).strftime("%Y-%m-%d")
        assert by_url["https://ex.com/flat/2"]["date"] == expected

    def test_fallback_handles_mixed_and_malformed_items(self, monkeypatch, db_with_portfolio):
        """빈 content / 누락 필드 / 잘못된 타입 혼재 — 크래시 없이 skip."""
        import sys

        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = ImportError("broken")
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        mixed = [
            # nested 정상
            {"content": {"title": "Good", "canonicalUrl": {"url": "https://ok.com/1"}, "pubDate": "2026-04-15T00:00:00Z", "provider": {"displayName": "X"}}},
            # nested 에 title 없음
            {"content": {"canonicalUrl": {"url": "https://skip.com/1"}, "pubDate": "2026-04-15T00:00:00Z"}},
            # nested 에 url 없음
            {"content": {"title": "No url", "pubDate": "2026-04-15T00:00:00Z"}},
            # flat 에 url 없음
            {"title": "Flat no url", "publisher": "Y"},
            # None 아이템
            None,
            # 잘못된 타입
            "string item",
            # flat 정상
            {"title": "Good flat", "link": "https://ok.com/2", "publisher": "Z", "providerPublishTime": 1745000000},
        ]

        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.news = mixed
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = NewsCollector().collect()
        urls = {r["url"] for r in results}
        assert "https://ok.com/1" in urls
        assert "https://ok.com/2" in urls
        # malformed skipped
        assert "https://skip.com/1" not in urls

    def test_fallback_returns_empty_when_yfinance_raises(self, monkeypatch, db_with_portfolio):
        """yfinance 자체가 exception — fallback 은 per-ticker [] 반환 (silent degrade)."""
        import sys

        from nuri.collectors.news import NewsCollector

        mock_obb = MagicMock()
        mock_obb.news.company.side_effect = ImportError("broken")
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("network fail")
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        results = NewsCollector().collect()
        assert results == []

    def test_iso_utc_to_kst_date_boundaries(self):
        """UTC→KST date 변환 경계값. KST=UTC+9 이므로 15:00 UTC 가 자정 경계."""
        from nuri.collectors.news import NewsCollector

        fn = NewsCollector._iso_utc_to_kst_date
        # UTC 14:59 → KST 23:59 (같은 날)
        assert fn("2026-04-16T14:59:59Z") == "2026-04-16"
        # UTC 15:00 → KST 00:00 (다음 날)
        assert fn("2026-04-16T15:00:00Z") == "2026-04-17"
        # +00:00 suffix
        assert fn("2026-04-16T15:00:00+00:00") == "2026-04-17"
        # naive (no tz) — UTC 로 간주
        assert fn("2026-04-16T15:00:00") == "2026-04-17"
        # 잘못된 입력
        assert fn("invalid") is None
        assert fn("") is None
        assert fn(None) is None
        # 짧은 ISO date-only
        assert fn("2026-04-17") == "2026-04-17"
