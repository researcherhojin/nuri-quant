"""Yahoo 기사 파싱 — 원본 `tradingagents/dataflows/vendors/yahoo/news.py` (e8f5503) 의
`_extract_article_data` 와 `_search_news` 의 태그 필터.

바꾼 점 (Modified):
- 발행 시각을 aware datetime 이 아니라 UTC 문자열("YYYY-MM-DD HH:MM:SS")로 돌려준다 — 근거 묶음 · `macro_events`
  와 같은 형식.
- 시간대 없는 ISO 시각은 None 이다. 원본은 naive datetime 을 그대로 두는데, 그러면 비교 시 기기 시간대로
  해석될 수 있다(원본 #1126 이 epoch 쪽에서 고친 것과 같은 축).
- `relatedTickers` 대조를 원본처럼 대문자로 하되, 기사 dict 가 아닌 항목은 버린다.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, Optional


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def extract_article_data(article: dict[str, Any]) -> dict[str, Any]:
    """Extract article data from yfinance news format (handles nested 'content' structure).

    Yahoo sends some fields as null rather than leaving them out, so each falls
    back to its default on a null as well as on a missing key (upstream #1458).
    """
    content = article.get("content")
    if isinstance(content, dict):
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        pub_date_str = content.get("pubDate") or ""
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                parsed = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                pub_date = _utc(parsed) if parsed.tzinfo else None
        return {
            "title": content.get("title") or "No title",
            "summary": content.get("summary") or "",
            "publisher": (content.get("provider") or {}).get("displayName") or "Unknown",
            "link": url_obj.get("url") or "",
            "pub_date": pub_date,
        }
    # Fallback for flat structure. Parse the epoch publish time so flat
    # articles are date-filterable too (otherwise they bypass the
    # historical window and leak future news, upstream #992/#1007).
    pub_date = None
    ts = article.get("providerPublishTime")
    if ts:
        # Epoch seconds are UTC; parse them as UTC-aware so filtering does
        # not shift with the host timezone (upstream #1126).
        with contextlib.suppress(ValueError, OSError, TypeError, OverflowError):
            pub_date = _utc(datetime.fromtimestamp(ts, tz=timezone.utc))
    return {
        "title": article.get("title") or "No title",
        "summary": article.get("summary") or "",
        "publisher": article.get("publisher") or "Unknown",
        "link": article.get("link") or "",
        "pub_date": pub_date,
    }


def tagged(articles: list[Any], symbol: str) -> list[dict[str, Any]]:
    """Search 결과 중 `symbol` 이 태그된 기사 — 검색어 매칭이라 느슨하게 태그된 기사가 섞인다."""
    canonical = symbol.upper()
    return [
        a
        for a in articles
        if isinstance(a, dict) and canonical in (str(t).upper() for t in a.get("relatedTickers") or [])
    ]


def answered(news: Optional[list[Any]], quotes: Optional[list[Any]], symbol: str) -> bool:
    """Yahoo 가 답했는가 — 원본 `_search_news` 의 `knows or bool(search.news)`: 같은 심볼의 종목 결과가 있거나
    기사가 하나라도 돌아왔으면 답한 것이다."""
    canonical = symbol.upper()
    knows = any(isinstance(q, dict) and (q.get("symbol") or "").upper() == canonical for q in quotes or [])
    return knows or bool(news)
