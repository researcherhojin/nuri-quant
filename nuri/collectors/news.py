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

    def collect(self, **kwargs) -> list[dict]:
        """보유 미국 종목 뉴스 수집."""
        from openbb import obb

        tickers = self._get_tickers(market="us")
        records = []

        for ticker in tickers:
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

                    records.append({
                        "ticker": ticker,
                        "date": date,
                        "title": str(row.get("title", ""))[:500],
                        "url": str(url)[:1000],
                        "source": str(row.get("source", ""))[:100],
                        "sentiment": None,
                    })

            except Exception as e:
                self.logger.debug(f"{ticker}: 뉴스 수집 실패 — {e}")

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
