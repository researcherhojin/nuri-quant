"""
D-1: 시장 레짐 분류기 — Bull/Bear/Sideways x High/Low Volatility.

임계값은 과거 252일(1년) 롤링 분위수에서 동적으로 결정.
히스테리시스로 잦은 레짐 전환 방지.

사용법:
    python -m nuri.quant.regime.classifier
    python -m nuri.quant.regime.classifier --history
"""
import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from nuri.core.db import query, query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

MARKET_TICKER = "SPY"

# 히스테리시스: 레짐 전환에 필요한 최소 연속 확인 일수
# VIX 25+ 고변동 시 적응적으로 2일로 단축 (빠른 전환)
HYSTERESIS_DAYS = 5
HYSTERESIS_DAYS_HIGH_VOL = 2
VIX_HIGH_VOL_THRESHOLD = 25

# 동적 임계값 계산에 사용할 롤링 윈도우 (거래일)
LOOKBACK_WINDOW = 252


@dataclass
class RegimeState:
    """시장 레짐 상태."""
    date: str
    trend: str            # "bull", "bear", "sideways"
    volatility: str       # "high", "low"
    regime: str           # "bull_low_vol" 등
    confidence: float     # 0.0 ~ 1.0
    details: dict         # 개별 지표 값 + 사용된 임계값


# ═══════════════════════════════════════════════════════
# 동적 임계값 계산
# ═══════════════════════════════════════════════════════


def compute_dynamic_thresholds(db_path=None, date: str | None = None) -> dict:
    """과거 데이터의 분위수에서 임계값을 도출.

    VIX: 중앙값(50th pctile)을 high/low 경계로 사용.
    SMA gap: 표준편차의 0.5배를 sideways 범위로 사용.
    BB Width: 중앙값을 vol 보조 경계로 사용.
    """
    date_filter = f"AND date <= '{date}'" if date else ""

    # VIX 이력
    vix_df = query_df(
        f"SELECT value FROM macro WHERE indicator = 'vix' {date_filter} "
        f"ORDER BY date DESC LIMIT {LOOKBACK_WINDOW}",
        db_path=db_path,
    )

    if not vix_df.empty and len(vix_df) >= 20:
        vix_median = float(vix_df["value"].median())
        vix_p75 = float(vix_df["value"].quantile(0.75))
    else:
        # VIX 데이터 부족 시 역사적 기본값
        vix_median = 18.0
        vix_p75 = 24.0

    # SPY SMA gap 이력 → sideways 범위 결정
    spy_df = query_df(
        f"SELECT date, close FROM prices WHERE ticker = ? {date_filter} ORDER BY date",
        (MARKET_TICKER,), db_path=db_path,
    )

    if not spy_df.empty and len(spy_df) >= 250:
        close = spy_df["close"]
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        gap_pct = ((sma50 - sma200) / sma200 * 100).dropna()

        if len(gap_pct) >= 50:
            gap_std = float(gap_pct.std())
            sideways_threshold = max(1.0, gap_std * 0.5)  # 최소 1%

            # BB Width 이력
            sma20 = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_width = (4 * bb_std / sma20 * 100).dropna()
            bb_median = float(bb_width.tail(LOOKBACK_WINDOW).median()) if len(bb_width) >= 50 else 6.0
        else:
            sideways_threshold = 2.0
            bb_median = 6.0
    else:
        sideways_threshold = 2.0
        bb_median = 6.0

    return {
        "vix_threshold": round(vix_median, 1),
        "vix_bear_threshold": round(vix_p75, 1),
        "sideways_pct": round(sideways_threshold, 2),
        "bb_width_threshold": round(bb_median, 2),
    }


# ═══════════════════════════════════════════════════════
# 지표 로딩
# ═══════════════════════════════════════════════════════


def _load_spy_series(date: str | None = None, db_path=None) -> pd.DataFrame | None:
    """SPY 전체 시계열 + 지표 계산."""
    date_filter = f"AND date <= '{date}'" if date else ""
    df = query_df(
        f"SELECT date, close FROM prices WHERE ticker = ? {date_filter} ORDER BY date",
        (MARKET_TICKER,), db_path=db_path,
    )
    if df.empty or len(df) < 200:
        return None

    close = df["close"]
    df["sma50"] = close.rolling(50).mean()
    df["sma200"] = close.rolling(200).mean()
    df["sma20"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_width"] = 4 * bb_std / df["sma20"] * 100

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # SMA50 20일 기울기 (%)
    df["sma50_slope"] = df["sma50"].pct_change(20) * 100

    return df


def _get_vix(date: str | None = None, db_path=None) -> float | None:
    date_filter = f"AND date <= '{date}'" if date else ""
    rows = query(
        f"SELECT value FROM macro WHERE indicator = 'vix' {date_filter} ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    return rows[0]["value"] if rows else None


def _get_fear_greed(date: str | None = None, db_path=None) -> float | None:
    date_filter = f"AND date <= '{date}'" if date else ""
    rows = query(
        f"SELECT value FROM macro WHERE indicator = 'fear_greed' {date_filter} ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    return rows[0]["value"] if rows else None


# ═══════════════════════════════════════════════════════
# 레짐 분류
# ═══════════════════════════════════════════════════════


def _classify_single(close, sma50, sma200, vix, bb_width, thresholds) -> tuple[str, str]:
    """단일 시점의 추세 + 변동성 판별 (히스테리시스 없이)."""
    sma_diff_pct = (sma50 - sma200) / sma200 * 100 if sma200 > 0 else 0
    sideways_th = thresholds["sideways_pct"]

    # 추세 판별: 가격 위치 + SMA 크로스 + sideways 범위
    price_above_sma200 = close > sma200
    sma50_above_sma200 = sma50 > sma200

    if abs(sma_diff_pct) < sideways_th:
        trend = "sideways"
    elif price_above_sma200 and sma50_above_sma200:
        trend = "bull"
    elif not price_above_sma200 and not sma50_above_sma200:
        trend = "bear"
    else:
        trend = "sideways"  # 혼조

    # 변동성 판별
    vix_th = thresholds["vix_bear_threshold"] if trend == "bear" else thresholds["vix_threshold"]
    if vix is not None:
        volatility = "low" if vix < vix_th else "high"
    else:
        bb_th = thresholds["bb_width_threshold"]
        volatility = "low" if bb_width < bb_th else "high"

    return trend, volatility


_freshness_warned = False


def _check_data_freshness(db_path=None) -> bool:
    """SPY 데이터 신선도 체크 (최대 24시간). 주말/공휴일 감안 72시간 허용."""
    global _freshness_warned
    from nuri.core.db import query as _query
    rows = _query(
        "SELECT MAX(date) as latest FROM prices WHERE ticker = 'SPY'",
        db_path=db_path,
    )
    if not rows or not rows[0]["latest"]:
        return False
    from datetime import datetime
    latest = datetime.strptime(rows[0]["latest"], "%Y-%m-%d")
    age_hours = (datetime.now() - latest).total_seconds() / 3600
    # 주말 감안: 금요일 데이터 → 월요일 체크 = 72시간
    if age_hours > 72:
        if not _freshness_warned:
            logger.warning("SPY 데이터 %d시간 경과 (max 72h). 수집 필요: make collect", int(age_hours))
            _freshness_warned = True
        return False
    return True


def classify_regime(date: str | None = None, db_path=None) -> RegimeState | None:
    """시장 레짐 분류 (동적 임계값 + 히스테리시스)."""
    # 데이터 신선도 경고 (차단하지는 않음)
    if date is None:
        _check_data_freshness(db_path)

    spy_df = _load_spy_series(date, db_path)
    if spy_df is None:
        logger.warning("SPY 기술적 데이터 부족 (최소 200일 필요)")
        return None

    thresholds = compute_dynamic_thresholds(db_path, date)
    vix = _get_vix(date, db_path)
    fear_greed = _get_fear_greed(date, db_path)

    latest = spy_df.iloc[-1]
    close = latest["close"]
    sma50 = latest["sma50"]
    sma200 = latest["sma200"]
    rsi = float(latest["rsi"]) if pd.notna(latest["rsi"]) else None
    bb_width = float(latest["bb_width"]) if pd.notna(latest["bb_width"]) else 0
    sma50_slope = float(latest["sma50_slope"]) if pd.notna(latest["sma50_slope"]) else 0

    # ── 적응형 히스테리시스: VIX 25+ 시 2일, 그 외 5일 ──
    hyst_days = HYSTERESIS_DAYS_HIGH_VOL if (vix and vix >= VIX_HIGH_VOL_THRESHOLD) else HYSTERESIS_DAYS
    if len(spy_df) >= hyst_days + 200:
        recent_trends = []
        recent_vols = []
        for i in range(-hyst_days, 0):
            row = spy_df.iloc[i]
            if pd.isna(row["sma50"]) or pd.isna(row["sma200"]):
                continue
            # 각 날짜의 VIX는 최신값으로 근사 (일별 VIX 조회는 비용 큼)
            t, v = _classify_single(
                row["close"], row["sma50"], row["sma200"],
                vix,
                float(row["bb_width"]) if pd.notna(row["bb_width"]) else 0,
                thresholds,
            )
            recent_trends.append(t)
            recent_vols.append(v)

        if recent_trends:
            # 다수결
            from collections import Counter
            trend_counts = Counter(recent_trends)
            vol_counts = Counter(recent_vols)
            trend = trend_counts.most_common(1)[0][0]
            volatility = vol_counts.most_common(1)[0][0]
        else:
            trend, volatility = _classify_single(close, sma50, sma200, vix, bb_width, thresholds)
    else:
        trend, volatility = _classify_single(close, sma50, sma200, vix, bb_width, thresholds)

    regime = f"{trend}_{volatility}_vol"
    sma_diff_pct = (sma50 - sma200) / sma200 * 100 if sma200 > 0 else 0

    # ── 신뢰도: 보조 지표 일치도 ──
    checks = []

    # 1. Fear & Greed
    if fear_greed is not None:
        if trend == "bull":
            checks.append(fear_greed > 40)
        elif trend == "bear":
            checks.append(fear_greed < 40)
        else:
            checks.append(25 <= fear_greed <= 75)

    # 2. RSI
    if rsi is not None:
        if trend == "bull":
            checks.append(rsi > 45)
        elif trend == "bear":
            checks.append(rsi < 55)
        else:
            checks.append(35 <= rsi <= 65)

    # 3. SMA50 기울기
    if trend == "bull":
        checks.append(sma50_slope > 0)
    elif trend == "bear":
        checks.append(sma50_slope < 0)
    else:
        checks.append(abs(sma50_slope) < thresholds["sideways_pct"])

    # 4. VIX-BB Width 교차 검증
    if vix is not None:
        vix_th = thresholds["vix_bear_threshold"] if trend == "bear" else thresholds["vix_threshold"]
        vix_says_high = vix >= vix_th
        bb_says_high = bb_width >= thresholds["bb_width_threshold"]
        checks.append(vix_says_high == bb_says_high)

    confidence = sum(checks) / len(checks) if checks else 0.5

    return RegimeState(
        date=spy_df["date"].iloc[-1],
        trend=trend,
        volatility=volatility,
        regime=regime,
        confidence=round(confidence, 2),
        details={
            "spy_close": round(float(close), 2),
            "sma50": round(float(sma50), 2),
            "sma200": round(float(sma200), 2),
            "sma_diff_pct": round(sma_diff_pct, 2),
            "vix": round(vix, 2) if vix else None,
            "fear_greed": round(fear_greed, 1) if fear_greed else None,
            "rsi": round(rsi, 1) if rsi else None,
            "bb_width": round(bb_width, 2),
            "thresholds": thresholds,
        },
    )


def classify_regime_history(
    start_date: str | None = None,
    end_date: str | None = None,
    db_path=None,
) -> list[RegimeState]:
    """기간별 레짐 이력 (월말 샘플링)."""
    date_filter = ""
    if start_date:
        date_filter += f" AND date >= '{start_date}'"
    if end_date:
        date_filter += f" AND date <= '{end_date}'"

    dates = query(
        f"SELECT DISTINCT date FROM prices WHERE ticker = ? {date_filter} ORDER BY date",
        (MARKET_TICKER,), db_path=db_path,
    )
    if not dates:
        return []

    all_dates = [d["date"] for d in dates]

    # 월말 날짜 추출
    seen_months = set()
    monthly_dates = []
    for d in reversed(all_dates):
        month = d[:7]
        if month not in seen_months:
            seen_months.add(month)
            monthly_dates.append(d)
    monthly_dates.reverse()

    history = []
    for d in monthly_dates:
        state = classify_regime(date=d, db_path=db_path)
        if state:
            history.append(state)

    return history


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


def print_regime(state: RegimeState | None) -> None:
    if state is None:
        print("레짐 분류 불가 (데이터 부족)")
        return

    trend_label = {"bull": "BULL", "bear": "BEAR", "sideways": "SIDEWAYS"}
    vol_label = {"high": "HIGH VOL", "low": "LOW VOL"}
    d = state.details
    th = d.get("thresholds", {})

    print(f"\n{'=' * 60}")
    print(f"  Market Regime: {trend_label[state.trend]} + {vol_label[state.volatility]}")
    print(f"  ({state.regime})  Confidence: {state.confidence:.0%}")
    print(f"{'=' * 60}")
    print(f"  Date:       {state.date}")
    print(f"  SPY:        ${d['spy_close']:,.2f}")
    print(f"  SMA50:      ${d['sma50']:,.2f}")
    print(f"  SMA200:     ${d['sma200']:,.2f}")
    print(f"  SMA Gap:    {d['sma_diff_pct']:+.1f}%")
    if d.get("vix") is not None:
        print(f"  VIX:        {d['vix']:.1f}")
    if d.get("fear_greed") is not None:
        print(f"  Fear&Greed: {d['fear_greed']:.0f}")
    if d.get("rsi") is not None:
        print(f"  RSI:        {d['rsi']:.1f}")
    if th:
        print(f"  --- Dynamic Thresholds (from {LOOKBACK_WINDOW}d history) ---")
        print(f"  VIX th:     {th.get('vix_threshold', '?')} / bear: {th.get('vix_bear_threshold', '?')}")
        print(f"  Sideways:   ±{th.get('sideways_pct', '?')}%")
        print(f"  BB Width:   {th.get('bb_width_threshold', '?')}")
    print()


def print_history(history: list[RegimeState]) -> None:
    if not history:
        print("레짐 이력 없음")
        return

    print(f"\n{'=' * 70}")
    print(f"  Market Regime History ({len(history)} months)")
    print(f"{'=' * 70}")
    print(f"  {'Date':<12} {'Regime':<22} {'Conf':>5} {'SPY':>10} {'VIX':>6} {'F&G':>5}")
    print(f"  {'-' * 62}")

    for s in history:
        d = s.details
        vix = f"{d['vix']:.0f}" if d.get("vix") else "—"
        fg = f"{d['fear_greed']:.0f}" if d.get("fear_greed") else "—"
        print(f"  {s.date:<12} {s.regime:<22} {s.confidence:>4.0%} "
              f"${d['spy_close']:>8,.2f} {vix:>6} {fg:>5}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 시장 레짐 분류기")
    parser.add_argument("--history", action="store_true", help="레짐 이력 출력")
    parser.add_argument("--start", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", help="종료일 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.history:
        history = classify_regime_history(start_date=args.start, end_date=args.end)
        print_history(history)

        if history:
            today = datetime.now().strftime("%Y-%m-%d")
            output_dir = REPORT_DIR / today
            output_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([asdict(s) for s in history]).to_csv(
                output_dir / "regime_history.csv", index=False
            )
    else:
        state = classify_regime()
        print_regime(state)
