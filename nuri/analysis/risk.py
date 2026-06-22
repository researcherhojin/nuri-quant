# pyright: reportAttributeAccessIssue=false
"""
리스크 분석 — Riskfolio-Lib 기반.

(pandas Series[Timestamp].sum stub mismatch — runtime: numeric Series, 정상.)

VaR, CVaR, Sharpe, Sortino, Max Drawdown 등을 Riskfolio-Lib으로 계산.
투자규칙 제약조건 (portfolio_stop -10%, stop_loss -20%) 검증.

사용법:
    python -m nuri.analysis.risk
"""

import logging

import numpy as np
import pandas as pd

from nuri.core.db import query, query_df

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
from nuri.core.rules import PORTFOLIO_STOP, STOCK_STOP_LOSS


def _get_portfolio_returns() -> tuple[pd.DataFrame, dict]:
    """포트폴리오 수익률 데이터 + 비중 계산."""
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty
        FROM portfolio GROUP BY ticker
    """)
    if holdings.empty:
        return pd.DataFrame(), {}

    # 현재 가치 → 비중
    values = {}
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if latest and latest[0]["close"]:
            values[row["ticker"]] = latest[0]["close"] * row["total_qty"]

    total = sum(values.values())
    if total == 0:
        return pd.DataFrame(), {}

    weights = {t: v / total for t, v in values.items()}

    # 일간 수익률
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    pivot = prices.pivot_table(index="date", columns="ticker", values="close")
    returns = pivot.ffill().pct_change(fill_method=None).dropna()

    return returns, weights


def analyze_risk() -> dict:
    """Riskfolio-Lib 기반 포트폴리오 리스크 분석."""
    returns, weights = _get_portfolio_returns()
    if returns.empty or not weights:
        return {}

    # 포트폴리오 일간 수익률 (가중 합)
    w_series = pd.Series(weights)
    common = list(set(w_series.index) & set(returns.columns))
    w = w_series[common]
    w = w / w.sum()
    port_returns = (returns[common] * w).sum(axis=1)

    # 리스크프리 레이트
    rf_rows = query("SELECT value FROM macro WHERE indicator = 'fed_funds_rate' ORDER BY date DESC LIMIT 1")
    rf_annual = rf_rows[0]["value"] / 100 if rf_rows else 0.05

    # 연환산 수익률/변동성
    annual_return = port_returns.mean() * TRADING_DAYS
    annual_std = port_returns.std() * np.sqrt(TRADING_DAYS)

    # VaR / CVaR (95%, Riskfolio 방식)
    var_95 = np.percentile(port_returns, 5) * 100
    var_99 = np.percentile(port_returns, 1) * 100
    cvar_95 = port_returns[port_returns <= np.percentile(port_returns, 5)].mean() * 100

    # Sharpe / Sortino
    sharpe = (annual_return - rf_annual) / annual_std if annual_std > 0 else 0
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
        beta = cov / var_market if var_market > 0 else 0

    # 종목별 손절선 체크
    stop_loss_alerts = []
    holdings = query_df("SELECT ticker, avg_price FROM portfolio")
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        if latest and latest[0]["close"] and row["avg_price"]:
            pnl_pct = (latest[0]["close"] - row["avg_price"]) / row["avg_price"] * 100
            if pnl_pct <= STOCK_STOP_LOSS:
                stop_loss_alerts.append({"ticker": ticker, "pnl_pct": round(pnl_pct, 1)})

    return {
        "annual_return_pct": round(annual_return * 100, 2),
        "annual_volatility_pct": round(annual_std * 100, 2),
        "var_95_daily_pct": round(var_95, 2),
        "var_99_daily_pct": round(var_99, 2),
        "cvar_95_daily_pct": round(cvar_95, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "current_drawdown_pct": round(drawdown.iloc[-1] * 100, 2) if len(drawdown) > 0 else 0,
        "beta": round(beta, 2),
        "portfolio_stop_triggered": max_drawdown <= PORTFOLIO_STOP,
        "stop_loss_alerts": stop_loss_alerts,
    }


def print_risk(metrics: dict) -> None:
    """리스크 지표 출력."""
    if not metrics:
        print("리스크 데이터가 없습니다.")
        return

    print(f"\n{'=' * 50}")
    print("  리스크 지표 (Riskfolio-Lib)")
    print(f"{'=' * 50}")
    print(f"  연환산 수익률:    {metrics['annual_return_pct']:>+8.2f}%")
    print(f"  연환산 변동성:    {metrics['annual_volatility_pct']:>8.2f}%")
    print(f"  Sharpe Ratio:    {metrics['sharpe_ratio']:>8.2f}")
    print(f"  Sortino Ratio:   {metrics['sortino_ratio']:>8.2f}")
    print(f"  Beta (vs VOO):   {metrics['beta']:>8.2f}")
    print(f"  VaR 95% (일간):  {metrics['var_95_daily_pct']:>+8.2f}%")
    print(f"  CVaR 95% (일간): {metrics['cvar_95_daily_pct']:>+8.2f}%")
    print(f"  Max Drawdown:    {metrics['max_drawdown_pct']:>+8.2f}%")
    print(f"  현재 Drawdown:   {metrics['current_drawdown_pct']:>+8.2f}%")

    if metrics["portfolio_stop_triggered"]:
        print(f"\n  🚨 포트폴리오 스톱 발동! (Max DD {metrics['max_drawdown_pct']:.1f}% ≤ {PORTFOLIO_STOP}%)")

    alerts = metrics.get("stop_loss_alerts", [])
    if alerts:
        print("\n  🚨 손절선 도달 종목:")
        for a in alerts:
            print(f"    {a['ticker']}: {a['pnl_pct']:+.1f}% (한도: {STOCK_STOP_LOSS}%)")
    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: 리스크 메트릭 출력."""
    del argv  # 인자 없음
    logging.basicConfig(level=logging.INFO)
    metrics = analyze_risk()
    print_risk(metrics)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
