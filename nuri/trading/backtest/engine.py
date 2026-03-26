"""
백테스트 엔진 — VectorBT 기반 벡터화 백테스트.

모멘텀 팩터 시그널로 포트폴리오 백테스트를 실행하고,
QuantStats 티어시트를 생성한다.

사용법:
    python -m nuri.quant.backtest.engine
    python -m nuri.quant.backtest.engine --period 1y
"""
import argparse
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

from nuri.core.db import query_df, query

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "exports"


def run_momentum_backtest(
    period: str = "3mo",
    top_n: int = 5,
    rebalance_days: int = 20,
) -> dict:
    """모멘텀 기반 Top-N 전략 백테스트.

    Args:
        period: 가격 데이터 기간
        top_n: 상위 N 종목에 투자
        rebalance_days: 리밸런싱 주기 (영업일)

    Returns:
        백테스트 결과 딕셔너리
    """
    # 가격 데이터 로드
    prices_df = query_df("SELECT ticker, date, close FROM prices ORDER BY date")
    if prices_df.empty:
        logger.warning("가격 데이터 없음")
        return {}

    pivot = prices_df.pivot_table(index="date", columns="ticker", values="close")
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot.dropna(axis=1, how="all").ffill()

    # 한국 종목 제외 (통화 혼합 방지)
    us_tickers = [t for t in pivot.columns if not t.endswith(".KS")]
    pivot = pivot[us_tickers]

    if pivot.empty or len(pivot) < 20:
        logger.warning("미국 종목 가격 데이터 부족")
        return {}

    # 모멘텀 시그널: N일 수익률 기반
    lookback = min(rebalance_days, max(5, len(pivot) // 4))
    momentum = pivot.pct_change(lookback)

    # 리밸런싱 시점에서 상위 top_n 종목 선택
    entries = pd.DataFrame(False, index=pivot.index, columns=pivot.columns)
    exits = pd.DataFrame(False, index=pivot.index, columns=pivot.columns)

    for i in range(lookback, len(pivot), rebalance_days):
        if i >= len(momentum):
            break
        row = momentum.iloc[i]
        top_tickers = row.nlargest(top_n).index.tolist()

        # 모든 종목 exit → top_n만 entry
        if i < len(exits):
            exits.iloc[i] = True
            for t in top_tickers:
                entries.loc[entries.index[i], t] = True

    # VectorBT 포트폴리오 시뮬레이션
    pf = vbt.Portfolio.from_signals(
        close=pivot,
        entries=entries,
        exits=exits,
        freq="1D",
        init_cash=100000,
        size=100000 / top_n,  # 균등 금액 배분
        size_type="value",
    )

    # 결과 추출
    stats = pf.stats()
    total_return = float(stats.get("Total Return [%]", 0))
    sharpe = float(stats.get("Sharpe Ratio", 0))
    max_dd = float(stats.get("Max Drawdown [%]", 0))
    win_rate = float(stats.get("Win Rate [%]", 0))

    # QuantStats HTML
    try:
        import quantstats as qs
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        port_returns = pf.returns()
        qs.reports.html(
            port_returns,
            output=str(EXPORT_DIR / "backtest_tearsheet.html"),
            title=f"Nuri-Quant Momentum Top-{top_n} Backtest",
        )
        logger.info(f"백테스트 티어시트: {EXPORT_DIR / 'backtest_tearsheet.html'}")
    except Exception as e:
        logger.warning(f"QuantStats 리포트 생성 실패: {e}")

    result = {
        "strategy": f"Momentum Top-{top_n}",
        "period": period,
        "rebalance_days": rebalance_days,
        "total_return_pct": round(total_return, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct": round(win_rate, 1),
        "total_trades": int(stats.get("Total Trades", 0)),
    }

    return result


def print_backtest(result: dict) -> None:
    """백테스트 결과 출력."""
    if not result:
        print("백테스트 데이터 없음.")
        return

    print(f"\n{'=' * 50}")
    print(f"  백테스트 결과 (VectorBT)")
    print(f"  전략: {result['strategy']}")
    print(f"{'=' * 50}")
    print(f"  총 수익률:       {result['total_return_pct']:>+8.2f}%")
    print(f"  Sharpe Ratio:   {result['sharpe_ratio']:>8.2f}")
    print(f"  Max Drawdown:   {result['max_drawdown_pct']:>+8.2f}%")
    print(f"  Win Rate:       {result['win_rate_pct']:>7.1f}%")
    print(f"  총 거래 횟수:   {result['total_trades']:>8d}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Nuri-Quant 백테스트 (VectorBT)")
    parser.add_argument("--period", default="3mo", help="데이터 기간")
    parser.add_argument("--top-n", type=int, default=5, help="상위 N 종목")
    parser.add_argument("--rebalance", type=int, default=20, help="리밸런싱 주기(일)")
    args = parser.parse_args()

    result = run_momentum_backtest(
        period=args.period, top_n=args.top_n, rebalance_days=args.rebalance,
    )
    print_backtest(result)
