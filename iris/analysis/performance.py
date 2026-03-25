"""
수익률/기여도 분석 — 종목별 포트폴리오 기여도, 벤치마크 대비 성과.

사용법:
    python -m iris.analysis.performance
"""
import logging

import pandas as pd

from iris.db import query_df

logger = logging.getLogger(__name__)


def analyze_performance(days: int = 30) -> pd.DataFrame:
    """종목별 수익률 기여도 분석."""
    # 포트폴리오 현황
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty,
               AVG(avg_price) as avg_price, currency
        FROM portfolio
        GROUP BY ticker
    """)

    if holdings.empty:
        return pd.DataFrame()

    results = []
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        prices = query_df(
            f"SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT {days + 1}",
            (ticker,),
        )
        if len(prices) < 2:
            continue

        latest = prices.iloc[0]["close"]
        oldest = prices.iloc[-1]["close"]
        period_return = (latest - oldest) / oldest * 100 if oldest != 0 else 0

        results.append({
            "ticker": ticker,
            "current_price": latest,
            "period_start_price": oldest,
            "period_return_pct": round(period_return, 2),
            "total_qty": row["total_qty"],
        })

    df = pd.DataFrame(results)
    if df.empty:
        return df

    # 포트폴리오 가치 기준 비중 계산
    df["current_value"] = df["current_price"] * df["total_qty"]
    total_value = df["current_value"].sum()
    df["weight"] = df["current_value"] / total_value
    df["contribution_pct"] = round(df["weight"] * df["period_return_pct"], 2)

    # 벤치마크 (VOO) 비교
    voo_prices = query_df(
        f"SELECT date, close FROM prices WHERE ticker = 'VOO' ORDER BY date DESC LIMIT {days + 1}",
    )
    benchmark_return = 0.0
    if len(voo_prices) >= 2:
        benchmark_return = (voo_prices.iloc[0]["close"] - voo_prices.iloc[-1]["close"]) / voo_prices.iloc[-1]["close"] * 100

    portfolio_return = df["contribution_pct"].sum()
    df.attrs["portfolio_return"] = round(portfolio_return, 2)
    df.attrs["benchmark_return"] = round(benchmark_return, 2)
    df.attrs["alpha"] = round(portfolio_return - benchmark_return, 2)
    df.attrs["period_days"] = days

    return df.sort_values("contribution_pct", ascending=False)


def print_performance(df: pd.DataFrame) -> None:
    """수익률 분석 출력."""
    if df.empty:
        print("수익률 데이터가 없습니다.")
        return

    days = df.attrs.get("period_days", 30)
    port_ret = df.attrs.get("portfolio_return", 0)
    bench_ret = df.attrs.get("benchmark_return", 0)
    alpha = df.attrs.get("alpha", 0)

    print(f"\n{'=' * 60}")
    print(f"  수익률 분석 (최근 {days}일)")
    print(f"  포트폴리오: {port_ret:+.2f}% | VOO: {bench_ret:+.2f}% | Alpha: {alpha:+.2f}%")
    print(f"{'=' * 60}")

    # 상위 기여 종목
    print(f"\n  {'Ticker':<12} {'수익률%':>10} {'비중%':>8} {'기여도%':>10}")
    print(f"  {'-' * 42}")
    for _, row in df.head(10).iterrows():
        print(f"  {row['ticker']:<12} {row['period_return_pct']:>+9.2f}% "
              f"{row['weight'] * 100:>7.1f}% {row['contribution_pct']:>+9.2f}%")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = analyze_performance()
    print_performance(df)
