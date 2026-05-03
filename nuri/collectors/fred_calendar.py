"""
FRED 경제 캘린더 수집기 — 주요 경제 지표 발표 일정 사전 알림.

FRED 릴리스 캘린더에서 향후 2주 이내 예정된 경제 지표 발표를 수집.
CPI, 고용, GDP, FOMC 등 시장에 영향을 미치는 주요 이벤트를 events 테이블에 저장.

FRED_API_KEY 필요 (없으면 하드코딩 캘린더 폴백).

사용법:
    python -m nuri.collectors.fred_calendar
"""

import logging
import os
from datetime import timedelta

import requests
from dotenv import load_dotenv

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, insert_events
from nuri.core.timezone import kst_now

load_dotenv()

FRED_RELEASES_URL = "https://api.stlouisfed.org/fred/releases/dates"

# FRED release_id → 이벤트 설명 매핑 (시장 영향이 큰 주요 릴리스)
IMPORTANT_RELEASES = {
    10: ("CPI", 3),  # Consumer Price Index
    50: ("고용 보고서", 3),  # Employment Situation
    53: ("GDP", 3),  # Gross Domestic Product
    21: ("소매판매", 2),  # Retail Sales
    46: ("PPI", 2),  # Producer Price Index
    32: ("ISM 제조업", 2),  # ISM Manufacturing
    116: ("소비자 심리지수", 2),  # U of Michigan Consumer Sentiment
    20: ("산업생산", 1),  # Industrial Production and Capacity Utilization
    83: ("주택착공", 1),  # Housing Starts
    11: ("내구재 주문", 1),  # Advance Report on Durable Goods
    22: ("무역수지", 1),  # US International Trade in Goods and Services
}

# 2026년 주요 경제 이벤트 (FRED API 없을 때 폴백)
# CPI: 매월 둘째 주 화요일/수요일
# 고용보고서: 매월 첫째 금요일
_FALLBACK_2026 = [
    # CPI 발표일 (2026 예정)
    ("2026-01-14", "CPI", 3),
    ("2026-02-12", "CPI", 3),
    ("2026-03-11", "CPI", 3),
    ("2026-04-14", "CPI", 3),
    ("2026-05-12", "CPI", 3),
    ("2026-06-10", "CPI", 3),
    ("2026-07-14", "CPI", 3),
    ("2026-08-12", "CPI", 3),
    ("2026-09-15", "CPI", 3),
    ("2026-10-13", "CPI", 3),
    ("2026-11-12", "CPI", 3),
    ("2026-12-10", "CPI", 3),
    # 고용보고서 (매월 첫째 금요일)
    ("2026-01-09", "고용 보고서", 3),
    ("2026-02-06", "고용 보고서", 3),
    ("2026-03-06", "고용 보고서", 3),
    ("2026-04-03", "고용 보고서", 3),
    ("2026-05-08", "고용 보고서", 3),
    ("2026-06-05", "고용 보고서", 3),
    ("2026-07-02", "고용 보고서", 3),
    ("2026-08-07", "고용 보고서", 3),
    ("2026-09-04", "고용 보고서", 3),
    ("2026-10-02", "고용 보고서", 3),
    ("2026-11-06", "고용 보고서", 3),
    ("2026-12-04", "고용 보고서", 3),
    # GDP (분기별)
    ("2026-01-29", "GDP", 3),
    ("2026-04-29", "GDP", 3),
    ("2026-07-29", "GDP", 3),
    ("2026-10-29", "GDP", 3),
]


class FREDCalendarCollector(BaseCollector):
    """FRED 경제 캘린더 수집 — 주요 지표 발표 사전 알림."""

    def __init__(self):
        super().__init__("fred_calendar")
        self.api_key = os.getenv("FRED_API_KEY", "")

    def collect(self, days_ahead: int = 14, **kwargs) -> list[dict]:
        """향후 N일 이내 예정된 주요 경제 이벤트 수집."""
        if days_ahead <= 0:
            self.logger.warning("days_ahead %d 유효하지 않음, 기본값 14 사용", days_ahead)
            days_ahead = 14

        # FRED API 시도
        if self.api_key and self.api_key != "your_fred_api_key_here":
            try:
                return self._collect_fred_api(days_ahead)
            except Exception as e:
                self.logger.warning("FRED API 실패, 폴백 캘린더 사용: %s", e)

        # 폴백: 하드코딩 캘린더
        return self._collect_fallback(days_ahead)

    def _collect_fred_api(self, days_ahead: int) -> list[dict]:
        """FRED Release Dates API에서 예정 이벤트 조회."""
        today = kst_now().replace(tzinfo=None)
        end_date = today + timedelta(days=days_ahead)

        params = {
            "api_key": self.api_key,
            "file_type": "json",
            "realtime_start": today.strftime("%Y-%m-%d"),
            "realtime_end": end_date.strftime("%Y-%m-%d"),
            "include_release_dates_with_no_data": "true",
        }

        resp = requests.get(FRED_RELEASES_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        records = []
        release_dates = data.get("release_dates", [])

        for rd in release_dates:
            release_id = rd.get("release_id")
            if release_id not in IMPORTANT_RELEASES:
                continue

            desc, importance = IMPORTANT_RELEASES[release_id]
            date_str = rd.get("date", "")

            records.append(
                {
                    "date": date_str,
                    "event_type": "economic",
                    "ticker": None,
                    "description": f"FRED: {desc}",
                    "importance": importance,
                }
            )

        self.logger.info("FRED 캘린더: %d개 이벤트 (향후 %d일)", len(records), days_ahead)
        return records

    def _collect_fallback(self, days_ahead: int) -> list[dict]:
        """하드코딩 캘린더 폴백."""
        today = kst_now().replace(tzinfo=None)
        end_date = today + timedelta(days=days_ahead)
        today_str = today.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        records = []
        for date_str, desc, importance in _FALLBACK_2026:
            if today_str <= date_str <= end_str:
                records.append(
                    {
                        "date": date_str,
                        "event_type": "economic",
                        "ticker": None,
                        "description": f"FRED: {desc}",
                        "importance": importance,
                    }
                )

        self.logger.info("FRED 캘린더 (폴백): %d개 이벤트", len(records))
        return records

    def save(self, data: list[dict]) -> int:
        """events 테이블에 저장. 기존 동일 이벤트 삭제 후 재삽입."""
        if not data:
            return 0

        with get_db() as conn:
            for record in data:
                conn.execute(
                    """DELETE FROM events
                       WHERE date = ? AND event_type = 'economic'
                             AND description = ?""",
                    (record["date"], record["description"]),
                )
        return insert_events(data)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = FREDCalendarCollector()
    collector.run()
