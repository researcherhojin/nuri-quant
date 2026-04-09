"""
매크로 뉴스 수집기 — GoogleNews RSS 기반 키워드 검색 (Phase A).

종목별 뉴스(`news.py`)와 분리. 이 collector는 시장 전체에 영향을 주는
이벤트(휴전, Fed 정책, 유가, 섹터 로테이션 등)를 수집하기 위함.

각 헤드라인은 nuri.llm.event_classifier를 통해 카테고리/감성/신뢰도로
분류된 후 macro_events 테이블에 저장된다.

Phase A는 데이터 lifecycle만 흐르게 한다 — 의사결정 로직은
Phase B/C에서 별도 PR로 통합한다 (#142, #143).

사용법:
    python -m nuri.collectors.macro_news
"""
import logging
import re
import xml.etree.ElementTree as ET  # noqa: N817 — stdlib alias
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector
from nuri.core.db import upsert_macro_events
from nuri.core.timezone import kst_now
from nuri.llm.event_classifier import classify_event

logger = logging.getLogger(__name__)

# Phase A 키워드 — 매크로 영향이 큰 이벤트만. 종목별 뉴스는 news.py가 담당.
# 새 키워드 추가는 PR로 (config 외부화는 데이터 흐름 본 후 결정).
KEYWORDS: tuple[str, ...] = (
    "Federal Reserve FOMC",
    "Iran Israel ceasefire",
    "oil price WTI crude",
    "semiconductor demand TSMC",
    "China tariff trade",
    "Korea export",
    "yen carry trade",
    "NVIDIA earnings",
    "S&P 500 sector rotation",
    "geopolitical risk",
)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
RSS_TIMEOUT_SEC = 15
MAX_ITEMS_PER_KEYWORD = 10


class MacroNewsCollector(BaseCollector):
    """GoogleNews RSS → event_classifier → macro_events 테이블."""

    def __init__(self, *, use_llm: bool = True):
        super().__init__("macro_news")
        # use_llm=False는 테스트/CI용 (Ollama 없이 regex 폴백만)
        self.use_llm = use_llm

    def collect(self, **kwargs) -> list[dict]:
        """모든 키워드에 대해 RSS 수집 + 분류."""
        records: list[dict] = []
        for keyword in KEYWORDS:
            try:
                items = self._fetch_rss(keyword)
            except Exception as e:  # noqa: BLE001 — 한 키워드 실패가 전체를 막지 않게
                self.logger.debug("RSS fetch 실패 (%s): %s", keyword, e)
                continue

            for item in items:
                classified = classify_event(item["headline"], use_llm=self.use_llm)
                records.append(
                    {
                        "published_at": item["published_at"],
                        "source": item["source"],
                        "query_keyword": keyword,
                        "headline": item["headline"],
                        "url": item["url"],
                        "category": classified["category"],
                        "sentiment": classified["sentiment"],
                        "confidence": classified["confidence"],
                        "regime_hint": classified["regime_hint"],
                        "raw_json": None,
                    }
                )

        self.logger.info(
            "[%s] %d개 키워드 → %d개 raw items 수집",
            self.name,
            len(KEYWORDS),
            len(records),
        )
        return records

    def save(self, data: list[dict]) -> int:
        """upsert_macro_events 호출 — URL 기준 dedup."""
        return upsert_macro_events(data)

    def _fetch_rss(self, keyword: str) -> list[dict]:
        """단일 키워드의 RSS feed 파싱 → 표준 dict 리스트."""
        params = {
            "q": keyword,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        # quote_plus는 RSS query string에서 더 안정적 (& 등 escape)
        url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(keyword)}&hl=en-US&gl=US&ceid=US:en"
        del params  # 명시: 디버그용으로만 남김

        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=RSS_TIMEOUT_SEC)
        resp.raise_for_status()
        return _parse_rss_items(resp.content)[:MAX_ITEMS_PER_KEYWORD]


def _parse_rss_items(xml_bytes: bytes) -> list[dict]:
    """RSS 2.0 XML → list of {published_at, headline, url, source}.

    GoogleNews RSS 포맷:
        <channel>
            <item>
                <title>Headline — Source</title>
                <link>https://news.google.com/...</link>
                <pubDate>Wed, 09 Apr 2026 12:34:56 GMT</pubDate>
                <source url="...">Source Name</source>
            </item>
        </channel>
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.debug("RSS XML 파싱 실패: %s", e)
        return []

    items = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        source_el = item.find("source")

        if title_el is None or link_el is None or not link_el.text:
            continue

        headline = (title_el.text or "").strip()
        url = link_el.text.strip()
        if not headline or not url:
            continue

        # GoogleNews는 title을 "Headline - Source" 형식으로 줌. source 분리 시도.
        source_name = ""
        if source_el is not None and source_el.text:
            source_name = source_el.text.strip()
            # title에서 trailing source 제거 (있을 때)
            headline = re.sub(rf"\s*[-—]\s*{re.escape(source_name)}\s*$", "", headline)
        else:
            source_name = "GoogleNews"

        published_at = _parse_pubdate(pubdate_el.text if pubdate_el is not None else None)

        items.append(
            {
                "headline": headline,
                "url": url,
                "published_at": published_at,
                "source": source_name,
            }
        )
    return items


def _parse_pubdate(raw: str | None) -> str:
    """RFC 822 pubDate → ISO 8601 string. 실패 시 현재 KST."""
    if not raw:
        return kst_now().isoformat(timespec="seconds")
    try:
        dt = parsedate_to_datetime(raw)
        return dt.isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return kst_now().isoformat(timespec="seconds")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = MacroNewsCollector()
    collector.run()
