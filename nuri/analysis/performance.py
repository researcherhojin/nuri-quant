"""
수익률/성과 분석 — QuantStats 기반 HTML 티어시트 + 콘솔 출력.

QuantStats가 Sharpe, Sortino, Calmar, MaxDD 등 30+ 지표를 자동 계산하고
HTML 리포트를 생성한다.

사용법:
    python -m nuri.analysis.performance
    python -m nuri.analysis.performance --html   # HTML 티어시트 생성
"""
import argparse
import logging
from pathlib import Path

import pandas as pd
import quantstats as qs

from nuri.db import query_df, query

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).parent.parent.parent / "data" / "exports"


def get_portfolio_returns(days: int = 90) -> pd.Series:
    """포트폴리오 가중 일간 수익률 Series 반환."""
    holdings = query_df("""
        SELECT ticker, SUM(quantity) as total_qty
        FROM portfolio GROUP BY ticker
    """)
    if holdings.empty:
        return pd.Series(dtype=float)

    # 현재 가치 → 비중
    values = {}
    for _, row in holdings.iterrows():
        latest = query(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (row["ticker"],),
        )
        if latest:
            values[row["ticker"]] = latest[0]["close"] * row["total_qty"]

    total = sum(values.values())
    if total == 0:
        return pd.Series(dtype=float)

    weights = {t: v / total for t, v in values.items()}

    # 일간 수익률
    prices = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    pivot = prices.pivot_table(index="date", columns="ticker", values="close")
    returns = pivot.pct_change(fill_method=None).dropna()

    # 포트폴리오 수익률
    w = pd.Series(weights)
    common = list(set(w.index) & set(returns.columns))
    w = w[common]
    w = w / w.sum()

    port_returns = (returns[common] * w).sum(axis=1)
    port_returns.index = pd.to_datetime(port_returns.index)
    port_returns.name = "Nuri-Quant Portfolio"

    return port_returns


def get_benchmark_returns() -> pd.Series:
    """VOO 벤치마크 수익률."""
    prices = query_df(
        "SELECT date, close FROM prices WHERE ticker = 'VOO' ORDER BY date"
    )
    if prices.empty:
        return pd.Series(dtype=float)

    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date")
    returns = prices["close"].pct_change().dropna()
    returns.name = "VOO"
    return returns


def generate_html_report(port_returns: pd.Series, benchmark: pd.Series) -> str:
    """QuantStats HTML 티어시트 생성."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_DIR / "tearsheet.html"

    qs.reports.html(
        port_returns,
        benchmark=benchmark if not benchmark.empty else None,
        output=str(output_path),
        title="Nuri-Quant Portfolio Performance",
    )

    logger.info(f"HTML 티어시트 저장: {output_path}")
    return str(output_path)


def print_performance(port_returns: pd.Series, benchmark: pd.Series) -> None:
    """QuantStats 기반 성과 요약 콘솔 출력."""
    if port_returns.empty:
        print("성과 데이터가 없습니다.")
        return

    # QuantStats 기본 지표
    total_return = qs.stats.comp(port_returns) * 100
    sharpe = qs.stats.sharpe(port_returns)
    sortino = qs.stats.sortino(port_returns)
    max_dd = qs.stats.max_drawdown(port_returns) * 100
    calmar = qs.stats.calmar(port_returns)
    volatility = qs.stats.volatility(port_returns) * 100
    win_rate = qs.stats.win_rate(port_returns) * 100

    # 벤치마크 대비
    bench_return = qs.stats.comp(benchmark) * 100 if not benchmark.empty else 0

    print(f"\n{'=' * 55}")
    print(f"  성과 분석 (QuantStats)")
    print(f"{'=' * 55}")
    print(f"  누적 수익률:     {total_return:>+8.2f}%")
    print(f"  연환산 변동성:   {volatility:>8.2f}%")
    print(f"  Sharpe Ratio:   {sharpe:>8.2f}")
    print(f"  Sortino Ratio:  {sortino:>8.2f}")
    print(f"  Calmar Ratio:   {calmar:>8.2f}")
    print(f"  Max Drawdown:   {max_dd:>+8.2f}%")
    print(f"  Win Rate:       {win_rate:>7.1f}%")
    print(f"  벤치마크 (VOO): {bench_return:>+8.2f}%")
    print(f"  Alpha:          {total_return - bench_return:>+8.2f}%")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Nuri-Quant 성과 분석 (QuantStats)")
    parser.add_argument("--html", action="store_true", help="HTML 티어시트 생성")
    args = parser.parse_args()

    port = get_portfolio_returns()
    bench = get_benchmark_returns()

    print_performance(port, bench)

    if args.html:
        path = generate_html_report(port, bench)
        print(f"  📄 HTML 리포트: {path}")
