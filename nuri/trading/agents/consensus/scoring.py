"""Consensus scoring — weighted vote + risk veto + divergence penalty.

`_build_consensus` is the pure scoring kernel. No DB I/O, no agent execution.
Inputs: ticker + verdicts + weight dict. Output: ConsensusResult with full
scoring_detail breakdown for audit/UI reconstruction.
"""

from __future__ import annotations

from nuri.core.agent_config import AGENT_CONFIG
from nuri.trading.agents.base import AgentVerdict

from .models import ConsensusResult

__all__ = ["_build_consensus"]


def _build_consensus(ticker: str, verdicts: list[AgentVerdict], weights: dict) -> ConsensusResult:
    """가중 투표로 합의 결과 산출 (analyze_ticker / stream_analyze_ticker 공용)."""
    action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        action_scores[v.action] += w * (v.confidence / 100)

    # 리스크 에이전트 거부권 — PR A: alpha_action="FLAT" 만 발동 (기존
    # `action=="SELL"` 에서 변경). concentration > 15% 같은 portfolio rule 은
    # alpha=FLAT 을 emit 하지 않으므로 veto 못 건다 → SIEGE REJECT → SELL 경로
    # 구조적 차단 (§ STRATEGY 2.6 Soft penalty vs Hard veto).
    # Back-compat: `alpha_action` 이 None 인 legacy/기타 agent 는 action=="SELL"
    # 로 폴백 판정 (risk agent 만 PR A 범위에서 axis 채움).
    veto_threshold = AGENT_CONFIG.get("consensus", {}).get("risk_veto_threshold", 80)
    risk_v = next((v for v in verdicts if v.agent_name == "risk"), None)
    risk_veto_fired = False
    veto_fired_now = False
    if risk_v is not None and risk_v.confidence >= veto_threshold:
        alpha_flat = risk_v.alpha_action == "FLAT"
        legacy_sell = risk_v.alpha_action is None and risk_v.action == "SELL"
        veto_fired_now = alpha_flat or legacy_sell
    if veto_fired_now:
        assert risk_v is not None  # veto_fired_now => risk_v non-None
        final_action = "SELL"
        final_confidence = risk_v.confidence
        reasoning = f"리스크 에이전트 거부권 발동: {risk_v.reasoning}"
        risk_veto_fired = True
    else:
        final_action = max(action_scores, key=lambda k: action_scores[k])
        total_weight = sum(action_scores.values())
        final_confidence = (action_scores[final_action] / total_weight * 100) if total_weight > 0 else 0
        supporters = [v for v in verdicts if v.action == final_action]
        reasoning = " | ".join(f"{v.agent_name}: {v.reasoning}" for v in supporters)

    # Divergence detection — docs/HARNESS.md §2 (JKHY, 2026-04-14) 재발 방지.
    # 9개 fundamentals-ish 에이전트가 BUY 를 몰아주면 TechnicalAgent 의 SELL
    # 반대가 묻힘. 합의 action 이 BUY/SELL 이고 technical 이 정확히 반대 action
    # 이면 flag + reason 을 surface. HOLD 는 "약한 반대" 로 간주해 flag 하지 않음.
    divergence_flag = False
    divergence_reason = ""
    tech_v = next((v for v in verdicts if v.agent_name == "technical"), None)
    if tech_v and final_action in ("BUY", "SELL"):
        opposite = {"BUY": "SELL", "SELL": "BUY"}[final_action]
        if tech_v.action == opposite:
            divergence_flag = True
            divergence_reason = (
                f"기술지표 반대: TechnicalAgent 가 {tech_v.action} "
                f"(conf {tech_v.confidence:.0f}) — 합의 {final_action} 과 충돌. "
                f"근거: {tech_v.reasoning[:120]}"
            )

    # Divergence mechanical penalty — flag 가 informational 인 P1 A1/A2 한계 보완.
    # tech confidence 가 threshold 이상일 때만 final_action 을 HOLD 로 downgrade.
    # 원래 계산된 final_confidence 는 **그대로 유지** (downstream 이 신뢰도 정보
    # 로 사용할 수 있게). reasoning 에 penalty 근거 prepend. Risk veto 가 이미
    # 발동했다면 precedence 에 따라 penalty skip.
    divergence_threshold = AGENT_CONFIG.get("consensus", {}).get("divergence_technical_threshold", 80)
    penalty_applied = False
    pre_penalty_action_str = ""
    if divergence_flag and not risk_veto_fired and tech_v and tech_v.confidence >= divergence_threshold:
        pre_penalty_action_str = final_action  # BUY 또는 SELL
        final_action = "HOLD"
        reasoning = f"기술지표 반대로 downgrade (tech {tech_v.action} conf {tech_v.confidence:.0f} ≥ {divergence_threshold}) | {reasoning}"
        penalty_applied = True

    # agreement_rate / dissent 는 **penalty 이전** 의 원 verdict 분포 기준으로
    # 계산 — 사용자가 "10 중 몇 개가 HOLD 동의" 가 아니라 "원래 BUY/SELL 쪽은
    # 몇 개 였는지" 를 볼 수 있어야 penalty 맥락을 이해할 수 있다.
    dist_basis = pre_penalty_action_str if penalty_applied else final_action
    agree_count = sum(1 for v in verdicts if v.action == dist_basis)
    agreement_rate = agree_count / len(verdicts) if verdicts else 0
    dissent = [
        f"{v.agent_name}({v.action}, {v.confidence:.0f}): {v.reasoning}" for v in verdicts if v.action != dist_basis
    ]

    # Phase 2 A-2a — scoring breakdown. 사용자가 "왜 이 action 이 나왔는가" 를
    # reconstruct 할 수 있도록 per-agent weight × confidence 기여도를 저장.
    # Risk veto / divergence penalty 도 함께 기록해 audit trail 확보.
    #
    # Schema (codex A-2a review 대응):
    # - `source="consensus"` + `schema_version=1` — candidates.py scoring_detail
    #   (tier/conflict_penalty 기반) 와 같은 column 공유하므로 discriminator 필수.
    # - `basis_action` — contributions 가 참조하는 action 방향. penalty 미발동 시
    #   final_action 과 동일, 발동 시 pre_penalty_action (downgrade 전 원 방향).
    # - `final_action_source` — 어느 메커니즘이 final_action 을 결정했는가.
    #   "weighted_sum" | "risk_veto" | "divergence_penalty".
    final_confidence_rounded = round(final_confidence, 1)
    basis_action = pre_penalty_action_str if penalty_applied else final_action
    if risk_veto_fired:
        final_action_source = "risk_veto"
    elif penalty_applied:
        final_action_source = "divergence_penalty"
    else:
        final_action_source = "weighted_sum"
    contributions = []
    for v in verdicts:
        w = weights.get(v.agent_name, 0.1)
        weighted = round(w * (v.confidence / 100), 4)
        contributions.append(
            {
                "agent_name": v.agent_name,
                "action": v.action,
                "confidence": round(float(v.confidence), 1),
                "weight": round(float(w), 4),
                "weighted": weighted,
                # basis_action 방향 (penalty 발동 시 pre_penalty_action, 아니면
                # final_action) 에 실제 기여한 verdict 를 True 로 마킹. UI 는 이
                # 플래그로 "합의 방향 지지자" 를 강조하되 final_action 과 다를 수
                # 있음을 `basis_action` 별도 노출로 처리.
                "counted_for_basis_action": v.action == basis_action,
            }
        )
    scoring_detail = {
        "source": "consensus",
        "schema_version": 1,
        "weights": {k: round(float(v), 4) for k, v in weights.items()},
        "action_scores": {k: round(float(val), 4) for k, val in action_scores.items()},
        "contributions": contributions,
        "final_action": final_action,
        "final_confidence": final_confidence_rounded,
        "final_action_source": final_action_source,
        "basis_action": basis_action,
        "agreement_rate": round(agreement_rate, 2),
        "risk_veto_fired": risk_veto_fired,
        "divergence_flag": divergence_flag,
        "penalty_applied": penalty_applied,
        "pre_penalty_action": pre_penalty_action_str,
    }

    return ConsensusResult(
        ticker=ticker,
        final_action=final_action,
        final_confidence=final_confidence_rounded,
        agreement_rate=round(agreement_rate, 2),
        verdicts=verdicts,
        dissent=dissent,
        reasoning=reasoning,
        divergence_flag=divergence_flag,
        divergence_reason=divergence_reason,
        penalty_applied=penalty_applied,
        pre_penalty_action=pre_penalty_action_str,
        scoring_detail=scoring_detail,
    )
