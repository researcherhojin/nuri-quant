"""
펀더멘탈 데이터 수집기 — yfinance Ticker.info 기반.

PE, P/B, PEG, ROE, 마진, 성장률, 부채비율, 베타 등 16개 지표 수집.

이전 OpenBB equity.fundamental.metrics는 openbb-core 버전 충돌(`OBBject_EquityInfo`
import error)로 모든 종목 수집 실패. yfinance Ticker.info의 다음 필드를 직접
사용:
    marketCap, trailingPE, forwardPE, priceToBook, pegRatio,
    returnOnEquity, returnOnAssets, grossMargins, operatingMargins,
    profitMargins, revenueGrowth, earningsGrowth, debtToEquity,
    currentRatio, dividendYield, beta

사용법:
    python -m nuri.collectors.fundamental
"""

import logging
import math
from typing import Any

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)

# yfinance Ticker.info 필드 → DB 컬럼 매핑
YF_FIELDS = {
    "marketCap": "market_cap",
    "trailingPE": "pe_ratio",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "pegRatio": "peg_ratio",
    "returnOnEquity": "roe",
    "returnOnAssets": "roa",
    "grossMargins": "gross_margin",
    "operatingMargins": "operating_margin",
    "profitMargins": "profit_margin",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "dividendYield": "dividend_yield",
    "dividendRate": "annual_dividend_usd",
    "beta": "beta",
}


def _safe_num(val) -> float | None:
    """yfinance dict 필드 → None 안전 float (NaN/Inf 방지)."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


class FundamentalCollector(BaseCollector):
    """yfinance Ticker.info로 펀더멘탈 데이터 수집."""

    def __init__(self):
        super().__init__("fundamental")

    def collect(self, **kwargs) -> list[dict]:
        """전 보유종목 펀더멘탈 수집."""
        import yfinance as yf

        tickers = self._get_tickers()
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        self.logger.info(f"펀더멘탈 수집 대상: {len(tickers)}종목")
        from nuri.core.timezone import today_kst

        today = today_kst()
        results = []

        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                if not info or "regularMarketPrice" not in info:
                    self.logger.warning(f"{ticker}: yfinance info 비어있음")
                    continue

                record = {"ticker": ticker, "date": today}
                non_null = 0
                for src_field, db_field in YF_FIELDS.items():
                    val = _safe_num(info.get(src_field))
                    record[db_field] = val
                    if val is not None:
                        non_null += 1

                # dividend_yield_pct: yfinance dividendYield는 소수 (0.005 = 0.5%)
                # → 백분율로 변환 (0.5)
                dy = record.get("dividend_yield")
                record["dividend_yield_pct"] = round(dy * 100, 2) if dy else None

                if non_null == 0:
                    self.logger.info(f"{ticker}: 모든 펀더멘탈 필드 None — 스킵")
                    continue

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
                dividend_yield, beta, annual_dividend_usd, dividend_yield_pct)
               VALUES (:ticker, :date, :market_cap, :pe_ratio, :forward_pe, :price_to_book,
                       :peg_ratio, :roe, :roa, :gross_margin, :operating_margin, :profit_margin,
                       :revenue_growth, :earnings_growth, :debt_to_equity, :current_ratio,
                       :dividend_yield, :beta, :annual_dividend_usd, :dividend_yield_pct)""",
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
    rows = query(
        "SELECT ticker, pe_ratio, forward_pe, roe, revenue_growth, debt_to_equity FROM fundamentals ORDER BY ticker"
    )
    if rows:
        print(f"\n{'=' * 70}")
        print(f"  펀더멘탈 수집 완료: {count}종목")
        print(f"{'=' * 70}")
        print(f"  {'Ticker':<12} {'PE':>8} {'Fwd PE':>8} {'ROE':>8} {'매출성장':>8} {'D/E':>8}")
        print(f"  {'-' * 56}")
        for r in rows:
            pe = f"{r['pe_ratio']:.1f}" if r["pe_ratio"] else "N/A"
            fpe = f"{r['forward_pe']:.1f}" if r["forward_pe"] else "N/A"
            roe = f"{r['roe'] * 100:.1f}%" if r["roe"] else "N/A"
            rg = f"{r['revenue_growth'] * 100:.1f}%" if r["revenue_growth"] else "N/A"
            de = f"{r['debt_to_equity']:.1f}" if r["debt_to_equity"] else "N/A"
            print(f"  {r['ticker']:<12} {pe:>8} {fpe:>8} {roe:>8} {rg:>8} {de:>8}")
        print()
