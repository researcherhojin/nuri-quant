"""
이벤트 캘린더 수집기 — 실적발표, FOMC, 배당일 수집.

OpenBB Platform으로 실적 캘린더 조회 + FOMC 하드코딩.

사용법:
    python -m nuri.collectors.events
"""
import logging

from nuri.collectors.base import BaseCollector
from nuri.core.db import insert_events

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

        # 종목별 실적 일정 (OpenBB)
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
        """OpenBB로 종목별 실적/배당 일정 수집."""
        from openbb import obb

        records = []
        try:
            # 실적발표일
            result = obb.equity.calendar.earnings(
                symbol=ticker, provider="yfinance",
            )
            df = result.to_dataframe()
            if not df.empty:
                for _, row in df.iterrows():
                    date_val = row.get("report_date", row.get("date"))
                    if date_val is None:
                        # index가 날짜일 수 있음
                        if hasattr(row.name, "strftime"):
                            date_val = row.name
                        else:
                            continue

                    date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10]
                    records.append({
                        "date": date_str,
                        "event_type": "earnings",
                        "ticker": ticker,
                        "description": f"{ticker} 실적발표",
                        "importance": 2,
                    })
        except Exception as e:
            self.logger.debug(f"{ticker}: 실적 캘린더 조회 실패 — {e}")

        try:
            # 배당 일정
            result = obb.equity.calendar.dividend(
                symbol=ticker, provider="yfinance",
            )
            df = result.to_dataframe()
            if not df.empty:
                row = df.iloc[0]
                ex_date = row.get("ex_dividend_date", row.get("date"))
                if ex_date:
                    date_str = ex_date.strftime("%Y-%m-%d") if hasattr(ex_date, "strftime") else str(ex_date)[:10]
                    records.append({
                        "date": date_str,
                        "event_type": "ex_dividend",
                        "ticker": ticker,
                        "description": f"{ticker} 배당락일",
                        "importance": 1,
                    })
        except Exception:
            pass  # 배당 미지원 종목 무시

        return records

    def save(self, data: list[dict]) -> int:
        """이벤트를 DB에 저장. 기존 동일 이벤트 삭제 후 재삽입."""
        if not data:
            return 0

        from nuri.core.db import get_db
        with get_db() as conn:
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
