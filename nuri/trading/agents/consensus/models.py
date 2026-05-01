"""Consensus data shapes — output type + Learning Memory eligibility state.

Extracted from consensus.py P2.1 split (codex Round 1 layout). No behavior here.
"""

from __future__ import annotations

from dataclasses import dataclass

from nuri.trading.agents.base import AgentVerdict

__all__ = ["ConsensusResult", "AgentEligibility"]


@dataclass
class ConsensusResult:
    """멀티 에이전트 합의 결과."""

    ticker: str
    final_action: str  # "BUY", "SELL", "HOLD"
    final_confidence: float  # 0~100
    agreement_rate: float  # 0~1 (동일 action 비율)
    verdicts: list[AgentVerdict]
    dissent: list[str]  # 반대 의견 에이전트 목록
    reasoning: str  # 합의 근거 요약
    divergence_flag: bool = False  # TechnicalAgent 가 합의 BUY/SELL 에 정면 반대 (#5.10 JKHY 방지)
    divergence_reason: str = ""  # flag 가 True 일 때 사용자에게 노출할 설명
    # Mechanical penalty 감사 필드 — caller 가 `consensus_penalty_applied` 이벤트 emit 시 사용.
    penalty_applied: bool = False  # True 면 divergence penalty 로 action 이 downgrade 됨
    pre_penalty_action: str = ""  # penalty 발동 전 원 action (BUY/SELL). flag=False 이면 빈 문자열.
    # Phase 2 A-2a: per-agent contribution breakdown. `save_to_recommendations` 가
    # JSON 직렬화해 recommendations.scoring_detail 에 persist. 이전에는 None 이라
    # API/frontend 가 "왜 이 판정이 나왔는지" 를 reconstruct 할 수 없었음.
    scoring_detail: dict | None = None


@dataclass
class AgentEligibility:
    """Per-agent state at a single outcome horizon (canonical 30d or provisional 21d).

    #468 codex Plan consult Round 1 — structural separation: canonical vs provisional
    return identical shapes so `select_weight_source` can run per-agent precedence.
    """

    name: str
    sample_count: int  # BUY/SELL verdicts with non-null outcome at this horizon
    weight: float  # adjusted (capped) weight, or DEFAULT_WEIGHTS[name] when not eligible
    eligible: bool  # sample_count >= min_agent_records (per-agent gate)
