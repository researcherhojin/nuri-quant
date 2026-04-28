"""
Q1 Recovery state machine — STRATEGY §2.6 4번째 rung (Symmetric amplifier) 의 진입 게이트.

Codex consult 2026-04-28 session 019dd3f6 권고:
    "replace classifier._detect_recovery() with prior_stress AND repair_persisted"

핵심 invariant:
    1. 회복은 prior stress 가 있을 때만 인정 (panic 없는 그냥 상승은 회복 아님)
    2. 단일 일 bounce 차단 — 3 거래일 연속 repair 필요 (false dawn)
    3. Hysteresis — 2일 연속 실패 또는 VIX≥25 시 회복 종료
    4. F&G 데이터 부족 (DB 14 rows only) → SPY/VIX 만으로 동작 가능 (graceful fallback)

Stage 0 no-lookahead audit (STRATEGY §3.6): 모든 rolling stats 는 ≤ as_of_date 만 read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from nuri.core.db import query_df

logger = logging.getLogger(__name__)

# Codex 권고 임계값 (Q1)
PRIOR_STRESS_VIX_PEAK_LOOKBACK = 20  # 20d VIX peak ≥ 25 면 prior_stress
PRIOR_STRESS_VIX_PEAK_THRESHOLD = 25.0
PRIOR_STRESS_SPY_DD_LOOKBACK = 63  # 63d SPY drawdown ≤ -8% 면 prior_stress
PRIOR_STRESS_SPY_DD_THRESHOLD = -0.08
PRIOR_STRESS_FG_LOOKBACK = 10  # 10d F&G min < 30 면 prior_stress (optional)
PRIOR_STRESS_FG_THRESHOLD = 30.0

REPAIR_SPY_SMA_LOOKBACK = 20  # SPY > 20DMA
REPAIR_SPY_RETURN_LOOKBACK = 3  # SPY 3d return > 0
REPAIR_VIX_SLOPE_LOOKBACK = 3  # VIX 3d slope < 0
REPAIR_VIX_PEAK_FRACTION = 0.8  # VIX ≤ 0.8 × 20d peak

REPAIR_PERSIST_DAYS = 3  # 3 연속 거래일 (Q1 invariant)

EXIT_REPAIR_FAIL_DAYS = 2  # 2 연속 실패 → exit
EXIT_VIX_THRESHOLD = 25.0  # VIX ≥ 25 → exit


@dataclass
class RecoveryEvaluation:
    """단일 시점 recovery 평가 결과 (shadow telemetry 용)."""

    as_of_date: str
    prior_stress: bool
    prior_stress_reasons: list[str]  # 어떤 stress source 가 trigger 했나
    repair_day: bool
    repair_components: dict  # SPY/VIX 각 component PASS/FAIL
    consecutive_repair_days: int  # 직전 일자 포함
    recovery_confirmed: bool  # consecutive_repair_days ≥ REPAIR_PERSIST_DAYS
    exit_recovery: bool  # exit hysteresis 발동


def _fetch_macro_series(indicator: str, as_of_date: str, days: int = 90, db_path=None) -> pd.DataFrame:
    """Macro indicator 시계열 조회 — as_of_date 까지만 (no-lookahead)."""
    sql = """
        SELECT date, value FROM macro
        WHERE indicator = ? AND date <= ?
        ORDER BY date DESC LIMIT ?
    """
    df = query_df(sql, params=(indicator, as_of_date, days), db_path=db_path)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def _fetch_spy_series(as_of_date: str, days: int = 90, db_path=None) -> pd.DataFrame:
    """SPY 가격 시계열 조회 — as_of_date 까지만."""
    sql = """
        SELECT date, close FROM prices
        WHERE ticker = 'SPY' AND date <= ?
        ORDER BY date DESC LIMIT ?
    """
    df = query_df(sql, params=(as_of_date, days), db_path=db_path)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


def detect_prior_stress(as_of_date: str, db_path=None) -> tuple[bool, list[str]]:
    """직전 기간에 stress 가 있었는지 확인.

    조건 (any):
        - 20d VIX peak ≥ 25
        - 63d SPY drawdown ≤ -8%
        - 10d F&G min < 30 (F&G 데이터 부족 시 skip)

    Returns:
        (prior_stress 여부, 어떤 source 가 발동했는지 list)
    """
    reasons: list[str] = []

    # 20d VIX peak
    vix_df = _fetch_macro_series("vix", as_of_date, days=PRIOR_STRESS_VIX_PEAK_LOOKBACK, db_path=db_path)
    if not vix_df.empty:
        vix_peak = vix_df["value"].max()
        if pd.notna(vix_peak) and vix_peak >= PRIOR_STRESS_VIX_PEAK_THRESHOLD:
            reasons.append(f"vix_peak_20d={vix_peak:.2f}")

    # 63d SPY drawdown — running-max 기준 window 내 어느 날이라도 -8% 발생 시 stress
    # (codex Round 1 P1 fix — naive `now/max-1` 은 회복 후 stress 흔적 망각, false negative)
    spy_df = _fetch_spy_series(as_of_date, days=PRIOR_STRESS_SPY_DD_LOOKBACK, db_path=db_path)
    if len(spy_df) >= 2:
        closes = spy_df["close"].dropna()
        if len(closes) >= 2:
            running_max = closes.cummax()
            drawdowns = (closes / running_max) - 1.0
            max_dd_observed = drawdowns.min()  # 가장 음수
            if pd.notna(max_dd_observed) and max_dd_observed <= PRIOR_STRESS_SPY_DD_THRESHOLD:
                reasons.append(f"spy_max_dd_63d={max_dd_observed:.4f}")

    # 10d F&G min (optional — 데이터 부족 시 skip)
    fg_df = _fetch_macro_series("fear_greed", as_of_date, days=PRIOR_STRESS_FG_LOOKBACK, db_path=db_path)
    if not fg_df.empty:
        fg_min = fg_df["value"].min()
        if pd.notna(fg_min) and fg_min < PRIOR_STRESS_FG_THRESHOLD:
            reasons.append(f"fg_min_10d={fg_min:.2f}")

    return (len(reasons) > 0, reasons)


def evaluate_repair_day(as_of_date: str, db_path=None) -> tuple[bool, dict]:
    """단일 일자가 repair_day 자격 충족하는지 확인.

    조건 (all required):
        1. SPY > 20DMA
        2. SPY 3d return > 0
        3. VIX 3d slope < 0
        4. VIX ≤ 0.8 × 20d VIX peak

    Returns:
        (repair_day 여부, 각 component pass/fail dict)
    """
    components = {
        "spy_above_20dma": False,
        "spy_3d_return_positive": False,
        "vix_3d_slope_negative": False,
        "vix_below_80pct_peak": False,
    }

    # SPY 데이터
    spy_df = _fetch_spy_series(
        as_of_date, days=max(REPAIR_SPY_SMA_LOOKBACK, REPAIR_SPY_RETURN_LOOKBACK + 1) + 5, db_path=db_path
    )
    if len(spy_df) >= REPAIR_SPY_SMA_LOOKBACK:
        # SPY > 20DMA
        spy_now = spy_df["close"].iloc[-1]
        spy_sma20 = spy_df["close"].iloc[-REPAIR_SPY_SMA_LOOKBACK:].mean()
        if pd.notna(spy_now) and pd.notna(spy_sma20):
            components["spy_above_20dma"] = bool(spy_now > spy_sma20)

        # SPY 3d return > 0
        if len(spy_df) >= REPAIR_SPY_RETURN_LOOKBACK + 1:
            spy_3d_ago = spy_df["close"].iloc[-(REPAIR_SPY_RETURN_LOOKBACK + 1)]
            if pd.notna(spy_now) and pd.notna(spy_3d_ago) and spy_3d_ago > 0:
                ret_3d = (spy_now / spy_3d_ago) - 1.0
                components["spy_3d_return_positive"] = bool(ret_3d > 0)

    # VIX 데이터
    vix_df = _fetch_macro_series(
        "vix", as_of_date, days=max(PRIOR_STRESS_VIX_PEAK_LOOKBACK, REPAIR_VIX_SLOPE_LOOKBACK + 1) + 5, db_path=db_path
    )
    if len(vix_df) >= REPAIR_VIX_SLOPE_LOOKBACK + 1:
        # VIX 3d slope < 0 (단순 endpoint 비교)
        vix_now = vix_df["value"].iloc[-1]
        vix_3d_ago = vix_df["value"].iloc[-(REPAIR_VIX_SLOPE_LOOKBACK + 1)]
        if pd.notna(vix_now) and pd.notna(vix_3d_ago):
            components["vix_3d_slope_negative"] = bool(vix_now < vix_3d_ago)

        # VIX ≤ 0.8 × 20d peak
        if len(vix_df) >= PRIOR_STRESS_VIX_PEAK_LOOKBACK:
            vix_peak = vix_df["value"].iloc[-PRIOR_STRESS_VIX_PEAK_LOOKBACK:].max()
            if pd.notna(vix_now) and pd.notna(vix_peak) and vix_peak > 0:
                components["vix_below_80pct_peak"] = bool(vix_now <= vix_peak * REPAIR_VIX_PEAK_FRACTION)

    repair_day = all(components.values())
    return (repair_day, components)


def evaluate_recovery(as_of_date: str, db_path=None) -> RecoveryEvaluation:
    """단일 시점 recovery state 평가.

    Phase 1 shadow 용 — 결과는 telemetry 로만 사용. action 변경 없음.

    Args:
        as_of_date: 평가 기준일 (YYYY-MM-DD). 이 일자까지의 데이터만 사용.
        db_path: 테스트 격리용 DB 경로.

    Returns:
        RecoveryEvaluation 객체. recovery_confirmed=True 면 amplifier 1번째
        mandatory 조건 충족.
    """
    # Q1 invariant 1: prior_stress 없으면 회복 아님
    prior_stress, stress_reasons = detect_prior_stress(as_of_date, db_path=db_path)

    # 오늘 repair_day 인가
    repair_day_today, repair_components = evaluate_repair_day(as_of_date, db_path=db_path)

    # 직전 N-1 거래일 거슬러 올라가며 consecutive repair 카운트
    # (현재 일자 1 + 과거 일자 검증)
    consecutive = 1 if repair_day_today else 0
    if repair_day_today:
        # 가장 가까운 거래일 sequence 가져오기 (SPY 가격일 기준)
        spy_dates = _fetch_spy_series(as_of_date, days=REPAIR_PERSIST_DAYS + 5, db_path=db_path)
        if len(spy_dates) >= REPAIR_PERSIST_DAYS:
            # 최근 N-1 일자 (오늘 제외)
            prior_trading_dates = spy_dates["date"].iloc[-(REPAIR_PERSIST_DAYS):-1].tolist()
            for prior_date in reversed(prior_trading_dates):
                prior_repair, _ = evaluate_repair_day(prior_date, db_path=db_path)
                if prior_repair:
                    consecutive += 1
                else:
                    break

    # Q1 invariant 2: 3 연속 repair 필요
    recovery_confirmed = prior_stress and repair_day_today and consecutive >= REPAIR_PERSIST_DAYS

    # Q1 invariant 3: exit hysteresis — VIX ≥ 25 OR 최근 N 거래일 연속 repair 실패
    # (codex Round 1 P2 fix — file header 가 "2 consecutive fails OR VIX≥25" 로 명세하나
    # 기존 구현은 VIX 만 surface. 두 path 모두 lock 필요.)
    vix_df = _fetch_macro_series("vix", as_of_date, days=1, db_path=db_path)
    exit_recovery = False
    if not vix_df.empty:
        vix_now = vix_df["value"].iloc[-1]
        if pd.notna(vix_now) and vix_now >= EXIT_VIX_THRESHOLD:
            exit_recovery = True

    # Repair-fail 연속 — 가장 최근 EXIT_REPAIR_FAIL_DAYS 거래일 모두 repair_day=False 면 exit
    spy_for_exit = _fetch_spy_series(as_of_date, days=EXIT_REPAIR_FAIL_DAYS + 5, db_path=db_path)
    if len(spy_for_exit) >= EXIT_REPAIR_FAIL_DAYS:
        exit_check_dates = spy_for_exit["date"].iloc[-EXIT_REPAIR_FAIL_DAYS:].tolist()
        consecutive_fails = 0
        for d in exit_check_dates:
            rd_check, _ = evaluate_repair_day(d, db_path=db_path)
            if rd_check:
                consecutive_fails = 0
            else:
                consecutive_fails += 1
        if consecutive_fails >= EXIT_REPAIR_FAIL_DAYS:
            exit_recovery = True

    return RecoveryEvaluation(
        as_of_date=as_of_date,
        prior_stress=prior_stress,
        prior_stress_reasons=stress_reasons,
        repair_day=repair_day_today,
        repair_components=repair_components,
        consecutive_repair_days=consecutive,
        recovery_confirmed=bool(recovery_confirmed),
        exit_recovery=bool(exit_recovery),
    )
