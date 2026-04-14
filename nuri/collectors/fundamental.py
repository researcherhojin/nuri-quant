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

    def collect(self, source: str = "portfolio", **kwargs) -> list[dict]:
        """펀더멘탈 수집. source='universe' 시 S&P500/KOSPI200 전체 (#272 Phase 2b)."""
        import logging as _logging

        import yfinance as yf
        from tqdm import tqdm

        tickers = self._get_tickers(source=source)
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        self.logger.info(f"펀더멘탈 수집 대상: {len(tickers)}종목 (source={source})")
        from nuri.core.timezone import today_kst

        today = today_kst()
        results = []
        skipped: list[str] = []
        failed: list[str] = []

        # universe 모드: yfinance ERROR 노이즈 억제
        _yflog = _logging.getLogger("yfinance")
        _orig_level = _yflog.level
        if source != "portfolio":
            _yflog.setLevel(_logging.CRITICAL)

        try:
            iterator = tqdm(tickers, desc=f"  fundamentals [{source}]", unit="tk", disable=len(tickers) < 20)
            for ticker in iterator:
                try:
                    info = yf.Ticker(ticker).info
                    if not info or "regularMarketPrice" not in info:
                        skipped.append(ticker)
                        continue

                    record = {"ticker": ticker, "date": today}
                    non_null = 0
                    for src_field, db_field in YF_FIELDS.items():
                        val = _safe_num(info.get(src_field))
                        record[db_field] = val
                        if val is not None:
                            non_null += 1

                    dy = record.get("dividend_yield")
                    record["dividend_yield_pct"] = round(dy * 100, 2) if dy else None

                    if non_null == 0:
                        skipped.append(ticker)
                        continue

                    results.append(record)
                except Exception:
                    failed.append(ticker)
                    continue
        finally:
            _yflog.setLevel(_orig_level)

        if len(tickers) >= 20:
            sample_failed = ", ".join((failed + skipped)[:5]) + (
                f" 외 {len(failed) + len(skipped) - 5}개" if len(failed) + len(skipped) > 5 else ""
            )
            self.logger.info(
                "📊 펀더멘탈: ✅ %d 성공 / ⚠️  %d 데이터부족 / ❌ %d 실패 (총 %d) — issues: %s",
                len(results),
                len(skipped),
                len(failed),
                len(tickers),
                sample_failed or "없음",
            )

            # 필드별 N/A 분석 — 사용자 질문 응답: "N/A는 데이터 없는 거? 못 가져온 거?"
            # 답: 성공 ticker 안에서 None 비율을 측정 → 진짜 데이터 부재 vs API 한계 구분
            if results:
                self.logger.info("📋 필드별 coverage (성공 %d ticker 중 non-null 비율):", len(results))
                for db_field in ["pe_ratio", "forward_pe", "roe", "revenue_growth", "debt_to_equity", "dividend_yield"]:
                    non_null = sum(1 for r in results if r.get(db_field) is not None)
                    pct = non_null / len(results) * 100
                    flag = "✅" if pct >= 80 else "⚠️ " if pct >= 50 else "🔴"
                    self.logger.info(
                        "   %s %-20s %5.1f%% (%d/%d) — N/A 는 yfinance가 미제공",
                        flag,
                        db_field,
                        pct,
                        non_null,
                        len(results),
                    )

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
    import argparse

    parser = argparse.ArgumentParser(description="Nuri-Quant 펀더멘탈 수집기 (yfinance)")
    parser.add_argument(
        "--source", default="portfolio", choices=["portfolio", "universe", "all"], help="ticker 소스 (#272 Phase 2b)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = FundamentalCollector()
    count = collector.run(source=args.source)

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
