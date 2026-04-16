"""Tests for nuri.collectors.macro_news.

Network-free:
- requests.get는 monkeypatch로 mock된 fixture XML 반환
- classify_event는 use_llm=False로 regex만 사용
"""
from datetime import timedelta
from email.utils import format_datetime
from unittest.mock import MagicMock

import pytest

from nuri.collectors.macro_news import (
    MacroNewsCollector,
    _parse_pubdate,
    _parse_rss_items,
)
from nuri.core.db import query
from nuri.core.timezone import kst_now


def _recent_date_rfc822(hours_ago: int = 6) -> str:
    """테스트용 — stale 필터를 통과하는 최근 날짜 RFC 822 문자열."""
    return format_datetime(kst_now() - timedelta(hours=hours_ago))


def _build_rss_fixture() -> bytes:
    """최소 fixture — Reuters source 분리, source 없는 item, 빈 link 등 edge case 포함.

    pubDate 는 실행 시각 기준 -2h / -1h 로 동적 생성 — 7일 stale filter 통과 보장.
    (이전 하드코딩 `Wed, 09 Apr 2026 ...` 는 7일 경과 후 테스트 fail 하는 time-bomb.)
    """
    d1 = _recent_date_rfc822(hours_ago=2).encode()
    d2 = _recent_date_rfc822(hours_ago=1).encode()
    return (
        b'<?xml version="1.0"?>'
        b'<rss version="2.0"><channel>'
        b'<item>'
        b'<title>Iran agrees to ceasefire - Reuters</title>'
        b'<link>https://news.google.com/articles/abc123</link>'
        b'<pubDate>' + d1 + b'</pubDate>'
        b'<source url="https://www.reuters.com">Reuters</source>'
        b'</item>'
        b'<item>'
        b'<title>Fed signals rate cut next meeting</title>'
        b'<link>https://news.google.com/articles/def456</link>'
        b'<pubDate>' + d2 + b'</pubDate>'
        b'</item>'
        b'<item>'
        b'<title>No URL</title>'
        b'<link></link>'
        b'</item>'
        b'</channel></rss>'
    )


RSS_FIXTURE = _build_rss_fixture()

EMPTY_RSS = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'


class TestParseRssItems:
    def test_parses_two_valid_items(self):
        items = _parse_rss_items(RSS_FIXTURE)
        assert len(items) == 2

    def test_strips_source_from_title(self):
        items = _parse_rss_items(RSS_FIXTURE)
        assert items[0]["headline"] == "Iran agrees to ceasefire"
        assert items[0]["source"] == "Reuters"

    def test_default_source_when_missing(self):
        items = _parse_rss_items(RSS_FIXTURE)
        assert items[1]["source"] == "GoogleNews"

    def test_drops_empty_link_items(self):
        items = _parse_rss_items(RSS_FIXTURE)
        urls = [i["url"] for i in items]
        assert "" not in urls

    def test_empty_channel_returns_empty(self):
        assert _parse_rss_items(EMPTY_RSS) == []

    def test_malformed_xml_returns_empty(self):
        assert _parse_rss_items(b"<not xml") == []


class TestParsePubdate:
    def test_valid_rfc822(self):
        result = _parse_pubdate("Wed, 09 Apr 2026 12:34:56 GMT")
        assert result.startswith("2026-04-09T12:34:56")

    def test_none_returns_kst_now(self):
        result = _parse_pubdate(None)
        # YYYY-MM-DDTHH:MM:SS+09:00 형식 — KST timezone 확인
        assert "T" in result
        assert len(result) >= 19

    def test_junk_returns_kst_now(self):
        result = _parse_pubdate("not a date at all")
        assert "T" in result


class TestCollect:
    def test_collect_uses_classifier_and_returns_records(self, monkeypatch, db_path):
        # mock requests.get → 항상 fixture 반환
        mock_resp = MagicMock()
        mock_resp.content = RSS_FIXTURE
        mock_resp.raise_for_status = MagicMock()

        import nuri.collectors.macro_news as mod
        monkeypatch.setattr(mod.requests, "get", MagicMock(return_value=mock_resp))

        # 키워드 리스트를 1개로 줄여서 빠르게
        monkeypatch.setattr(mod, "KEYWORDS", ("Iran ceasefire",))

        collector = MacroNewsCollector(use_llm=False)  # regex만
        records = collector.collect()

        assert len(records) == 2
        # 첫 record가 분류된 카테고리 가지고 있는지
        assert records[0]["query_keyword"] == "Iran ceasefire"
        assert records[0]["category"] == "geopolitical_de_escalation"
        assert records[0]["regime_hint"] == "recovery"
        assert records[0]["sentiment"] > 0
        # 둘째는 fed_dovish (rate cut 매칭)
        assert records[1]["category"] == "fed_dovish"
        # classification_method 필드 존재 확인
        assert records[0]["classification_method"] == "regex"

    def test_collect_filters_stale_articles(self, monkeypatch, db_path):
        """7일 초과 기사는 DROP된다."""
        # 2025년 11월 기사를 포함하는 RSS
        stale_rss = (
            b'<?xml version="1.0"?>'
            b'<rss version="2.0"><channel>'
            b'<item>'
            b'<title>Very old article about yen carry trade</title>'
            b'<link>https://news.google.com/articles/old1</link>'
            b'<pubDate>Thu, 19 Nov 2025 08:00:00 GMT</pubDate>'
            b'<source url="https://example.com">Example</source>'
            b'</item>'
            b'<item>'
            b'<title>Iran agrees to ceasefire today</title>'
            b'<link>https://news.google.com/articles/fresh1</link>'
            b'<pubDate>' + _recent_date_rfc822().encode() + b'</pubDate>'
            b'<source url="https://reuters.com">Reuters</source>'
            b'</item>'
            b'</channel></rss>'
        )
        mock_resp = MagicMock()
        mock_resp.content = stale_rss
        mock_resp.raise_for_status = MagicMock()

        import nuri.collectors.macro_news as mod
        monkeypatch.setattr(mod.requests, "get", MagicMock(return_value=mock_resp))
        monkeypatch.setattr(mod, "KEYWORDS", ("test",))

        records = MacroNewsCollector(use_llm=False).collect()
        # stale 기사는 필터링되고 최근 기사만 남아야 함
        assert len(records) == 1
        assert "ceasefire" in records[0]["headline"].lower()

    def test_collect_handles_keyword_failure(self, monkeypatch, db_path):
        """한 키워드 실패가 다른 키워드를 막지 않음."""
        call_count = {"n": 0}

        def fake_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("network down")
            mock_resp = MagicMock()
            mock_resp.content = RSS_FIXTURE
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        import nuri.collectors.macro_news as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod, "KEYWORDS", ("first", "second"))

        records = MacroNewsCollector(use_llm=False).collect()
        # 첫 키워드는 실패, 둘째는 성공 → 2개 item
        assert len(records) == 2

    def test_collect_empty_rss_returns_no_records(self, monkeypatch, db_path):
        mock_resp = MagicMock()
        mock_resp.content = EMPTY_RSS
        mock_resp.raise_for_status = MagicMock()

        import nuri.collectors.macro_news as mod
        monkeypatch.setattr(mod.requests, "get", MagicMock(return_value=mock_resp))
        monkeypatch.setattr(mod, "KEYWORDS", ("test",))

        assert MacroNewsCollector(use_llm=False).collect() == []


class TestSave:
    def test_save_empty_returns_zero(self, db_path):
        assert MacroNewsCollector().save([]) == 0

    def test_save_inserts_records(self, db_path):
        records = [
            {
                "published_at": "2026-04-09T12:00:00+00:00",
                "source": "Reuters",
                "query_keyword": "Iran ceasefire",
                "headline": "Iran agrees to ceasefire",
                "url": "https://news.google.com/articles/abc",
                "category": "geopolitical_de_escalation",
                "sentiment": 0.5,
                "confidence": 0.5,
                "regime_hint": "recovery",
                "raw_json": None,
            },
            {
                "published_at": "2026-04-09T13:00:00+00:00",
                "source": "GoogleNews",
                "query_keyword": "Fed",
                "headline": "Fed signals rate cut",
                "url": "https://news.google.com/articles/def",
                "category": "fed_dovish",
                "sentiment": 0.4,
                "confidence": 0.5,
                "regime_hint": "bull_low_vol",
                "raw_json": None,
            },
        ]
        n = MacroNewsCollector().save(records)
        assert n == 2

        rows = query("SELECT category, regime_hint FROM macro_events ORDER BY id")
        assert len(rows) == 2
        assert rows[0]["category"] == "geopolitical_de_escalation"
        assert rows[1]["regime_hint"] == "bull_low_vol"

    def test_save_dedups_by_url(self, db_path):
        record = {
            "published_at": "2026-04-09T12:00:00+00:00",
            "source": "Reuters",
            "query_keyword": "Iran",
            "headline": "Ceasefire announced",
            "url": "https://news.google.com/articles/dup",
            "category": "geopolitical_de_escalation",
            "sentiment": 0.5,
            "confidence": 0.5,
            "regime_hint": "recovery",
            "raw_json": None,
        }
        collector = MacroNewsCollector()
        n1 = collector.save([record])
        n2 = collector.save([record])
        assert n1 == 1
        assert n2 == 0  # URL UNIQUE → INSERT OR IGNORE
        rows = query("SELECT COUNT(*) AS cnt FROM macro_events")
        assert rows[0]["cnt"] == 1
