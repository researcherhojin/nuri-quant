"""Agent registry + default weights.

`build_all_agents()` is preferred over a module-level mutable list — but the
package root re-binds `ALL_AGENTS = build_all_agents()` for monkeypatch
compatibility (tests do `monkeypatch.setattr(consensus, "ALL_AGENTS", [...])`).
"""

from __future__ import annotations

from nuri.trading.agents.crypto_agent import CryptoAgent
from nuri.trading.agents.fundamental import FundamentalAgent
from nuri.trading.agents.korean_market import KoreanMarketAgent
from nuri.trading.agents.macro_agent import MacroAgent
from nuri.trading.agents.options_agent import OptionsAgent
from nuri.trading.agents.retail_agent import RetailAgent
from nuri.trading.agents.risk_agent import RiskAgent
from nuri.trading.agents.smart_money import SmartMoneyAgent
from nuri.trading.agents.technical import TechnicalAgent
from nuri.trading.agents.wallstreet import WallStreetAgent

__all__ = ["DEFAULT_WEIGHTS", "build_all_agents"]


# 기본 가중치 (과거 데이터 없을 때)
# 7→10 에이전트 확장: 기존 에이전트 비중 소폭 하향, 신규 3개 배분
DEFAULT_WEIGHTS = {
    "technical": 0.152,  # 16→15.2 (×0.95)
    "fundamental": 0.114,  # 12→11.4
    "macro": 0.114,  # 12→11.4
    "risk": 0.19,  # 20→19 (거부권 유지)
    "smart_money": 0.076,  # 8→7.6
    "wallstreet": 0.105,  # 11→10.5
    "korean_market": 0.076,  # 8→7.6 (.KS 종목에서만 실질 영향)
    "options": 0.076,  # 8→7.6
    "crypto": 0.047,  # 5→4.7
    "retail": 0.05,  # 0→5% 활성화: WSB 역발상 시그널
}


def build_all_agents():
    """Construct fresh agent instances. Each call returns a new list."""
    return [
        TechnicalAgent(),
        FundamentalAgent(),
        MacroAgent(),
        RiskAgent(),
        SmartMoneyAgent(),
        WallStreetAgent(),
        KoreanMarketAgent(),
        OptionsAgent(),
        CryptoAgent(),
        RetailAgent(),
    ]
