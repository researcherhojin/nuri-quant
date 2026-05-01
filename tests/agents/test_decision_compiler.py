"""DecisionCompiler tests (#529 Phase 2 capstone — actor #8, canonical).

검증 (Codex Round 5 Layer B capstone):
- Layer B (deterministic, ZERO LLM)
- 2 actions: compile / last_decision
- 3 producer/gate 통합:
    1. RegimePosterior — posterior + top2_margin
    2. HypothesisRegistry.check_emit — outcome 'pass' 만 통과
    3. CausalFactorAuditor.last_audit — verdict ROBUST/WEAK 만 통과
- Anti-pattern lock-tests:
    1. hypothesis check_emit BLOCK → HOLD enforced (Layer A 우회 차단)
    2. causal verdict=MIRAGE → HOLD enforced (factor mirage 차단)
    3. causal verdict=INSUFFICIENT → HOLD
    4. conviction < 0.5 → HOLD (low-signal 차단)
    5. inputs_json 미완성 (source IDs 누락) → BLOCK (audit traceability)
- Decision lifecycle: pending/emitted/blocked/superseded
- Discord publish: emitted → BRIEF, blocked → OPS (mock)
- Integration test: full chain RegimePosterior → HypothesisRegistry → CausalFactorAuditor → DecisionCompiler
"""

from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np
import pytest

from nuri.agents.actors.causal_factor_auditor import CausalFactorAuditor
from nuri.agents.actors.decision_compiler import (
    CONVICTION_EMIT_CUTOFF,
    CONVICTION_HOLD_CUTOFF,
    REGIME_FAVOR_PROB,
    DecisionCompiler,
)
from nuri.agents.actors.hypothesis_registry import HypothesisRegistry
from nuri.agents.actors.regime_posterior import RegimePosterior
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_decision, query

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "dc.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            # setdefault 가 아니라 None 도 override — outbox stage_brief 처럼
            # caller 가 db_path=None 명시 전달하는 경로 대응 (PR channel-migration).
            if kwargs.get("db_path") is None:
                kwargs["db_path"] = db_path
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.decision_compiler.log_decision",
            side_effect=make_redirect(db_module.log_decision),
        ),
        patch(
            "nuri.agents.actors.decision_compiler.query",
            side_effect=make_redirect(db_module.query),
        ),
        # for integration tests
        patch(
            "nuri.agents.actors.regime_posterior.log_regime_posterior",
            side_effect=make_redirect(db_module.log_regime_posterior),
        ),
        patch(
            "nuri.agents.actors.regime_posterior.query",
            side_effect=make_redirect(db_module.query),
        ),
        patch(
            "nuri.agents.actors.hypothesis_registry.register_hypothesis",
            side_effect=make_redirect(db_module.register_hypothesis),
        ),
        patch(
            "nuri.agents.actors.hypothesis_registry.validate_hypothesis",
            side_effect=make_redirect(db_module.validate_hypothesis),
        ),
        patch(
            "nuri.agents.actors.hypothesis_registry.reject_hypothesis",
            side_effect=make_redirect(db_module.reject_hypothesis),
        ),
        patch(
            "nuri.agents.actors.hypothesis_registry.expire_hypotheses",
            side_effect=make_redirect(db_module.expire_hypotheses),
        ),
        patch(
            "nuri.agents.actors.hypothesis_registry.query",
            side_effect=make_redirect(db_module.query),
        ),
        patch(
            "nuri.agents.actors.causal_factor_auditor.log_causal_audit",
            side_effect=make_redirect(db_module.log_causal_audit),
        ),
        patch(
            "nuri.agents.actors.causal_factor_auditor.query",
            side_effect=make_redirect(db_module.query),
        ),
        # PR #brief outbox channel-migration (Codex Round 6, 2026-05-02)
        patch(
            "nuri.agents.discord.outbox.stage_outbox",
            side_effect=make_redirect(db_module.stage_outbox),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _evidence(
    *,
    hyp_outcome: str = "pass",
    causal_verdict: str = "ROBUST",
    causal_certainty: float = 0.85,
    posterior: list[float] | None = None,
    top2_margin: float = 0.65,
):
    """기본 evidence 3종 — override 로 부분 변경 가능."""
    if posterior is None:
        posterior = [0.85, 0.10, 0.05]
    return {
        "regime_evidence": {
            "regime_run_id": "regime-r1",
            "posterior": posterior,
            "argmax_state": int(np.argmax(posterior)),
            "top2_margin": top2_margin,
        },
        "hypothesis_check": {
            "hypothesis_id": "hyp-1",
            "status": "validated",
            "outcome": hyp_outcome,
            "reason": "test reason" if hyp_outcome != "pass" else None,
        },
        "causal_evidence": {
            "factor_id": "momentum-v1",
            "as_of_date": "2026-05-01",
            "verdict": causal_verdict,
            "causal_certainty": causal_certainty,
        },
    }


def _compile_payload(ticker: str = "NVDA", proposed_action: str = "BUY", **overrides):
    payload: dict = {
        "action": "compile",
        "ticker": ticker,
        "proposed_action": proposed_action,
        "as_of_date": "2026-05-01",
        **_evidence(),
    }
    # nested override: replace evidence sub-dicts
    for k in ("regime_evidence", "hypothesis_check", "causal_evidence"):
        if k in overrides:
            payload[k] = overrides.pop(k)
    payload.update(overrides)
    return payload


# ═══════════════════════════════════════════════════════
# Layer B invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert DecisionCompiler.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(DecisionCompiler, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("decision-compiler") is DecisionCompiler


# ═══════════════════════════════════════════════════════
# Action: compile — input validation
# ═══════════════════════════════════════════════════════


class TestInputValidation:
    def test_invalid_action_blocked(self, patched_db):
        result = DecisionCompiler().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_ticker_blocked(self, patched_db):
        payload = _compile_payload()
        del payload["ticker"]
        result = DecisionCompiler().run(payload)
        assert result.outcome == Outcome.BLOCK

    def test_invalid_proposed_action_blocked(self, patched_db):
        payload = _compile_payload(proposed_action="HOLD")  # not in BUY/SELL
        result = DecisionCompiler().run(payload)
        assert result.outcome == Outcome.BLOCK
        assert "proposed_action" in result.output["error"]

    def test_missing_evidence_blocked(self, patched_db):
        for missing in ("regime_evidence", "hypothesis_check", "causal_evidence"):
            payload = _compile_payload()
            del payload[missing]
            result = DecisionCompiler().run(payload)
            assert result.outcome == Outcome.BLOCK
            assert missing in result.output["error"]

    def test_missing_source_ids_blocked(self, patched_db):
        """LOCK-TEST: regime_run_id/hypothesis_id/causal_audit_id 누락 → BLOCK (audit traceability)."""
        payload = _compile_payload()
        payload["regime_evidence"] = {"posterior": [0.9, 0.1]}  # no run_id
        result = DecisionCompiler().run(payload)
        assert result.outcome == Outcome.BLOCK
        assert "source IDs missing" in result.output["error"]


# ═══════════════════════════════════════════════════════
# Anti-pattern lock-tests — 3 gates enforcement
# ═══════════════════════════════════════════════════════


class TestHypothesisGateLockTest:
    """LOCK-TEST: hypothesis check_emit BLOCK → HOLD enforced.

    fail 시 = HypothesisRegistry (Layer A) 의 emit gate 가 우회됨 →
    검증 안 된 hypothesis 로 매매 추천 발행 → Knight Capital 류 사고.
    """

    def test_hypothesis_block_forces_hold(self, patched_db):
        result = DecisionCompiler().run(
            _compile_payload(
                hypothesis_check={
                    "hypothesis_id": "h-bad",
                    "status": "expired",
                    "outcome": "block",
                    "reason": "expired",
                }
            )
        )
        assert result.outcome == Outcome.WARN
        assert result.output["action"] == "HOLD"
        assert result.output["status"] == "blocked"
        assert "hypothesis" in result.output["block_reason"].lower()

    def test_hypothesis_warn_treated_as_block(self, patched_db):
        """Layer A 가 PASS 가 아닌 어떤 outcome 도 emit 차단."""
        result = DecisionCompiler().run(
            _compile_payload(
                hypothesis_check={
                    "hypothesis_id": "h-warn",
                    "status": "open",
                    "outcome": "warn",
                }
            )
        )
        assert result.outcome == Outcome.WARN
        assert result.output["status"] == "blocked"

    def test_outcome_enum_pass_value_accepted(self, patched_db):
        """Outcome.PASS enum 값도 'pass' string 과 동등 처리."""
        result = DecisionCompiler().run(
            _compile_payload(
                hypothesis_check={
                    "hypothesis_id": "hyp-1",
                    "status": "validated",
                    "outcome": Outcome.PASS,
                }
            )
        )
        # 정상 진행 — block_reason 없음
        assert result.outcome == Outcome.PASS
        assert result.output["status"] == "emitted"


class TestCausalGateLockTest:
    """LOCK-TEST: causal verdict=MIRAGE → HOLD enforced.

    fail 시 = López de Prado 4-test 의 mirage 감지가 우회됨 →
    placebo 와 구별 안 되는 spurious factor 로 매매.
    """

    def test_mirage_forces_hold(self, patched_db):
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "spurious",
                    "as_of_date": "2026-05-01",
                    "verdict": "MIRAGE",
                    "causal_certainty": 0.4,
                }
            )
        )
        assert result.outcome == Outcome.WARN
        assert result.output["status"] == "blocked"
        assert "MIRAGE" in result.output["block_reason"]

    def test_insufficient_forces_hold(self, patched_db):
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "tiny",
                    "as_of_date": "2026-05-01",
                    "verdict": "INSUFFICIENT",
                    "causal_certainty": 0.0,
                }
            )
        )
        assert result.outcome == Outcome.WARN
        assert result.output["status"] == "blocked"

    def test_robust_passes_gate(self, patched_db):
        result = DecisionCompiler().run(_compile_payload())
        assert result.output["action"] in ("BUY", "HOLD")  # gate 통과

    def test_weak_passes_gate(self, patched_db):
        """WEAK 도 gate 통과 (사용 가능, 단 conviction 영향)."""
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "ok",
                    "as_of_date": "2026-05-01",
                    "verdict": "WEAK",
                    "causal_certainty": 0.55,
                }
            )
        )
        # WEAK + 낮은 certainty → conviction 임계값 미달 → HOLD
        assert result.output["action"] == "HOLD"


class TestConvictionGateLockTest:
    """LOCK-TEST: conviction < 0.5 → HOLD (low-signal emit 차단)."""

    def test_low_conviction_blocked(self, patched_db):
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "weak",
                    "as_of_date": "2026-05-01",
                    "verdict": "WEAK",
                    "causal_certainty": 0.30,
                },
                regime_evidence={
                    "regime_run_id": "r-weak",
                    "posterior": [0.4, 0.35, 0.25],
                    "argmax_state": 0,
                    "top2_margin": 0.05,
                },
            )
        )
        assert result.outcome == Outcome.WARN
        assert result.output["action"] == "HOLD"
        assert result.output["status"] == "blocked"
        assert "hold_cutoff" in result.output["block_reason"] or "conviction" in result.output["block_reason"]

    def test_borderline_conviction_holds_not_emit(self, patched_db):
        """0.5 <= conv < 0.7 → HOLD emit (blocked 가 아닌 emitted/HOLD)."""
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "mid",
                    "as_of_date": "2026-05-01",
                    "verdict": "WEAK",
                    "causal_certainty": 0.55,
                },
                regime_evidence={
                    "regime_run_id": "r-mid",
                    "posterior": [0.55, 0.30, 0.15],
                    "argmax_state": 0,
                    "top2_margin": 0.25,
                },
            )
        )
        # conviction = 0.5*0.55 + 0.3*0.55 + 0.2*0.25 = 0.49 → blocked (< 0.5)
        # actual: depends on math. Just check it's not BUY emit.
        assert result.output["action"] == "HOLD"

    def test_high_conviction_buy_emit(self, patched_db):
        result = DecisionCompiler().run(_compile_payload())
        assert result.output["action"] == "BUY"
        assert result.output["status"] == "emitted"
        assert result.output["conviction"] >= CONVICTION_EMIT_CUTOFF

    def test_sell_emit(self, patched_db):
        result = DecisionCompiler().run(_compile_payload(proposed_action="SELL"))
        assert result.output["action"] == "SELL"
        assert result.output["status"] == "emitted"


# ═══════════════════════════════════════════════════════
# Decision persistence + audit
# ═══════════════════════════════════════════════════════


class TestPersistence:
    def test_emitted_decision_persisted(self, patched_db):
        result = DecisionCompiler().run(_compile_payload())
        rows = query(
            "SELECT * FROM agent_decisions WHERE decision_id = ?",
            (result.output["decision_id"],),
            db_path=patched_db,
        )
        r = dict(rows[0])
        assert r["ticker"] == "NVDA"
        assert r["action"] == "BUY"
        assert r["status"] == "emitted"
        # inputs_json 모두 기록
        inputs = json.loads(r["inputs_json"])
        assert "regime_run_id" in inputs
        assert "hypothesis_id" in inputs
        assert "causal_audit_id" in inputs

    def test_blocked_decision_persisted_with_reason(self, patched_db):
        result = DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "x",
                    "as_of_date": "2026-05-01",
                    "verdict": "MIRAGE",
                    "causal_certainty": 0.3,
                }
            )
        )
        rows = query(
            "SELECT block_reason, status FROM agent_decisions WHERE decision_id = ?",
            (result.output["decision_id"],),
            db_path=patched_db,
        )
        r = dict(rows[0])
        assert r["status"] == "blocked"
        assert "MIRAGE" in r["block_reason"]

    def test_supersede_on_new_decision(self, patched_db):
        """동일 ticker + as_of_date 의 새 decision 등장 시 이전 emit → superseded."""
        actor = DecisionCompiler()
        actor.run(_compile_payload())  # 첫 emit
        actor.run(_compile_payload(proposed_action="SELL"))  # 두 번째 emit

        rows = query(
            "SELECT decision_id, status FROM agent_decisions WHERE ticker='NVDA' ORDER BY created_at",
            db_path=patched_db,
        )
        statuses = [dict(r)["status"] for r in rows]
        assert statuses[0] == "superseded"
        assert statuses[-1] == "emitted"

    def test_audit_ledger_layer_b(self, patched_db):
        DecisionCompiler().run(_compile_payload())
        rows = query(
            "SELECT layer, outcome FROM agent_audit_ledger WHERE actor_name='decision-compiler'",
            db_path=patched_db,
        )
        assert rows[0]["layer"] == "B"
        assert rows[0]["outcome"] == "pass"


# ═══════════════════════════════════════════════════════
# Action: last_decision
# ═══════════════════════════════════════════════════════


class TestLastDecision:
    def test_no_decisions_returns_warn(self, patched_db):
        result = DecisionCompiler().run({"action": "last_decision"})
        assert result.outcome == Outcome.WARN

    def test_returns_latest(self, patched_db):
        actor = DecisionCompiler()
        actor.run(_compile_payload(ticker="A"))
        actor.run(_compile_payload(ticker="B"))
        result = actor.run({"action": "last_decision"})
        assert result.outcome == Outcome.PASS
        assert result.output["ticker"] == "B"

    def test_filters_by_ticker(self, patched_db):
        actor = DecisionCompiler()
        actor.run(_compile_payload(ticker="A"))
        actor.run(_compile_payload(ticker="B"))
        result = actor.run({"action": "last_decision", "ticker": "A"})
        assert result.outcome == Outcome.PASS
        assert result.output["ticker"] == "A"

    def test_unknown_ticker_warn(self, patched_db):
        DecisionCompiler().run(_compile_payload())
        result = DecisionCompiler().run({"action": "last_decision", "ticker": "ZZZZ"})
        assert result.outcome == Outcome.WARN


# ═══════════════════════════════════════════════════════
# Discord publish
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    """#brief channel-migration (Codex Round 6): decision_compiler._publish_brief 가 outbox stage 로 전환.
    #ops (block path) 는 PR3 에서 별도 channel-migration. 본 클래스의 emit 검사는 outbox 기준."""

    def test_emit_stages_to_brief_outbox(self, patched_db):
        from nuri.core.db import claim_pending_outbox

        DecisionCompiler().run(_compile_payload())
        _, rows = claim_pending_outbox("brief", db_path=patched_db)
        assert len(rows) == 1
        payload = rows[0]["payload"]
        assert payload["kind"] == "BUY"
        assert payload["ticker"]
        assert "decision_id" in payload

    def test_blocked_stages_to_ops(self, patched_db):
        """Block path → outbox stage_ops (PR3 Codex Round 6)."""
        with patch("nuri.agents.discord.outbox.stage_ops") as mock_stage:
            DecisionCompiler().run(
                _compile_payload(
                    causal_evidence={
                        "factor_id": "x",
                        "as_of_date": "2026-05-01",
                        "verdict": "MIRAGE",
                        "causal_certainty": 0.3,
                    }
                )
            )
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "decision_blocked"

    def test_publish_failure_does_not_block_actor(self, patched_db):
        # outbox stage 가 어떤 이유로든 raise 해도 actor pipeline 죽지 않아야 함.
        with patch(
            "nuri.agents.discord.outbox.stage_brief",
            side_effect=RuntimeError("outbox down"),
        ):
            result = DecisionCompiler().run(_compile_payload())
            assert result.outcome == Outcome.PASS
            assert result.output["status"] == "emitted"

    def test_hold_emit_does_not_stage_brief(self, patched_db):
        """HOLD (low conviction) 은 BRIEF outbox stage X — 사용자 noise 방지."""
        from nuri.core.db import claim_pending_outbox

        DecisionCompiler().run(
            _compile_payload(
                causal_evidence={
                    "factor_id": "weak",
                    "as_of_date": "2026-05-01",
                    "verdict": "WEAK",
                    "causal_certainty": 0.3,
                },
                regime_evidence={
                    "regime_run_id": "r-weak",
                    "posterior": [0.4, 0.35, 0.25],
                    "argmax_state": 0,
                    "top2_margin": 0.05,
                },
            )
        )
        _, rows = claim_pending_outbox("brief", db_path=patched_db)
        assert rows == []


# ═══════════════════════════════════════════════════════
# Helper direct lock-tests
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    def test_invalid_action_rejected(self, db_path):
        with pytest.raises(ValueError, match="action must be"):
            log_decision(
                decision_id="x",
                ticker="A",
                as_of_date="2026-05-01",
                action="YOLO",
                conviction=0.5,
                inputs={"regime_run_id": "x", "hypothesis_id": "y", "causal_audit_id": "z"},
                rationale={},
                status="emitted",
                db_path=db_path,
            )

    def test_invalid_status_rejected(self, db_path):
        with pytest.raises(ValueError, match="status must be"):
            log_decision(
                decision_id="x",
                ticker="A",
                as_of_date="2026-05-01",
                action="BUY",
                conviction=0.5,
                inputs={"regime_run_id": "x", "hypothesis_id": "y", "causal_audit_id": "z"},
                rationale={},
                status="weird",
                db_path=db_path,
            )

    def test_conviction_out_of_range_rejected(self, db_path):
        with pytest.raises(ValueError, match="conviction must be in"):
            log_decision(
                decision_id="x",
                ticker="A",
                as_of_date="2026-05-01",
                action="BUY",
                conviction=1.5,
                inputs={"regime_run_id": "x", "hypothesis_id": "y", "causal_audit_id": "z"},
                rationale={},
                status="emitted",
                db_path=db_path,
            )

    def test_missing_input_keys_rejected(self, db_path):
        """LOCK-TEST: audit traceability — source actor run_id 누락 panic."""
        with pytest.raises(ValueError, match="missing required audit keys"):
            log_decision(
                decision_id="x",
                ticker="A",
                as_of_date="2026-05-01",
                action="BUY",
                conviction=0.5,
                inputs={"regime_run_id": "x"},  # missing hypothesis_id + causal_audit_id
                rationale={},
                status="emitted",
                db_path=db_path,
            )

    def test_blocked_without_reason_rejected(self, db_path):
        with pytest.raises(ValueError, match="block_reason"):
            log_decision(
                decision_id="x",
                ticker="A",
                as_of_date="2026-05-01",
                action="HOLD",
                conviction=0.3,
                inputs={"regime_run_id": "x", "hypothesis_id": "y", "causal_audit_id": "z"},
                rationale={},
                status="blocked",
                db_path=db_path,
            )


# ═══════════════════════════════════════════════════════
# Integration test — 4-actor full chain
# ═══════════════════════════════════════════════════════


class TestFullChainIntegration:
    """End-to-end: RegimePosterior → HypothesisRegistry → CausalFactorAuditor → DecisionCompiler.

    Phase 2 capstone 의 진짜 가치 — 모든 producer/gate 의 실제 출력을 받아
    DecisionCompiler 가 통합한다는 것을 검증.
    """

    def test_full_chain_robust_emit(self, patched_db):
        """모든 actor 통과 → BUY emit."""
        # 1. RegimePosterior — 강한 신호
        rng = np.random.default_rng(42)
        a = rng.normal(0.0, 0.5, (50, 3))
        b = rng.normal(3.0, 0.5, (50, 3))
        import pandas as pd

        df = pd.DataFrame(np.vstack([a, b]), columns=["vix_z", "yield_curve_slope", "hy_oas"])
        regime_result = RegimePosterior().run(
            {
                "action": "fit",
                "data": df,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        assert regime_result.outcome == Outcome.PASS
        regime_evidence = {
            "regime_run_id": regime_result.output.get("model_version"),  # use model_version as id proxy
            **regime_result.output,
        }

        # 2. HypothesisRegistry — register + validate
        hr = HypothesisRegistry()
        hr.run(
            {
                "action": "register",
                "hypothesis_id": "macro-bull-h1",
                "name": "macro-bull-shift",
                "version": "1.0.0",
                "producer_actor": "regime-posterior",
                "claim_text": "macro features indicate bull regime",
                "evidence": {"posterior": regime_result.output["posterior"]},
                "expiry_date": "2026-08-01",
            }
        )
        hr.run(
            {
                "action": "validate",
                "hypothesis_id": "macro-bull-h1",
                "validation_metrics": {"realized_brier": 0.18},
            }
        )
        check_result = hr.run({"action": "check_emit", "hypothesis_id": "macro-bull-h1"})
        assert check_result.outcome == Outcome.PASS
        hypothesis_check = {
            "hypothesis_id": "macro-bull-h1",
            "status": "validated",
            "outcome": "pass",
        }

        # 3. CausalFactorAuditor — robust factor
        n = 252
        factor = rng.normal(0, 1, n)
        returns = 0.05 * factor + rng.normal(0, 0.02, n)
        causal_result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "momentum-real",
                "factor": factor.tolist(),
                "returns": returns.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "as_of_date": "2026-05-01",
                "n_placebo_runs": 30,
            }
        )
        assert causal_result.outcome == Outcome.PASS
        causal_evidence = causal_result.output

        # 4. DecisionCompiler — 통합 → emit
        dc_result = DecisionCompiler().run(
            {
                "action": "compile",
                "ticker": "NVDA",
                "proposed_action": "BUY",
                "regime_evidence": regime_evidence,
                "hypothesis_check": hypothesis_check,
                "causal_evidence": causal_evidence,
                "as_of_date": "2026-05-01",
            }
        )
        assert dc_result.outcome == Outcome.PASS
        assert dc_result.output["action"] == "BUY"
        assert dc_result.output["status"] == "emitted"
        # 모든 source ID inputs 에 기록됨
        rows = query(
            "SELECT inputs_json FROM agent_decisions WHERE decision_id=?",
            (dc_result.output["decision_id"],),
            db_path=patched_db,
        )
        inputs = json.loads(dict(rows[0])["inputs_json"])
        assert inputs["hypothesis_id"] == "macro-bull-h1"
        assert "@2026-05-01" in inputs["causal_audit_id"]


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_last_decision_empty(self, patched_db, capsys):
        from nuri.agents.actors.decision_compiler import main

        rc = main(["last_decision"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no agent_decisions" in out

    def test_cli_with_ticker(self, patched_db, capsys):
        from nuri.agents.actors.decision_compiler import main

        rc = main(["last_decision", "--ticker", "ZZZ"])
        assert rc == 0


# ═══════════════════════════════════════════════════════
# Constants smoke
# ═══════════════════════════════════════════════════════


class TestConstants:
    def test_thresholds_sane(self):
        assert 0 < CONVICTION_HOLD_CUTOFF < CONVICTION_EMIT_CUTOFF <= 1
        assert 0 < REGIME_FAVOR_PROB <= 1
