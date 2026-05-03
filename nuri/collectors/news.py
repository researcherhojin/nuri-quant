# pyright: reportAttributeAccessIssue=false
"""
뉴스 수집기 — OpenBB Platform primary + yfinance direct fallback.

(OpenBB BaseApp 동적 attribute (news 등) stub 부재 — runtime 정상.)

OpenBB 상류 bug (#274, upstream OpenBB-finance/OpenBB #7379/#7460) 로 news.company import
가 깨진 상태 — yfinance `Ticker.news` 로 자동 fallback 하여 수집 지속. upstream release
이 수정되면 OpenBB 경로가 자연 복원됨 (stock.py 와 동일 패턴).

사용법:
    python -m nuri.collectors.news
"""

import logging

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_news


class NewsCollector(BaseCollector):
    """OpenBB primary + yfinance fallback 으로 종목별 뉴스 수집."""

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

    def _fetch_ticker_news(self, ticker: str) -> list[dict]:
        """단일 종목 뉴스. OpenBB → yfinance 직접 폴백."""
        # 1차: OpenBB
        try:
            from openbb import obb

            result = obb.news.company(symbol=ticker, provider="yfinance", limit=10)
            df = result.to_dataframe()
            if not df.empty:
                return self._parse_openbb_news(df, ticker)
        except Exception as e:
            self.logger.debug(f"{ticker}: OpenBB news 실패 — {e}")

        # 2차: yfinance 직접 호출 (OpenBB 장애 시 폴백)
        try:
            import yfinance as yf

            raw = yf.Ticker(ticker).news or []
            return self._parse_yfinance_news(raw, ticker)
        except Exception as e:
            self.logger.debug(f"{ticker}: yfinance news 폴백 실패 — {e}")
            return []

    def _parse_openbb_news(self, df, ticker: str) -> list[dict]:
        """OpenBB DataFrame → news record list."""
        from nuri.core.timezone import today_kst

        records: list[dict] = []
        for _, row in df.iterrows():
            url = row.get("url", "")
            if not url:
                continue

            # 날짜: index 또는 컬럼
            if hasattr(row.name, "strftime"):
                date = row.name.strftime("%Y-%m-%d")
            elif "date" in row.index:
                date = str(row["date"])[:10]
            else:
                date = today_kst()

            records.append(
                {
                    "ticker": ticker,
                    "date": date,
                    "title": str(row.get("title", ""))[:500],
                    "url": str(url)[:1000],
                    "source": str(row.get("source", ""))[:100],
                    "sentiment": None,
                }
            )
        return records

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


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = NewsCollector()
    collector.run()
