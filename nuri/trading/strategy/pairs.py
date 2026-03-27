"""
Pairs Trading 전략 — 상관관계 높은 종목 쌍의 스프레드 수렴을 노린다.

1. 포트폴리오 내 종목 쌍별 상관관계 계산
2. 상관관계 ≥ 0.7인 쌍에서 Z-score 스프레드 추적
3. Z > 2.0 → Long underperformer + Short outperformer
4. Z → 0 수렴 시 청산

사용법:
    python -m nuri.trading.strategy.pairs
"""
import logging
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nuri.core.db import get_tickers, query_df

logger = logging.getLogger(__name__)

MIN_CORRELATION = 0.7
Z_ENTRY = 2.0
Z_EXIT = 0.5
LOOKBACK = 60  # 상관관계/스프레드 계산 기간


@dataclass
class PairSignal:
    ticker_long: str    # 매수 (underperformer)
    ticker_short: str   # 매도 (outperformer)
    correlation: float
    z_score: float
    spread_pct: float   # 현재 스프레드 %
    date: str


@dataclass
class PairStats:
    ticker_a: str
    ticker_b: str
    correlation: float
    mean_spread: float
    std_spread: float
    current_z: float


def find_pairs(
    min_corr: float = MIN_CORRELATION,
    db_path: Optional[Path] = None,
) -> list[PairStats]:
    """포트폴리오 내 상관관계 높은 종목 쌍 탐색."""
    tickers = get_tickers(db_path=db_path)
    # US 종목만 (KR 종목은 거래 시간 다름)
    us_tickers = [t for t in tickers if not t.endswith(".KS")]

    if len(us_tickers) < 2:
        return []

    # 가격 데이터 로드
    prices = {}
    for ticker in us_tickers:
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, LOOKBACK), db_path=db_path,
        )
        if len(df) >= LOOKBACK // 2:
            prices[ticker] = df.set_index("date")["close"]

    if len(prices) < 2:
        return []

    # 공통 날짜 기준 수익률 DataFrame
    price_df = pd.DataFrame(prices).dropna()
    if len(price_df) < 30:
        return []

    returns_df = price_df.pct_change().dropna()
    pairs = []

    for t1, t2 in combinations(returns_df.columns, 2):
        corr = returns_df[t1].corr(returns_df[t2])
        if corr < min_corr:
            continue

        # 가격 비율 스프레드 (log ratio)
        ratio = np.log(price_df[t1] / price_df[t2])
        mean_spread = ratio.mean()
        std_spread = ratio.std()
        if std_spread == 0:
            continue

        current_z = (ratio.iloc[-1] - mean_spread) / std_spread

        pairs.append(PairStats(
            ticker_a=t1, ticker_b=t2,
            correlation=round(corr, 3),
            mean_spread=round(mean_spread, 4),
            std_spread=round(std_spread, 4),
            current_z=round(current_z, 2),
        ))

    pairs.sort(key=lambda p: abs(p.current_z), reverse=True)
    return pairs


def scan_pair_signals(
    db_path: Optional[Path] = None,
) -> list[PairSignal]:
    """진입 조건(Z > 2.0) 충족 쌍 스캔."""
    pairs = find_pairs(db_path=db_path)
    signals = []

    for p in pairs:
        if abs(p.current_z) < Z_ENTRY:
            continue

        # Z > 0: A가 상대적 고평가 → Short A + Long B
        if p.current_z > 0:
            long_ticker = p.ticker_b
            short_ticker = p.ticker_a
        else:
            long_ticker = p.ticker_a
            short_ticker = p.ticker_b

        signals.append(PairSignal(
            ticker_long=long_ticker,
            ticker_short=short_ticker,
            correlation=p.correlation,
            z_score=p.current_z,
            spread_pct=p.std_spread * abs(p.current_z) * 100,
            date="latest",
        ))

    return signals


def backtest_pairs(
    max_hold: int = 20,
    db_path: Optional[Path] = None,
) -> dict:
    """페어 트레이딩 백테스트 (간이 시뮬레이션)."""
    pairs = find_pairs(db_path=db_path)
    eligible = [p for p in pairs if p.correlation >= MIN_CORRELATION]

    if not eligible:
        return {"total_trades": 0, "pairs_found": 0}

    all_trades = []

    for pair in eligible[:10]:  # 상위 10개 쌍만
        price_a = query_df(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date",
            (pair.ticker_a,), db_path=db_path,
        )
        price_b = query_df(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date",
            (pair.ticker_b,), db_path=db_path,
        )

        if price_a.empty or price_b.empty:
            continue

        merged = price_a.merge(price_b, on="date", suffixes=("_a", "_b")).dropna()
        if len(merged) < LOOKBACK:
            continue

        ratio = np.log(merged["close_a"].values / merged["close_b"].values)

        i = LOOKBACK
        while i < len(merged) - 1:
            window = ratio[i - LOOKBACK:i]
            mean_r = window.mean()
            std_r = window.std()
            if std_r == 0:
                i += 1
                continue

            z = (ratio[i] - mean_r) / std_r

            if abs(z) >= Z_ENTRY:
                entry_i = i
                # Z 수렴 또는 max_hold
                for j in range(i + 1, min(i + max_hold + 1, len(merged))):
                    z_j = (ratio[j] - mean_r) / std_r
                    if abs(z_j) <= Z_EXIT:
                        break
                else:
                    j = min(i + max_hold, len(merged) - 1)

                # 스프레드 수렴 수익
                spread_ret = (ratio[entry_i] - ratio[j]) if z > 0 else (ratio[j] - ratio[entry_i])
                pct_ret = spread_ret * 100

                all_trades.append({
                    "pair": f"{pair.ticker_a}/{pair.ticker_b}",
                    "return_pct": pct_ret,
                    "hold_days": j - entry_i,
                })
                i = j + 1
            else:
                i += 1

    if not all_trades:
        return {"total_trades": 0, "pairs_found": len(eligible)}

    returns = [t["return_pct"] for t in all_trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    return {
        "strategy": "pairs_trading",
        "pairs_found": len(eligible),
        "total_trades": len(returns),
        "win_rate": len(wins) / len(returns),
        "avg_return": round(np.mean(returns), 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf"),
        "avg_hold_days": round(np.mean([t["hold_days"] for t in all_trades]), 1),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Correlated Pairs ===")
    pairs = find_pairs()
    for p in pairs[:10]:
        print(f"  {p.ticker_a} / {p.ticker_b}: corr={p.correlation} Z={p.current_z}")

    print("\n=== Pair Signals (Z > 2.0) ===")
    signals = scan_pair_signals()
    for s in signals:
        print(f"  Long {s.ticker_long} / Short {s.ticker_short}: "
              f"corr={s.correlation} Z={s.z_score}")

    print("\n=== Pairs Backtest ===")
    result = backtest_pairs()
    for k, v in result.items():
        print(f"  {k}: {v}")
