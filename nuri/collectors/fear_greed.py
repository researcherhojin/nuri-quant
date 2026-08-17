"""
CNN Fear & Greed Index 수집기.

JSON API 우선, 실패 시 HTML 스크래핑 폴백.

사용법:
    python -m nuri.collectors.fear_greed
"""

import logging

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector, today_str
from nuri.core.db import upsert_macro

# CNN Fear & Greed API 엔드포인트
FG_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


class FearGreedCollector(BaseCollector):
    """CNN Fear & Greed Index 수집."""

    def __init__(self):
        super().__init__("fear_greed")

    def collect(self, **kwargs) -> list[dict]:
        """Fear & Greed Index 수집.

        전면 실패는 `[]` 가 아니라 **raise** 다 (#1042, coingecko #1043 과 동일 규약).
        `[]` 로 돌려주면 보고할 게 없던 날과 DB 기록이 같아진다 — 둘 다
        `collector_runs.status='finished'` 가 박히고 `#ops` 알림도 안 뜬다.
        """
        errors: list[Exception] = []
        records: list[dict] = []

        try:
            records = self._collect_api()
        except Exception as e:
            self.logger.warning(f"JSON API 실패, HTML 스크래핑 시도: {e}")
            errors.append(e)
            # 폴백은 API 가 **예외로 죽었을 때만** 탄다. 200 인데 내용이 빈 것은
            # NO_DATA 지 실패가 아니므로 스크래핑으로 재시도하지 않는다.
            try:
                records = self._collect_scrape()
            except Exception as scrape_error:
                self.logger.error(f"HTML 스크래핑도 실패: {scrape_error}")
                errors.append(scrape_error)

        # 예외가 났는데 한 건도 못 건졌다 = 전면 실패. 스크래핑이 예외 없이 점수를 못
        # 찾은 경우(`[]`)도 포함된다 — API 가 이미 죽은 마당에 폴백이 빈손이면 그건
        # "오늘 값이 없다"가 아니라 수집 실패다.
        #
        # `errors and` 는 장식이 아니다: API 가 200 빈 응답이면 errors 가 비어 있는데
        # 그 절을 빼면 `errors[0]` 이 IndexError 로 터진다. 즉 NO_DATA 경로를 지키는
        # 것이 바로 이 절이다.
        #
        # `errors[0]`: 마지막이 아니라 **첫** 원인을 올린다. 마지막은 항상 스크래핑이라
        # 운영자가 진짜 원인(API 쪽 4xx/5xx)을 못 보게 된다.
        if errors and not records:
            raise errors[0]
        return records

    def _collect_api(self) -> list[dict]:
        """CNN JSON API에서 Fear & Greed 데이터 수집."""
        resp = requests.get(FG_API_URL, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        records = []
        today = today_str()

        # 현재 지수
        if "fear_and_greed" in data:
            fg = data["fear_and_greed"]
            score = fg.get("score", fg.get("value"))
            if score is not None:
                records.append(
                    {
                        "indicator": "fear_greed",
                        "date": today,
                        "value": float(score),
                        "source": "CNN",
                    }
                )
                rating = fg.get("rating", "")
                self.logger.info(f"Fear & Greed: {score:.1f} ({rating})")

        return records

    def _collect_scrape(self) -> list[dict]:
        """HTML 스크래핑 폴백."""
        from bs4 import BeautifulSoup

        url = "https://edition.cnn.com/markets/fear-and-greed"
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        score_elem = soup.find("text", class_="market-fng-gauge__dial-number-value")
        if score_elem:
            score = float(score_elem.text.strip())
            return [
                {
                    "indicator": "fear_greed",
                    "date": today_str(),
                    "value": score,
                    "source": "CNN_scrape",
                }
            ]

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
