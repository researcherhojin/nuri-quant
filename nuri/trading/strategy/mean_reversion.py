"""
Mean-Reversion 전략 — 단기 과매도 종목의 평균 회귀를 노린다.

진입: Bollinger Band 하단 이탈 + RSI < 30
청산: BB 중간선 도달 또는 5일 경과

사용법:
    python -m nuri.trading.strategy.mean_reversion
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nuri.core.db import get_tickers, query_df

logger = logging.getLogger(__name__)


@dataclass
class MeanRevSignal:
    ticker: str
    date: str
    entry_price: float
    bb_lower: float
    rsi: float
    z_score: float          # 20일 평균 대비 표준편차
    expected_target: float  # BB 중간선 (목표가)


def scan_mean_reversion(
    lookback: int = 5,
    db_path: Optional[Path] = None,
) -> list[MeanRevSignal]:
    """최근 N일 내 mean-reversion 진입 조건 종목 스캔."""
    tickers = get_tickers(db_path=db_path)
    signals = []

    for ticker in tickers:
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 60",
            (ticker,), db_path=db_path,
        )
        if len(df) < 30:
            continue

        df = df.iloc[::-1].reset_index(drop=True)  # 오래된 순
        close = df["close"].values

        # 지표 계산
        sma20 = pd.Series(close).rolling(20).mean().values
        std20 = pd.Series(close).rolling(20).std().values
        bb_lower = sma20 - 2 * std20
        bb_mid = sma20

        # RSI
        delta = pd.Series(close).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).values

        # 최근 N일 확인
        for i in range(max(len(df) - lookback, 20), len(df)):
            if np.isnan(bb_lower[i]) or np.isnan(rsi[i]):
                continue
            if close[i] < bb_lower[i] and rsi[i] < 30:
                z_score = (close[i] - sma20[i]) / std20[i] if std20[i] > 0 else 0
                signals.append(MeanRevSignal(
                    ticker=ticker,
                    date=df["date"].iloc[i],
                    entry_price=close[i],
                    bb_lower=bb_lower[i],
                    rsi=rsi[i],
                    z_score=z_score,
                    expected_target=bb_mid[i],
                ))

    # Z-score가 큰 순 (가장 과매도)
    signals.sort(key=lambda s: s.z_score)
    return signals


def backtest_mean_reversion(
    max_hold: int = 5,
    db_path: Optional[Path] = None,
) -> dict:
    """전체 기간 mean-reversion 백테스트."""
    tickers = get_tickers(db_path=db_path)
    all_trades = []

    for ticker in tickers:
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date",
            (ticker,), db_path=db_path,
        )
        if len(df) < 60:
            continue

        close = df["close"].values
        sma20 = pd.Series(close).rolling(20).mean().values
        std20 = pd.Series(close).rolling(20).std().values
        bb_lower = sma20 - 2 * std20
        bb_mid = sma20

        delta = pd.Series(close).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).values

        i = 20
        while i < len(df) - max_hold:
            if np.isnan(bb_lower[i]) or np.isnan(rsi[i]):
                i += 1
                continue
            if close[i] < bb_lower[i] and rsi[i] < 30:
                entry = close[i]
                # BB 중간선 도달 또는 max_hold일 경과
                exit_idx = min(i + max_hold, len(df) - 1)
                for j in range(i + 1, min(i + max_hold + 1, len(df))):
                    if not np.isnan(bb_mid[j]) and close[j] >= bb_mid[j]:
                        exit_idx = j
                        break
                ret = (close[exit_idx] - entry) / entry * 100
                all_trades.append({
                    "ticker": ticker,
                    "entry_date": df["date"].iloc[i],
                    "exit_date": df["date"].iloc[exit_idx],
                    "return_pct": ret,
                    "hold_days": exit_idx - i,
                })
                i = exit_idx + 1
            else:
                i += 1

    if not all_trades:
        return {"total_trades": 0}

    returns = [t["return_pct"] for t in all_trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    return {
        "strategy": "mean_reversion",
        "total_trades": len(returns),
        "win_rate": len(wins) / len(returns),
        "avg_return": np.mean(returns),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else float("inf"),
        "avg_hold_days": np.mean([t["hold_days"] for t in all_trades]),
        "best": max(returns),
        "worst": min(returns),
    }


def main() -> int:
    """CLI entry — Mean-Reversion 스캔 + 백테스트 출력 (testable, no argparse)."""
    logging.basicConfig(level=logging.INFO)

    print("=== Mean-Reversion Scan ===")
    signals = scan_mean_reversion()
    for s in signals[:10]:
        print(f"  {s.ticker} @ {s.entry_price:.2f} | RSI={s.rsi:.0f} "
              f"Z={s.z_score:.1f} → target {s.expected_target:.2f}")

    print("\n=== Mean-Reversion Backtest ===")
    result = backtest_mean_reversion()
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":  # pragma: no cover  # invariant: 표준 entry idiom — main() 이 testable
    raise SystemExit(main())
