# pyright: reportAttributeAccessIssue=false
"""
뉴스 수집기 — yfinance `Ticker.news` 직접 호출.

openbb 1차 경로(news.company)는 #1477 로 제거 — 상류 bug(#274) 이후로도 실제 수집은 늘 이 경로였다.

사용법:
    python -m nuri.collectors.news
"""

import logging

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_news


class NewsCollector(BaseCollector):
    """yfinance `Ticker.news` 로 종목별 뉴스 수집."""

    def __init__(self):
        super().__init__("news")

    def collect(self, source: str = "portfolio", **kwargs) -> list[dict]:
        """뉴스 수집. source='universe' 시 universe.yaml 전체."""
        from tqdm import tqdm

        tickers = self._get_tickers(market="us", source=source)
        records = []
        failed: list[str] = []

        if not tickers:
            return []

        self.logger.info(f"뉴스 수집 대상: {len(tickers)} 종목 (source={source})")
        iterator = tqdm(tickers, desc=f"  news [{source}]", unit="tk", disable=len(tickers) < 20)

        for ticker in iterator:
            items = self._fetch_ticker_news(ticker)
            if not items:
                failed.append(ticker)
                continue
            records.extend(items)

        if len(tickers) >= 20:
            sample = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
            self.logger.info(
                "📊 뉴스: %d 건 수집 / ❌ %d 종목 실패 (총 %d) — failed: %s",
                len(records),
                len(failed),
                len(tickers),
                sample or "없음",
            )
        else:
            self.logger.info(f"뉴스 {len(records)}건 수집")
        return records

    #: 종목당 요청 기사 수. Search 는 검색어 매칭이라 아래에서 `relatedTickers` 로 다시 거른다.
    NEWS_COUNT = 20

    def _fetch_ticker_news(self, ticker: str) -> list[dict]:
        """단일 종목 뉴스 (yfinance Search).

        `Ticker.news` 는 2026-10-02 부터 **예외 없이 빈 목록**을 준다 (#1921, yfinance 1.7.0 고정 상태에서
        Yahoo 쪽 변화) — 수집기는 그걸 "기사 없음" 으로 받아 3주 동안 매시간 0행을 `finished` 로 남겼다.
        `Search(ticker).news` 는 같은 flat 형식으로 기사를 주지만 검색어 매칭이라 다른 종목 기사가 섞인다.
        이 테이블은 SELL 촉매 게이트(`core/catalyst.has_recent_catalyst`)가 읽으므로, `relatedTickers` 에
        그 종목이 **있는** 기사만 남긴다 — 필드가 없는 기사는 관련성을 알 수 없어 버린다.
        """
        try:
            import yfinance as yf

            raw = yf.Search(ticker, news_count=self.NEWS_COUNT).news or []
            related = [i for i in raw if isinstance(i, dict) and ticker in (i.get("relatedTickers") or [])]
            return self._parse_yfinance_news(related, ticker)
        except Exception as e:
            self.logger.debug(f"{ticker}: yfinance news 폴백 실패 — {e}")
            return []

    def _parse_yfinance_news(self, raw: list, ticker: str) -> list[dict]:
        """yfinance Ticker.news → news record list.

        yfinance 는 두 payload format 을 혼재 사용:
        - 구형 (flat): {"title", "link", "publisher", "providerPublishTime": epoch}
        - 신형 (nested): {"id", "content": {"title", "canonicalUrl": {"url"}, "provider": {"displayName"}, "pubDate": ISO}}
        버전/제공자에 따라 달라지므로 둘 다 처리한다.

        날짜는 모두 KST 기준으로 정규화 (프로젝트 표준: `today_kst()` — §4.3).
        """
        from datetime import datetime

        from nuri.core.timezone import KST, today_kst

        records: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if isinstance(content, dict):
                # 신형 nested
                title = content.get("title") or ""
                url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else ""
                provider_obj = content.get("provider") or {}
                source = provider_obj.get("displayName", "") if isinstance(provider_obj, dict) else ""

                pub_date = content.get("pubDate") or content.get("displayTime") or ""
                date = self._iso_utc_to_kst_date(pub_date) or today_kst()
            else:
                # 구형 flat
                title = item.get("title") or ""
                url = item.get("link") or ""
                source = item.get("publisher") or ""

                epoch = item.get("providerPublishTime")
                if isinstance(epoch, (int, float)) and epoch > 0:
                    # epoch 는 UTC 기준 → KST 전환 후 날짜 추출
                    date = datetime.fromtimestamp(int(epoch), tz=KST).strftime("%Y-%m-%d")
                else:
                    date = today_kst()

            if not title or not url:
                continue

            records.append(
                {
                    "ticker": ticker,
                    "date": date,
                    "title": str(title)[:500],
                    "url": str(url)[:1000],
                    "source": str(source)[:100],
                    "sentiment": None,
                }
            )
        return records

    @staticmethod
    def _iso_utc_to_kst_date(pub_date: str) -> str | None:
        """ISO 8601 UTC ("2026-04-17T14:42:20Z") → KST "YYYY-MM-DD".

        실패 시 None 반환 — 호출자가 `today_kst()` fallback.
        """
        if not isinstance(pub_date, str) or len(pub_date) < 10:
            return None
        try:
            from datetime import datetime

            from nuri.core.timezone import KST

            # Python fromisoformat 은 "Z" suffix 를 3.11+ 부터 인식, 안전을 위해 명시 치환
            iso = pub_date.rstrip("Z")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                from datetime import timezone as _tz

                dt = dt.replace(tzinfo=_tz.utc)
            return dt.astimezone(KST).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def save(self, data: list[dict]) -> int:
        """뉴스를 DB에 저장 (URL 중복 자동 제거)."""
        return upsert_news(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = NewsCollector()
    collector.run()
