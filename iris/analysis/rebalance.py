"""
리밸런싱 제안 — 현재 비중 vs 목표 비중 비교, ±5% 이탈 시 매매 제안.

레버리지 ETF 매수 제안 금지.

사용법:
    python -m iris.analysis.rebalance
"""
import logging

import pandas as pd

from iris.db import query_df, query

logger = logging.getLogger(__name__)

REBALANCE_THRESHOLD = 5.0  # %
LEVERAGE_ETFS = {"TSLL", "TQQQ", "SQQQ", "UPRO", "SPXU"}


def analyze_rebalance() -> pd.DataFrame:
    """리밸런싱 필요 종목 분석. 동일 비중(Equal Weight) 기준."""
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty, sector
        FROM portfolio
        GROUP BY ticker
    """)

    if holdings.empty:
        return pd.DataFrame()

    # 현재 가치 계산
    results = []
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if not latest:
            continue
        results.append({
            "ticker": row["ticker"],
            "sector": row["sector"],
            "quantity": row["total_qty"],
            "current_price": latest[0]["close"],
            "current_value": latest[0]["close"] * row["total_qty"],
        })

    df = pd.DataFrame(results)
    if df.empty:
        return df

    total = df["current_value"].sum()
    n = len(df)

    # 동일 비중 목표 (레버리지 ETF는 0% 목표)
    leverage_mask = df["ticker"].isin(LEVERAGE_ETFS)
    non_leverage_count = (~leverage_mask).sum()
    target_weight = 100.0 / non_leverage_count if non_leverage_count > 0 else 0

    df["current_weight"] = round(df["current_value"] / total * 100, 2)
    df["target_weight"] = 0.0
    df.loc[~leverage_mask, "target_weight"] = round(target_weight, 2)
    df["drift"] = round(df["current_weight"] - df["target_weight"], 2)
    df["needs_rebalance"] = abs(df["drift"]) > REBALANCE_THRESHOLD

    # 매매 제안 금액
    df["trade_value_usd"] = round((df["target_weight"] - df["current_weight"]) / 100 * total, 0)
    df["trade_shares"] = round(df["trade_value_usd"] / df["current_price"], 1)
    df["action"] = df.apply(
        lambda r: "SELL" if r["trade_value_usd"] < -100 else ("BUY" if r["trade_value_usd"] > 100 else "HOLD"),
        axis=1,
    )

    # 레버리지 ETF는 무조건 SELL
    df.loc[leverage_mask, "action"] = "SELL (레버리지)"

    return df.sort_values("drift", key=abs, ascending=False)


def print_rebalance(df: pd.DataFrame) -> None:
    """리밸런싱 제안 출력."""
    if df.empty:
        print("리밸런싱 데이터가 없습니다.")
        return

    needs = df[df["needs_rebalance"]]

    print(f"\n{'=' * 60}")
    print(f"  리밸런싱 제안 (임계값: ±{REBALANCE_THRESHOLD}%)")
    print(f"{'=' * 60}")

    if needs.empty:
        print("  ✅ 리밸런싱 불필요 — 모든 종목 목표 비중 범위 내")
    else:
        print(f"\n  {'Ticker':<12} {'현재%':>8} {'목표%':>8} {'차이%':>8} {'제안':>12}")
        print(f"  {'-' * 52}")
        for _, row in needs.iterrows():
            print(f"  {row['ticker']:<12} {row['current_weight']:>7.1f}% "
                  f"{row['target_weight']:>7.1f}% {row['drift']:>+7.1f}% "
                  f"{row['action']:>12}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = analyze_rebalance()
    print_rebalance(df)
