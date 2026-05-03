# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""
백테스트 파라미터 최적화 — Grid Search.

시그널별 RSI 임계값, 보유 기간 등을 변경하며 최적 파라미터를 탐색한다.
기존 signal_backtest의 데이터를 활용하고, 결과를 CSV로 저장.

사용법:
    python -m nuri.quant.backtest.optimizer
    python -m nuri.quant.backtest.optimizer --signal rsi_oversold
"""

import itertools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nuri.core.db import query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


@dataclass
class OptResult:
    signal_id: str
    params: dict
    total_trades: int
    win_rate: float
    avg_return: float
    profit_factor: float
    sharpe: float


# ═══════════════════════════════════════════════════════
# 파라미터 그리드 정의
# ═══════════════════════════════════════════════════════

PARAM_GRIDS = {
    "rsi_oversold": {
        "rsi_threshold": [25, 30, 35],
        "hold_days": [10, 15, 20, 30],
    },
    "rsi_overbought": {
        "rsi_threshold": [65, 70, 75],
        "hold_days": [10, 15, 20, 30],
    },
    "bb_bounce": {
        "bb_period": [15, 20, 25],
        "bb_std": [1.5, 2.0, 2.5],
        "hold_days": [10, 15, 20, 30],
    },
    "macd_golden": {
        "fast": [8, 12, 16],
        "slow": [21, 26, 30],
        "signal": [7, 9, 12],
    },
}


def _backtest_signal_with_params(
    prices_df: pd.DataFrame,
    signal_id: str,
    params: dict,
) -> OptResult:
    """단일 파라미터 조합으로 시그널 백테스트."""
    close = prices_df["close"].values
    n = len(close)

    # 지표 계산
    try:
        import talib

        rsi = talib.RSI(close, timeperiod=14)
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        sig = params.get("signal", 9)
        macd, macd_sig, _ = talib.MACD(close, fastperiod=fast, slowperiod=slow, signalperiod=sig)
        bb_period = params.get("bb_period", 20)
        bb_std = params.get("bb_std", 2.0)
        bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=bb_period, nbdevup=bb_std, nbdevdn=bb_std)
    except ImportError:
        # pandas 폴백
        s = pd.Series(close)
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).values
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        sig = params.get("signal", 9)
        ema_f = s.ewm(span=fast).mean()
        ema_s = s.ewm(span=slow).mean()
        macd = (ema_f - ema_s).values
        macd_sig = pd.Series(macd).ewm(span=sig).mean().values
        bb_period = params.get("bb_period", 20)
        bb_std_val = params.get("bb_std", 2.0)
        bb_mid = s.rolling(bb_period).mean().values
        bb_s = s.rolling(bb_period).std().values
        bb_lower = bb_mid - bb_std_val * bb_s

    # 진입 감지
    entries = []
    hold_days = params.get("hold_days", 20)
    rsi_thresh = params.get("rsi_threshold", 30)

    for i in range(1, n):
        if signal_id == "rsi_oversold":
            if not np.isnan(rsi[i]) and not np.isnan(rsi[i - 1]):
                if rsi[i - 1] < rsi_thresh and rsi[i] >= rsi_thresh:
                    entries.append(i)
        elif signal_id == "rsi_overbought":
            if not np.isnan(rsi[i]) and not np.isnan(rsi[i - 1]):
                if rsi[i - 1] > rsi_thresh and rsi[i] <= rsi_thresh:
                    entries.append(i)
        elif signal_id == "bb_bounce":
            if not np.isnan(bb_lower[i]) and not np.isnan(bb_lower[i - 1]):
                if close[i - 1] < bb_lower[i - 1] and close[i] >= bb_lower[i]:
                    entries.append(i)
        elif signal_id == "macd_golden":
            if (
                not np.isnan(macd[i])
                and not np.isnan(macd_sig[i])
                and not np.isnan(macd[i - 1])
                and not np.isnan(macd_sig[i - 1])
            ):
                if macd[i - 1] < macd_sig[i - 1] and macd[i] >= macd_sig[i]:
                    entries.append(i)

    # 수익률 계산
    returns = []
    for entry_idx in entries:
        if signal_id == "macd_golden":
            # 반대 크로스까지 홀딩
            exit_idx = None
            for j in range(entry_idx + 1, n):
                if not np.isnan(macd[j]) and not np.isnan(macd_sig[j]):
                    if macd[j] < macd_sig[j]:
                        exit_idx = j
                        break
            if exit_idx is None:
                continue
        else:
            exit_idx = entry_idx + hold_days
            if exit_idx >= n:
                continue

        ret = (close[exit_idx] - close[entry_idx]) / close[entry_idx] * 100
        # RSI overbought는 숏 시그널
        if signal_id == "rsi_overbought":
            ret = -ret
        returns.append(ret)

    if not returns:
        return OptResult(signal_id, params, 0, 0.0, 0.0, 0.0, 0.0)

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    total_gain = sum(wins)
    total_loss = abs(sum(losses)) if losses else 0.001
    avg_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 1.0

    return OptResult(
        signal_id=signal_id,
        params=params,
        total_trades=len(returns),
        win_rate=len(wins) / len(returns),
        avg_return=avg_ret,
        profit_factor=total_gain / total_loss,
        sharpe=avg_ret / std_ret if std_ret > 0 else 0.0,
    )


def optimize_signal(
    signal_id: str,
    db_path: Optional[Path] = None,
) -> list[OptResult]:
    """단일 시그널의 파라미터 그리드 서치."""
    if signal_id not in PARAM_GRIDS:
        logger.warning(f"Grid not defined for {signal_id}")
        return []

    grid = PARAM_GRIDS[signal_id]
    keys = list(grid.keys())
    values = list(grid.values())

    # 포트폴리오 전체 가격 데이터 로드
    prices = query_df(
        "SELECT ticker, date, close FROM prices ORDER BY ticker, date",
        db_path=db_path,
    )
    if prices.empty:
        logger.warning("No price data")
        return []

    tickers = prices["ticker"].unique()
    results = []

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        combo_returns = []

        for ticker in tickers:
            ticker_df = prices[prices["ticker"] == ticker].reset_index(drop=True)
            if len(ticker_df) < 200:
                continue
            r = _backtest_signal_with_params(ticker_df, signal_id, params)
            if r.total_trades > 0:
                combo_returns.append(r)

        if combo_returns:
            total_trades = sum(r.total_trades for r in combo_returns)
            avg_wr = np.mean([r.win_rate for r in combo_returns])
            avg_ret = np.mean([r.avg_return for r in combo_returns])
            avg_pf = np.mean([r.profit_factor for r in combo_returns])
            avg_sharpe = np.mean([r.sharpe for r in combo_returns])
            results.append(
                OptResult(
                    signal_id,
                    params,
                    total_trades,
                    avg_wr,
                    avg_ret,
                    avg_pf,
                    avg_sharpe,
                )
            )

    # Profit Factor 기준 정렬
    results.sort(key=lambda r: r.profit_factor, reverse=True)
    return results


def optimize_all(db_path: Optional[Path] = None) -> pd.DataFrame:
    """모든 시그널 최적화 실행 → 결과 DataFrame."""
    all_results = []
    for signal_id in PARAM_GRIDS:
        logger.info(f"Optimizing {signal_id}...")
        results = optimize_signal(signal_id, db_path=db_path)
        for r in results:
            all_results.append(
                {
                    "signal_id": r.signal_id,
                    "params": str(r.params),
                    "total_trades": r.total_trades,
                    "win_rate": round(r.win_rate, 3),
                    "avg_return": round(r.avg_return, 2),
                    "profit_factor": round(r.profit_factor, 2),
                    "sharpe": round(r.sharpe, 2),
                }
            )

    df = pd.DataFrame(all_results)
    if not df.empty:
        # 시그널별 베스트 파라미터 표시
        best = df.loc[df.groupby("signal_id")["profit_factor"].idxmax()]
        print("\n=== Best Parameters per Signal ===")
        for _, row in best.iterrows():
            print(
                f"  {row['signal_id']}: PF={row['profit_factor']:.2f} "
                f"WR={row['win_rate']:.0%} Sharpe={row['sharpe']:.2f} "
                f"| {row['params']}"
            )

        # CSV 저장
        from datetime import date

        report_dir = REPORT_DIR / str(date.today())
        report_dir.mkdir(parents=True, exist_ok=True)
        csv_path = report_dir / "optimization_results.csv"
        df.to_csv(csv_path, index=False)
        print(f"\nSaved {len(df)} results to {csv_path}")

    return df


if __name__ == "__main__":  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", help="특정 시그널만 최적화")
    args = parser.parse_args()

    if args.signal:
        results = optimize_signal(args.signal)
        for r in results[:10]:
            print(f"  PF={r.profit_factor:.2f} WR={r.win_rate:.0%} trades={r.total_trades} | {r.params}")
    else:
        optimize_all()
