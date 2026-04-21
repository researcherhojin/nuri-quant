"""ATR-based exit / stop-loss computation (PR F, codex bubble-bear #6).

**Status**: SHADOW only — 현 production `stop_loss` (percent-based) 와 병렬
surface. Validation (paired walk-forward + 4/6 metric) 통과 전까지는 urgent
bucket / certification / risk_agent semantic 변경 없음.

## Why (codex Q5 실측, 2026-04-20)

로컬 DB 2021-04-08 ~ 2026-04-20 SPY long-sleeve backtest:
- `-7%`   = 36.0% (현 STOCK_STOP_LOSS — inherited O'Neil CAN SLIM, 재검증 0)
- `-15%`  = 42.7%
- `-20%`  = 42.7%
- `no stop` = 93.4% ← SPY buy-hold (71.4%) 보다 높음
- → 현 -7% 는 empirically too tight. 더 넓은 stop 또는 ATR-volatility-scaled
  stop 이 잠재적으로 우위.

## Design (codex Plan consult 2026-04-22, Q1-A + Q3-A+B)

- ATR 계산: talib.ATR(14-day) 사용. prices OHLC 충분.
- Grid: `k ∈ {1.5, 2.0, 2.5, 3.0}` × regime multiplier {bull_low_vol 0.8,
  neutral 1.0, bear_high_vol 1.3} = **12 조합**. E3-3c regime_override 와 동일
  structure, walk-forward statistical power 확보.
- Stop = `entry_price - (k × regime_mult × ATR_at_entry)`. **entry_atr_fixed**
  (static anchor, trailing dynamic 은 PR F2).

## Anchor contract (codex Biggest Risk)

현 codebase 가 `avg_price` (held) / `current_price` fallback / per-account row
/ decision-time 을 섞어 씀. 이 PR 에서 **freeze**:

- Held positions: `entry_price = avg_price` (portfolio table per-row).
  per-account row 가 여러 개면 각 row 별 per-account stop.
- Non-held candidates (price_targets): `entry_price = current_price` (최신 close).
- ATR = 14-day ATR at **entry time** (held = avg_price 책정일자, non-held =
  today). 이 PR 에선 `ATR_today` 로 근사 — proper entry_date tracking 은 PR F2.

## Fallback (insufficient history)

- OHLC < 14 rows → ATR 계산 불가 → `None` 반환 (caller 가 legacy percent stop
  fallback). PR C 의 shadow signal graceful degrade 패턴 재사용.
- Volume-low ticker: ATR 계산은 되지만 noise 높음 — PR F2 에서 `atr_valid`
  flag 추가 (e.g. ATR/close < 0.5% → invalidate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Grid frozen — codex Plan Q1-A adjusted
K_GRID = (1.5, 2.0, 2.5, 3.0)

# Regime multiplier — E3-3c `regime_overrides` 와 동일 패턴 (codex Plan Q1)
# 높은 multiplier = 더 넓은 stop (bear 에서 overshoot 방지).
REGIME_MULTIPLIER = {
    "bull_low_vol": 0.8,
    "bull_high_vol": 1.0,
    "neutral": 1.0,
    "sideways_low_vol": 1.0,
    "sideways_high_vol": 1.0,
    "recovery": 1.0,
    "bear_low_vol": 1.0,
    "bear_high_vol": 1.3,
    "euphoria": 1.0,
    "stagflation": 1.3,
}

DEFAULT_K = 2.0         # validation 전 default — validation 통과 후 변경
DEFAULT_PERIOD = 14     # ATR period (talib standard)
MIN_ROWS_FOR_ATR = 14   # OHLC row 최소 개수 — 미달 시 None


@dataclass
class AtrStopResult:
    """ATR stop 결과 — per-ticker per-account.

    Semantic:
        - atr: 최신 14-day ATR (None if insufficient)
        - atr_pct_of_price: ATR/entry_price. volatility-normalized.
        - stop_price: entry_price - (k × regime_mult × atr)
        - stop_pct: (stop_price - entry_price) / entry_price × 100. 음수.
        - k, regime, regime_multiplier: provenance (승격 결정 audit).
        - breached: current_price <= stop_price (live 실측).
        - basis: "entry_atr_fixed" (이 PR) — 승격 시 "trailing_atr_dynamic" 추가 예정.
    """
    ticker: str
    account: str | None
    entry_price: float
    current_price: float
    atr: float | None
    atr_pct_of_price: float | None
    k: float
    regime: str
    regime_multiplier: float
    stop_price: float | None
    stop_pct: float | None
    breached: bool
    basis: str = "entry_atr_fixed"
    detail: str = ""


def compute_atr(df: pd.DataFrame, period: int = DEFAULT_PERIOD) -> Optional[pd.Series]:
    """14-day ATR — talib 사용. OHLC row 부족하면 None.

    df: columns {high, low, close} 필요. talib 이 OHLC 를 float64 array 로 요구.

    Returns:
        ATR Series (pd.Series) with same index as df, or None if insufficient.
    """
    if df is None or len(df) < MIN_ROWS_FOR_ATR:
        return None
    if not all(c in df.columns for c in ("high", "low", "close")):
        return None

    import talib
    try:
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        close = df["close"].astype(float).values
        atr_arr = talib.ATR(high, low, close, timeperiod=period)
        return pd.Series(atr_arr, index=df.index)
    except Exception:
        return None


def compute_atr_stop(
    ticker: str,
    *,
    entry_price: float,
    current_price: float,
    account: str | None = None,
    regime: str = "neutral",
    k: float = DEFAULT_K,
    period: int = DEFAULT_PERIOD,
    db_path=None,
) -> AtrStopResult:
    """Single ticker ATR stop 계산.

    Anchor contract (codex Biggest Risk):
        - entry_price: held → portfolio.avg_price; non-held → current_price.
        - ATR: 최신 `period` (14d) at computation time. entry_date tracking 은 PR F2.

    Returns AtrStopResult with stop_price None if insufficient history.
    """
    from nuri.core.db import query_df

    df = query_df(
        "SELECT date, high, low, close FROM prices WHERE ticker = ? "
        "ORDER BY date DESC LIMIT ?",
        (ticker, period * 3),  # 3x 로 padding — talib 초기 NaN 고려
        db_path=db_path,
    )

    if df is None or df.empty or len(df) < MIN_ROWS_FOR_ATR:
        rows = 0 if df is None else len(df)
        return AtrStopResult(
            ticker=ticker, account=account,
            entry_price=entry_price, current_price=current_price,
            atr=None, atr_pct_of_price=None,
            k=k, regime=regime,
            regime_multiplier=REGIME_MULTIPLIER.get(regime, 1.0),
            stop_price=None, stop_pct=None, breached=False,
            detail=f"OHLC 부족 ({rows} rows < 필요 {MIN_ROWS_FOR_ATR}) — legacy percent stop fallback 권장",
        )

    df = df.sort_values("date").reset_index(drop=True)
    atr_series = compute_atr(df, period=period)
    if atr_series is None:
        return AtrStopResult(
            ticker=ticker, account=account,
            entry_price=entry_price, current_price=current_price,
            atr=None, atr_pct_of_price=None,
            k=k, regime=regime,
            regime_multiplier=REGIME_MULTIPLIER.get(regime, 1.0),
            stop_price=None, stop_pct=None, breached=False,
            detail="ATR 계산 실패 — talib 에러 또는 insufficient NaN 제거",
        )

    atr_latest = atr_series.iloc[-1]
    if pd.isna(atr_latest) or atr_latest <= 0:
        return AtrStopResult(
            ticker=ticker, account=account,
            entry_price=entry_price, current_price=current_price,
            atr=None, atr_pct_of_price=None,
            k=k, regime=regime,
            regime_multiplier=REGIME_MULTIPLIER.get(regime, 1.0),
            stop_price=None, stop_pct=None, breached=False,
            detail="ATR NaN/0 — 데이터 품질 점검 필요",
        )

    atr_val = float(atr_latest)
    regime_mult = REGIME_MULTIPLIER.get(regime, 1.0)
    effective_k = k * regime_mult
    stop_distance = effective_k * atr_val
    stop_price = entry_price - stop_distance
    stop_pct = (stop_price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
    breached = current_price <= stop_price
    atr_pct = atr_val / entry_price * 100 if entry_price > 0 else 0.0

    return AtrStopResult(
        ticker=ticker, account=account,
        entry_price=entry_price, current_price=current_price,
        atr=atr_val, atr_pct_of_price=atr_pct,
        k=k, regime=regime, regime_multiplier=regime_mult,
        stop_price=stop_price, stop_pct=stop_pct, breached=breached,
        detail=(
            f"entry={entry_price:.2f}, ATR{period}={atr_val:.2f} ({atr_pct:.1f}%), "
            f"k={k}×{regime_mult} ({regime}), stop={stop_price:.2f} ({stop_pct:+.1f}%)"
            + (" — 🚨 BREACHED" if breached else "")
        ),
    )
