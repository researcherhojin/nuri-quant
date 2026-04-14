"""
ETF 자금흐름 수집기 — 섹터 ETF AUM/거래량 추적.

OpenBB etf.info (yfinance) → total_assets, volume_avg, nav_price.
AUM 변화를 주기적으로 수집하여 섹터 자금흐름(rotation)을 추정한다.

사용법:
    python -m nuri.collectors.etf_flows
"""

import logging
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query_df

logger = logging.getLogger(__name__)

# 11 SPDR 섹터 ETF + 주요 지수 ETF
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financial",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrial",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

INDEX_ETFS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "EFA": "EAFE (International)",
    "EEM": "Emerging Markets",
}

ALL_ETFS = {**SECTOR_ETFS, **INDEX_ETFS}


class EtfFlowsCollector(BaseCollector):
    """섹터/지수 ETF AUM 추적 수집기."""

    def __init__(self):
        super().__init__("etf_flows")

    def collect(self, **kwargs) -> list[dict]:
        """OpenBB etf.info로 ETF 정보 수집.

        Note: 2026-04 기준 OpenBB OBBject_EtfCountries import 깨짐 (#274). 모든 fetch 실패.
        """
        import warnings

        from openbb import obb
        from tqdm import tqdm

        warnings.filterwarnings("ignore")

        from nuri.core.timezone import today_kst

        today = today_kst()
        results = []
        failed: list[str] = []

        etfs_list = list(ALL_ETFS.items())
        self.logger.info(f"ETF 정보 수집: {len(etfs_list)}개")
        iterator = tqdm(etfs_list, desc="  etf_flows", unit="etf", disable=len(etfs_list) < 10)

        for ticker, label in iterator:
            try:
                r = obb.etf.info(ticker, provider="yfinance")
                df = r.to_df()
                if df.empty:
                    continue

                row = df.iloc[0]
                results.append(
                    {
                        "ticker": ticker,
                        "date": today,
                        "name": str(row.get("name", label))[:100],
                        "total_assets": float(row["total_assets"]) if pd.notna(row.get("total_assets")) else None,
                        "volume_avg": float(row["volume_avg"]) if pd.notna(row.get("volume_avg")) else None,
                        "nav_price": float(row["nav_price"]) if pd.notna(row.get("nav_price")) else None,
                    }
                )
                if len(etfs_list) < 10:
                    self.logger.info(f"  {ticker} ({label}): AUM=${row.get('total_assets', 0) / 1e9:.1f}B")

            except Exception as e:
                failed.append(ticker)
                self.logger.debug(f"{ticker}: 수집 실패 — {e}")
                continue

        sample = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
        self.logger.info(
            "📊 ETF flows: ✅ %d 성공 / ❌ %d 실패 (총 %d) — failed: %s%s",
            len(results),
            len(failed),
            len(etfs_list),
            sample or "없음",
            "  [⚠️ OpenBB #274 깨짐 — 모두 실패 정상]" if len(failed) == len(etfs_list) else "",
        )
        return results

    def save(self, data: Any) -> int:
        """etf_flows 테이블에 upsert."""
        if not data:
            return 0
        return _upsert_etf_flows(data)


def _upsert_etf_flows(records: list[dict], db_path=None) -> int:
    """etf_flows 테이블에 upsert."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO etf_flows
               (ticker, date, name, total_assets, volume_avg, nav_price)
               VALUES (:ticker, :date, :name, :total_assets, :volume_avg, :nav_price)""",
            records,
        )
        return len(records)


def analyze_sector_rotation(days: int = 30, db_path=None) -> pd.DataFrame | None:
    """섹터 ETF AUM 변화로 자금흐름 분석.

    Returns:
        DataFrame with columns: ticker, sector, aum_current, aum_prev,
                                 aum_change_pct, volume_trend
    """
    df = query_df(
        """SELECT ticker, date, total_assets, volume_avg, nav_price
           FROM etf_flows
           WHERE ticker IN ({})
           ORDER BY ticker, date""".format(",".join(f"'{t}'" for t in SECTOR_ETFS)),
        db_path=db_path,
    )

    if df.empty or len(df["date"].unique()) < 2:
        logger.warning("섹터 로테이션 분석 불가: 최소 2일 이상의 데이터 필요")
        return None

    results = []
    for ticker in SECTOR_ETFS:
        tdf = df[df["ticker"] == ticker].sort_values("date")
        if len(tdf) < 2:
            continue

        latest = tdf.iloc[-1]
        earliest = tdf.iloc[0]

        aum_current = latest["total_assets"]
        aum_prev = earliest["total_assets"]

        if aum_prev and aum_prev > 0:
            aum_change_pct = (aum_current - aum_prev) / aum_prev * 100
        else:
            aum_change_pct = 0.0

        # 거래량 트렌드 (최근 vs 이전)
        if len(tdf) >= 4:
            mid = len(tdf) // 2
            vol_recent = tdf.iloc[mid:]["volume_avg"].mean()
            vol_earlier = tdf.iloc[:mid]["volume_avg"].mean()
            vol_trend = (vol_recent - vol_earlier) / vol_earlier * 100 if vol_earlier > 0 else 0.0
        else:
            vol_trend = 0.0

        results.append(
            {
                "ticker": ticker,
                "sector": SECTOR_ETFS[ticker],
                "aum_current": aum_current,
                "aum_prev": aum_prev,
                "aum_change_pct": round(aum_change_pct, 2),
                "volume_trend_pct": round(vol_trend, 2),
            }
        )

    if not results:
        return None

    result_df = pd.DataFrame(results).sort_values("aum_change_pct", ascending=False)
    return result_df


def print_sector_rotation(df: pd.DataFrame | None) -> None:
    """섹터 로테이션 CLI 출력."""
    if df is None or df.empty:
        print("섹터 로테이션 데이터 없음 (최소 2일 이상 수집 필요)")
        return

    print(f"\n{'=' * 65}")
    print("  섹터 ETF 자금흐름 (AUM 변화)")
    print(f"{'=' * 65}")
    print(f"  {'ETF':<6} {'섹터':<25} {'AUM($B)':>10} {'AUM변화':>10} {'거래량추세':>10}")
    print(f"  {'-' * 60}")

    for _, row in df.iterrows():
        aum_b = row["aum_current"] / 1e9 if row["aum_current"] else 0
        print(
            f"  {row['ticker']:<6} {row['sector']:<25} "
            f"{aum_b:>9.1f} {row['aum_change_pct']:>+9.1f}% {row['volume_trend_pct']:>+9.1f}%"
        )
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    collector = EtfFlowsCollector()
    collector.run()

    # 분석 (데이터가 2일 이상 쌓이면)
    result = analyze_sector_rotation()
    print_sector_rotation(result)
