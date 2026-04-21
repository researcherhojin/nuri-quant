"""Market-wide crash precursor signals (PR C, codex bubble-bear #3).

Per-ticker signal_backtest 와 구조 분리 — SHADOW `actionable: false` 신호들을
구조적으로 candidates 경로에서 격리 (codex Plan consult Biggest Risk). 현재
포함 신호:

- `yield_curve_inversion`  — FRED `us_3m_yield` > `us_10y_yield`.
- `hy_oas_widening`        — BofA HY OAS 수준 + 63d 변화 둘 다 임계 돌파.

두 detector 모두 `macro` 테이블 read-only. 데이터 누락 시 `None` 반환 →
scorecard/UI 가 "insufficient data" 로 graceful degrade.

STRATEGY §2.6 Surface 단계. 승격은 human judgment (별도 PR).
"""
from __future__ import annotations

from dataclasses import dataclass

from nuri.core.db import query
from nuri.core.signal_config import get_signal_params

# Sentinel ticker — scorecard 집계에서 market-wide signal 을 per-ticker row 와
# 섞이지 않게 분리 (codex Plan Q3-C-special + Q4 scorecard schema 반영).
MARKET_TICKER = "_MARKET_"


@dataclass
class MarketSignalState:
    """Market-wide signal 의 current snapshot.

    Shadow 신호는 single point-in-time 판정. backtest 는 `_history` 함수로 별도.
    """
    signal_id: str
    fired: bool
    level: float | None        # 현재 값 (inversion=spread bps, oas=percent)
    threshold: float | None    # 임계 (fired 판정용 1차 threshold)
    detail: str                # 인간 가독 설명 ("3M=5.52 > 10Y=4.28, 역전")


def detect_yield_curve_inversion(db_path=None) -> MarketSignalState:
    """3M-10Y 역전 감지. 가장 최근 observed date 에서 `us_3m_yield > us_10y_yield`.

    반환 level = spread (bps, 음수일수록 역전). threshold = 0 (cross-over point).
    """
    params = get_signal_params("yield_curve_inversion")
    short_indicator = params.get("short_indicator", "us_3m_yield")
    long_indicator = params.get("long_indicator", "us_10y_yield")

    row = query(
        """
        SELECT
            (SELECT value FROM macro WHERE indicator = :short ORDER BY date DESC LIMIT 1) AS short_v,
            (SELECT value FROM macro WHERE indicator = :long ORDER BY date DESC LIMIT 1) AS long_v
        """,
        {"short": short_indicator, "long": long_indicator},  # type: ignore[arg-type]
        db_path=db_path,
    )
    if not row or row[0]["short_v"] is None or row[0]["long_v"] is None:
        return MarketSignalState(
            signal_id="yield_curve_inversion",
            fired=False, level=None, threshold=0.0,
            detail=f"데이터 부족 ({short_indicator} 또는 {long_indicator})",
        )

    short_v = float(row[0]["short_v"])
    long_v = float(row[0]["long_v"])
    spread_bps = (long_v - short_v) * 100  # FRED yield 는 percent → bps 환산
    fired = short_v > long_v  # 역전 = short > long
    detail = (
        f"3M={short_v:.2f}%, 10Y={long_v:.2f}%, spread={spread_bps:+.0f}bps — "
        f"{'역전 (SHADOW 경고)' if fired else '정상'}"
    )
    return MarketSignalState(
        signal_id="yield_curve_inversion",
        fired=fired, level=spread_bps, threshold=0.0, detail=detail,
    )


def detect_hy_oas_widening(db_path=None) -> MarketSignalState:
    """HY OAS 확대 감지. Level threshold + 63d 변화 threshold 둘 다 넘어야 fire.

    반환 level = 현재 HY OAS percent. threshold = `level_threshold_pct` (5.0).
    """
    params = get_signal_params("hy_oas_widening")
    level_pct = float(params.get("level_threshold_pct", 5.0))
    change_pct = float(params.get("change_threshold_pct", 1.5))
    lookback = int(params.get("lookback_days", 63))

    rows = query(
        "SELECT date, value FROM macro WHERE indicator = 'hy_oas' "
        "ORDER BY date DESC LIMIT :limit",
        {"limit": lookback + 1},  # type: ignore[arg-type]
        db_path=db_path,
    )
    if not rows:
        return MarketSignalState(
            signal_id="hy_oas_widening",
            fired=False, level=None, threshold=level_pct,
            detail="데이터 부족 (hy_oas) — FRED_API_KEY 확인 필요 (BAMLH0A0HYM2)",
        )
    current = float(rows[0]["value"])
    # 63 거래일 (lookback) 전 값. rows 이 DESC 라 마지막 element 가 가장 오래된.
    oldest = float(rows[-1]["value"])
    change = current - oldest
    level_ok = current >= level_pct
    change_ok = change >= change_pct
    fired = level_ok and change_ok
    detail = (
        f"HY OAS 현재 {current:.2f}% (임계 {level_pct}%, "
        f"{lookback}d 변화 {change:+.2f}pp 임계 {change_pct}pp) — "
        f"{'확대 (SHADOW 경고)' if fired else '정상'}"
    )
    return MarketSignalState(
        signal_id="hy_oas_widening",
        fired=fired, level=current, threshold=level_pct, detail=detail,
    )


# Registry — 추가 market-wide detector 는 여기 등록. Daily brief / engine dashboard
# 가 이 목록을 iterate 해 SHADOW 섹션 생성.
DETECTORS = {
    "yield_curve_inversion": detect_yield_curve_inversion,
    "hy_oas_widening": detect_hy_oas_widening,
}


def detect_all(db_path=None) -> list[MarketSignalState]:
    """모든 SHADOW market-wide signal 을 한 번에 평가 (UI 편의)."""
    return [fn(db_path=db_path) for fn in DETECTORS.values()]


def fired_shadow_signals(db_path=None) -> list[MarketSignalState]:
    """현재 발동 중인 SHADOW signal 만 반환 — daily brief 의 경고 섹션."""
    return [s for s in detect_all(db_path=db_path) if s.fired]
