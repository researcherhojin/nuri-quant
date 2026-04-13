"""
B1: 매크로 이벤트 스코어 — macro_events 테이블 → -20~+20 adjustment.

macro_score.py의 9번째 입력으로 사용.
이벤트 0건 → score 0 (기존 macro_score 영향 없음).

사용법:
    python -m nuri.quant.regime.event_score
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from nuri.core.db import query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

# 카테고리별 방향 가중치 (-1.0 ~ +1.0).
# 양수 = 시장 우호적 (macro_score 상승), 음수 = 시장 비우호적 (하락).
# event_classifier.py의 CATEGORIES와 동기화.
CATEGORY_WEIGHT: dict[str, float] = {
    "geopolitical_escalation": -0.8,
    "geopolitical_de_escalation": 0.7,
    "fed_dovish": 0.6,
    "fed_hawkish": -0.5,
    "oil_supply_shock": -0.4,
    "oil_demand_drop": -0.3,
    "earnings_beat": 0.5,
    "earnings_miss": -0.5,
    "sector_rally": 0.4,
    "sector_selloff": -0.6,
    "trade_war": -0.7,
    "neutral": 0.0,
}

# 최근 N일간 이벤트만 반영
LOOKBACK_DAYS = 3

# 최종 스코어 클램프 범위
SCORE_MIN = -20.0
SCORE_MAX = 20.0

# 이 신뢰도 미만의 이벤트는 스코어 계산에서 제외 — 노이즈 방지 (#137)
CONFIDENCE_FLOOR = 0.3


@dataclass
class EventScore:
    """매크로 이벤트 종합 점수."""
    date: str
    score: float              # -20 ~ +20
    event_count: int          # 분석 이벤트 수
    category_breakdown: dict  # {category: contribution}
    dominant_category: str | None  # 가장 영향력 큰 카테고리
    regime_hint: str | None   # dominant category의 regime hint


def compute_event_score(
    lookback_days: int = LOOKBACK_DAYS,
    date: str | None = None,
    db_path: Optional[Path] = None,
) -> EventScore:
    """macro_events 테이블에서 최근 이벤트를 읽어 종합 점수 산출.

    각 이벤트의 기여 = category_weight × sentiment × confidence.
    전체 합산 후 [-20, +20] 범위로 클램프.

    이벤트 0건 → score 0 (기존 macro_score 영향 없음).
    """
    ref_date = date or today_kst()

    rows = query(
        """
        SELECT category, sentiment, confidence, regime_hint
        FROM macro_events
        WHERE published_at >= date(?, '-' || ? || ' days')
          AND category IS NOT NULL
        ORDER BY published_at DESC
        """,
        (ref_date, str(lookback_days)),
        db_path=db_path,
    )

    if not rows:
        return EventScore(
            date=ref_date, score=0.0, event_count=0,
            category_breakdown={}, dominant_category=None, regime_hint=None,
        )

    # 저신뢰 이벤트 필터링 — regex fallback이나 분류 실패로 인한 노이즈 제거
    filtered = [r for r in rows if (r["confidence"] or 0.0) >= CONFIDENCE_FLOOR]
    if len(filtered) < len(rows):
        logger.debug("이벤트 %d건 중 %d건 신뢰도 미달 제외 (< %.1f)", len(rows), len(rows) - len(filtered), CONFIDENCE_FLOOR)

    # 카테고리별 기여 합산
    breakdown: dict[str, float] = {}
    for row in filtered:
        cat = row["category"]
        sentiment = row["sentiment"] or 0.0
        confidence = row["confidence"] or 0.5
        weight = CATEGORY_WEIGHT.get(cat, 0.0)

        # 기여 = 방향 가중치 × |감성| × 신뢰도
        # 카테고리 방향(weight)이 이미 부호를 내포하므로,
        # sentiment은 강도(절대값)만 사용. 이중 부정 방지.
        intensity = abs(sentiment) if abs(sentiment) > 0.01 else 0.5
        contribution = weight * intensity * confidence

        breakdown[cat] = breakdown.get(cat, 0.0) + contribution

    # 합산 → 스케일링 → 클램프
    raw_sum = sum(breakdown.values())
    # 이벤트 수가 많을수록 효과 감소 (diminishing returns)
    # √(event_count)로 정규화하여 1개 이벤트와 100개 이벤트의 차이를 줄임
    event_count = len(filtered)
    normalized = raw_sum / (event_count ** 0.5) if event_count > 0 else 0.0

    # 20점 스케일로 변환 (경험적 스케일링 팩터)
    score = normalized * 40.0
    score = max(SCORE_MIN, min(SCORE_MAX, score))

    # dominant category 결정
    dominant = max(breakdown, key=lambda k: abs(breakdown[k])) if breakdown else None
    regime_hint = None
    if dominant:
        from nuri.llm.event_classifier import REGIME_HINT_BY_CATEGORY
        regime_hint = REGIME_HINT_BY_CATEGORY.get(dominant)

    return EventScore(
        date=ref_date,
        score=round(score, 1),
        event_count=event_count,
        category_breakdown={k: round(v, 3) for k, v in breakdown.items()},
        dominant_category=dominant,
        regime_hint=regime_hint,
    )


def print_event_score(es: EventScore) -> None:
    """이벤트 스코어 CLI 출력."""
    print(f"\n{'=' * 50}")
    print(f"  Event Score: {es.score:+.1f} ({es.event_count} events)")
    print(f"{'=' * 50}")
    print(f"  Date:      {es.date}")
    if es.dominant_category:
        print(f"  Dominant:  {es.dominant_category} → {es.regime_hint or 'none'}")
    if es.category_breakdown:
        print("  Breakdown:")
        for cat, val in sorted(es.category_breakdown.items(), key=lambda x: -abs(x[1])):
            direction = "+" if val > 0 else ""
            print(f"    {cat:35s} {direction}{val:.3f}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    es = compute_event_score()
    print_event_score(es)
