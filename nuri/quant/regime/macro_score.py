"""
D-2: 매크로 스코어 — 거시경제 건강도 0~100 점수.

매크로 지표 8개를 개별 점수화 후 가중 합산.
- 기존 6개: yield_curve(2Y-10Y), VIX, sentiment, employment, inflation, monetary
- 추가 2개: yield_spread_3m10y(3M-10Y, 경기침체 예측), put_call_ratio(옵션 심리)

사용법:
    python -m nuri.quant.regime.macro_score
"""
import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from nuri.core.db import query

logger = logging.getLogger(__name__)

# 가중치 (총합 1.0)
# 기존 6개 비중 축소 + 신규 2개 (yield_spread_3m10y, put_call_ratio) 추가
WEIGHTS = {
    "yield_curve": 0.15,          # 10Y-2Y (기존, 0.20→0.15)
    "yield_spread_3m10y": 0.10,   # 3M-10Y (신규, 경기침체 예측력 ↑)
    "vix": 0.17,                  # VIX (기존, 0.20→0.17)
    "put_call_ratio": 0.08,       # CBOE PCR (신규, 옵션 심리)
    "sentiment": 0.12,            # F&G (기존, 0.15→0.12)
    "employment": 0.13,           # 실업률 (기존, 0.15→0.13)
    "inflation": 0.13,            # CPI (기존, 0.15→0.13)
    "monetary": 0.12,             # FFR (기존, 0.15→0.12)
}


@dataclass
class MacroScore:
    """거시경제 종합 점수."""
    date: str
    total_score: float          # 0~100
    yield_curve_score: float
    yield_spread_3m10y_score: float
    vix_score: float
    put_call_ratio_score: float
    sentiment_score: float
    employment_score: float
    inflation_score: float
    monetary_score: float
    interpretation: str         # "Favorable", "Neutral", "Cautious", "Adverse"
    details: dict               # 원본 지표 값
    warnings: list[str] | None = None  # 누락된 지표 경고 목록


def _get_latest_macro(indicator: str, date: str | None = None, db_path=None) -> float | None:
    """macro 테이블에서 최신값 로드."""
    date_filter = f"AND date <= '{date}'" if date else ""
    rows = query(
        f"SELECT value FROM macro WHERE indicator = ? {date_filter} ORDER BY date DESC LIMIT 1",
        (indicator,), db_path=db_path,
    )
    return rows[0]["value"] if rows else None


def _get_macro_trend(indicator: str, months: int = 3, date: str | None = None, db_path=None) -> float | None:
    """지표의 N개월 변화량."""
    ref_date = date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(ref_date, "%Y-%m-%d") - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    current = _get_latest_macro(indicator, date=ref_date, db_path=db_path)
    past = _get_latest_macro(indicator, date=start, db_path=db_path)

    if current is not None and past is not None:
        return current - past
    return None


def _score_yield_curve(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """수익률곡선 점수 (10Y - 2Y spread)."""
    y10 = _get_latest_macro("us_10y_yield", date, db_path)
    y2 = _get_latest_macro("us_2y_yield", date, db_path)

    if y10 is None or y2 is None:
        return 50.0, {"10y": y10, "2y": y2, "spread": None}

    spread = y10 - y2

    # 정상(>0.5) = 100, 평탄(0~0.5) = 50~100, 역전(<0) = 0~50
    if spread > 1.0:
        score = 100.0
    elif spread > 0.5:
        score = 75 + (spread - 0.5) / 0.5 * 25
    elif spread > 0:
        score = 50 + spread / 0.5 * 25
    elif spread > -0.5:
        score = 25 + (spread + 0.5) / 0.5 * 25
    else:
        score = max(0, 25 + spread * 25)

    return min(100, max(0, score)), {"10y": y10, "2y": y2, "spread": round(spread, 2)}


def _score_vix(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """VIX 점수."""
    vix = _get_latest_macro("vix", date, db_path)
    if vix is None:
        return 50.0, {"vix": None}

    # VIX <12 = 100, 12~15 = 80~100, 15~20 = 60~80, 20~30 = 20~60, >30 = 0~20
    if vix < 12:
        score = 100.0
    elif vix < 15:
        score = 80 + (15 - vix) / 3 * 20
    elif vix < 20:
        score = 60 + (20 - vix) / 5 * 20
    elif vix < 30:
        score = 20 + (30 - vix) / 10 * 40
    else:
        score = max(0, 20 - (vix - 30))

    return min(100, max(0, score)), {"vix": round(vix, 1)}


def _score_sentiment(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """Fear & Greed 점수 (극단값에 페널티)."""
    fg = _get_latest_macro("fear_greed", date, db_path)
    if fg is None:
        return 50.0, {"fear_greed": None}

    # 40~60 = 최적 (80~100), 극단(0~20 또는 80~100) = 저조
    if 40 <= fg <= 60:
        score = 80 + (1 - abs(fg - 50) / 10) * 20
    elif 25 <= fg < 40:
        score = 50 + (fg - 25) / 15 * 30
    elif 60 < fg <= 75:
        score = 50 + (75 - fg) / 15 * 30
    elif fg < 25:
        score = fg / 25 * 50
    else:  # fg > 75
        score = (100 - fg) / 25 * 50

    return min(100, max(0, score)), {"fear_greed": round(fg, 1)}


def _score_employment(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """실업률 점수 (낮으면 좋고, 상승 추세면 나쁨)."""
    unemp = _get_latest_macro("unemployment", date, db_path)
    trend = _get_macro_trend("unemployment", months=3, date=date, db_path=db_path)

    if unemp is None:
        return 50.0, {"unemployment": None, "trend": None}

    # 실업률 수준: <4% = 좋음, 4-6% = 보통, >6% = 나쁨
    if unemp < 3.5:
        level_score = 100
    elif unemp < 4.5:
        level_score = 70 + (4.5 - unemp) * 30
    elif unemp < 6.0:
        level_score = 30 + (6.0 - unemp) / 1.5 * 40
    else:
        level_score = max(0, 30 - (unemp - 6) * 10)

    # 추세 보정: 상승하면 감점, 하락하면 가점
    trend_adj = 0
    if trend is not None:
        trend_adj = -trend * 20  # 0.5%p 상승 → -10점

    score = level_score + trend_adj
    return min(100, max(0, score)), {"unemployment": unemp, "trend_3m": round(trend, 2) if trend else None}


def _score_inflation(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """CPI 점수 (2% 타겟 대비)."""
    cpi = _get_latest_macro("cpi_yoy", date, db_path)
    if cpi is None:
        return 50.0, {"cpi_yoy": None}

    # 1.5~2.5% = 최적 (90~100), 0~1.5% 또는 2.5~4% = 보통, >5% = 나쁨
    target = 2.0
    deviation = abs(cpi - target)

    if deviation < 0.5:
        score = 90 + (0.5 - deviation) / 0.5 * 10
    elif deviation < 1.5:
        score = 60 + (1.5 - deviation) / 1.0 * 30
    elif deviation < 3.0:
        score = 20 + (3.0 - deviation) / 1.5 * 40
    else:
        score = max(0, 20 - (deviation - 3) * 5)

    # 디플레이션(<0%)은 추가 감점
    if cpi < 0:
        score = min(score, 20)

    return min(100, max(0, score)), {"cpi_yoy": round(cpi, 2)}


def _score_monetary(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """금리정책 점수 (인하 우호, 인상 비우호)."""
    fed = _get_latest_macro("fed_funds_rate", date, db_path)
    # fallback: fed_funds_rate 없으면 us_2y_yield (13-week T-Bill) 사용
    if fed is None:
        fed = _get_latest_macro("us_2y_yield", date, db_path)
    trend = _get_macro_trend("fed_funds_rate", months=6, date=date, db_path=db_path)
    if trend is None:
        trend = _get_macro_trend("us_2y_yield", months=6, date=date, db_path=db_path)

    if fed is None:
        return 50.0, {"fed_funds": None, "trend": None}

    # 절대 수준: <2% = 완화적, 2~4% = 보통, >4% = 긴축적
    if fed < 1.0:
        level_score = 90
    elif fed < 2.5:
        level_score = 70 + (2.5 - fed) / 1.5 * 20
    elif fed < 4.0:
        level_score = 40 + (4.0 - fed) / 1.5 * 30
    elif fed < 5.5:
        level_score = 20 + (5.5 - fed) / 1.5 * 20
    else:
        level_score = max(0, 20 - (fed - 5.5) * 10)

    # 추세: 인하 중(-)이면 가점, 인상 중(+)이면 감점
    trend_adj = 0
    if trend is not None:
        trend_adj = -trend * 15  # 1%p 인상 → -15점

    score = level_score + trend_adj
    return min(100, max(0, score)), {"fed_funds": fed, "trend_6m": round(trend, 2) if trend else None}


def _score_yield_spread_3m10y(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """3M-10Y 수익률 스프레드 점수 (경기침체 예측 지표).

    연구: 3M-10Y 스프레드가 2Y-10Y보다 경기침체 예측력이 높음 (NY Fed 모델).
    역전(< 0) 시 6-18개월 내 경기침체 확률 상승.
    """
    y10 = _get_latest_macro("us_10y_yield", date, db_path)
    y3m = _get_latest_macro("us_3m_yield", date, db_path)

    if y10 is None or y3m is None:
        return 50.0, {"3m": y3m, "spread_3m10y": None}

    spread = y10 - y3m

    # 정상(>1.0) = 100, 평탄(0~1.0) = 50~100, 역전(<0) = 0~50
    if spread > 1.5:
        score = 100.0
    elif spread > 1.0:
        score = 85 + (spread - 1.0) / 0.5 * 15
    elif spread > 0.5:
        score = 65 + (spread - 0.5) / 0.5 * 20
    elif spread > 0:
        score = 50 + spread / 0.5 * 15
    elif spread > -0.5:
        # 역전 초기: 강한 경고
        score = 20 + (spread + 0.5) / 0.5 * 30
    else:
        # 깊은 역전: 경기침체 임박
        score = max(0, 20 + spread * 20)

    return min(100, max(0, score)), {"3m": y3m, "spread_3m10y": round(spread, 2)}


def _score_put_call_ratio(db_path=None, date: str | None = None) -> tuple[float, dict]:
    """CBOE Put/Call Ratio 점수 (옵션 시장 심리 지표).

    PCR은 역발상 지표로 해석:
    - PCR > 1.0: 풋 과매수 → 공포 극단 → 반등 가능 (역발상 강세)
    - PCR 0.7~1.0: 정상 범위
    - PCR < 0.7: 콜 과매수 → 탐욕 극단 → 조정 가능 (역발상 약세)

    중립 구간(0.8~0.95)에서 최고점, 극단값에서 감점.
    """
    pcr = _get_latest_macro("put_call_ratio", date, db_path)

    if pcr is None:
        return 50.0, {"put_call_ratio": None}

    # 중립 구간 (0.80~0.95) = 최적 (85~100)
    if 0.80 <= pcr <= 0.95:
        score = 85 + (1 - abs(pcr - 0.875) / 0.075) * 15
    elif 0.70 <= pcr < 0.80:
        # 콜 매수 증가 → 약한 탐욕
        score = 65 + (pcr - 0.70) / 0.10 * 20
    elif 0.95 < pcr <= 1.10:
        # 풋 매수 증가 → 약한 공포
        score = 65 + (1.10 - pcr) / 0.15 * 20
    elif pcr < 0.70:
        # 과도한 탐욕 → 조정 경고
        score = max(20, 65 - (0.70 - pcr) * 150)
    else:
        # PCR > 1.10: 과도한 공포 → 항복 매도 → 역발상 반등 가능
        # 패닉 자체는 위험하므로 점수 낮게, 하지만 극단 공포는 바닥 신호일 수 있음
        score = max(15, 65 - (pcr - 1.10) * 100)

    return min(100, max(0, score)), {"put_call_ratio": round(pcr, 3)}


# ═══════════════════════════════════════════════════════
# 종합 스코어
# ═══════════════════════════════════════════════════════


def compute_macro_score(date: str | None = None, db_path=None) -> MacroScore:
    """거시경제 종합 점수 계산 (8개 지표)."""
    yc_score, yc_detail = _score_yield_curve(db_path, date)
    ys3m10y_score, ys3m10y_detail = _score_yield_spread_3m10y(db_path, date)
    vix_score, vix_detail = _score_vix(db_path, date)
    pcr_score, pcr_detail = _score_put_call_ratio(db_path, date)
    sent_score, sent_detail = _score_sentiment(db_path, date)
    emp_score, emp_detail = _score_employment(db_path, date)
    inf_score, inf_detail = _score_inflation(db_path, date)
    mon_score, mon_detail = _score_monetary(db_path, date)

    # 누락 지표 감지: 50점(중립) 폴백 시 원본 데이터가 None이면 경고
    warnings: list[str] = []
    _MISSING_CHECKS: list[tuple[str, float, dict, list[str]]] = [
        ("yield_curve", yc_score, yc_detail, ["10y", "2y"]),
        ("yield_spread_3m10y", ys3m10y_score, ys3m10y_detail, ["3m", "spread_3m10y"]),
        ("vix", vix_score, vix_detail, ["vix"]),
        ("put_call_ratio", pcr_score, pcr_detail, ["put_call_ratio"]),
        ("sentiment", sent_score, sent_detail, ["fear_greed"]),
        ("employment", emp_score, emp_detail, ["unemployment"]),
        ("inflation", inf_score, inf_detail, ["cpi_yoy"]),
        ("monetary", mon_score, mon_detail, ["fed_funds"]),
    ]
    for name, score, detail, keys in _MISSING_CHECKS:
        if score == 50.0 and any(detail.get(k) is None for k in keys):
            missing_keys = [k for k in keys if detail.get(k) is None]
            msg = f"{name}: 데이터 누락 ({', '.join(missing_keys)}) → 중립 50점 사용"
            warnings.append(msg)
            logger.debug("매크로 지표 누락 — %s", msg)  # debug로 변경 (매 호출마다 반복 방지)

    total = (
        yc_score * WEIGHTS["yield_curve"]
        + ys3m10y_score * WEIGHTS["yield_spread_3m10y"]
        + vix_score * WEIGHTS["vix"]
        + pcr_score * WEIGHTS["put_call_ratio"]
        + sent_score * WEIGHTS["sentiment"]
        + emp_score * WEIGHTS["employment"]
        + inf_score * WEIGHTS["inflation"]
        + mon_score * WEIGHTS["monetary"]
    )

    if total >= 70:
        interpretation = "Favorable"
    elif total >= 50:
        interpretation = "Neutral"
    elif total >= 30:
        interpretation = "Cautious"
    else:
        interpretation = "Adverse"

    return MacroScore(
        date=date or datetime.now().strftime("%Y-%m-%d"),
        total_score=round(total, 1),
        yield_curve_score=round(yc_score, 1),
        yield_spread_3m10y_score=round(ys3m10y_score, 1),
        vix_score=round(vix_score, 1),
        put_call_ratio_score=round(pcr_score, 1),
        sentiment_score=round(sent_score, 1),
        employment_score=round(emp_score, 1),
        inflation_score=round(inf_score, 1),
        monetary_score=round(mon_score, 1),
        interpretation=interpretation,
        details={**yc_detail, **ys3m10y_detail, **vix_detail, **pcr_detail,
                 **sent_detail, **emp_detail, **inf_detail, **mon_detail},
        warnings=warnings if warnings else None,
    )


def print_macro_score(score: MacroScore) -> None:
    """매크로 스코어 CLI 출력."""
    print(f"\n{'=' * 55}")
    print(f"  Macro Score: {score.total_score:.0f}/100 — {score.interpretation}")
    print(f"{'=' * 55}")
    print(f"  Date:             {score.date}")
    print(f"  Yield Curve:      {score.yield_curve_score:5.1f}  (2Y-10Y: {score.details.get('spread', '—')})")
    print(f"  Yield 3M-10Y:     {score.yield_spread_3m10y_score:5.1f}  (3M-10Y: {score.details.get('spread_3m10y', '—')})")
    print(f"  VIX:              {score.vix_score:5.1f}  ({score.details.get('vix', '—')})")
    print(f"  Put/Call Ratio:   {score.put_call_ratio_score:5.1f}  (PCR: {score.details.get('put_call_ratio', '—')})")
    print(f"  Sentiment:        {score.sentiment_score:5.1f}  (F&G: {score.details.get('fear_greed', '—')})")
    print(f"  Employment:       {score.employment_score:5.1f}  (unemp: {score.details.get('unemployment', '—')}%)")
    print(f"  Inflation:        {score.inflation_score:5.1f}  (CPI: {score.details.get('cpi_yoy', '—')}%)")
    print(f"  Monetary:         {score.monetary_score:5.1f}  (FFR: {score.details.get('fed_funds', '—')}%)")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 매크로 스코어")
    parser.add_argument("--date", help="특정 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()

    score = compute_macro_score(date=args.date)
    print_macro_score(score)
