"""
리스크 지표 분석 — VaR, Sharpe, Sortino, Max Drawdown, Beta.

리스크 제약:
- portfolio_stop: -10% (전체 포트폴리오 드로다운 한도)
- stop_loss: -20% (종목별 손절선)

사용법:
    python -m iris.analysis.risk
"""
import logging

import numpy as np
import pandas as pd

from iris.db import query_df, query

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
PORTFOLIO_STOP = -10.0  # %
STOCK_STOP_LOSS = -20.0  # %


def analyze_risk(days: int = 60) -> dict:
    """포트폴리오 리스크 지표 계산."""
    # 보유 종목 + 비중
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty
        FROM portfolio GROUP BY ticker
    """)
    if holdings.empty:
        return {}

    # 종목별 최신 가격 → 비중 계산
    values = {}
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if latest:
            values[row["ticker"]] = latest[0]["close"] * row["total_qty"]

    total_value = sum(values.values())
    if total_value == 0:
        return {}

    weights = {t: v / total_value for t, v in values.items()}

    # 일간 수익률 매트릭스
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    pivot = prices.pivot_table(index="date", columns="ticker", values="close")
    returns = pivot.pct_change().dropna()

    if len(returns) < 10:
        logger.warning("수익률 데이터 부족")
        return {}

    # 포트폴리오 일간 수익률 (가중 합)
    port_weights = pd.Series(weights)
    common_tickers = list(set(port_weights.index) & set(returns.columns))
    w = port_weights[common_tickers]
    w = w / w.sum()  # 재정규화
    port_returns = (returns[common_tickers] * w).sum(axis=1)

    # 리스크프리 레이트
    rf_rows = query(
        "SELECT value FROM macro WHERE indicator = 'fed_funds_rate' ORDER BY date DESC LIMIT 1"
    )
    rf_annual = rf_rows[0]["value"] / 100 if rf_rows else 0.05
    rf_daily = rf_annual / TRADING_DAYS

    # 연환산 수익률/변동성
    annual_return = port_returns.mean() * TRADING_DAYS
    annual_std = port_returns.std() * np.sqrt(TRADING_DAYS)

    # VaR (95%, 99%)
    var_95 = np.percentile(port_returns, 5) * 100
    var_99 = np.percentile(port_returns, 1) * 100

    # Sharpe Ratio
    sharpe = (annual_return - rf_annual) / annual_std if annual_std > 0 else 0.0

    # Sortino Ratio (하방 변동성만)
    downside = port_returns[port_returns < 0]
    downside_std = downside.std() * np.sqrt(TRADING_DAYS) if len(downside) > 0 else 0.001
    sortino = (annual_return - rf_annual) / downside_std

    # Max Drawdown
    cumulative = (1 + port_returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    max_drawdown = drawdown.min() * 100

    # Beta (vs VOO)
    beta = 0.0
    if "VOO" in returns.columns:
        cov = port_returns.cov(returns["VOO"])
        var_market = returns["VOO"].var()
        beta = cov / var_market if var_market > 0 else 0.0

    # 종목별 손절선 체크
    stop_loss_alerts = []
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        avg_price_rows = query(
            "SELECT avg_price FROM portfolio WHERE ticker = ?", (ticker,)
        )
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        if avg_price_rows and latest:
            avg_p = avg_price_rows[0]["avg_price"]
            cur_p = latest[0]["close"]
            pnl_pct = (cur_p - avg_p) / avg_p * 100 if avg_p != 0 else 0
            if pnl_pct <= STOCK_STOP_LOSS:
                stop_loss_alerts.append({
                    "ticker": ticker,
                    "pnl_pct": round(pnl_pct, 1),
                })

    result = {
        "annual_return_pct": round(annual_return * 100, 2),
        "annual_volatility_pct": round(annual_std * 100, 2),
        "var_95_daily_pct": round(var_95, 2),
        "var_99_daily_pct": round(var_99, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "current_drawdown_pct": round(drawdown.iloc[-1] * 100, 2) if len(drawdown) > 0 else 0,
        "beta": round(beta, 2),
        "total_value_usd": round(total_value, 0),
        "portfolio_stop_triggered": max_drawdown <= PORTFOLIO_STOP,
        "stop_loss_alerts": stop_loss_alerts,
    }

    return result


def print_risk(metrics: dict) -> None:
    """리스크 지표 출력."""
    if not metrics:
        print("리스크 데이터가 없습니다.")
        return

    print(f"\n{'=' * 50}")
    print("  리스크 지표")
    print(f"{'=' * 50}")
    print(f"  연환산 수익률:    {metrics['annual_return_pct']:>+8.2f}%")
    print(f"  연환산 변동성:    {metrics['annual_volatility_pct']:>8.2f}%")
    print(f"  Sharpe Ratio:    {metrics['sharpe_ratio']:>8.2f}")
    print(f"  Sortino Ratio:   {metrics['sortino_ratio']:>8.2f}")
    print(f"  Beta (vs VOO):   {metrics['beta']:>8.2f}")
    print(f"  VaR 95% (일간):  {metrics['var_95_daily_pct']:>+8.2f}%")
    print(f"  VaR 99% (일간):  {metrics['var_99_daily_pct']:>+8.2f}%")
    print(f"  Max Drawdown:    {metrics['max_drawdown_pct']:>+8.2f}%")
    print(f"  현재 Drawdown:   {metrics['current_drawdown_pct']:>+8.2f}%")

    if metrics["portfolio_stop_triggered"]:
        print(f"\n  🚨 포트폴리오 스톱 발동! (Max DD {metrics['max_drawdown_pct']:.1f}% ≤ {PORTFOLIO_STOP}%)")

    alerts = metrics.get("stop_loss_alerts", [])
    if alerts:
        print(f"\n  🚨 손절선 도달 종목:")
        for a in alerts:
            print(f"    {a['ticker']}: {a['pnl_pct']:+.1f}% (한도: {STOCK_STOP_LOSS}%)")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    metrics = analyze_risk()
    print_risk(metrics)
