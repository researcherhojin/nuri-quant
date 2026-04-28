"""
Symmetric Amplifier Gate — STRATEGY §2.6 4번째 rung.

Phase 1 (현재): SHADOW only.
    - 모든 조건 평가 후 `pipeline_events` 에 emit
    - 실제 confidence/size 변경 없음 (no-op)
    - enabled=false (config) 일 때는 evaluate() 도 호출 안 됨

Source plan: docs/plans/E3_symmetric_amplifier_design.md
Codex consult: 2026-04-28 session 019dd3f6

Anti-revenge guardrails (영구 — 코드 레벨):
    - drawdown × multiplier 형식 사용 금지 (이 모듈에 절대 import 안 함)
    - 단일 조건 발동 차단 (minimum_satisfied 항상 ≥ 2)
    - Hard veto 우회 차단 (caller 책임 — 본 모듈은 post-veto 만 호출됨)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Q5: amplifier 와 충돌하면 안 되는 hard veto/penalty 결과 list.
# Caller (consensus.py 통합 시) 가 이 list 의 final_action 인 경우 evaluate() 호출 금지.
HARD_VETO_FINAL_ACTIONS = {"FLAT", "SELL"}


@dataclass
class AmplifierConditions:
    """단일 시점의 amplifier 조건 평가 결과."""

    recovery_confirmed: bool = False  # mandatory
    vix_favorable: bool = False  # mandatory
    regime_favorable: bool = False
    entry_strength: bool = False
    macro_benign: bool = False

    # Diagnostic data (telemetry 용)
    vix_value: float | None = None
    regime_label: str | None = None
    regime_confidence: float | None = None
    event_score: float | None = None

    def satisfied_count(self) -> int:
        """충족 조건 개수."""
        return sum(
            [
                self.recovery_confirmed,
                self.vix_favorable,
                self.regime_favorable,
                self.entry_strength,
                self.macro_benign,
            ]
        )

    def mandatory_satisfied(self) -> bool:
        """mandatory 2개 (recovery + VIX) 모두 충족 여부."""
        return self.recovery_confirmed and self.vix_favorable


@dataclass
class AmplifierResult:
    """Amplifier evaluate() 산출물.

    Phase 1: would_fire 만 telemetry 로 emit. fired 는 항상 False (shadow).
    Phase 3+: shadow_mode=false 일 때 fired=True 가능.
    """

    enabled: bool  # config.symmetric_amplifier.enabled
    shadow_mode: bool  # config.symmetric_amplifier.shadow_mode
    in_caution_zone: bool  # VIX 25-30 zone (Q5)

    conditions: AmplifierConditions
    minimum_satisfied: int  # config 임계값
    would_fire: bool  # 조건 충족 시 fire 했을 것인가
    fired: bool  # 실제 alpha/portfolio 변경 발생?

    # Phase 3+: alpha confidence boost 가 적용되면 amount 기록
    alpha_confidence_boost_applied: float = 0.0
    portfolio_size_multiplier_applied: float = 1.0

    # 진단 정보
    skip_reason: str | None = None  # fire 안 한 이유
    extras: dict[str, Any] = field(default_factory=dict)


def _is_in_caution_zone(vix_value: float | None, caution_min: float, caution_max: float) -> bool:
    """VIX 25-30 caution zone 여부 (Q5: amplifier 완전 비활성)."""
    if vix_value is None:
        return False
    return caution_min <= vix_value <= caution_max


def evaluate(
    *,
    config: dict,
    final_action: str,
    final_action_source: str,
    conditions: AmplifierConditions,
    final_action_blocked_by_veto: bool = False,
) -> AmplifierResult:
    """단일 candidate 에 대한 amplifier 평가.

    Phase 1: shadow only — `fired` 항상 False, telemetry 만.

    Args:
        config: `config/rules.yaml symmetric_amplifier` section.
        final_action: post-veto 결과 ("BUY" / "HOLD" / "SELL" / "FLAT").
        final_action_source: consensus 결과 source ("weighted_sum" 등).
        conditions: 사전 계산된 조건 평가 (recovery_detector + 기타 sources).
        final_action_blocked_by_veto: risk veto / divergence penalty 가 발동했나.
            (caller responsibility — 본 모듈은 이 정보를 근거로 skip).

    Returns:
        AmplifierResult — `fired` 는 Phase 1 에서 항상 False.
    """
    enabled = bool(config.get("enabled", False))
    shadow_mode = bool(config.get("shadow_mode", True))
    minimum = int(config.get("minimum_satisfied", 4))

    caution = config.get("caution_zone", {})
    caution_min = float(caution.get("vix_min", 25.0))
    caution_max = float(caution.get("vix_max", 30.0))
    in_caution = _is_in_caution_zone(conditions.vix_value, caution_min, caution_max)

    # Q5: Hard veto / penalty 통과 못 한 candidate 는 amplifier 대상 아님
    skip_reason: str | None = None
    if final_action_blocked_by_veto:
        skip_reason = "blocked_by_veto_or_penalty"
    elif final_action != "BUY":
        skip_reason = f"non_buy_action:{final_action}"
    elif final_action_source != "weighted_sum":
        skip_reason = f"non_weighted_source:{final_action_source}"
    elif in_caution:
        skip_reason = f"vix_caution_zone:{conditions.vix_value}"

    # Q2 mandatory 조건: recovery + VIX favorable 둘 다 필요
    mandatory_ok = conditions.mandatory_satisfied()
    satisfied = conditions.satisfied_count()
    would_fire = mandatory_ok and satisfied >= minimum and skip_reason is None

    # Q7 anti-pattern: 단일 조건 발동 차단 (minimum=1 같은 config 도 거부)
    if minimum < 2:
        logger.warning(
            "amplifier minimum_satisfied=%d < 2 — single-condition fire blocked (anti-pattern)",
            minimum,
        )
        would_fire = False
        if skip_reason is None:
            skip_reason = f"minimum_too_low:{minimum}"

    # Phase 1: enabled=False 또는 shadow_mode=True → fired=False (no-op)
    fired = enabled and not shadow_mode and would_fire

    return AmplifierResult(
        enabled=enabled,
        shadow_mode=shadow_mode,
        in_caution_zone=in_caution,
        conditions=conditions,
        minimum_satisfied=minimum,
        would_fire=bool(would_fire),
        fired=bool(fired),
        skip_reason=skip_reason,
        # Phase 1: 실제 boost 0
        alpha_confidence_boost_applied=0.0,
        portfolio_size_multiplier_applied=1.0,
    )
