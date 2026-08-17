# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""차트 시각 패턴 분석 — BB 위치, MACD 전환, 52주 거리, 매물대(POC), 추세선.

사용자가 차트에서 시각적으로 보는 정보를 정량화하여 시그널/에이전트가 활용 가능하게 한다.
신규 데이터 수집 없음 — 기존 prices(OHLCV 5년) + signals(BB/MACD-hist) 테이블 사용.

핵심 함수:
    analyze_chart(ticker) → ChartAnalysis  (모든 패턴을 한 번에)

개별 헬퍼:
    macd_histogram_turn(df)            → "bullish" | "bearish" | None
    bb_position(df)                    → 0(하단) ~ 100(상단)
    distance_from_52w_high(df)         → -(percent)
    distance_from_52w_low(df)          → +(percent)
    volume_profile_poc(df, lookback)   → POC price (Point of Control)
    trend_strength_9d(df)              → -100(약세) ~ +100(강세)

차트 정보 → 시그널 매핑:
    BB 위치       ⇄ bb_position()      ⇄ bb_squeeze_breakout 시그널
    MACD 히스토그램 ⇄ macd_histogram_turn() ⇄ macd_bullish_turn / bearish_turn 시그널
    52주 고저     ⇄ distance_from_52w_*() ⇄ near_52w_low_bounce 시그널
    매물대        ⇄ volume_profile_poc()   ⇄ volume_profile_resistance 시그널
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nuri.core.db import query_df

# ── 상수 ──

LOOKBACK_52W = 252  # 거래일 기준 52주
POC_LOOKBACK = 120  # 매물대 계산 기본 lookback (약 6개월)
POC_BINS = 50  # 매물대 가격 구간 수
TREND_WINDOW = 9  # 추세선 (KIS 앱과 동일한 9일)
MIN_DATA_POINTS = 30


@dataclass
class ChartAnalysis:
    """단일 종목 차트 패턴 종합."""

    ticker: str
    price: float
    # MACD 히스토그램 전환
    macd_turn: str | None  # "bullish" | "bearish" | None
    macd_hist: float  # 현재 histogram 값
    # Bollinger Band 위치
    bb_position: float  # 0(lower) ~ 100(upper)
    bb_width_pct: float  # band width / middle (squeeze 감지)
    # 52주 고저
    dist_from_52w_high: float  # 음수 percent (-15.0 = 고점 대비 -15%)
    dist_from_52w_low: float  # 양수 percent
    high_52w: float
    low_52w: float
    # 매물대 (Volume Profile Point of Control)
    poc_price: float  # 가장 거래 활발했던 가격대
    dist_from_poc: float  # percent (현재가 vs POC)
    # 추세선
    trend_strength: float  # -100 ~ +100
    # 종합 시각 점수
    visual_bias: str  # "bullish" | "bearish" | "neutral"
    reasons: list[str]  # 시각 패턴 사람이 읽기 쉬운 설명


# ═══════════════════════════════════════════════════════
# 개별 패턴 계산
# ═══════════════════════════════════════════════════════


def macd_histogram_turn(df: pd.DataFrame, *, col: str = "macd_hist") -> str | None:
    """MACD 히스토그램 부호 전환 감지.

    Returns:
        "bullish": 직전 음수 → 현재 양수 (모멘텀 회복 시작)
        "bearish": 직전 양수 → 현재 음수 (모멘텀 둔화 시작)
        None: 변화 없음 또는 데이터 부족
    """
    if col not in df.columns or len(df) < 2:
        return None
    h, h_prev = df[col].iloc[-1], df[col].iloc[-2]
    if pd.isna(h) or pd.isna(h_prev):
        return None
    if h_prev < 0 and h >= 0:
        return "bullish"
    if h_prev > 0 and h <= 0:
        return "bearish"
    return None


def bb_position(df: pd.DataFrame) -> float:
    """볼린저 밴드 내 종가 위치 (0=하단, 50=중단, 100=상단).

    상단 돌파 시 100 초과 가능, 하단 이탈 시 0 미만 가능.
    """
    required = {"close", "bb_upper", "bb_lower"}
    if not required.issubset(df.columns) or len(df) == 0:
        return 50.0
    close = df["close"].iloc[-1]
    upper = df["bb_upper"].iloc[-1]
    lower = df["bb_lower"].iloc[-1]
    if pd.isna(close) or pd.isna(upper) or pd.isna(lower) or upper <= lower:
        return 50.0
    return float((close - lower) / (upper - lower) * 100)


def bb_width_pct(df: pd.DataFrame) -> float:
    """BB 폭 / 중심선 (squeeze 감지용). 작을수록 폭 좁음 = 변동성 압축."""
    required = {"bb_upper", "bb_lower", "bb_middle"}
    if not required.issubset(df.columns) or len(df) == 0:
        return 0.0
    upper = df["bb_upper"].iloc[-1]
    lower = df["bb_lower"].iloc[-1]
    middle = df["bb_middle"].iloc[-1]
    if pd.isna(upper) or pd.isna(lower) or pd.isna(middle) or middle == 0:
        return 0.0
    return float((upper - lower) / middle * 100)


def distance_from_52w_high(df: pd.DataFrame, *, lookback: int = LOOKBACK_52W) -> tuple[float, float]:
    """현재가의 52주 고점 대비 거리 (%).

    Returns: (거리_퍼센트_음수, 52주_고점)
    """
    if "close" not in df.columns or len(df) == 0:
        return 0.0, 0.0
    window = df["close"].tail(lookback)
    high = float(window.max())
    price = float(df["close"].iloc[-1])
    if high == 0:
        return 0.0, high
    return float((price - high) / high * 100), high


def distance_from_52w_low(df: pd.DataFrame, *, lookback: int = LOOKBACK_52W) -> tuple[float, float]:
    """현재가의 52주 저점 대비 거리 (%)."""
    if "close" not in df.columns or len(df) == 0:
        return 0.0, 0.0
    window = df["close"].tail(lookback)
    low = float(window.min())
    price = float(df["close"].iloc[-1])
    if low == 0:
        return 0.0, low
    return float((price - low) / low * 100), low


def volume_profile_poc(
    df: pd.DataFrame,
    *,
    lookback: int = POC_LOOKBACK,
    bins: int = POC_BINS,
) -> float:
    """Volume Profile Point of Control (가장 거래량이 많았던 가격대).

    가격을 bins개로 나누고 각 구간에 해당하는 거래량을 합산하여
    가장 큰 구간의 중간값을 반환.
    """
    if "close" not in df.columns or "volume" not in df.columns or len(df) == 0:
        return 0.0
    sub = df[["close", "volume"]].tail(lookback).dropna()
    if sub.empty or sub["volume"].sum() == 0:
        return float(df["close"].iloc[-1])
    price_min, price_max = sub["close"].min(), sub["close"].max()
    if price_max <= price_min:
        return float(price_min)
    edges = np.linspace(price_min, price_max, bins + 1)
    idx = np.digitize(sub["close"], edges) - 1
    idx = np.clip(idx, 0, bins - 1)
    vol_at_price = np.zeros(bins)
    for i, v in zip(idx, sub["volume"], strict=False):
        vol_at_price[i] += v
    poc_bin = int(vol_at_price.argmax())
    return float((edges[poc_bin] + edges[poc_bin + 1]) / 2)


def trend_strength_9d(df: pd.DataFrame, *, window: int = TREND_WINDOW) -> float:
    """단기 추세 강도 (-100 ~ +100). KIS 앱의 9일 추세선과 동일 컨셉.

    9일 선형회귀 기울기를 가격 대비 정규화. 양수=상승, 음수=하락.
    """
    if "close" not in df.columns or len(df) < window:
        return 0.0
    y = df["close"].tail(window).values.astype(float)
    if np.any(np.isnan(y)):
        return 0.0
    x = np.arange(len(y))
    slope = float(np.polyfit(x, y, 1)[0])
    avg = float(y.mean())
    if avg == 0:
        return 0.0
    # 일평균 변화율 → 100점 스케일 (1%/day = 100점)
    return max(-100.0, min(100.0, slope / avg * 100 * 100))


# ═══════════════════════════════════════════════════════
# 종합 분석 (Agent용 진입점)
# ═══════════════════════════════════════════════════════


def analyze_chart(ticker: str, db_path=None, lookback_days: int = 365) -> ChartAnalysis:
    """단일 종목의 차트 패턴 종합 분석.

    prices + signals 테이블에서 데이터를 읽어 ChartAnalysis 반환.
    """
    df = query_df(
        """
        SELECT p.date, p.open, p.high, p.low, p.close, p.volume,
               s.macd_hist, s.bb_upper, s.bb_middle, s.bb_lower,
               s.sma_20, s.sma_50, s.sma_200
        FROM prices p
        LEFT JOIN signals s ON s.ticker = p.ticker AND s.date = p.date
        WHERE p.ticker = ?
        ORDER BY p.date
        """,
        (ticker,),
        db_path=db_path,
    )

    if df.empty or len(df) < MIN_DATA_POINTS:
        return ChartAnalysis(
            ticker=ticker,
            price=0.0,
            macd_turn=None,
            macd_hist=0.0,
            bb_position=50.0,
            bb_width_pct=0.0,
            dist_from_52w_high=0.0,
            dist_from_52w_low=0.0,
            high_52w=0.0,
            low_52w=0.0,
            poc_price=0.0,
            dist_from_poc=0.0,
            trend_strength=0.0,
            visual_bias="neutral",
            reasons=["데이터 부족"],
        )

    # signals JOIN이 NULL이면 인라인 계산 (collector 미실행 시 fallback)
    if df["bb_upper"].isna().all():
        df = _compute_indicators_inline(df)

    price = float(df["close"].iloc[-1])
    turn = macd_histogram_turn(df)
    hist = float(df["macd_hist"].iloc[-1]) if pd.notna(df["macd_hist"].iloc[-1]) else 0.0
    bbpos = bb_position(df)
    bbw = bb_width_pct(df)
    dist_high, high = distance_from_52w_high(df)
    dist_low, low = distance_from_52w_low(df)
    poc = volume_profile_poc(df)
    dist_poc = float((price - poc) / poc * 100) if poc > 0 else 0.0
    trend = trend_strength_9d(df)

    # 시각 편향 종합 (룰 기반 점수)
    score = 0
    reasons: list[str] = []

    if turn == "bullish":
        score += 2
        reasons.append("MACD 히스토그램 양전환")
    elif turn == "bearish":
        score -= 2
        reasons.append("MACD 히스토그램 음전환")

    if bbpos >= 80:
        score += 1
        reasons.append(f"BB 상단 근접 ({bbpos:.0f})")
    elif bbpos <= 20:
        score -= 1
        reasons.append(f"BB 하단 근접 ({bbpos:.0f})")

    if dist_high >= -5:
        reasons.append(f"52주 고점 근접 ({dist_high:.1f}%)")
    elif dist_high <= -30:
        reasons.append(f"52주 고점 한참 아래 ({dist_high:.1f}%)")

    if dist_low <= 10 and trend > 0:
        score += 1
        reasons.append(f"52주 저점 +{dist_low:.0f}% 반등 시도")

    if abs(dist_poc) <= 2:
        reasons.append(f"매물대(POC) 근접 ({dist_poc:+.1f}%)")

    if trend >= 30:
        score += 1
        reasons.append(f"단기 추세 강세 ({trend:+.0f})")
    elif trend <= -30:
        score -= 1
        reasons.append(f"단기 추세 약세 ({trend:+.0f})")

    if score >= 2:
        bias = "bullish"
    elif score <= -2:
        bias = "bearish"
    else:
        bias = "neutral"

    return ChartAnalysis(
        ticker=ticker,
        price=price,
        macd_turn=turn,
        macd_hist=hist,
        bb_position=round(bbpos, 1),
        bb_width_pct=round(bbw, 2),
        dist_from_52w_high=round(dist_high, 2),
        dist_from_52w_low=round(dist_low, 2),
        high_52w=round(high, 2),
        low_52w=round(low, 2),
        poc_price=round(poc, 2),
        dist_from_poc=round(dist_poc, 2),
        trend_strength=round(trend, 1),
        visual_bias=bias,
        reasons=reasons,
    )


def _compute_indicators_inline(df: pd.DataFrame) -> pd.DataFrame:
    """signals 테이블 데이터가 없을 때 인라인 계산 (테스트/fallback용)."""
    close = df["close"].astype(float)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_middle"] = bb_mid
    df["bb_lower"] = bb_mid - 2 * bb_std
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = macd - macd_signal
    return df
