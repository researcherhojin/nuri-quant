"""
이벤트 캘린더 수집기 — 실적발표, FOMC, 배당일 수집.

yfinance의 calendar 데이터 + FOMC 하드코딩.

사용법:
    python -m iris.collectors.events
"""
import logging
from datetime import datetime

import yfinance as yf

from iris.collectors.base import BaseCollector
from iris.db import insert_events, query

# 2026년 FOMC 회의 일정 (예정)
FOMC_2026 = [
    "2026-01-27", "2026-03-17", "2026-05-05",
    "2026-06-16", "2026-07-28", "2026-09-15",
    "2026-11-03", "2026-12-15",
]


class EventsCollector(BaseCollector):
    """실적발표/FOMC/배당 이벤트 수집."""

    def __init__(self):
        super().__init__("events")

    def collect(self, **kwargs) -> list[dict]:
        """종목별 이벤트 + FOMC 일정 수집."""
        records = []

        # FOMC 일정
        records.extend(self._collect_fomc())

        # 종목별 실적/배당 일정
        tickers = self._get_tickers(market="us")
        for ticker in tickers:
            records.extend(self._collect_ticker_events(ticker))

        return records

    def _collect_fomc(self) -> list[dict]:
        """FOMC 회의 일정."""
        records = []
        for date in FOMC_2026:
            records.append({
                "date": date,
                "event_type": "fomc",
                "ticker": None,
                "description": "FOMC 회의",
                "importance": 3,
            })
        return records

    def _collect_ticker_events(self, ticker: str) -> list[dict]:
        """yfinance에서 종목별 실적/배당 일정 수집."""
        records = []
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None or (hasattr(cal, 'empty') and cal.empty):
                return records

            # calendar는 dict 또는 DataFrame
            if isinstance(cal, dict):
                # 실적발표일
                earnings_date = cal.get("Earnings Date")
                if earnings_date:
                    dates = earnings_date if isinstance(earnings_date, list) else [earnings_date]
                    for d in dates:
                        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                        records.append({
                            "date": date_str,
                            "event_type": "earnings",
                            "ticker": ticker,
                            "description": f"{ticker} 실적발표",
                            "importance": 2,
                        })

                # 배당일
                ex_div = cal.get("Ex-Dividend Date")
                if ex_div:
                    date_str = ex_div.strftime("%Y-%m-%d") if hasattr(ex_div, "strftime") else str(ex_div)
                    records.append({
                        "date": date_str,
                        "event_type": "ex_dividend",
                        "ticker": ticker,
                        "description": f"{ticker} 배당락일",
                        "importance": 1,
                    })

        except Exception as e:
            self.logger.debug(f"{ticker}: 이벤트 수집 실패 — {e}")

        return records

    def save(self, data: list[dict]) -> int:
        """이벤트를 DB에 저장. 기존 데이터 삭제 후 재삽입."""
        if not data:
            return 0

        # 기존 이벤트 중복 방지: 날짜+종목+타입 기준 확인
        from iris.db import get_db
        with get_db() as conn:
            # 이번에 수집한 이벤트와 동일한 기존 이벤트 삭제 후 삽입
            for record in data:
                conn.execute(
                    """DELETE FROM events
                       WHERE date = ? AND event_type = ? AND
                             (ticker = ? OR (ticker IS NULL AND ? IS NULL))""",
                    (record["date"], record["event_type"],
                     record.get("ticker"), record.get("ticker")),
                )
        return insert_events(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = EventsCollector()
    collector.run()
