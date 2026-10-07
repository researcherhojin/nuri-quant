"""공개 기사 본문 확인과 짧은 발췌. 제목으로 내용을 추정하지 않는다.

cspell:words garturlreq garturlres itemprop caas Tema newsct
"""

import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from nuri.core.timezone import kst_now


def _public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.port not in {None, 443}:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError):
        return False


def _html(url: str) -> tuple[str, str]:
    import requests

    # 기사 링크와 모든 redirect를 확인한다. HTML 크기도 제한한다.
    for _ in range(4):
        if not _public_url(url):
            raise ValueError("Not a public publisher URL")
        with requests.get(url, timeout=5, allow_redirects=False, stream=True) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", ""):
                raise ValueError("Not an article page")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("Article page too large")
                chunks.append(chunk)
            return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"), url
    raise ValueError("Too many redirects")


def _publisher_url(url: str) -> str:
    """Google 중계 링크를 발행사 링크로 해석한다. 내부 프로토콜 변경은 실패로 드러낸다.

    Protocol reference: https://gist.github.com/huksley/bc3cb046157a99cd9d1517b32f91a99e
    """
    import requests
    from bs4 import BeautifulSoup

    parsed = urlparse(url)
    if parsed.hostname != "news.google.com":
        return url
    article_id = parsed.path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", article_id):
        raise ValueError("Invalid article identifier")
    html, _ = _html(f"https://news.google.com/articles/{article_id}")
    node = BeautifulSoup(html, "html.parser").select_one("[data-n-a-sg][data-n-a-ts]")
    if not node:
        raise ValueError("Publisher URL unavailable")
    context = [
        ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
        "X",
        "X",
        1,
        [1, 1, 1],
        1,
        1,
        None,
        0,
        0,
        None,
        0,
    ]
    timestamp = node.get("data-n-a-ts")
    signature = node.get("data-n-a-sg")
    if not isinstance(timestamp, str) or not isinstance(signature, str):
        raise ValueError("Invalid publisher URL attributes")
    arguments = ["garturlreq", context, article_id, int(timestamp), signature]
    response = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data={"f.req": json.dumps([[["Fbv4je", json.dumps(arguments)]]])},
        timeout=5,
    )
    response.raise_for_status()
    for line in response.text.splitlines():
        if not line.startswith("[["):
            continue
        for row in json.loads(line):
            if len(row) > 2 and row[0] == "wrb.fr" and row[1] == "Fbv4je":
                result = json.loads(row[2])
                if result[0] == "garturlres" and _public_url(result[1]):
                    return result[1]
    raise ValueError("Publisher URL unavailable")


def parse_article(html: str, identity: str | list[str], symbol: str, *, include_body: bool = False) -> dict | None:
    """본문에 종목 신원이 확인되는 경우에만 최대 24단어를 보관한다."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script:not([type='application/ld+json']), style, nav, footer, aside"):
        node.decompose()
    text = ""

    def body(node):
        if isinstance(node, dict):
            if isinstance(node.get("articleBody"), str):
                return node["articleBody"]
            return next((found for value in node.values() if (found := body(value))), "")
        if isinstance(node, list):
            return next((found for value in node if (found := body(value))), "")
        return ""

    for script in soup.select("script[type='application/ld+json']"):
        try:
            text = body(json.loads(script.string or ""))
        except (ValueError, TypeError):
            continue
        if text:
            break
    if not text:
        article = soup.select_one(
            "article, [itemprop='articleBody'], .caas-body, #articleBodyContents, #dic_area, .article-body, .newsct_article"
        )
        text = " ".join(p.get_text(" ", strip=True) for p in article.select("p")) if article else ""
    text = " ".join(text.split())
    markers = [name.casefold() for name in ([identity] if isinstance(identity, str) else identity)]
    # NASA 정부기관 기사 등 동명 검색 결과는 확인된 상품명이 본문에 있어야 한다.
    if symbol == "NASA":
        markers = [*markers, "tema space innovators"]
    sentences = re.split(r"(?<=[.!?])\s+", text)

    def matches(sentence):
        for marker in markers:
            pattern = (
                re.escape(marker) + r"(?=$|[\s.,·()]|은|는|가|의|를|와|에서)"
                if re.search(r"[가-힣]", marker)
                else r"(?<!\w)" + re.escape(marker) + r"(?!\w)"
            )
            if re.search(pattern, sentence.casefold()):
                return True
        return False

    relevant = next(
        (
            sentence
            for sentence in sentences
            if matches(sentence)
            or (
                symbol != "NASA"
                and len(symbol) >= 3
                and re.search(r"(?<!\w)" + re.escape(symbol) + r"(?!\w)", sentence)
            )
        ),
        None,
    )
    if not relevant or len(text.split()) < 40:
        return None
    words = relevant.split()
    excerpt = " ".join(words[:24]) + ("…" if len(words) > 24 else "")
    topics = [
        key
        for key, pattern in [
            ("earnings", r"\b(earnings|revenue|profit)\b"),
            ("holdings", r"\b(holding|holdings|portfolio|spacex)\b"),
            ("capital", r"\b(offering|financing|debt|funding)\b"),
            ("operations", r"\b(launch|contract|satellite|production)\b"),
            ("earnings", r"실적|매출|영업이익|순이익"),
            ("capital", r"자금 조달|유상증자|부채|대출"),
            ("operations", r"생산|계약|판매량|출시|공장"),
        ]
        if re.search(pattern, text, re.I)
    ]
    result = {"excerpt": excerpt, "topics": list(dict.fromkeys(topics))}
    if include_body:
        result["analysis_text"] = text[:18000]
    return result


def enrich_news(records: list[dict], identity: str | list[str], symbol: str) -> list[dict]:
    def enrich(item):
        result = {**item, "content_status": "not_checked"}
        if not item.get("url"):
            return result
        try:
            url = _publisher_url(item["url"])
            html, final_url = _html(url)
            parsed = parse_article(html, identity, symbol, include_body=True)
            result.update(content_checked_at=kst_now().isoformat(), content_status="unavailable")
            if parsed:
                result.update(parsed, content_status="verified", article_url=final_url)
        except Exception:
            result.update(content_checked_at=kst_now().isoformat(), content_status="unavailable")
        return result

    # 첫 세 기사는 동시 조회해 수집 대기시간을 제한한다. 나머지는 제목 검색 결과로 남긴다.
    with ThreadPoolExecutor(max_workers=3) as pool:
        leading = list(pool.map(enrich, records[:3]))
    return leading + [{**item, "content_status": "not_checked"} for item in records[3:]]
