"""보유 종목의 자산군 분류 — `config/rules.yaml asset_class_rules` 의 유일한 실행기.

측정 모드(STRATEGY §3.11)의 벤치마크 분류(`nuri/agents/actors/forward_outcome_tracker.py`),
전략 배분(`nuri/trading/strategy/strategic_allocation.py`), 그리고 폐기 전까지의 SIEGE
인증기(`nuri/trading/engine/certification.py`)가 같은 함수를 쓴다. 사본을 두면 두 분류가
갈라진다 — 분류가 어긋나면 결정 행의 벤치마크가 바뀌어 사전등록된 알파 측정이 오염된다.

#1619 PR 2: `certification.py` 에서 옮겼다. 인증기는 폐기되지만 분류는 남는다.
`nuri/trading/recommend/holdings_monitor.py` 의 `_classify_asset_class` 는 통화 기반의 다른
체계(`equity_us` / `equity_kr` / `crypto`)라 이 함수와 무관하다.
"""

from __future__ import annotations


def classify_asset_class(ticker: str, sector: str, rules: list[dict]) -> str:
    """보유 종목을 asset_class 로 분류.

    `rules` 는 `RULES["asset_class_rules"]` — 위에서부터 first-match. 더 구체적인 rule 이
    위에 있어야 하며 `default` 는 마지막. match key: sector_prefix / ticker_suffix / sector / default.
    """
    sector = sector or ""
    for rule in rules:
        m = rule.get("match", {})
        if m.get("default"):
            return rule["asset_class"]
        if "sector_prefix" in m and sector.startswith(m["sector_prefix"]):
            return rule["asset_class"]
        if "ticker_suffix" in m and ticker.endswith(m["ticker_suffix"]):
            return rule["asset_class"]
        if "sector" in m and sector == m["sector"]:
            return rule["asset_class"]
    return "us_equity"  # safety net — YAML 에 default rule 없을 때
