"""
ARK Invest 매매 추적 수집기.

소스 우선순위 (모두 무료, fallback chain):
    1. cathiesark.com 통합 CSV (CSV)
    2. ark-funds.com 공식 ARK_TRADE.csv (CSV)
    3. yfinance ETF holdings (ARKK/ARKW/ARKG/ARKQ/ARKF) — REST 차단 시 폴백

사용법:
    python -m nuri.collectors.ark
"""

import csv
import io
import logging

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector, parse_date, today_str
from nuri.core.db import get_tickers, upsert_ark

# ARK 매매 내역 URL (우선순위 순)
ARK_TRADE_URLS = [
    "https://cathiesark.com/ark-combined-holdings-of-etf.csv",
    "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_TRADE.csv",
]

# 폴백: yfinance로 직접 조회할 ARK ETF 목록
ARK_ETFS = ["ARKK", "ARKW", "ARKG", "ARKQ", "ARKF"]


class ARKCollector(BaseCollector):
    """ARK Invest 일일 매매 추적."""

    def __init__(self):
        super().__init__("ark")

    def collect(self, **kwargs) -> list[dict]:
        """ARK 매매 CSV 다운로드 및 파싱. CSV 실패 시 yfinance fallback."""
        held_tickers = set(get_tickers())

        for url in ARK_TRADE_URLS:
            try:
                records = self._collect_csv(url, held_tickers)
                if records:
                    return records
            except Exception as e:
                self.logger.warning("ARK CSV 다운로드 실패 (%s): %s", url.split("/")[2], e)

        # yfinance 폴백 — ETF holdings 조회
        try:
            records = self._collect_yfinance(held_tickers)
            if records:
                self.logger.info("ARK 데이터 yfinance fallback 사용 (%d건)", len(records))
                return records
        except Exception as e:
            self.logger.warning("yfinance ARK fallback 실패: %s", e)

        self.logger.warning("모든 ARK 소스 실패 (CSV + yfinance)")
        return []

    def _collect_yfinance(self, held_tickers: set) -> list[dict]:
        """yfinance Ticker.funds_data 또는 holdings로 ARK ETF의 보유 종목 조회.

        yfinance API는 ETF의 일별 매매 내역은 제공하지 않으므로,
        '오늘 날짜의 보유 비중' (held=hold) 스냅샷만 기록한다.
        """
        import yfinance as yf
        from tqdm import tqdm

        records = []
        succeeded: list[str] = []
        failed: list[str] = []
        today = today_str()

        self.logger.info(f"ARK ETF holdings 수집: {len(ARK_ETFS)}개 ETF")
        iterator = tqdm(ARK_ETFS, desc="  ARK ETFs", unit="etf", disable=len(ARK_ETFS) < 5)
        for etf in iterator:
            try:
                t = yf.Ticker(etf)
                # yfinance 0.2.x: funds_data.top_holdings → DataFrame
                fd = getattr(t, "funds_data", None)
                holdings_df = None
                if fd is not None:
                    holdings_df = getattr(fd, "top_holdings", None)
                if holdings_df is None or len(holdings_df) == 0:
                    continue
                # 컬럼 정규화
                cols = {c.lower(): c for c in holdings_df.columns}
                weight_col = cols.get("holding percent") or cols.get("weight")
                for symbol, row in holdings_df.iterrows():
                    sym = str(symbol).strip().upper()
                    if sym not in held_tickers:
                        continue
                    weight = float(row[weight_col]) * 100 if weight_col else 0.0
                    records.append(
                        {
                            "date": today,
                            "ticker": sym,
                            "direction": "Hold",  # 매매 내역 X, 보유 스냅샷
                            "shares": 0.0,
                            "weight": weight,
                            "fund": etf,
                        }
                    )
                succeeded.append(etf)
            except Exception as e:
                failed.append(etf)
                self.logger.debug("ARK yfinance %s 실패: %s", etf, e)
                continue

        self.logger.info(
            "📊 ARK ETF holdings: ✅ %d 성공 / ❌ %d 실패 — total %d holdings recorded",
            len(succeeded),
            len(failed),
            len(records),
        )
        return records

    def _collect_csv(self, url: str, held_tickers: set) -> list[dict]:
        """ARK CSV에서 매매/보유 내역 파싱."""
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
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
            date = parse_date(date_raw) or date_raw

            shares_raw = row.get("Shares", row.get("shares", "0"))
            shares = float(str(shares_raw).replace(",", "")) if shares_raw else 0.0

            weight_raw = row.get("% of ETF", row.get("weight", "0"))
            weight = float(str(weight_raw).replace("%", "").replace(",", "")) if weight_raw else 0.0

            records.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "direction": row.get("Direction", row.get("direction", "")).strip(),
                    "shares": shares,
                    "weight": weight,
                    "fund": row.get("Fund", row.get("fund", "")).strip(),
                }
            )

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
