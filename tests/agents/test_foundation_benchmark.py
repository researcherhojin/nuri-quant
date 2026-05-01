"""FoundationBenchmark tests (#529 Phase 2 — actor #7, canonical).

Layer B 검증 (Codex Round 5):
- Layer B (deterministic, ZERO LLM)
- 3 actions: benchmark / compare / list_runs
- caller-injected metric_value 패턴 (foundation 모델 inference 는 별도 PR)

Anti-pattern lock-tests:
1. model_kind / metric_name enum 위반 → BLOCK (helper level)
2. sample_n < 0 → BLOCK
3. compare 시 단 1개 model 만 등록 → WARN (insufficient_models)
4. compare benchmark_run 미존재 → BLOCK
5. higher_is_better 방향 따라 winner 결정 정확
6. Discord publish foundation>baseline (>10%) 시만 발화 (mock)
7. CLI happy path
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.foundation_benchmark import (
    SIGNIFICANT_IMPROVEMENT_PCT,
    FoundationBenchmark,
    main,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_foundation_benchmark, query

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "fb.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch(
            "nuri.agents.base.log_agent_audit",
            side_effect=make_redirect(db_module.log_agent_audit),
        ),
        patch(
            "nuri.agents.base.start_agent_run",
            side_effect=make_redirect(db_module.start_agent_run),
        ),
        patch(
            "nuri.agents.base.finish_agent_run",
            side_effect=make_redirect(db_module.finish_agent_run),
        ),
        patch(
            "nuri.agents.actors.foundation_benchmark.log_foundation_benchmark",
            side_effect=make_redirect(db_module.log_foundation_benchmark),
        ),
        patch(
            "nuri.agents.actors.foundation_benchmark.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _seed(
    db_path,
    *,
    benchmark_run: str = "2026-05-01-test",
    model_id: str = "sticky-hmm-v1",
    model_kind: str = "baseline",
    metric_name: str = "brier",
    metric_value: float = 0.20,
    higher_is_better: bool = False,
    sample_n: int = 100,
) -> int:
    """foundation_benchmarks row 시드."""
    return log_foundation_benchmark(
        benchmark_run=benchmark_run,
        model_id=model_id,
        model_kind=model_kind,
        metric_name=metric_name,
        metric_value=metric_value,
        higher_is_better=higher_is_better,
        sample_n=sample_n,
        db_path=db_path,
    )


# ═══════════════════════════════════════════════════════
# Layer B invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert FoundationBenchmark.layer == Layer.B

    def test_actor_name(self):
        assert FoundationBenchmark.name == "foundation-benchmark"

    def test_no_llm_dependency(self):
        assert getattr(FoundationBenchmark, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert "foundation-benchmark" in REGISTRY.CANONICAL_15
        assert REGISTRY.get("foundation-benchmark") is FoundationBenchmark


# ═══════════════════════════════════════════════════════
# Helper lock tests (model_kind / metric_name / sample_n)
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    """log_foundation_benchmark helper 의 enum + range 검증."""

    def test_unknown_model_kind_rejected(self, db_path):
        with pytest.raises(ValueError, match="model_kind"):
            log_foundation_benchmark(
                benchmark_run="r",
                model_id="m",
                model_kind="weird",
                metric_name="brier",
                metric_value=0.1,
                higher_is_better=False,
                sample_n=10,
                db_path=db_path,
            )

    def test_unknown_metric_name_rejected(self, db_path):
        with pytest.raises(ValueError, match="metric_name"):
            log_foundation_benchmark(
                benchmark_run="r",
                model_id="m",
                model_kind="baseline",
                metric_name="unknown",
                metric_value=0.1,
                higher_is_better=False,
                sample_n=10,
                db_path=db_path,
            )

    def test_negative_sample_n_rejected(self, db_path):
        with pytest.raises(ValueError, match="sample_n"):
            log_foundation_benchmark(
                benchmark_run="r",
                model_id="m",
                model_kind="baseline",
                metric_name="brier",
                metric_value=0.1,
                higher_is_better=False,
                sample_n=-1,
                db_path=db_path,
            )

    def test_returns_lastrowid(self, db_path):
        bid = log_foundation_benchmark(
            benchmark_run="r",
            model_id="m",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.1,
            higher_is_better=False,
            sample_n=10,
            db_path=db_path,
        )
        assert bid >= 1


# ═══════════════════════════════════════════════════════
# benchmark action
# ═══════════════════════════════════════════════════════


class TestBenchmarkAction:
    def test_benchmark_inserts_row(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "2026-05-01-pilot",
                "model_id": "sticky-hmm-v1",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": 0.18,
                "sample_n": 252,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["benchmark_id"] >= 1
        assert result.output["model_kind"] == "baseline"
        rows = query("SELECT * FROM foundation_benchmarks", db_path=patched_db)
        assert len(rows) == 1
        assert rows[0]["model_id"] == "sticky-hmm-v1"
        assert rows[0]["benchmark_run"] == "2026-05-01-pilot"

    def test_benchmark_higher_is_better_default_for_sharpe(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m1",
                "model_kind": "baseline",
                "metric_name": "sharpe",
                "metric_value": 1.2,
                "sample_n": 100,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["higher_is_better"] is True

    def test_benchmark_higher_is_better_default_for_brier(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m1",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": 0.15,
                "sample_n": 100,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["higher_is_better"] is False

    def test_benchmark_caller_can_override_higher_is_better(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m1",
                "model_kind": "foundation",
                "metric_name": "sharpe",
                "metric_value": 1.5,
                "sample_n": 100,
                "higher_is_better": False,  # override (의도적)
            }
        )
        assert result.output["higher_is_better"] is False

    def test_benchmark_persists_walkforward_link(self, patched_db):
        actor = FoundationBenchmark()
        actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m1",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": 0.2,
                "sample_n": 50,
                "pit_hash": "abc123",
                "walkforward_run_id": "wf-uuid-1",
                "notes": "fold spec rolling/252/21/21",
            }
        )
        rows = query("SELECT * FROM foundation_benchmarks", db_path=patched_db)
        assert rows[0]["pit_hash"] == "abc123"
        assert rows[0]["walkforward_run_id"] == "wf-uuid-1"
        assert rows[0]["notes"] == "fold spec rolling/252/21/21"

    def test_benchmark_records_actor_run_id(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m1",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": 0.2,
                "sample_n": 50,
            }
        )
        rows = query("SELECT * FROM foundation_benchmarks", db_path=patched_db)
        # actor_run_id is set by actor (RunContext.run_id)
        assert rows[0]["actor_run_id"] is not None
        assert len(rows[0]["actor_run_id"]) > 0
        # PASS output 에 benchmark_id 포함
        assert "benchmark_id" in result.output


class TestBenchmarkValidation:
    def test_missing_required_fields_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "benchmark", "benchmark_run": "r1"})
        assert result.outcome == Outcome.BLOCK
        assert "missing" in result.output["error"].lower() or "requires" in result.output["error"].lower()

    def test_invalid_model_kind_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m",
                "model_kind": "not_a_kind",
                "metric_name": "brier",
                "metric_value": 0.1,
                "sample_n": 10,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "model_kind" in result.output["error"]

    def test_invalid_metric_name_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m",
                "model_kind": "baseline",
                "metric_name": "not_a_metric",
                "metric_value": 0.1,
                "sample_n": 10,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "metric_name" in result.output["error"]

    def test_negative_sample_n_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": 0.1,
                "sample_n": -5,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "sample_n" in result.output["error"]

    def test_uncastable_metric_value_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "benchmark",
                "benchmark_run": "r1",
                "model_id": "m",
                "model_kind": "baseline",
                "metric_name": "brier",
                "metric_value": "not_a_number",
                "sample_n": 10,
            }
        )
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# compare action
# ═══════════════════════════════════════════════════════


class TestCompareAction:
    def test_unknown_run_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "ghost"})
        assert result.outcome == Outcome.BLOCK
        assert "not found" in result.output["error"]

    def test_missing_benchmark_run_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare"})
        assert result.outcome == Outcome.BLOCK

    def test_single_model_returns_warn(self, patched_db):
        _seed(patched_db, benchmark_run="r-solo", model_id="lone")
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "r-solo"})
        assert result.outcome == Outcome.WARN
        assert result.output["comparisons"][0]["verdict"] == "insufficient_models"

    def test_foundation_wins_significantly_pass(self, patched_db):
        # baseline brier 0.20, foundation brier 0.15 → foundation 25% 우수 (lower better)
        _seed(
            patched_db,
            benchmark_run="rcmp",
            model_id="hmm-base",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rcmp",
            model_id="timesfm-2.5",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.15,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rcmp"})
        assert result.outcome == Outcome.PASS
        cmp = result.output["comparisons"][0]
        assert cmp["winner_model_id"] == "timesfm-2.5"
        assert cmp["verdict"] == "foundation_wins_significantly"
        assert result.output["any_foundation_significant_win"] is True

    def test_baseline_wins_pass(self, patched_db):
        # baseline brier 0.10 < foundation brier 0.30 → baseline winner
        _seed(
            patched_db,
            benchmark_run="rb",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.10,
        )
        _seed(
            patched_db,
            benchmark_run="rb",
            model_id="big-foundation",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.30,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rb"})
        assert result.outcome == Outcome.PASS
        cmp = result.output["comparisons"][0]
        assert cmp["winner_kind"] == "baseline"
        assert cmp["verdict"] == "baseline_robust"
        assert result.output["any_foundation_significant_win"] is False

    def test_foundation_wins_marginal(self, patched_db):
        # baseline 0.20, foundation 0.198 → 1% improvement (< SIGNIFICANT 10%)
        _seed(
            patched_db,
            benchmark_run="rm",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rm",
            model_id="found-light",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.198,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rm"})
        assert result.outcome == Outcome.PASS
        cmp = result.output["comparisons"][0]
        assert cmp["verdict"] == "foundation_wins_marginal"
        assert result.output["any_foundation_significant_win"] is False

    def test_tie_verdict(self, patched_db):
        # 둘 다 0.200 ≈ 동일 → tie (delta < 1%)
        _seed(
            patched_db,
            benchmark_run="rt",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.200,
        )
        _seed(
            patched_db,
            benchmark_run="rt",
            model_id="found-tie",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.2005,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rt"})
        cmp = result.output["comparisons"][0]
        assert cmp["verdict"] == "tie"

    def test_higher_is_better_direction_sharpe(self, patched_db):
        # sharpe higher better — baseline 0.8 vs foundation 1.5 → foundation winner (87% improvement)
        _seed(
            patched_db,
            benchmark_run="rs",
            model_id="hmm",
            model_kind="baseline",
            metric_name="sharpe",
            metric_value=0.8,
            higher_is_better=True,
        )
        _seed(
            patched_db,
            benchmark_run="rs",
            model_id="found",
            model_kind="foundation",
            metric_name="sharpe",
            metric_value=1.5,
            higher_is_better=True,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rs"})
        cmp = result.output["comparisons"][0]
        assert cmp["winner_model_id"] == "found"
        assert cmp["verdict"] == "foundation_wins_significantly"
        # delta_relative ≈ 0.875 (87.5%)
        assert cmp["delta_relative"] > SIGNIFICANT_IMPROVEMENT_PCT

    def test_metric_name_filter(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rfilt",
            model_id="m1",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rfilt",
            model_id="m2",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.10,
        )
        _seed(
            patched_db,
            benchmark_run="rfilt",
            model_id="m1",
            model_kind="baseline",
            metric_name="sharpe",
            metric_value=0.5,
            higher_is_better=True,
        )
        _seed(
            patched_db,
            benchmark_run="rfilt",
            model_id="m2",
            model_kind="foundation",
            metric_name="sharpe",
            metric_value=1.0,
            higher_is_better=True,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rfilt", "metric_name": "brier"})
        assert result.outcome == Outcome.PASS
        # only brier compared
        assert result.output["n_metrics"] == 1
        assert result.output["comparisons"][0]["metric_name"] == "brier"

    def test_invalid_metric_filter_blocked(self, patched_db):
        _seed(patched_db, benchmark_run="rx")
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rx", "metric_name": "garbage"})
        assert result.outcome == Outcome.BLOCK

    def test_model_ids_filter(self, patched_db):
        _seed(patched_db, benchmark_run="rmid", model_id="a", model_kind="baseline", metric_value=0.20)
        _seed(patched_db, benchmark_run="rmid", model_id="b", model_kind="foundation", metric_value=0.10)
        _seed(patched_db, benchmark_run="rmid", model_id="c", model_kind="traditional", metric_value=0.30)
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "compare",
                "benchmark_run": "rmid",
                "model_ids": ["a", "b"],
            }
        )
        assert result.outcome == Outcome.PASS
        cmp = result.output["comparisons"][0]
        # winner among {a, b} should be b (foundation 0.10 < baseline 0.20)
        assert cmp["winner_model_id"] == "b"
        assert cmp["n_models"] == 2

    def test_invalid_model_ids_filter_blocked(self, patched_db):
        _seed(patched_db, benchmark_run="rmid2")
        actor = FoundationBenchmark()
        result = actor.run(
            {
                "action": "compare",
                "benchmark_run": "rmid2",
                "model_ids": "not_a_list",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_traditional_winner_verdict(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rtr",
            model_id="naive",
            model_kind="traditional",
            metric_name="brier",
            metric_value=0.10,
        )
        _seed(
            patched_db,
            benchmark_run="rtr",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        actor = FoundationBenchmark()
        result = actor.run({"action": "compare", "benchmark_run": "rtr"})
        cmp = result.output["comparisons"][0]
        assert cmp["verdict"] == "traditional_wins"


# ═══════════════════════════════════════════════════════
# list_runs action
# ═══════════════════════════════════════════════════════


class TestListRuns:
    def test_empty_db(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs"})
        assert result.outcome == Outcome.PASS
        assert result.output["n_runs"] == 0

    def test_distinct_runs_returned(self, patched_db):
        _seed(patched_db, benchmark_run="r-A", model_id="m1")
        _seed(patched_db, benchmark_run="r-A", model_id="m2")
        _seed(patched_db, benchmark_run="r-B", model_id="m1")
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs"})
        assert result.outcome == Outcome.PASS
        run_ids = {r["benchmark_run"] for r in result.output["runs"]}
        assert run_ids == {"r-A", "r-B"}

    def test_n_models_aggregation(self, patched_db):
        _seed(patched_db, benchmark_run="rN", model_id="m1")
        _seed(patched_db, benchmark_run="rN", model_id="m2")
        _seed(
            patched_db, benchmark_run="rN", model_id="m1", metric_name="sharpe", metric_value=1.0, higher_is_better=True
        )  # 같은 model_id 다른 metric
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs"})
        runs = {r["benchmark_run"]: r for r in result.output["runs"]}
        assert runs["rN"]["n_models"] == 2  # distinct model_id
        assert runs["rN"]["n_rows"] == 3

    def test_limit_respected(self, patched_db):
        for i in range(5):
            _seed(patched_db, benchmark_run=f"r-{i}", model_id="m1")
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs", "limit": 3})
        assert result.outcome == Outcome.PASS
        assert result.output["n_runs"] == 3

    def test_invalid_limit_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs", "limit": "huge"})
        assert result.outcome == Outcome.BLOCK

    def test_zero_limit_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "list_runs", "limit": 0})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Invalid action
# ═══════════════════════════════════════════════════════


class TestInvalidAction:
    def test_invalid_action_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({"action": "ghost"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_action_blocked(self, patched_db):
        actor = FoundationBenchmark()
        result = actor.run({})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Discord publish
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    """PR3 Codex Round 6: foundation win → outbox stage_rollout."""

    def test_significant_foundation_win_stages(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rpub",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rpub",
            model_id="found",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.10,
        )
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            actor = FoundationBenchmark()
            result = actor.run({"action": "compare", "benchmark_run": "rpub"})
            assert result.outcome == Outcome.PASS
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "foundation_promotion"

    def test_baseline_winner_does_not_stage(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rnopub",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.10,
        )
        _seed(
            patched_db,
            benchmark_run="rnopub",
            model_id="found",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.30,
        )
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            actor = FoundationBenchmark()
            actor.run({"action": "compare", "benchmark_run": "rnopub"})
            assert not mock_stage.called

    def test_marginal_foundation_win_does_not_stage(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rmar",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rmar",
            model_id="found",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.198,
        )
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            actor = FoundationBenchmark()
            actor.run({"action": "compare", "benchmark_run": "rmar"})
            assert not mock_stage.called

    def test_publish_failure_does_not_block_actor(self, patched_db):
        _seed(
            patched_db,
            benchmark_run="rfail",
            model_id="hmm",
            model_kind="baseline",
            metric_name="brier",
            metric_value=0.20,
        )
        _seed(
            patched_db,
            benchmark_run="rfail",
            model_id="found",
            model_kind="foundation",
            metric_name="brier",
            metric_value=0.10,
        )
        with patch(
            "nuri.agents.discord.outbox.stage_rollout",
            side_effect=RuntimeError("outbox down"),
        ):
            actor = FoundationBenchmark()
            result = actor.run({"action": "compare", "benchmark_run": "rfail"})
            assert result.outcome == Outcome.PASS

    def test_benchmark_action_does_not_publish(self, patched_db):
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            actor = FoundationBenchmark()
            actor.run(
                {
                    "action": "benchmark",
                    "benchmark_run": "r1",
                    "model_id": "m1",
                    "model_kind": "foundation",
                    "metric_name": "brier",
                    "metric_value": 0.05,
                    "sample_n": 100,
                }
            )
            assert not mock_stage.called


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCLI:
    def test_cli_list_runs_returns_zero(self, patched_db, capsys):
        rc = main(["list_runs", "--limit", "3"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "runs" in out

    def test_cli_benchmark_missing_required_returns_2(self, patched_db, capsys):
        rc = main(["benchmark"])
        assert rc == 2

    def test_cli_compare_missing_required_returns_2(self, patched_db, capsys):
        rc = main(["compare"])
        assert rc == 2

    def test_cli_benchmark_happy_path(self, patched_db, capsys):
        rc = main(
            [
                "benchmark",
                "--benchmark-run",
                "cli-test",
                "--model-id",
                "m-cli",
                "--model-kind",
                "baseline",
                "--metric-name",
                "brier",
                "--metric-value",
                "0.15",
                "--sample-n",
                "50",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "benchmark_id" in out
