"""섹터 문자열 → defensive / growth / neutral 분류 (#920).

`portfolio.yaml` 의 sector 필드는 자유 문자열("Technology", "Finance", "AI/Cloud",
"헬스케어" …)이라 정확 매칭이 아니라 키워드 포함으로 판정한다.

**여기 사는 이유**: 이 분류는 어느 한 단계의 로직이 아니라 여러 단계가 공유하는
어휘다. 원래 `nuri/trading/recommend/rebalance.py` 의 private `_classify_sector`
였고, `nuri/trading/agents/macro_agent.py` 가 그 밑줄 이름을 건너와 import 하고
있었다 — consensus 단계가 track 단계의 비공개 API 에 의존하는 형태였다. 공용
어휘를 `nuri/core/` 로 올리면 그 교차 의존이 사라지고, 밑줄을 뗀 공개 이름이 된다.
"""

from __future__ import annotations

DEFENSIVE_SECTOR_KEYWORDS = {
    "Staples",
    "Utilities",
    "Health",
    "Real Estate",
    "Insurance",
    "Bond",
    "Defense",
    "Pharma",
}

GROWTH_SECTOR_KEYWORDS = {
    "Technology",
    "Tech",
    "AI",
    "Cloud",
    "EV",
    "Semiconductor",
    "Software",
    "Consumer Discretionary",
    "Communication",
    "Growth",
    "Innovation",
}


def classify_sector(sector: str) -> str:
    """섹터 문자열을 defensive / growth / neutral 로 분류.

    defensive 를 먼저 본다 — "Consumer Staples" 는 두 목록의 키워드를 모두
    포함하지만(Staples / Consumer Discretionary 의 Consumer 는 아니지만
    유사 케이스가 생길 수 있다) 방어 성격이 우선이다. 어느 쪽에도 안 걸리면
    neutral 이며, 빈 문자열도 neutral 이다.
    """
    if not sector:
        return "neutral"
    upper = sector.upper()
    for kw in DEFENSIVE_SECTOR_KEYWORDS:
        if kw.upper() in upper:
            return "defensive"
    for kw in GROWTH_SECTOR_KEYWORDS:
        if kw.upper() in upper:
            return "growth"
    return "neutral"
