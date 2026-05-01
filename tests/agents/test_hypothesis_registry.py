"""HypothesisRegistry tests (#529 Phase 2 — actor #4, canonical).

검증 (Codex Round 5 Layer A):
- Layer A enforcement (outcome 필수, ZERO LLM)
- 6 actions: register / validate / reject / expire / check_emit / list_open
- Status machine (open → validated|rejected|expired) 강제
- Anti-pattern lock-tests:
    1. validation_metrics 없이 validated 전이 → ValueError
    2. rejection_reason 없이 rejected 전이 → ValueError
    3. expired/rejected/open hypothesis emit 시도 → BLOCK
    4. validated 재validate → ValueError
    5. 동일 (producer + claim) 중복 register → idempotent (기존 id, is_new=False)
- Discord publish: validated/rejected → ROLLOUT (mock), publish 실패 시 actor outcome 영향 X
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from nuri.agents.actors.hypothesis_registry import (
    DEFAULT_EXPIRY_DAYS,
    HypothesisRegistry,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import (
    expire_hypotheses,
    init_db,
    query,
    register_hypothesis,
    reject_hypothesis,
    validate_hypothesis,
)

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "hr.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect (base + actor + helpers)."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
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
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _register_payload(**overrides):
    """기본 register payload — 테스트마다 부분 override."""
    payload = {
        "action": "register",
        "hypothesis_id": "h-1",
        "name": "regime-bull-shift",
        "version": "1.0.0",
        "producer_actor": "regime-posterior",
        "claim_text": "posterior bull > 0.7",
        "evidence": {"posterior": [0.8, 0.15, 0.05]},
        "expiry_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


# ═══════════════════════════════════════════════════════
# Layer A invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_a(self):
        assert HypothesisRegistry.layer == Layer.A

    def test_no_llm_dependency(self):
        assert getattr(HypothesisRegistry, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("hypothesis-registry") is HypothesisRegistry


# ═══════════════════════════════════════════════════════
# Action: register — input validation + idempotency
# ═══════════════════════════════════════════════════════


class TestActionRegister:
    def test_invalid_action_blocked(self, patched_db):
        result = HypothesisRegistry().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_required_blocks(self, patched_db):
        for missing in ("hypothesis_id", "name", "version", "producer_actor", "claim_text", "evidence"):
            payload = _register_payload()
            del payload[missing]
            result = HypothesisRegistry().run(payload)
            assert result.outcome == Outcome.BLOCK, f"missing {missing} should block"
            assert missing in result.output["error"]

    def test_register_pass(self, patched_db):
        result = HypothesisRegistry().run(_register_payload())
        assert result.outcome == Outcome.PASS
        assert result.output["hypothesis_id"] == "h-1"
        assert result.output["is_new"] is True

    def test_register_idempotent_on_claim_hash(self, patched_db):
        """동일 (producer + claim) 재등록 → 기존 id 반환, is_new=False."""
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run(_register_payload(hypothesis_id="different-id"))
        assert result.outcome == Outcome.PASS
        assert result.output["hypothesis_id"] == "h-1"  # 기존 id 유지
        assert result.output["is_new"] is False

    def test_register_default_expiry_90d(self, patched_db):
        """expiry_date 미제공 시 today + 90d 자동 설정."""
        payload = _register_payload()
        del payload["expiry_date"]
        from nuri.core.timezone import today_kst

        result = HypothesisRegistry().run(payload)
        assert result.outcome == Outcome.PASS
        expected = (date.fromisoformat(today_kst()) + timedelta(days=DEFAULT_EXPIRY_DAYS)).isoformat()
        assert result.output["expiry_date"] == expected

    def test_invalid_canary_scope_blocked(self, patched_db):
        result = HypothesisRegistry().run(_register_payload(canary_scope="beta"))
        assert result.outcome == Outcome.BLOCK
        assert "canary_scope" in result.output["error"]

    def test_register_persists_full_row(self, patched_db):
        HypothesisRegistry().run(_register_payload(feature_flag="cycle_engine_v1", canary_scope="paper"))
        rows = query("SELECT * FROM hypotheses WHERE hypothesis_id=?", ("h-1",), db_path=patched_db)
        r = dict(rows[0])
        assert r["status"] == "open"
        assert r["feature_flag"] == "cycle_engine_v1"
        assert r["canary_scope"] == "paper"
        assert r["validated_at"] is None


# ═══════════════════════════════════════════════════════
# Action: validate — Anti-pattern lock-test #1, #4
# ═══════════════════════════════════════════════════════


class TestActionValidate:
    def test_validate_pass(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run(
            {
                "action": "validate",
                "hypothesis_id": "h-1",
                "validation_metrics": {"realized_brier": 0.18, "logloss": 0.42},
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["status"] == "validated"

    def test_validate_missing_metrics_blocks(self, patched_db):
        """LOCK-TEST: validation_metrics 없이 validated 전이 차단."""
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run({"action": "validate", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK

    def test_validate_empty_metrics_blocks(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {}})
        assert result.outcome == Outcome.BLOCK

    def test_validate_unknown_id_blocks(self, patched_db):
        result = HypothesisRegistry().run(
            {"action": "validate", "hypothesis_id": "nonexistent", "validation_metrics": {"x": 1}}
        )
        assert result.outcome == Outcome.BLOCK
        assert "not found" in result.output["error"]

    def test_revalidate_blocked(self, patched_db):
        """LOCK-TEST: validated → validated 재전이 차단 (status machine)."""
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {"x": 1}})
        result = actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {"x": 2}})
        assert result.outcome == Outcome.BLOCK
        assert "status='validated'" in result.output["error"] or "status=" in result.output["error"]


# ═══════════════════════════════════════════════════════
# Action: reject — Anti-pattern lock-test #2
# ═══════════════════════════════════════════════════════


class TestActionReject:
    def test_reject_pass(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run(
            {
                "action": "reject",
                "hypothesis_id": "h-1",
                "rejection_reason": "Brier > 0.4 (poor calibration)",
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["status"] == "rejected"

    def test_reject_missing_reason_blocks(self, patched_db):
        """LOCK-TEST: rejection_reason 없이 rejected 전이 차단."""
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run({"action": "reject", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK

    def test_reject_already_rejected_blocks(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        actor.run({"action": "reject", "hypothesis_id": "h-1", "rejection_reason": "x"})
        result = actor.run({"action": "reject", "hypothesis_id": "h-1", "rejection_reason": "y"})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Action: expire — cron-style sweep
# ═══════════════════════════════════════════════════════


class TestActionExpire:
    def test_expire_no_stale_returns_zero(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())  # expiry 2026-08-01 미래
        result = actor.run({"action": "expire"})
        assert result.outcome == Outcome.PASS
        assert result.output["expired_count"] == 0

    def test_expire_marks_stale(self, patched_db):
        """과거 expiry_date 의 open → expired 자동 전이."""
        actor = HypothesisRegistry()
        actor.run(_register_payload(expiry_date="2020-01-01"))
        result = actor.run({"action": "expire"})
        assert result.outcome == Outcome.PASS
        assert result.output["expired_count"] == 1
        rows = query("SELECT status FROM hypotheses WHERE hypothesis_id=?", ("h-1",), db_path=patched_db)
        assert dict(rows[0])["status"] == "expired"


# ═══════════════════════════════════════════════════════
# Action: check_emit — Anti-pattern lock-test #3 (emit gate)
# ═══════════════════════════════════════════════════════


class TestActionCheckEmit:
    """LOCK-TEST: check_emit 가 status enforcement 의 진짜 gate.

    fail 시 = open/expired/rejected hypothesis 의 emit 가 통과 → Decision-Compiler
    가 미검증 가설로 매매 추천 발행. Layer A 의 존재 이유.
    """

    def test_validated_passes(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {"x": 1}})
        result = actor.run({"action": "check_emit", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.PASS

    def test_open_blocks(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        result = actor.run({"action": "check_emit", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK
        assert "validated" in result.output["reason"]

    def test_rejected_blocks(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        actor.run({"action": "reject", "hypothesis_id": "h-1", "rejection_reason": "x"})
        result = actor.run({"action": "check_emit", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK

    def test_expired_blocks(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload(expiry_date="2020-01-01"))
        actor.run({"action": "expire"})
        result = actor.run({"action": "check_emit", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK

    def test_open_past_expiry_auto_blocks_without_explicit_expire(self, patched_db):
        """expire() 호출 안 했어도 emit 시점에 expiry 자동 감지 → BLOCK."""
        actor = HypothesisRegistry()
        actor.run(_register_payload(expiry_date="2020-01-01"))
        result = actor.run({"action": "check_emit", "hypothesis_id": "h-1"})
        assert result.outcome == Outcome.BLOCK
        assert "expiry_date" in result.output["reason"]

    def test_unknown_id_blocks(self, patched_db):
        result = HypothesisRegistry().run({"action": "check_emit", "hypothesis_id": "nonexistent"})
        assert result.outcome == Outcome.BLOCK
        assert "not found" in result.output["error"]

    def test_missing_id_blocks(self, patched_db):
        result = HypothesisRegistry().run({"action": "check_emit"})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Action: list_open
# ═══════════════════════════════════════════════════════


class TestActionListOpen:
    def test_empty_db_returns_zero(self, patched_db):
        result = HypothesisRegistry().run({"action": "list_open"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 0

    def test_only_open_returned(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload(hypothesis_id="open-1"))
        actor.run(_register_payload(hypothesis_id="rej-1", claim_text="other"))
        actor.run({"action": "reject", "hypothesis_id": "rej-1", "rejection_reason": "x"})
        result = actor.run({"action": "list_open"})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 1
        assert result.output["hypotheses"][0]["hypothesis_id"] == "open-1"


# ═══════════════════════════════════════════════════════
# Audit ledger trace + Layer A enforcement
# ═══════════════════════════════════════════════════════


class TestAuditLedger:
    def test_register_logged_with_layer_a(self, patched_db):
        HypothesisRegistry().run(_register_payload())
        rows = query(
            "SELECT layer, outcome FROM agent_audit_ledger WHERE actor_name='hypothesis-registry'",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "pass"

    def test_check_emit_block_logged(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())  # open
        actor.run({"action": "check_emit", "hypothesis_id": "h-1"})  # BLOCK
        rows = query(
            """SELECT outcome FROM agent_audit_ledger
               WHERE actor_name='hypothesis-registry' AND outcome='block'""",
            db_path=patched_db,
        )
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════
# Discord publish — best-effort
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    """PR3 Codex Round 6: validate/reject → outbox stage_rollout."""

    def test_validate_stages_to_rollout(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            result = actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {"brier": 0.2}})
            assert result.outcome == Outcome.PASS
            mock_stage.assert_called_once()
            kw = mock_stage.call_args.kwargs
            assert kw["actor_name"] == "hypothesis-registry"
            assert kw["payload"]["kind"] == "hypothesis_validated"

    def test_reject_stages_to_rollout(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            actor.run(
                {
                    "action": "reject",
                    "hypothesis_id": "h-1",
                    "rejection_reason": "Brier > 0.4",
                }
            )
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "hypothesis_rejected"

    def test_publish_failure_does_not_block_actor(self, patched_db):
        actor = HypothesisRegistry()
        actor.run(_register_payload())
        with patch(
            "nuri.agents.discord.outbox.stage_rollout",
            side_effect=RuntimeError("outbox down"),
        ):
            result = actor.run({"action": "validate", "hypothesis_id": "h-1", "validation_metrics": {"x": 1}})
            assert result.outcome == Outcome.PASS


# ═══════════════════════════════════════════════════════
# DB helper direct lock-tests (bypass actor)
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    def test_validate_helper_panics_without_metrics(self, db_path):
        register_hypothesis(
            hypothesis_id="x",
            name="x",
            version="1.0.0",
            producer_actor="test",
            claim_text="claim",
            evidence={},
            expiry_date="2026-12-31",
            db_path=db_path,
        )
        with pytest.raises(ValueError, match="validation_metrics dict required"):
            validate_hypothesis("x", {}, db_path=db_path)

    def test_reject_helper_panics_without_reason(self, db_path):
        register_hypothesis(
            hypothesis_id="y",
            name="y",
            version="1.0.0",
            producer_actor="test",
            claim_text="claim",
            evidence={},
            expiry_date="2026-12-31",
            db_path=db_path,
        )
        with pytest.raises(ValueError, match="rejection_reason required"):
            reject_hypothesis("y", "   ", db_path=db_path)

    def test_register_idempotent_helper(self, db_path):
        h1, new1 = register_hypothesis(
            hypothesis_id="z1",
            name="claim-A",
            version="1.0.0",
            producer_actor="P",
            claim_text="same claim",
            evidence={},
            expiry_date="2026-12-31",
            db_path=db_path,
        )
        h2, new2 = register_hypothesis(
            hypothesis_id="z2-different",
            name="claim-A",
            version="1.0.0",
            producer_actor="P",
            claim_text="same claim",
            evidence={},
            expiry_date="2026-12-31",
            db_path=db_path,
        )
        assert (h1, new1) == ("z1", True)
        assert (h2, new2) == ("z1", False)

    def test_invalid_canary_helper_rejected(self, db_path):
        with pytest.raises(ValueError, match="canary_scope must be"):
            register_hypothesis(
                hypothesis_id="bad",
                name="x",
                version="1.0.0",
                producer_actor="P",
                claim_text="x",
                evidence={},
                expiry_date="2026-12-31",
                canary_scope="beta",
                db_path=db_path,
            )

    def test_expire_helper_idempotent(self, db_path):
        register_hypothesis(
            hypothesis_id="stale",
            name="x",
            version="1.0.0",
            producer_actor="P",
            claim_text="x",
            evidence={},
            expiry_date="2020-01-01",
            db_path=db_path,
        )
        n1 = expire_hypotheses(db_path=db_path)
        n2 = expire_hypotheses(db_path=db_path)
        assert n1 == 1
        assert n2 == 0  # second call no-op


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_list_open_empty(self, patched_db, capsys):
        from nuri.agents.actors.hypothesis_registry import main

        rc = main(["list_open"])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"count": 0' in out

    def test_cli_register(self, patched_db, capsys):
        from nuri.agents.actors.hypothesis_registry import main

        rc = main(
            [
                "register",
                "--hypothesis-id",
                "cli-1",
                "--name",
                "test",
                "--version",
                "1.0.0",
                "--producer-actor",
                "test",
                "--claim-text",
                "test claim",
                "--evidence-json",
                '{"x": 1}',
                "--expiry-date",
                "2026-12-31",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "cli-1" in out

    def test_cli_check_emit_unknown(self, patched_db, capsys):
        from nuri.agents.actors.hypothesis_registry import main

        rc = main(["check_emit", "--hypothesis-id", "nonexistent"])
        assert rc == 1  # BLOCK exit

    def test_cli_expire(self, patched_db, capsys):
        from nuri.agents.actors.hypothesis_registry import main

        rc = main(["expire"])
        assert rc == 0
