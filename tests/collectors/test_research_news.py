"""뉴스 본문 확인: 제목 추정·동명 기사·사설 주소를 배제한다."""

import json

import pytest

from nuri.collectors import research_news as module

BODY = (
    "Demo Company reported revenue growth and earnings this quarter. "
    + "The report discusses operating results and financing conditions in detail. " * 5
)


def test_extracts_body_and_topics_but_not_navigation():
    parsed = module.parse_article(
        f"<nav>Demo Company launches</nav><article><p>{BODY}</p></article>", "Demo Company", "DEMO"
    )
    assert parsed["excerpt"].startswith("Demo Company reported revenue")
    assert len(parsed["excerpt"].split()) <= 24
    assert parsed["topics"] == ["earnings", "capital"]


def test_structured_body_and_excerpt_limit():
    body = "Demo Company " + "operates " * 50 + "."
    html = '<script type="application/ld+json">' + json.dumps({"@graph": [{"articleBody": body}]}) + "</script>"
    assert len(module.parse_article(html, "Demo Company", "DEMO")["excerpt"].split()) == 24


@pytest.mark.parametrize(
    "html",
    [
        f"<h1>Demo Company</h1><article><p>{BODY.replace('Demo Company', 'Other Company')}</p></article>",
        "<h1>Demo Company</h1><p>Paywall</p>",
        "<article><p>Demo Company brief headline.</p></article>",
    ],
)
def test_headline_or_unrelated_body_is_not_a_summary(html):
    assert module.parse_article(html, "Demo Company", "DEMO") is None


def test_nasa_agency_is_not_etf():
    assert (
        module.parse_article(
            f"<article><p>{BODY.replace('Demo Company', 'NASA')}</p></article>", "Tema Space Innovators ETF", "NASA"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/report",
        "https://127.0.0.1/report",
        "https://user:secret@example.com",
        "https://example.com:8001",
    ],
)
def test_private_or_unsupported_urls_are_not_fetched(url, monkeypatch):
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))])
    assert module._public_url(url) is False


def test_failed_body_fetch_is_explicit_and_extra_articles_remain_unchecked(monkeypatch):
    def unavailable(url):
        raise ValueError("Unavailable")

    monkeypatch.setattr(module, "_publisher_url", unavailable)
    articles = [{"title": f"Report {index}", "url": "https://example.com/news"} for index in range(4)]
    result = module.enrich_news(articles, "Demo Company", "DEMO")
    assert [item["content_status"] for item in result] == ["unavailable"] * 3 + ["not_checked"]
    assert all("excerpt" not in item for item in result)


def test_verified_body_keeps_publisher_url_and_checked_time(monkeypatch):
    monkeypatch.setattr(module, "_publisher_url", lambda url: "https://example.com/article")
    monkeypatch.setattr(module, "_html", lambda url: (f"<article><p>{BODY}</p></article>", url))
    result = module.enrich_news([{"url": "https://news.google.com/rss/articles/sample"}], "Demo Company", "DEMO")[0]
    assert result["content_status"] == "verified"
    assert result["article_url"] == "https://example.com/article"
    assert result["content_checked_at"]


def test_korean_alias_and_grammar_are_read_without_confusing_another_company():
    text = (
        "샘플기업은 매출과 영업이익이 증가했다고 발표했다. "
        + "생산 및 판매량과 계약 내용에 대한 상세한 설명을 제공하면서 관련 내용을 밝혔다. " * 6
    )
    result = module.parse_article(f"<article><p>{text}</p></article>", ["Demo Company", "샘플기업"], "000001.KS")
    assert result["topics"] == ["earnings", "operations"]
    assert (
        module.parse_article(
            f"<article><p>{text.replace('샘플기업은', '샘플기업증권은')}</p></article>",
            ["Demo Company", "샘플기업"],
            "000001.KS",
        )
        is None
    )
