"""
애널리스트 컨센서스 수집기 — OpenBB estimates.consensus 기반.

목표가, 투자의견, 애널리스트 수를 수집.

사용법:
    python -m nuri.collectors.estimates
"""
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)


class EstimatesCollector(BaseCollector):
    """OpenBB estimates.consensus로 애널리스트 컨센서스 수집."""

    def __init__(self):
        super().__init__("estimates")

    def collect(self, **kwargs) -> list[dict]:
        """전 보유종목 애널리스트 컨센서스 수집."""
        from openbb import obb

        tickers = self._get_tickers()
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        self.logger.info(f"애널리스트 컨센서스 수집: {len(tickers)}종목")
        today = datetime.now().strftime("%Y-%m-%d")
        results = []

        for ticker in tickers:
            try:
                r = obb.equity.estimates.consensus(ticker, provider="yfinance")
                df = r.to_dataframe()
                if df.empty:
                    self.logger.warning(f"{ticker}: 컨센서스 데이터 없음")
                    continue

                row = df.iloc[0]
                record = {
                    "ticker": ticker,
                    "date": today,
                    "recommendation": row.get("recommendation"),
                    "target_high": _safe_float(row.get("target_high")),
                    "target_low": _safe_float(row.get("target_low")),
                    "target_mean": _safe_float(row.get("target_consensus")),
                    "target_median": _safe_float(row.get("target_median")),
                    "num_analysts": _safe_int(row.get("number_of_analysts")),
                    "current_price": _safe_float(row.get("current_price")),
                }
                results.append(record)

            except Exception as e:
                self.logger.warning(f"{ticker}: 컨센서스 수집 실패 — {e}")
                continue

        return results

    def save(self, data: Any) -> int:
        if not data:
            return 0
        return _upsert_estimates(data)


def _safe_float(val) -> float | None:
    if val is not None and pd.notna(val):
        return float(val)
    return None


def _safe_int(val) -> int | None:
    if val is not None and pd.notna(val):
        return int(val)
    return None


def _upsert_estimates(records: list[dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO estimates
               (ticker, date, recommendation, target_high, target_low,
                target_mean, target_median, num_analysts, current_price)
               VALUES (:ticker, :date, :recommendation, :target_high, :target_low,
                       :target_mean, :target_median, :num_analysts, :current_price)""",
            records,
        )
        return len(records)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = EstimatesCollector()
    count = collector.run()

    rows = query(
        """SELECT ticker, recommendation, target_mean, target_median,
                  current_price, num_analysts
           FROM estimates ORDER BY ticker"""
    )
    if rows:
        print(f"\n{'=' * 75}")
        print(f"  애널리스트 컨센서스: {count}종목")
        print(f"{'=' * 75}")
        print(f"  {'Ticker':<12} {'의견':<12} {'목표가':>10} {'현재가':>10} {'괴리율':>8} {'인원':>5}")
        print(f"  {'-' * 60}")
        for r in rows:
            target = r["target_mean"] or r["target_median"]
            current = r["current_price"]
            if target and current and current > 0:
                gap = (target - current) / current * 100
                gap_str = f"{gap:+.1f}%"
            else:
                gap_str = "N/A"
            target_str = f"{target:,.0f}" if target else "N/A"
            current_str = f"{current:,.0f}" if current else "N/A"
            analysts = r["num_analysts"] or 0
            rec = r["recommendation"] or "N/A"
            print(f"  {r['ticker']:<12} {rec:<12} {target_str:>10} {current_str:>10} {gap_str:>8} {analysts:>5}")
        print()
