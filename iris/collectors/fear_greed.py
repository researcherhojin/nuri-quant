"""
CNN Fear & Greed Index 수집기.

JSON API 우선, 실패 시 HTML 스크래핑 폴백.

사용법:
    python -m iris.collectors.fear_greed
"""
import logging
from datetime import datetime

import requests

from iris.collectors.base import BaseCollector
from iris.db import upsert_macro

# CNN Fear & Greed API 엔드포인트
FG_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


class FearGreedCollector(BaseCollector):
    """CNN Fear & Greed Index 수집."""

    def __init__(self):
        super().__init__("fear_greed")

    def collect(self, **kwargs) -> list[dict]:
        """Fear & Greed Index 수집."""
        # JSON API 시도
        try:
            return self._collect_api()
        except Exception as e:
            self.logger.warning(f"JSON API 실패, HTML 스크래핑 시도: {e}")

        # HTML 스크래핑 폴백
        try:
            return self._collect_scrape()
        except Exception as e:
            self.logger.error(f"HTML 스크래핑도 실패: {e}")
            return []

    def _collect_api(self) -> list[dict]:
        """CNN JSON API에서 Fear & Greed 데이터 수집."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }
        resp = requests.get(FG_API_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        # 현재 지수
        if "fear_and_greed" in data:
            fg = data["fear_and_greed"]
            score = fg.get("score", fg.get("value"))
            if score is not None:
                records.append({
                    "indicator": "fear_greed",
                    "date": today,
                    "value": float(score),
                    "source": "CNN",
                })
                rating = fg.get("rating", "")
                self.logger.info(f"Fear & Greed: {score:.1f} ({rating})")

        return records

    def _collect_scrape(self) -> list[dict]:
        """HTML 스크래핑 폴백."""
        from bs4 import BeautifulSoup

        url = "https://edition.cnn.com/markets/fear-and-greed"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        # CNN 페이지 구조에 따라 파싱 (변경 가능성 있음)
        score_elem = soup.find("text", class_="market-fng-gauge__dial-number-value")
        if score_elem:
            score = float(score_elem.text.strip())
            return [{
                "indicator": "fear_greed",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "value": score,
                "source": "CNN_scrape",
            }]

        self.logger.warning("HTML에서 Fear & Greed 점수를 찾지 못함")
        return []

    def save(self, data: list[dict]) -> int:
        """매크로 테이블에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = FearGreedCollector()
    collector.run()
