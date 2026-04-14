"""
뉴스 수집기 — OpenBB Platform 기반 종목별 뉴스 수집.

사용법:
    python -m nuri.collectors.news
"""

import logging

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_news


class NewsCollector(BaseCollector):
    """OpenBB로 종목별 뉴스 수집."""

    def __init__(self):
        super().__init__("news")

    def collect(self, source: str = "portfolio", **kwargs) -> list[dict]:
        """뉴스 수집. source='universe' 시 universe.yaml 전체.

        Note: 2026-04 기준 OpenBB OBBject_CompanyNews import 깨짐 (#274). 모든 fetch 실패.
        구조는 유지하되 실제 작동은 #274 fix 후 가능.
        """
        from openbb import obb
        from tqdm import tqdm

        tickers = self._get_tickers(market="us", source=source)
        records = []
        failed: list[str] = []

        if not tickers:
            return []

        self.logger.info(f"뉴스 수집 대상: {len(tickers)} 종목 (source={source})")
        iterator = tqdm(tickers, desc=f"  news [{source}]", unit="tk", disable=len(tickers) < 20)

        for ticker in iterator:
            try:
                result = obb.news.company(symbol=ticker, provider="yfinance", limit=10)
                df = result.to_dataframe()
                if df.empty:
                    continue

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
                        from nuri.core.timezone import today_kst

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

            except Exception as e:
                failed.append(ticker)
                self.logger.debug(f"{ticker}: 뉴스 수집 실패 — {e}")

        if len(tickers) >= 20:
            sample = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
            self.logger.info(
                "📊 뉴스: %d 건 수집 / ❌ %d 종목 실패 (총 %d) — failed: %s%s",
                len(records),
                len(failed),
                len(tickers),
                sample or "없음",
                "  [⚠️ OpenBB #274 깨짐 — 대부분 실패 정상]" if len(failed) > len(tickers) * 0.5 else "",
            )
        else:
            self.logger.info(f"뉴스 {len(records)}건 수집")
        return records

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
