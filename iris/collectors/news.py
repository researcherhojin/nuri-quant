"""
뉴스 수집기 — yfinance 기반 종목별 뉴스 수집.

사용법:
    python -m iris.collectors.news
"""
import logging
from datetime import datetime

import yfinance as yf

from iris.collectors.base import BaseCollector
from iris.db import upsert_news


class NewsCollector(BaseCollector):
    """yfinance로 종목별 뉴스 수집."""

    def __init__(self):
        super().__init__("news")

    def collect(self, **kwargs) -> list[dict]:
        """보유 종목 뉴스 수집."""
        tickers = self._get_tickers(market="us")  # 한국 종목은 뉴스 미지원
        records = []

        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                news_list = t.news
                if not news_list:
                    continue

                for item in news_list:
                    # yfinance 뉴스 구조
                    content = item.get("content", item) if isinstance(item, dict) else item
                    if isinstance(content, dict):
                        title = content.get("title", "")
                        url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else content.get("url", content.get("link", ""))
                        source = content.get("provider", {}).get("displayName", "") if isinstance(content.get("provider"), dict) else content.get("source", "")
                        pub_date = content.get("pubDate", "")
                    else:
                        continue

                    if not url:
                        continue

                    # 날짜 파싱
                    try:
                        if pub_date and isinstance(pub_date, str):
                            date = datetime.fromisoformat(pub_date.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                        else:
                            date = datetime.now().strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        date = datetime.now().strftime("%Y-%m-%d")

                    records.append({
                        "ticker": ticker,
                        "date": date,
                        "title": title[:500] if title else "",
                        "url": url[:1000],
                        "source": source[:100] if source else "",
                        "sentiment": None,  # Phase 2에서 LLM으로 분석
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
