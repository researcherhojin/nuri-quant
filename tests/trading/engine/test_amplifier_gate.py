"""
Amplifier gate lock-tests — Q5 (post-veto ordering) + Q8 (disabled-by-default).

Locks invariants from `docs/plans/E3_symmetric_amplifier_design.md`:
    - Q5: Hard veto / penalty 통과 못 한 candidate 는 amplifier 대상 아님
    - Q5: VIX 25-30 caution zone 에서는 amplifier 완전 비활성
    - Q8: enabled=false (config) 일 때는 amplifier 가 conf/size 변경 절대 안 함
    - Q7 anti-pattern: 단일 조건 (minimum < 2) 발동 차단
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nuri.trading.engine.amplifier_gate import (
    AmplifierConditions,
    evaluate,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_YAML = REPO_ROOT / "config" / "rules.yaml"


@pytest.fixture()
def amplifier_config() -> dict:
    """`config/rules.yaml symmetric_amplifier` 섹션."""
    with open(RULES_YAML, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    return rules.get("symmetric_amplifier", {})


def _all_satisfied_conditions(vix: float = 18.0) -> AmplifierConditions:
    """5/5 충족 + mandatory 2개 통과 시나리오."""
    return AmplifierConditions(
        recovery_confirmed=True,
        vix_favorable=True,
        regime_favorable=True,
        entry_strength=True,
        macro_benign=True,
        vix_value=vix,
        regime_label="recovery",
        regime_confidence=0.75,
        event_score=2.0,
    )


# ════════════════════════════════════════════════════════════
# Q8: Config disabled-by-default invariant (가장 중요한 lock)
# ════════════════════════════════════════════════════════════
class TestAmplifierConfigDisabledByDefault:
    """ship 직후 amplifier 가 우연히 fire 하면 안 됨.
    config 가 explicit enable/shadow_off 후에만 fire (Phase 3+).
    """

    def test_yaml_default_enabled_is_false(self, amplifier_config):
        """rules.yaml 의 enabled 가 누군가 실수로 True 로 켜놓지 않았는지."""
        assert amplifier_config.get("enabled") is False, (
            "symmetric_amplifier.enabled MUST be false until Phase 3 ship (Stage 2 paired counterfactual PASS 후)"
        )

    def test_yaml_default_shadow_mode_is_true(self, amplifier_config):
        """shadow_mode=true 강제 — Phase 1 telemetry only."""
        assert amplifier_config.get("shadow_mode") is True, (
            "symmetric_amplifier.shadow_mode MUST be true in Phase 1 (no actual conf/size mutation until Stage 2 PASS)"
        )

    def test_disabled_config_never_fires(self, amplifier_config):
        cond = _all_satisfied_conditions()
        result = evaluate(
            config=amplifier_config,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        # would_fire 는 조건 충족 시 True 가능 (telemetry 용)
        # 하지만 실제 fired 는 enabled=false → 항상 False
        assert result.fired is False, "amplifier fired despite enabled=false"
        assert result.alpha_confidence_boost_applied == 0.0
        assert result.portfolio_size_multiplier_applied == 1.0

    def test_shadow_mode_blocks_actual_fire(self, amplifier_config):
        """enabled=true 라도 shadow_mode=true 면 fired=False (Phase 1 invariant)."""
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": True}
        cond = _all_satisfied_conditions()
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        # 조건은 모두 충족 — would_fire 는 True
        assert result.would_fire is True
        # 그러나 shadow_mode → fired False
        assert result.fired is False


# ════════════════════════════════════════════════════════════
# Q5: Post-veto ordering — amplifier never overrides hard veto
# ════════════════════════════════════════════════════════════
class TestAmplifierNeverOverridesVeto:
    """Codex Q5: amplifier 는 risk veto / divergence penalty / VIX caution 통과
    못한 candidate 에는 절대 fire 안 함. Hard veto > amplifier 우선순위 보호.
    """

    def test_blocked_by_veto_skips_amplifier(self, amplifier_config):
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = _all_satisfied_conditions()
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
            final_action_blocked_by_veto=True,
        )
        assert result.fired is False
        assert result.would_fire is False
        assert result.skip_reason == "blocked_by_veto_or_penalty"

    def test_non_buy_action_skips_amplifier(self, amplifier_config):
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = _all_satisfied_conditions()
        for non_buy_action in ("HOLD", "SELL", "FLAT"):
            result = evaluate(
                config=cfg,
                final_action=non_buy_action,
                final_action_source="weighted_sum",
                conditions=cond,
            )
            assert result.fired is False, f"amplifier fired on {non_buy_action} action"
            assert result.skip_reason and result.skip_reason.startswith("non_buy_action")

    def test_non_weighted_source_skips_amplifier(self, amplifier_config):
        """consensus 가 weighted_sum 이 아닌 path (예: risk_veto override) 면 skip."""
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = _all_satisfied_conditions()
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="risk_veto_override",
            conditions=cond,
        )
        assert result.fired is False
        assert result.skip_reason and result.skip_reason.startswith("non_weighted_source")

    def test_vix_caution_zone_disables_amplifier(self, amplifier_config):
        """VIX 25-30 zone 에서 amplifier 완전 비활성 (Q5)."""
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        # VIX 27 — caution zone 안
        cond = _all_satisfied_conditions(vix=27.0)
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.in_caution_zone is True
        assert result.fired is False
        assert result.skip_reason and result.skip_reason.startswith("vix_caution_zone")

    def test_vix_above_caution_max_is_module_invariant_blocked(self, amplifier_config):
        """VIX > caution_max (=30) 은 모듈 자체가 차단. caller 가 vix_favorable=True 잘못
        emit 하더라도 evaluate() 에서 fired=False 보장.

        Why this lock matters (codex Round 1 P2): caller contract 만으로는 wrong-emit
        시나리오를 차단 못 함. Hard veto rule 을 모듈 invariant 로 끌어올림.
        """
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        # 모든 조건 True + VIX 31 (운영상 invalid 하지만 잘못 emit 된 시나리오)
        cond = _all_satisfied_conditions(vix=31.0)
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.in_caution_zone is False, "VIX 31 은 25-30 zone 외부"
        assert result.fired is False, "VIX > caution_max → 모듈 invariant 로 fire 차단"
        assert result.would_fire is False, "would_fire 도 False — module 자체 reject"
        assert result.skip_reason is not None
        assert "vix_above_caution_max" in result.skip_reason, (
            f"skip_reason 에 vix_above_caution_max 포함되어야: {result.skip_reason}"
        )


# ════════════════════════════════════════════════════════════
# Q2/Q7 mandatory + minimum invariant
# ════════════════════════════════════════════════════════════
class TestAmplifierMandatoryConditions:
    """mandatory 조건 (recovery + VIX) 누락 시 amplifier fire 금지.
    또한 minimum_satisfied < 2 인 config 는 single-condition fire 방지 위해 거부.
    """

    def test_mandatory_recovery_missing_blocks_fire(self, amplifier_config):
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = _all_satisfied_conditions()
        cond.recovery_confirmed = False  # mandatory missing
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.fired is False
        assert result.would_fire is False

    def test_mandatory_vix_missing_blocks_fire(self, amplifier_config):
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = _all_satisfied_conditions()
        cond.vix_favorable = False  # mandatory missing
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.fired is False
        assert result.would_fire is False

    def test_three_of_five_does_not_fire(self, amplifier_config):
        """4/5 minimum 미달 — Codex Q2 권고."""
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False}
        cond = AmplifierConditions(
            recovery_confirmed=True,
            vix_favorable=True,
            regime_favorable=True,
            entry_strength=False,
            macro_benign=False,
            vix_value=18.0,
        )
        # 3/5 satisfied — minimum 4 미달
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.would_fire is False
        assert result.fired is False

    def test_minimum_below_2_is_rejected(self, amplifier_config):
        """anti-pattern: minimum_satisfied=1 single-condition fire 차단 (§2.6)."""
        cfg = {**amplifier_config, "enabled": True, "shadow_mode": False, "minimum_satisfied": 1}
        cond = AmplifierConditions(
            recovery_confirmed=True,
            vix_favorable=True,
            vix_value=18.0,
        )
        result = evaluate(
            config=cfg,
            final_action="BUY",
            final_action_source="weighted_sum",
            conditions=cond,
        )
        assert result.fired is False
        assert result.would_fire is False
        assert result.skip_reason and "minimum_too_low" in result.skip_reason


# ════════════════════════════════════════════════════════════
# Anti-revenge-trading code-level grep test (영구 lock)
# ════════════════════════════════════════════════════════════
class TestAntiRevengeTrading:
    """Codex verdict: 'the wrong amplifier is just revenge trading with math paint'.
    소스에 drawdown × multiplier 형식 arithmetic 이 등장하면 자동 fail.
    """

    def test_amplifier_source_no_drawdown_arithmetic(self):
        """amplifier_gate.py 소스에 'drawdown' 변수 사용 없는지 grep."""
        src = (REPO_ROOT / "nuri" / "trading" / "engine" / "amplifier_gate.py").read_text(encoding="utf-8")
        # drawdown 자체는 docstring/comment 에 등장 가능 (예: anti-pattern 설명).
        # 그러나 실제 산술 expression 으로는 사용 금지.
        # heuristic: 'drawdown' 이 등장하는 line 에 *, /, +, - 같은 산술 연산자 함께 있으면 fail.
        for lineno, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            # 주석/docstring 라인은 skip
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if "drawdown" in stripped.lower():
                # Code 라인에 drawdown 이 있으면 산술 연산자 동시 사용 검사
                forbidden_ops = ["*", "/"]  # '+', '-' 는 너무 광범위해서 제외
                if any(op in stripped for op in forbidden_ops):
                    pytest.fail(
                        f"amplifier_gate.py:{lineno} uses drawdown in arithmetic — "
                        f"revenge-trading anti-pattern (Codex verdict). Line: {stripped}"
                    )
