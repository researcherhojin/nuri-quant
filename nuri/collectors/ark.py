"""
ARK Invest 매매 추적 수집기.

ARK의 일일 매매 CSV를 다운로드하고, 보유/관심 종목만 필터링하여 저장.

사용법:
    python -m nuri.collectors.ark
"""
import csv
import io
import logging
from datetime import datetime

import requests

from nuri.collectors.base import BaseCollector
from nuri.db import get_tickers, upsert_ark

# ARK 매매 내역 CSV URL (공식)
ARK_TRADE_URL = "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_TRADE.csv"
# 대체 URL
ARK_TRADE_ALT_URL = "https://arkfunds.io/api/v2/etf/holdings?symbol=ARKK"


class ARKCollector(BaseCollector):
    """ARK Invest 일일 매매 추적."""

    def __init__(self):
        super().__init__("ark")

    def collect(self, **kwargs) -> list[dict]:
        """ARK 매매 CSV 다운로드 및 파싱."""
        held_tickers = set(get_tickers())

        try:
            return self._collect_csv(held_tickers)
        except Exception as e:
            self.logger.warning(f"ARK CSV 다운로드 실패: {e}")
            return []

    def _collect_csv(self, held_tickers: set) -> list[dict]:
        """ARK 공식 CSV에서 매매 내역 파싱."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }
        resp = requests.get(ARK_TRADE_URL, headers=headers, timeout=30)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        records = []

        for row in reader:
            # ARK CSV 컬럼: Date, Fund, Direction, Ticker, CUSIP, Name, Shares, % of ETF
            ticker = row.get("Ticker", row.get("ticker", "")).strip()
            if not ticker:
                continue

            # 보유 종목만 필터링
            if ticker not in held_tickers:
                continue

            # 날짜 파싱 (MM/DD/YYYY 또는 YYYY-MM-DD)
            date_raw = row.get("Date", row.get("date", "")).strip()
            try:
                if "/" in date_raw:
                    date = datetime.strptime(date_raw, "%m/%d/%Y").strftime("%Y-%m-%d")
                else:
                    date = date_raw
            except ValueError:
                date = date_raw

            shares_raw = row.get("Shares", row.get("shares", "0"))
            shares = float(str(shares_raw).replace(",", "")) if shares_raw else 0.0

            weight_raw = row.get("% of ETF", row.get("weight", "0"))
            weight = float(str(weight_raw).replace("%", "").replace(",", "")) if weight_raw else 0.0

            records.append({
                "date": date,
                "ticker": ticker,
                "direction": row.get("Direction", row.get("direction", "")).strip(),
                "shares": shares,
                "weight": weight,
                "fund": row.get("Fund", row.get("fund", "")).strip(),
            })

        self.logger.info(f"ARK 매매 {len(records)}건 (보유 종목 필터)")
        return records

    def save(self, data: list[dict]) -> int:
        """ARK 매매 내역을 DB에 저장."""
        return upsert_ark(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = ARKCollector()
    collector.run()
