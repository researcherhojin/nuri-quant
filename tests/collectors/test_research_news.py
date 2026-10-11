"""뉴스 본문 확인: 제목 추정·동명 기사·사설 주소를 배제한다."""

import json
import socket

import pytest
import requests

from nuri.collectors import research_news as module

BODY = (
    "Demo Company reported revenue growth and earnings this quarter. "
    + "The report discusses operating results and financing conditions in detail. " * 5
)
# 공개 주소로 판정되는 임의의 전역 IP. 실제 접속은 없다 (getaddrinfo 스텁의 반환값일 뿐).
PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    """requests 응답 대역 — `_html` 은 컨텍스트 매니저·스트리밍으로 읽는다."""

    def __init__(self, *, headers=None, chunks=(), encoding=None, redirect=False, text=""):
        self.is_redirect = redirect
        self.headers = headers or {}
        self.encoding = encoding
        self.text = text
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        yield from self._chunks


def _resolve(monkeypatch, addresses: dict[str, str]) -> list[str]:
    """DNS 스텁. 조회한 호스트를 순서대로 기록한다 — 미등록 호스트는 해석 실패."""
    looked_up = []

    def getaddrinfo(host, port, **kwargs):
        looked_up.append(host)
        if host not in addresses:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], port))]

    monkeypatch.setattr(module.socket, "getaddrinfo", getaddrinfo)
    return looked_up


def _serve(monkeypatch, *responses) -> list[tuple[str, dict]]:
    """requests.get 이 응답을 순서대로 돌려준다. 요청 URL·인자를 기록한다."""
    queue = iter(responses)
    requested = []

    def get(url, **kwargs):
        requested.append((url, kwargs))
        return next(queue)

    monkeypatch.setattr(requests, "get", get)
    return requested


def _forbidden(*args, **kwargs):
    raise AssertionError("network must not be reached")


def test_extracts_body_and_topics_but_not_navigation():
    parsed = module.parse_article(
        f"<nav>Demo Company launches</nav><article><p>{BODY}</p></article>", "Demo Company", "DEMO"
    )
    assert parsed is not None
    assert parsed["excerpt"].startswith("Demo Company reported revenue")
    assert len(parsed["excerpt"].split()) <= 24
    assert parsed["topics"] == ["earnings", "capital"]


def test_structured_body_and_excerpt_limit():
    body = "Demo Company " + "operates " * 50 + "."
    html = '<script type="application/ld+json">' + json.dumps({"@graph": [{"articleBody": body}]}) + "</script>"
    parsed = module.parse_article(html, "Demo Company", "DEMO")
    assert parsed is not None
    assert len(parsed["excerpt"].split()) == 24


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
    assert result is not None
    assert result["topics"] == ["earnings", "operations"]
    assert (
        module.parse_article(
            f"<article><p>{text.replace('샘플기업은', '샘플기업증권은')}</p></article>",
            ["Demo Company", "샘플기업"],
            "000001.KS",
        )
        is None
    )


def test_unresolvable_host_is_not_treated_as_public(monkeypatch):
    _resolve(monkeypatch, {})
    assert module._public_url("https://publisher.example/story") is False
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    assert module._public_url("https://publisher.example/story") is True


def test_html_rechecks_every_redirect_hop_and_decodes_as_utf8_by_default(monkeypatch):
    looked_up = _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    requested = _serve(
        monkeypatch,
        FakeResponse(redirect=True, headers={"Location": "/story/final"}),
        FakeResponse(headers={"Content-Type": "text/html; charset=utf-8"}, chunks=["기사 본문".encode()]),
    )
    html, final_url = module._html("https://publisher.example/story/start")
    assert html == "기사 본문"
    assert final_url == "https://publisher.example/story/final"
    assert [url for url, _ in requested] == [
        "https://publisher.example/story/start",
        "https://publisher.example/story/final",
    ]
    # requests 의 자동 redirect 를 끄고 직접 따라가야 hop 마다 주소 검사가 걸린다.
    assert all(kwargs == {"timeout": 5, "allow_redirects": False, "stream": True} for _, kwargs in requested)
    assert looked_up == ["publisher.example", "publisher.example"]


def test_redirect_into_a_private_network_is_refused_before_fetching(monkeypatch):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP, "internal.example": "10.0.0.5"})
    requested = _serve(monkeypatch, FakeResponse(redirect=True, headers={"Location": "https://internal.example/admin"}))
    with pytest.raises(ValueError, match="Not a public publisher URL"):
        module._html("https://publisher.example/story")
    assert [url for url, _ in requested] == ["https://publisher.example/story"]


def test_non_html_response_is_not_an_article(monkeypatch):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    _serve(monkeypatch, FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=[b"%PDF"]))
    with pytest.raises(ValueError, match="Not an article page"):
        module._html("https://publisher.example/report.pdf")


def test_article_page_size_is_capped_at_two_megabytes(monkeypatch):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    html_type = {"Content-Type": "text/html"}
    _serve(
        monkeypatch,
        FakeResponse(headers=html_type, chunks=[b"a" * 1_000_000, b"a" * 1_000_000]),
        FakeResponse(headers=html_type, chunks=[b"a" * 1_000_000, b"a" * 1_000_000, b"a"]),
    )
    assert len(module._html("https://publisher.example/at-limit")[0]) == 2_000_000
    with pytest.raises(ValueError, match="too large"):
        module._html("https://publisher.example/over-limit")


def test_redirect_chain_is_bounded(monkeypatch):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    requested = _serve(
        monkeypatch, *[FakeResponse(redirect=True, headers={"Location": f"/hop/{index}"}) for index in range(5)]
    )
    with pytest.raises(ValueError, match="Too many redirects"):
        module._html("https://publisher.example/start")
    assert len(requested) == 4


def test_publisher_link_is_used_as_is_without_network(monkeypatch):
    monkeypatch.setattr(module, "_html", _forbidden)
    monkeypatch.setattr(requests, "post", _forbidden)
    assert module._publisher_url("https://publisher.example/story?id=1") == "https://publisher.example/story?id=1"


@pytest.mark.parametrize(
    "url", ["https://news.google.com/rss/articles/bad.id", "https://news.google.com/rss/articles/"]
)
def test_malformed_google_article_identifier_is_refused_without_network(monkeypatch, url):
    monkeypatch.setattr(module, "_html", _forbidden)
    with pytest.raises(ValueError, match="Invalid article identifier"):
        module._publisher_url(url)


def test_google_page_without_publisher_signature_is_unavailable(monkeypatch):
    fetched = []
    monkeypatch.setattr(module, "_html", lambda url: (fetched.append(url), ("<p>Consent</p>", url))[1])
    monkeypatch.setattr(requests, "post", _forbidden)
    with pytest.raises(ValueError, match="Publisher URL unavailable"):
        module._publisher_url("https://news.google.com/rss/articles/CBMiSample?oc=5")
    assert fetched == ["https://news.google.com/articles/CBMiSample"]


def _batchexecute(monkeypatch, decoded_url: str) -> list[tuple[str, dict]]:
    """Google 중계 페이지 서명 + batchexecute 응답 스텁. POST 인자를 기록한다."""
    signed = '<div data-n-a-sg="SIG123" data-n-a-ts="1767225600"></div>'
    monkeypatch.setattr(module, "_html", lambda url: (signed, url))
    rows = [
        ["di", 42],
        ["wrb.fr", "OtherRpc", "[]"],
        ["wrb.fr", "Fbv4je", json.dumps(["garturlres", decoded_url, 1])],
    ]
    posted = []

    def post(url, **kwargs):
        posted.append((url, kwargs))
        return FakeResponse(text=")]}'\n\n" + json.dumps(rows) + "\n")

    monkeypatch.setattr(requests, "post", post)
    return posted


def test_google_link_resolves_to_the_signed_publisher_url(monkeypatch):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP})
    posted = _batchexecute(monkeypatch, "https://publisher.example/story")
    assert module._publisher_url("https://news.google.com/rss/articles/CBMiSample") == "https://publisher.example/story"
    ((url, kwargs),) = posted
    assert url == "https://news.google.com/_/DotsSplashUi/data/batchexecute"
    assert kwargs["timeout"] == 5
    ((rpc, arguments),) = json.loads(kwargs["data"]["f.req"])[0]
    assert rpc == "Fbv4je"
    request = json.loads(arguments)
    assert request[0] == "garturlreq"
    assert request[2:] == ["CBMiSample", 1767225600, "SIG123"]


@pytest.mark.parametrize("decoded", ["http://publisher.example/story", "https://internal.example/story"])
def test_decoded_destination_must_itself_be_public(monkeypatch, decoded):
    _resolve(monkeypatch, {"publisher.example": PUBLIC_IP, "internal.example": "10.0.0.5"})
    _batchexecute(monkeypatch, decoded)
    with pytest.raises(ValueError, match="Publisher URL unavailable"):
        module._publisher_url("https://news.google.com/rss/articles/CBMiSample")


@pytest.mark.parametrize(
    "decoy",
    [
        "{not json",
        # 본문 없는 메타데이터 블록은 다음 블록을 계속 찾게 한다.
        json.dumps({"@type": "NewsArticle", "headline": "Demo Company"}),
    ],
)
def test_structured_body_search_skips_malformed_or_bodiless_blocks(decoy):
    html = (
        f'<script type="application/ld+json">{decoy}</script>'
        f'<script type="application/ld+json">{json.dumps({"articleBody": BODY})}</script>'
        "<article><p>Unrelated page chrome.</p></article>"
    )
    parsed = module.parse_article(html, "Demo Company", "DEMO")
    assert parsed is not None
    assert parsed["excerpt"].startswith("Demo Company reported revenue")


def test_record_without_link_stays_unchecked_without_fetching(monkeypatch):
    monkeypatch.setattr(module, "_publisher_url", _forbidden)
    assert module.enrich_news([{"title": "No link"}], "Demo Company", "DEMO") == [
        {"title": "No link", "content_status": "not_checked"}
    ]


def test_fetched_page_about_another_company_is_unavailable_not_verified(monkeypatch):
    monkeypatch.setattr(module, "_publisher_url", lambda url: "https://publisher.example/story")
    other = BODY.replace("Demo Company", "Other Company")
    monkeypatch.setattr(module, "_html", lambda url: (f"<article><p>{other}</p></article>", url))
    result = module.enrich_news([{"url": "https://news.google.com/rss/articles/x"}], "Demo Company", "DEMO")[0]
    assert result["content_status"] == "unavailable"
    assert result["content_checked_at"]
    assert "article_url" not in result
    assert "excerpt" not in result
