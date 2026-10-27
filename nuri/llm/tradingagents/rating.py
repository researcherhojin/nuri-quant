"""5단계 등급 — 원본 `tradingagents/agents/rating.py` · `agents/schemas.py` (e8f5503).

바꾼 점 (Modified):
- 등급 enum(`PortfolioRating`)과 `REVIEW` 표식만 가져온다. 자유 텍스트에서 등급을 읽는
  `extract_rating` 은 가져오지 않는다 — 우리는 구조화 출력만 받고, 읽을 수 없으면 `REVIEW` 다(원본 #1170 의 규칙).
- `RECOMMENDATION_GUIDE` 는 원본 `ResearchPlan.recommendation` 필드 설명을 그대로 옮긴 문자열이다.
"""

from __future__ import annotations

from enum import StrEnum


class PortfolioRating(StrEnum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


# Signal emitted when the model's decision has no recognizable rating. It is not
# a tradeable position: it flags output that needs a human/re-run rather than
# silently degrading to Hold.
RATING_REVIEW = "REVIEW"

RECOMMENDATION_GUIDE = (
    "The investment recommendation. Exactly one of Buy / Overweight / "
    "Hold / Underweight / Sell. Conflicting arguments alone are not a "
    "reason to Hold: commit to the stronger side, sized by how "
    "decisively it wins. Choose Hold only when the evidence is still "
    "balanced after weighing, or too thin to support a call."
)

