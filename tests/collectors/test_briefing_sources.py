"""수집 실패·미래 자료와 날짜 없는 공식 문서를 근거로 위장하지 않는다."""

import json

import pytest

from nuri.collectors import briefing_sources as source
from nuri.core.timezone import kst_now, today_kst


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
