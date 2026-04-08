"""
애널리스트 컨센서스 수집기 — yfinance ticker.info 기반.

목표가, 투자의견, 애널리스트 수를 수집. 한국 종목(.KS)은 yfinance가 컨센서스
데이터를 제공하지 않으므로 자동 스킵.

이전 OpenBB equity.estimates.consensus는 openbb-core 버전 충돌(`OBBject_EquityInfo`
import error)로 모든 종목에서 0건 수집. yfinance Ticker.info의 다음 필드를 직접
사용하여 의존성 단순화 + 안정성 확보:
    recommendationKey, recommendationMean, numberOfAnalystOpinions,
    targetMeanPrice, targetMedianPrice, targetHighPrice, targetLowPrice,
    currentPrice

사용법:
    python -m nuri.collectors.estimates
"""
import logging
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)


class EstimatesCollector(BaseCollector):
    """yfinance Ticker.info로 애널리스트 컨센서스 수집."""

    def __init__(self):
        super().__init__("estimates")

    def collect(self, **kwargs) -> list[dict]:
        """전 보유종목 애널리스트 컨센서스 수집 (US 종목만)."""
        import yfinance as yf

        tickers = self._get_tickers()
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        # yfinance는 한국 종목(.KS) 컨센서스 데이터 미제공 — 스킵
        us_tickers = [t for t in tickers if not t.endswith(".KS")]
        if not us_tickers:
            self.logger.warning("US 종목이 없습니다 (yfinance 컨센서스는 .KS 미지원)")
            return []

        self.logger.info(f"애널리스트 컨센서스 수집: {len(us_tickers)}종목")
        from nuri.core.timezone import today_kst
        today = today_kst()
        results = []

        for ticker in us_tickers:
            try:
                info = yf.Ticker(ticker).info
                if not info or "regularMarketPrice" not in info:
                    self.logger.warning(f"{ticker}: yfinance info 비어있음")
                    continue

                num_analysts = _safe_int(info.get("numberOfAnalystOpinions"))
                target_mean = _safe_float(info.get("targetMeanPrice"))
                # 분석가 데이터 없으면 스킵
                if not num_analysts and not target_mean:
                    self.logger.info(f"{ticker}: 분석가 컨센서스 미제공")
                    continue

                record = {
                    "ticker": ticker,
                    "date": today,
                    "recommendation": info.get("recommendationKey"),
                    "target_high": _safe_float(info.get("targetHighPrice")),
                    "target_low": _safe_float(info.get("targetLowPrice")),
                    "target_mean": target_mean,
                    "target_median": _safe_float(info.get("targetMedianPrice")),
                    "num_analysts": num_analysts,
                    "current_price": _safe_float(
                        info.get("currentPrice") or info.get("regularMarketPrice")
                    ),
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
