"""수집 실패·미래 자료와 날짜 없는 공식 문서를 근거로 위장하지 않는다."""

import hashlib
import json
from datetime import date, datetime, time, timedelta

import pytest

from nuri.collectors import briefing_sources as source
from nuri.core.timezone import KST, kst_now, today_kst


@pytest.fixture
def source_config(tmp_path, monkeypatch):
    path = tmp_path / "sources.json"
    entry = {
        "url": "https://example.com/release",
        "published_at": today_kst(),
        "title": "Demo release",
        "identity": ["Demo Company"],
        "entity": "Demo Company",
        "kind": "official",
    }
    path.write_text(json.dumps({"DEMO": [entry]}))
    monkeypatch.setattr(source, "CONFIG", path)
    return path


def test_verified_article_has_source_metadata_and_private_body(source_config, monkeypatch):
    html = f'<html><meta property="article:published_time" content="{today_kst()}"><article><p>Demo Company plans production.</p></article></html>'
    monkeypatch.setattr(source, "_html", lambda url: (html, url))
    result = source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])
    assert len(result["sources"]) == 1
    assert result["sources"][0]["published_at"] == today_kst()
    assert result["sources"][0]["source_id"]
    assert result["failed_sources"] == []


@pytest.mark.parametrize(
    "date,body",
    [
        (None, "Demo Company plans production."),
        ("9999-01-01", "Demo Company plans production."),
        (today_kst(), "Other Company plans production."),
    ],
)
def test_unverified_date_or_identity_is_a_failure(source_config, monkeypatch, date, body):
    meta = f'<meta property="article:published_time" content="{date}">' if date else ""
    monkeypatch.setattr(source, "_html", lambda url: (f"{meta}<article><p>{body}</p></article>", url))
    result = source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])
    assert result["sources"] == []
    assert len(result["failed_sources"]) == 1


def test_title_only_news_not_used_for_analysis(source_config, monkeypatch):
    monkeypatch.setattr(source, "_html", lambda url: (_ for _ in ()).throw(ValueError("Unavailable")))
    news = [
        {
            "date": today_kst(),
            "title": "Demo strong outlook",
            "content_status": "unavailable",
            "url": "https://example.com/news",
        }
    ]
    assert source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, news)["sources"] == []


def test_official_structured_publication_date_matches_article_heading(source_config, monkeypatch):
    stamp = kst_now().isoformat()
    ld = json.dumps({"@type": "NewsArticle", "headline": "Demo Company strategy", "datePublished": stamp})
    html = f'<script type="application/ld+json">{ld}</script><div class="news-detail-view"><h2 class="cmpnt-title--view">Demo Company strategy</h2><div class="cmpnt-post__content">Production expansion plan.</div></div>'
    monkeypatch.setattr(source, "_html", lambda url: (html, url))
    result = source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])
    assert len(result["sources"]) == 1
    assert result["sources"][0]["published_at"] == today_kst()
    assert "Production expansion" in result["sources"][0]["text"]


def test_related_article_time_does_not_verify_main_article(source_config, monkeypatch):
    html = f'<aside><time datetime="{today_kst()}">Related article</time></aside><article>Demo Company production plan.</article>'
    monkeypatch.setattr(source, "_html", lambda url: (html, url))
    assert source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])["sources"] == []


def test_news_source_rechecks_identity_and_window(source_config, monkeypatch):
    monkeypatch.setattr(source, "_html", lambda url: (_ for _ in ()).throw(ValueError("Unavailable")))
    base = {
        "date": today_kst(),
        "title": "Demo news",
        "content_status": "verified",
        "analysis_text": "Other Company plan.",
        "url": "https://example.com/news",
    }
    assert source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [base])["sources"] == []
    assert (
        source.collect_briefing_sources(
            {"symbol": "DEMO", "name": "Demo Company"},
            [{**base, "date": "2000-01-01", "analysis_text": "Demo Company plan."}],
        )["sources"]
        == []
    )


@pytest.fixture
def noon(monkeypatch):
    """수집 시각을 오늘 12:00 KST 로 고정한다 — 자정 경계에서 날짜 비교가 흔들리지 않게."""
    fixed = datetime.combine(date.fromisoformat(today_kst()), time(12, 0), tzinfo=KST)
    monkeypatch.setattr(source, "kst_now", lambda: fixed)
    return fixed


def _ld(fields: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(fields)}</script>'


STRATEGY_PAGE = (
    '<div class="news-detail-view"><h2 class="cmpnt-title--view">Demo Company strategy</h2>'
    '<div class="cmpnt-post__content">Production expansion plan.</div></div>'
)


@pytest.mark.parametrize(
    "decoy",
    [
        '<script type="application/ld+json">{not json</script>',
        # 관련 기사 위젯 등 다른 기사의 발표일은 이 문서의 발표일이 아니다.
        _ld({"@type": "NewsArticle", "headline": "Unrelated story", "datePublished": "2000-01-01T09:00:00+09:00"}),
        # 같은 기사지만 날짜가 없는 블록은 다음 블록을 계속 찾게 한다.
        _ld({"@type": "NewsArticle", "headline": "Demo Company strategy"}),
    ],
)
def test_structured_date_comes_only_from_a_block_matching_the_heading(source_config, monkeypatch, decoy):
    real = _ld({"@type": "NewsArticle", "headline": "Demo Company strategy", "datePublished": kst_now().isoformat()})
    monkeypatch.setattr(source, "_html", lambda url: (decoy + real + STRATEGY_PAGE, url))
    result = source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])
    assert [item["published_at"] for item in result["sources"]] == [today_kst()]
    assert result["failed_sources"] == []


def test_publication_time_later_than_collection_is_rejected(source_config, monkeypatch, noon):
    def page(hour):
        stamp = noon.replace(hour=hour).isoformat()
        return f'<meta property="article:published_time" content="{stamp}"><article><p>Demo Company plans production.</p></article>'

    profile = {"symbol": "DEMO", "name": "Demo Company"}
    monkeypatch.setattr(source, "_html", lambda url: (page(15), url))
    future = source.collect_briefing_sources(profile, [])
    assert future["sources"] == []
    assert [item["url"] for item in future["failed_sources"]] == ["https://example.com/release"]
    # 같은 날짜라도 수집 시각 이전에 발표된 문서는 그대로 쓴다.
    monkeypatch.setattr(source, "_html", lambda url: (page(11), url))
    assert [item["published_at"] for item in source.collect_briefing_sources(profile, [])["sources"]] == [today_kst()]


@pytest.mark.parametrize("age_days,kept", [(30, True), (31, False)])
def test_registered_news_older_than_the_window_is_dropped_without_failure(
    source_config, monkeypatch, noon, age_days, kept
):
    published = (noon.date() - timedelta(days=age_days)).isoformat()
    entry = json.loads(source_config.read_text())["DEMO"][0]
    entry.update(kind="news", published_at=published)
    source_config.write_text(json.dumps({"DEMO": [entry]}))
    html = f'<meta property="article:published_time" content="{published}"><article><p>Demo Company plans production.</p></article>'
    monkeypatch.setattr(source, "_html", lambda url: (html, url))
    result = source.collect_briefing_sources({"symbol": "DEMO", "name": "Demo Company"}, [])
    assert [item["published_at"] for item in result["sources"]] == ([published] if kept else [])
    assert result["failed_sources"] == []
    assert result["official_registered"] is False


def test_verified_news_body_becomes_a_cited_source(source_config, monkeypatch):
    def unexpected(url):
        raise AssertionError("an unregistered symbol fetches no official page")

    monkeypatch.setattr(source, "_html", unexpected)
    news = [
        {
            "date": today_kst(),
            "title": "Demo expands",
            "url": "https://news.google.com/rss/articles/sample",
            "article_url": "https://publisher.example/demo-expands",
            "content_status": "verified",
            "analysis_text": "Demo Company expands production.",
        },
        {
            "date": today_kst(),
            "title": "샘플 소식",
            "url": "https://publisher.example/sample",
            "content_status": "verified",
            "analysis_text": "샘플기업은 생산을 늘렸다.",
        },
    ]
    profile = {"symbol": "NEWS", "name": "Demo Company", "display_name": "샘플기업"}
    result = source.collect_briefing_sources(profile, news)
    assert [(item["url"], item["kind"], item["entity"], item["published_at"]) for item in result["sources"]] == [
        ("https://publisher.example/demo-expands", "news", "Demo Company", today_kst()),
        ("https://publisher.example/sample", "news", "Demo Company", today_kst()),
    ]
    assert (
        result["sources"][0]["source_id"] == hashlib.sha256(b"https://publisher.example/demo-expands").hexdigest()[:12]
    )
    assert result["sources"][1]["text"] == "샘플기업은 생산을 늘렸다."
    assert result["official_registered"] is False
