"""브리핑 근거 수집. 원문은 내부 분석에만 쓰고 공개 응답에서는 제거한다.

cspell:words cmpnt itemprop
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from nuri.collectors.research_news import _html
from nuri.core.timezone import kst_now

CONFIG = Path(__file__).resolve().parents[2] / "config" / "research_sources.json"


def article_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, nav, footer, header, aside"):
        node.decompose()
    blocks = soup.select(".news-detail-view .cmpnt-post__content")
    if blocks:
        heading = soup.select_one(".news-detail-view .cmpnt-title--view")
        title = heading.get_text(" ", strip=True) if heading else ""
        return (title + "\n" + "\n".join(block.get_text(" ", strip=True) for block in blocks))[:36000]
    article = soup.select_one("article, [itemprop='articleBody'], main, .news-detail, .newsroom-detail")
    return " ".join((article or soup).stripped_strings)[:36000]


def collect_briefing_sources(profile: dict, news: list[dict]) -> dict:
    """설정된 공식 문서와 본문이 확인된 뉴스를 묶는다. 미등록은 명시적 결손이다."""
    config = json.loads(CONFIG.read_text())
    now = kst_now().isoformat()
    sources, failures = [], []
    for item in config.get(profile["symbol"], []):
        try:
            html, url = _html(item["url"])
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            date_node = soup.select_one(
                'meta[property="article:published_time"], meta[name="date"], article time[datetime]'
            )
            raw_date = (date_node.get("content") or date_node.get("datetime")) if date_node else None
            if not raw_date:
                heading_text = " ".join(node.get_text(" ", strip=True) for node in soup.select("h1, h2"))
                for node in soup.select('script[type="application/ld+json"]'):
                    try:
                        article = json.loads(node.string or "")
                        if (
                            isinstance(article, dict)
                            and article.get("@type") in {"NewsArticle", "Article"}
                            and article.get("headline")
                            and article["headline"] in heading_text
                        ):
                            raw_date = article.get("datePublished")
                            if raw_date:
                                break
                    except (ValueError, TypeError):
                        continue
            # 등록 시 확인된 발표일도 원문에 나타나야 한다. 발표일 없는 정책은 시점 분석에서 제외.
            stamp = str(raw_date or item.get("published_at", ""))
            parsed_date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            date = (parsed_date.astimezone(kst_now().tzinfo) if parsed_date.tzinfo else parsed_date).date().isoformat()
            if raw_date and item.get("published_at") and date != item["published_at"]:
                raise ValueError("Publication dates disagree")
            if parsed_date.tzinfo and parsed_date > kst_now():
                raise ValueError("Future publication timestamp")
            body = article_text(html)
            date_tokens = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", body)
            known = date in date_tokens or (item.get("date_marker") and item["date_marker"] in body)
            if not date or date > now[:10] or (not raw_date and not known):
                raise ValueError("Publication date not verified")
            if not any(alias.casefold() in body.casefold() for alias in item["identity"]):
                raise ValueError("Issuer identity not verified")
            if item["kind"] == "news" and date < (kst_now().date() - timedelta(days=30)).isoformat():
                continue
            sources.append({**item, "url": url, "published_at": date, "text": body, "collected_at": now})
        except Exception:
            failures.append({"url": item["url"], "reason": "본문·발표일·발행 주체를 확인하지 못했습니다."})
    for item in news:
        aliases = [name for name in (profile.get("name"), profile.get("display_name")) if name]
        body = item.get("analysis_text", "")
        identified = any(
            re.search(r"(?<!\w)" + re.escape(name) + r"(?=$|[\s.,·()]|은|는|가|의|를|와|에서)", body, re.I)
            for name in aliases
        )
        window_start = (kst_now().date() - timedelta(days=30)).isoformat()
        if (
            item.get("content_status") == "verified"
            and body
            and identified
            and window_start <= item["date"] <= now[:10]
        ):
            sources.append(
                {
                    "url": item.get("article_url") or item["url"],
                    "title": item["title"],
                    "published_at": item["date"],
                    "kind": "news",
                    "entity": profile["name"],
                    "text": item["analysis_text"],
                    "collected_at": now,
                }
            )
    for item in sources:
        item["source_id"] = hashlib.sha256(item["url"].encode()).hexdigest()[:12]
    return {
        "sources": sources,
        "failed_sources": failures,
        "official_registered": any(item["kind"] == "official" for item in config.get(profile["symbol"], [])),
    }
