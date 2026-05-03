"""nuri.agents.base 테스트 — Layer A/B/C 분리 + lifecycle audit (#529 Phase 1).

Codex Round 5 mandatory 검증:
- Layer A actor 는 outcome 필수 + LLM 의존 금지
- 모든 invocation 자동 audit + run_ledger 기록
- Exception 시 'failed' 상태 + ERROR outcome 기록 (graceful degradation)
- ActorRegistry 는 canonical 15-actor 목록만 허용
"""

from typing import Any
from unittest.mock import patch

import pytest

from nuri.agents.base import (
    Actor,
    ActorRegistry,
    ActorResult,
    Layer,
    Outcome,
    RunContext,
)
from nuri.core.db import init_db, query


@pytest.fixture
def db_path(tmp_path):
    """임시 DB — 매 테스트 격리 + #529 schema 적용."""
    path = tmp_path / "agents.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """nuri.agents.base 의 db 호출을 임시 DB 로 redirect."""
    from nuri.core import db as db_module

    original_log = db_module.log_agent_audit
    original_start = db_module.start_agent_run
    original_finish = db_module.finish_agent_run

    def log(*args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return original_log(*args, **kwargs)

    def start(*args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return original_start(*args, **kwargs)

    def finish(*args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return original_finish(*args, **kwargs)

    with (
        patch("nuri.agents.base.log_agent_audit", side_effect=log),
        patch("nuri.agents.base.start_agent_run", side_effect=start),
        patch("nuri.agents.base.finish_agent_run", side_effect=finish),
    ):
        yield db_path


# ─── Test fixtures: minimal Layer A/B/C actors ──────────────────────────────


class _FreshnessGatekeeperFake(Actor):
    name = "freshness-gatekeeper"
    version = "0.1.0"
    layer = Layer.A

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        stale = input_data.get("stale", False)
        return ActorResult(
            output={"stale": stale, "ticker": input_data.get("ticker")},
            outcome=Outcome.BLOCK if stale else Outcome.PASS,
            sample_n=1,
            input_summary=f"freshness check {input_data.get('ticker')}",
        )


class _RegimePosteriorFake(Actor):
    name = "regime-posterior"
    version = "0.1.0"
    layer = Layer.B

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        return ActorResult(
            output={"posterior": [0.05, 0.78, 0.15, 0.02]},
            sample_n=input_data.get("n", 100),
        )


class _DriftSentinelFake(Actor):
    name = "drift-sentinel"
    version = "0.1.0"
    layer = Layer.C

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        return ActorResult(
            output={"psi": 0.23},
            llm_narrative="drift detected after FOMC regime shift",
        )


class _CrashingActor(Actor):
    name = "execution-firewall"
    version = "0.1.0"
    layer = Layer.A

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        raise RuntimeError("KIS API 401")


class _LayerANoOutcomeActor(Actor):
    name = "audit-ledger"  # canonical name 재활용 (테스트 한정)
    version = "0.1.0"
    layer = Layer.A

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        return ActorResult(output={"x": 1})  # outcome 누락 → ValueError


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestActorBaseValidation:
    def test_missing_name_raises(self):
        class Anon(Actor):
            layer = Layer.B

            def execute(self, input_data, ctx):
                return ActorResult(output={})

        with pytest.raises(ValueError, match="name must be set"):
            Anon()

    def test_layer_a_with_llm_companion_raises(self):
        class BadActor(Actor):
            name = "freshness-gatekeeper"
            layer = Layer.A
            _uses_llm = True

            def execute(self, input_data, ctx):
                return ActorResult(output={}, outcome=Outcome.PASS)

        with pytest.raises(RuntimeError, match="Layer A actor cannot use LLM"):
            BadActor()


class TestActorLifecycle:
    def test_layer_a_pass_decision_logged(self, patched_db):
        actor = _FreshnessGatekeeperFake()
        result = actor.run({"ticker": "TSLA", "stale": False})
        assert result.outcome == Outcome.PASS

        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["actor_name"] == "freshness-gatekeeper"
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "pass"

    def test_layer_a_block_decision_logged(self, patched_db):
        actor = _FreshnessGatekeeperFake()
        result = actor.run({"ticker": "OKLO", "stale": True})
        assert result.outcome == Outcome.BLOCK

        rows = query(
            "SELECT outcome FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["outcome"] == "block"

    def test_layer_b_no_outcome_required(self, patched_db):
        actor = _RegimePosteriorFake()
        result = actor.run({"n": 250})
        assert result.outcome is None
        assert result.sample_n == 250

        rows = query(
            "SELECT layer, outcome, sample_n FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["layer"] == "B"
        assert rows[0]["outcome"] is None
        assert rows[0]["sample_n"] == 250

    def test_layer_c_llm_narrative_recorded(self, patched_db):
        actor = _DriftSentinelFake()
        actor.run({"ticker": "NVDA"})

        rows = query(
            "SELECT layer, llm_narrative FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["layer"] == "C"
        assert "FOMC" in rows[0]["llm_narrative"]

    def test_run_ledger_records_lifecycle(self, patched_db):
        actor = _RegimePosteriorFake()
        actor.run({"n": 100})

        rows = query(
            "SELECT actor_name, status, duration_ms FROM agent_run_ledger",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["actor_name"] == "regime-posterior"
        assert rows[0]["status"] == "finished"
        assert rows[0]["duration_ms"] is not None

    def test_exception_records_failed_status(self, patched_db):
        actor = _CrashingActor()
        with pytest.raises(RuntimeError, match="KIS API 401"):
            actor.run({"x": 1})

        runs = query(
            "SELECT status, error_message FROM agent_run_ledger",
            db_path=patched_db,
        )
        assert runs[0]["status"] == "failed"
        assert "401" in runs[0]["error_message"]

        audits = query(
            "SELECT outcome, output FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert audits[0]["outcome"] == "error"
        assert "401" in audits[0]["output"]

    def test_layer_a_missing_outcome_raises(self, patched_db):
        actor = _LayerANoOutcomeActor()
        with pytest.raises(ValueError, match="must return outcome"):
            actor.run({"x": 1})

        runs = query(
            "SELECT status, error_message FROM agent_run_ledger",
            db_path=patched_db,
        )
        assert runs[0]["status"] == "failed"
        assert "no outcome" in runs[0]["error_message"]

    def test_parent_run_id_chain_recorded(self, patched_db):
        """Decision-Compiler → Execution-Firewall causation chain."""
        parent = _RegimePosteriorFake()
        parent.run({"n": 50})

        # parent_run_id 추출 (audit ledger)
        parent_runs = query(
            "SELECT run_id FROM agent_run_ledger",
            db_path=patched_db,
        )
        parent_run_id = parent_runs[0]["run_id"]

        child = _FreshnessGatekeeperFake()
        child.run({"ticker": "X", "stale": False}, parent_run_id=parent_run_id)

        chains = query(
            "SELECT actor_name, parent_run_id FROM agent_run_ledger ORDER BY started_at",
            db_path=patched_db,
        )
        assert len(chains) == 2
        assert chains[1]["actor_name"] == "freshness-gatekeeper"
        assert chains[1]["parent_run_id"] == parent_run_id

    def test_input_hash_stable_across_dict_order(self, patched_db):
        """sort_keys 로 dict 순서 무관 hash."""
        actor1 = _RegimePosteriorFake()
        actor2 = _RegimePosteriorFake()
        actor1.run({"a": 1, "b": 2})
        actor2.run({"b": 2, "a": 1})

        hashes = query(
            "SELECT input_hash FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert hashes[0]["input_hash"] == hashes[1]["input_hash"]

    def test_decision_id_default_to_run_id(self, patched_db):
        actor = _RegimePosteriorFake()
        actor.run({"n": 1})

        rows = query(
            "SELECT decision_id, run_id FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["decision_id"] == rows[0]["run_id"]

    def test_explicit_decision_id_overrides(self, patched_db):
        actor = _RegimePosteriorFake()
        actor.run({"n": 1}, decision_id="dec-shared-001")

        rows = query(
            "SELECT decision_id FROM agent_audit_ledger",
            db_path=patched_db,
        )
        assert rows[0]["decision_id"] == "dec-shared-001"


class TestActorRegistry:
    def test_canonical_15_count(self):
        assert len(ActorRegistry.CANONICAL_15) == 15

    def test_register_canonical_actor(self):
        reg = ActorRegistry()
        cls = reg.register(_FreshnessGatekeeperFake)
        assert cls is _FreshnessGatekeeperFake
        assert reg.get("freshness-gatekeeper") is _FreshnessGatekeeperFake

    def test_register_non_canonical_raises(self):
        class FooActor(Actor):
            name = "foo-actor"
            layer = Layer.B

            def execute(self, input_data, ctx):
                return ActorResult(output={})

        reg = ActorRegistry()
        with pytest.raises(ValueError, match="not in canonical 15"):
            reg.register(FooActor)

    def test_register_same_class_idempotent(self):
        """re-import 시 같은 class 재등록 OK (python -m 패턴)."""
        reg = ActorRegistry()
        reg.register(_FreshnessGatekeeperFake)
        reg.register(_FreshnessGatekeeperFake)
        assert reg.get("freshness-gatekeeper") is _FreshnessGatekeeperFake

    def test_register_different_class_same_name_raises(self):
        """다른 class 가 같은 name 으로 등록 시도 시 거부 (silent overwrite 방지)."""

        class Conflicting(Actor):
            name = "freshness-gatekeeper"
            layer = Layer.A

            def execute(self, input_data, ctx):
                return ActorResult(output={}, outcome=Outcome.PASS)

        reg = ActorRegistry()
        reg.register(_FreshnessGatekeeperFake)
        with pytest.raises(ValueError, match="refusing to overwrite"):
            reg.register(Conflicting)

    def test_missing_returns_unregistered_actors(self):
        reg = ActorRegistry()
        reg.register(_FreshnessGatekeeperFake)
        missing = reg.missing()
        assert "freshness-gatekeeper" not in missing
        assert "execution-firewall" in missing
        assert len(missing) == 14

    def test_all_returns_dict_copy(self):
        """all() 은 internal registry dict 의 copy 를 반환 (line 281)."""
        reg = ActorRegistry()
        reg.register(_FreshnessGatekeeperFake)
        snapshot = reg.all()
        assert snapshot["freshness-gatekeeper"] is _FreshnessGatekeeperFake
        # mutation 이 internal state 에 새지 않아야 함 — copy 라면 caller 의 변경이 누설 안 됨
        snapshot.pop("freshness-gatekeeper")
        # 원본은 그대로 — copy 였다면
        assert reg.get("freshness-gatekeeper") is _FreshnessGatekeeperFake

    def test_invalid_layer_raises(self):
        """Layer Enum 외 값을 layer 로 강제 주입 시 ValueError (line 105)."""

        class BadLayer(Actor):
            name = "freshness-gatekeeper"  # canonical 통과
            # layer 를 Enum 이 아닌 raw string 으로 — typing 무시 시 발생
            layer = "Z"  # type: ignore[assignment]

            def execute(self, input_data, ctx):
                return ActorResult(output={}, outcome=Outcome.PASS)

        with pytest.raises(ValueError, match="layer must be"):
            BadLayer()
