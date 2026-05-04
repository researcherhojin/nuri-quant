"""Consensus event emission — soft penalty audit trail.

`_emit_penalty_event_if_fired` writes a `consensus_penalty_applied` row to
pipeline_events when the divergence-technical penalty downgrades a BUY/SELL to
HOLD. STRATEGY §2.6 escalation-ladder audit. Emit failures never block consensus.
"""

from __future__ import annotations

import logging

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict

from .models import ConsensusResult

__all__ = ["_emit_penalty_event_if_fired"]

logger = logging.getLogger(__name__)


def _emit_penalty_event_if_fired(result: ConsensusResult, verdicts: list[AgentVerdict], db_path=None) -> None:
    """Mechanical penalty 발동 시 `consensus_penalty_applied` 이벤트 기록.

    STRATEGY §2.6 Escalation Ladder — soft penalty rung 감사 로그. 1-2 달 후
    `pipeline_events` 조회로 "penalty 가 몇 % 발동하고, 몇 % 티커에 영향이며,
    BUY→HOLD swing 은 몇 건인가" 를 답할 수 있어야 한다. Emit 실패해도
    consensus 자체는 정상 반환.
    """
    if not result.penalty_applied:
        return
    tech_v = next((v for v in verdicts if v.agent_name == "technical"), None)
    if tech_v is None:  # pragma: no cover — penalty implies technical verdict present
        return
    threshold = AGENT_CONFIG.get("consensus", {}).get("divergence_technical_threshold", 80)
    try:
        from nuri.core.events import emit_event

        emit_event(
            "consensus_penalty_applied",
            step="recommend",
            payload={
                "ticker": result.ticker,
                "penalty_kind": "divergence_technical",
                "threshold": threshold,
                "technical_action": tech_v.action,
                "technical_confidence": tech_v.confidence,
                "consensus_action_before": result.pre_penalty_action,
                "consensus_confidence_before": result.final_confidence,
                "consensus_action_after": result.final_action,
                "consensus_confidence_after": result.final_confidence,
                "swing": f"{result.pre_penalty_action}_TO_{result.final_action}",
                "divergence_reason": result.divergence_reason,
            },
            db_path=db_path,
        )
    except Exception:
        logger.warning("consensus_penalty_applied 이벤트 emit 실패 — consensus 결과는 정상 반환", exc_info=True)
