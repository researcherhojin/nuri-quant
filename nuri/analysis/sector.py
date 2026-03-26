"""
섹터/지역 노출도 분석 — 섹터별, 지역별(US/KR) 비중 집계.

섹터 35% 초과 경고.

사용법:
    python -m nuri.analysis.sector
"""
import logging
from pathlib import Path

import pandas as pd

from nuri.core.db import query_df, query
from nuri.analysis.portfolio import get_exchange_rate

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).parent.parent.parent / "data" / "exports"
from nuri.core.rules import MAX_SECTOR_EXPOSURE as _MAX_SECTOR
MAX_SECTOR_EXPOSURE = _MAX_SECTOR * 100  # 0.35 → 35%


def analyze_sector() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """섹터/지역 노출도 분석. (섹터별, 지역별, 경고목록) 반환."""
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty, sector, currency
        FROM portfolio
        GROUP BY ticker
    """)

    if holdings.empty:
        return pd.DataFrame(), pd.DataFrame(), []

    usd_krw = get_exchange_rate()

    # 현재가치 계산 (USD 기준 통일)
    results = []
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if not latest:
            continue

        price = latest[0]["close"]
        qty = row["total_qty"]
        is_krw = row["currency"] == "KRW" or row["ticker"].endswith(".KS")
        current_value = (price * qty / usd_krw) if is_krw else (price * qty)
        region = "KR" if row["ticker"].endswith(".KS") else "US"

        results.append({
            "ticker": row["ticker"],
            "sector": row["sector"] or "Unknown",
            "region": region,
            "current_value": current_value,
        })

    df = pd.DataFrame(results)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), []

    total = df["current_value"].sum()

    # 섹터별 집계
    sector_df = df.groupby("sector")["current_value"].sum().reset_index()
    sector_df["weight_pct"] = round(sector_df["current_value"] / total * 100, 2)
    sector_df = sector_df.sort_values("weight_pct", ascending=False)

    # 지역별 집계
    region_df = df.groupby("region")["current_value"].sum().reset_index()
    region_df["weight_pct"] = round(region_df["current_value"] / total * 100, 2)

    # 경고
    warnings = []
    for _, row in sector_df.iterrows():
        if row["weight_pct"] > MAX_SECTOR_EXPOSURE:
            warnings.append(
                f"⚠️ {row['sector']}: {row['weight_pct']:.1f}% > {MAX_SECTOR_EXPOSURE}% 한도 초과!"
            )

    return sector_df, region_df, warnings


def print_sector(sector_df: pd.DataFrame, region_df: pd.DataFrame, warnings: list[str]) -> None:
    """섹터/지역 분석 출력."""
    print(f"\n{'=' * 50}")
    print("  섹터 노출도")
    print(f"{'=' * 50}")
    for _, row in sector_df.iterrows():
        bar = "█" * int(row["weight_pct"] / 2)
        print(f"  {row['sector']:<20} {row['weight_pct']:>6.1f}% {bar}")

    print(f"\n  지역 노출도")
    print(f"  {'-' * 30}")
    for _, row in region_df.iterrows():
        print(f"  {row['region']:<10} {row['weight_pct']:>6.1f}%")

    if warnings:
        print()
        for w in warnings:
            print(f"  {w}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sector, region, warns = analyze_sector()
    print_sector(sector, region, warns)
