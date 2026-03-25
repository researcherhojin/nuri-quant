"""
펀더멘탈 데이터 수집기 — OpenBB fundamental.metrics 기반.

PER, PBR, ROE, 마진, 성장률, 부채비율 등 30+개 지표 수집.
yfinance 프로바이더로 미국/한국 종목 모두 지원.

사용법:
    python -m nuri.collectors.fundamental
"""
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.db import get_db, query

logger = logging.getLogger(__name__)

# metrics에서 수집할 필드 매핑 (OpenBB 필드명 → DB 컬럼명)
METRICS_FIELDS = {
    "market_cap": "market_cap",
    "pe_ratio": "pe_ratio",
    "forward_pe": "forward_pe",
    "price_to_book": "price_to_book",
    "peg_ratio_ttm": "peg_ratio",
    "return_on_equity": "roe",
    "return_on_assets": "roa",
    "gross_margin": "gross_margin",
    "operating_margin": "operating_margin",
    "profit_margin": "profit_margin",
    "revenue_growth": "revenue_growth",
    "earnings_growth": "earnings_growth",
    "debt_to_equity": "debt_to_equity",
    "current_ratio": "current_ratio",
    "dividend_yield": "dividend_yield",
    "beta": "beta",
}


class FundamentalCollector(BaseCollector):
    """OpenBB fundamental.metrics로 펀더멘탈 데이터 수집."""

    def __init__(self):
        super().__init__("fundamental")

    def collect(self, **kwargs) -> list[dict]:
        """전 보유종목 펀더멘탈 수집."""
        from openbb import obb

        tickers = self._get_tickers()
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        self.logger.info(f"펀더멘탈 수집 대상: {len(tickers)}종목")
        today = datetime.now().strftime("%Y-%m-%d")
        results = []

        for ticker in tickers:
            try:
                r = obb.equity.fundamental.metrics(ticker, provider="yfinance")
                df = r.to_dataframe()
                if df.empty:
                    self.logger.warning(f"{ticker}: 펀더멘탈 데이터 없음")
                    continue

                row = df.iloc[0]
                record = {"ticker": ticker, "date": today}

                for src_field, db_field in METRICS_FIELDS.items():
                    val = row.get(src_field)
                    # NaN → None
                    if pd.notna(val):
                        record[db_field] = float(val)
                    else:
                        record[db_field] = None

                results.append(record)
                self.logger.debug(f"{ticker}: PE={record.get('pe_ratio')}, ROE={record.get('roe')}")

            except Exception as e:
                self.logger.warning(f"{ticker}: 펀더멘탈 수집 실패 — {e}")
                continue

        return results

    def save(self, data: Any) -> int:
        """펀더멘탈 데이터 DB 저장."""
        if not data:
            return 0
        return _upsert_fundamentals(data)


def _upsert_fundamentals(records: list[dict]) -> int:
    """fundamentals 테이블에 upsert."""
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO fundamentals
               (ticker, date, market_cap, pe_ratio, forward_pe, price_to_book,
                peg_ratio, roe, roa, gross_margin, operating_margin, profit_margin,
                revenue_growth, earnings_growth, debt_to_equity, current_ratio,
                dividend_yield, beta)
               VALUES (:ticker, :date, :market_cap, :pe_ratio, :forward_pe, :price_to_book,
                       :peg_ratio, :roe, :roa, :gross_margin, :operating_margin, :profit_margin,
                       :revenue_growth, :earnings_growth, :debt_to_equity, :current_ratio,
                       :dividend_yield, :beta)""",
            records,
        )
        return len(records)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = FundamentalCollector()
    count = collector.run()

    # 결과 출력
    rows = query("SELECT ticker, pe_ratio, forward_pe, roe, revenue_growth, debt_to_equity FROM fundamentals ORDER BY ticker")
    if rows:
        print(f"\n{'=' * 70}")
        print(f"  펀더멘탈 수집 완료: {count}종목")
        print(f"{'=' * 70}")
        print(f"  {'Ticker':<12} {'PE':>8} {'Fwd PE':>8} {'ROE':>8} {'매출성장':>8} {'D/E':>8}")
        print(f"  {'-' * 56}")
        for r in rows:
            pe = f"{r['pe_ratio']:.1f}" if r['pe_ratio'] else "N/A"
            fpe = f"{r['forward_pe']:.1f}" if r['forward_pe'] else "N/A"
            roe = f"{r['roe']*100:.1f}%" if r['roe'] else "N/A"
            rg = f"{r['revenue_growth']*100:.1f}%" if r['revenue_growth'] else "N/A"
            de = f"{r['debt_to_equity']:.1f}" if r['debt_to_equity'] else "N/A"
            print(f"  {r['ticker']:<12} {pe:>8} {fpe:>8} {roe:>8} {rg:>8} {de:>8}")
        print()
