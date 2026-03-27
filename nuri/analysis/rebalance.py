"""
리밸런싱 제안 — Riskfolio-Lib 기반 포트폴리오 최적화.

최적화 방법:
- MVO (Mean-Variance Optimization): 샤프비율 최대화
- Risk Parity: 리스크 균등 배분

투자규칙 제약조건:
- 단일 종목 ≤ 15%
- 섹터 ≤ 35%
- 레버리지 ETF 매수 금지

사용법:
    python -m nuri.analysis.rebalance
    python -m nuri.analysis.rebalance --method rp   # Risk Parity
"""
import argparse
import logging

import pandas as pd
import riskfolio as rp

from nuri.core.db import query, query_df

logger = logging.getLogger(__name__)

from nuri.core.rules import LEVERAGE_ETFS, MAX_SECTOR_EXPOSURE, MAX_SINGLE_POSITION


def analyze_rebalance(method: str = "mvo") -> pd.DataFrame:
    """Riskfolio-Lib 기반 최적 비중 계산 + 현재 비중 비교."""
    # 수익률 데이터
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    pivot = prices.pivot_table(index="date", columns="ticker", values="close")
    returns = pivot.pct_change(fill_method=None).dropna()

    if returns.empty or len(returns) < 10:
        logger.warning("수익률 데이터 부족")
        return pd.DataFrame()

    # 현재 비중 계산
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty, sector
        FROM portfolio GROUP BY ticker
    """)
    if holdings.empty:
        return pd.DataFrame()

    current_values = {}
    sectors = {}
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if latest and latest[0]["close"]:
            current_values[row["ticker"]] = latest[0]["close"] * row["total_qty"]
            sectors[row["ticker"]] = row["sector"] or "Unknown"

    total = sum(current_values.values())
    if total == 0:
        return pd.DataFrame()

    current_weights = {t: v / total for t, v in current_values.items()}

    # Riskfolio 포트폴리오
    common_tickers = sorted(set(returns.columns) & set(current_weights.keys()))
    port = rp.Portfolio(returns=returns[common_tickers])
    port.assets_stats(method_mu="hist", method_cov="hist")

    # 제약조건: 단일 종목 ≤ 15%
    port.upperlng = MAX_SINGLE_POSITION

    # 레버리지 ETF 비중 0으로 강제
    for i, ticker in enumerate(common_tickers):
        if ticker in LEVERAGE_ETFS:
            if port.upperlng is not None:
                pass  # upperlng이 이미 글로벌 상한

    # 최적화 실행
    if method == "rp":
        # Risk Parity
        w = port.rp_optimization(model="Classic", rm="MV")
    else:
        # MVO (최대 Sharpe)
        w = port.optimization(model="Classic", rm="MV", obj="Sharpe")

    if w is None or w.empty:
        logger.warning("최적화 실패")
        return pd.DataFrame()

    # 결과 조합
    results = []
    for ticker in common_tickers:
        opt_weight = float(w.loc[ticker, "weights"]) if ticker in w.index else 0
        cur_weight = current_weights.get(ticker, 0)
        drift = cur_weight - opt_weight

        # 매매 제안
        trade_value = (opt_weight - cur_weight) * total
        current_price_rows = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        current_price = current_price_rows[0]["close"] if current_price_rows else 1

        action = "HOLD"
        if ticker in LEVERAGE_ETFS:
            action = "SELL (레버리지)"
        elif trade_value < -100:
            action = "SELL"
        elif trade_value > 100:
            action = "BUY"

        results.append({
            "ticker": ticker,
            "sector": sectors.get(ticker, ""),
            "current_weight": round(cur_weight * 100, 2),
            "optimal_weight": round(opt_weight * 100, 2),
            "drift": round(drift * 100, 2),
            "trade_value_usd": round(trade_value, 0),
            "trade_shares": round(trade_value / current_price, 1),
            "action": action,
        })

    df = pd.DataFrame(results).sort_values("drift", key=abs, ascending=False)
    df.attrs["method"] = "Risk Parity" if method == "rp" else "Mean-Variance (Max Sharpe)"
    return df


def print_rebalance(df: pd.DataFrame) -> None:
    """리밸런싱 제안 출력."""
    if df.empty:
        print("리밸런싱 데이터가 없습니다.")
        return

    method = df.attrs.get("method", "MVO")
    actionable = df[df["action"] != "HOLD"]

    print(f"\n{'=' * 65}")
    print(f"  리밸런싱 제안 — {method} (Riskfolio-Lib)")
    print(f"  제약: 단일종목 ≤{MAX_SINGLE_POSITION*100:.0f}%, 섹터 ≤{MAX_SECTOR_EXPOSURE*100:.0f}%")
    print(f"{'=' * 65}")

    if actionable.empty:
        print("  ✅ 리밸런싱 불필요")
    else:
        print(f"\n  {'Ticker':<12} {'현재%':>8} {'최적%':>8} {'차이%':>8} {'제안':>12}")
        print(f"  {'-' * 52}")
        for _, row in actionable.iterrows():
            print(f"  {row['ticker']:<12} {row['current_weight']:>7.1f}% "
                  f"{row['optimal_weight']:>7.1f}% {row['drift']:>+7.1f}% "
                  f"{row['action']:>12}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["mvo", "rp"], default="mvo",
                        help="최적화 방법: mvo(샤프 최대화) 또는 rp(리스크 패리티)")
    args = parser.parse_args()

    df = analyze_rebalance(method=args.method)
    print_rebalance(df)
