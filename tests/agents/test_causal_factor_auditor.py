"""CausalFactorAuditor tests (#529 Phase 2 — actor #6, canonical).

검증 (Codex Round 5 + López de Prado 2025):
- Layer B (deterministic, ZERO LLM)
- 2 actions: audit / last_audit
- 4-test framework: DAG / placebo / event-study / negative control
- Anti-pattern lock-tests:
    1. n_obs < 100 → INSUFFICIENT (statistical power 부족)
    2. DAG cycle → INSUFFICIENT (검증 불가)
    3. placebo_t_ratio > 0.80 → MIRAGE (BLOCK 권고, WARN outcome)
    4. NaN/Inf in factor/returns → BLOCK
    5. shape mismatch → BLOCK
- composite causal_certainty ∈ [0, 1] 검증
- 12-field audit row (causal_audits) 영구 기록
- Discord publish: MIRAGE → ROLLOUT (mock), publish 실패 시 actor outcome 영향 X
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from nuri.agents.actors.causal_factor_auditor import (
    PLACEBO_T_RATIO_MIRAGE_CUTOFF,
    CausalFactorAuditor,
    _composite_certainty,
    _dag_plausibility_check,
    _event_study,
    _negative_control,
    _placebo_falsification,
    _t_stat,
    _verdict_from_results,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_causal_audit, query

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "cfa.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출 redirect."""
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
            "nuri.agents.actors.causal_factor_auditor.log_causal_audit",
            side_effect=make_redirect(db_module.log_causal_audit),
        ),
        patch(
            "nuri.agents.actors.causal_factor_auditor.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture
def genuine_factor():
    """진짜 causal: factor → returns 가 강한 신호."""
    rng = np.random.default_rng(42)
    n = 252
    factor = rng.normal(0, 1, n)
    returns = 0.05 * factor + rng.normal(0, 0.02, n)
    return factor, returns


@pytest.fixture
def random_factor():
    """Mirage 후보: factor 와 returns 무관 (placebo 가 origin 과 비슷)."""
    rng = np.random.default_rng(123)
    n = 252
    factor = rng.normal(0, 1, n)
    returns = rng.normal(0, 0.02, n)
    return factor, returns


# ═══════════════════════════════════════════════════════
# Layer B invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert CausalFactorAuditor.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(CausalFactorAuditor, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("causal-factor-auditor") is CausalFactorAuditor


# ═══════════════════════════════════════════════════════
# Math primitives
# ═══════════════════════════════════════════════════════


class TestMathPrimitives:
    def test_t_stat_perfect_relationship(self):
        x = np.linspace(-1, 1, 100)
        y = 2 * x + 0.001 * np.random.default_rng(0).normal(0, 1, 100)
        t = _t_stat(y, x)
        assert abs(t) > 50  # very strong t-stat

    def test_t_stat_no_relationship(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, 100)
        y = rng.normal(0, 1, 100)
        t = _t_stat(y, x)
        assert abs(t) < 5  # weak

    def test_t_stat_degenerate_zero(self):
        assert _t_stat(np.array([1.0, 1.0]), np.array([1.0, 2.0])) == 0.0
        assert _t_stat(np.array([1.0, 2.0]), np.array([1.0, 1.0])) == 0.0


# ═══════════════════════════════════════════════════════
# Test 1 — DAG plausibility
# ═══════════════════════════════════════════════════════


class TestDagPlausibility:
    def test_simple_chain_passes(self):
        result = _dag_plausibility_check([("a", "b"), ("b", "c")], ["a", "b", "c"])
        assert result["pass"] is True
        assert result["has_cycle"] is False

    def test_cycle_detected(self):
        """LOCK-TEST: cycle 검출 시 fail."""
        result = _dag_plausibility_check([("a", "b"), ("b", "a")], ["a", "b"])
        assert result["pass"] is False
        assert result["has_cycle"] is True

    def test_self_loop_detected(self):
        result = _dag_plausibility_check([("a", "a")], ["a"])
        assert result["pass"] is False
        assert result["has_cycle"] is True

    def test_unknown_node_in_edge(self):
        result = _dag_plausibility_check([("a", "z")], ["a", "b"])
        assert result["pass"] is False
        assert "unknown node" in result["reason"]

    def test_empty_dag_passes(self):
        result = _dag_plausibility_check([], [])
        assert result["pass"] is True

    def test_complex_dag(self):
        # a → b → d, a → c → d (diamond, no cycle)
        edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
        result = _dag_plausibility_check(edges, ["a", "b", "c", "d"])
        assert result["pass"] is True


# ═══════════════════════════════════════════════════════
# Test 2 — Placebo falsification
# ═══════════════════════════════════════════════════════


class TestPlaceboFalsification:
    def test_genuine_factor_passes_placebo(self, genuine_factor):
        f, r = genuine_factor
        result = _placebo_falsification(f, r, n_runs=100)
        assert result["pass"] is True
        assert result["verdict"] == "GENUINE"
        assert result["placebo_t_ratio"] < PLACEBO_T_RATIO_MIRAGE_CUTOFF

    def test_random_factor_flagged_as_mirage(self, random_factor):
        """LOCK-TEST: 무관한 factor → placebo 가 origin 과 비슷 → MIRAGE."""
        f, r = random_factor
        result = _placebo_falsification(f, r, n_runs=200)
        # random factor 의 origin t-stat 은 작고, placebo 도 비슷하게 작음
        # → ratio 가 cutoff 넘어감
        assert result["verdict"] == "MIRAGE"
        assert result["placebo_t_ratio"] > PLACEBO_T_RATIO_MIRAGE_CUTOFF

    def test_returns_origin_t_stat(self, genuine_factor):
        f, r = genuine_factor
        result = _placebo_falsification(f, r, n_runs=50)
        assert result["origin_t_stat"] > 0
        assert result["n_runs"] == 50


# ═══════════════════════════════════════════════════════
# Test 3 — Event-study
# ═══════════════════════════════════════════════════════


class TestEventStudy:
    def test_no_events_returns_skipped(self, genuine_factor):
        f, r = genuine_factor
        result = _event_study(f, r, [])
        assert result["pass"] is True
        assert result["skipped"] is True

    def test_strong_event_signal_passes(self):
        """artificially: event 직후 +5% returns spike."""
        n = 200
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.01, n)
        event_indices = [50, 100, 150]
        for ev in event_indices:
            returns[ev : ev + 3] += 0.05  # 3-day +5% spike
        factor = rng.normal(0, 1, n)
        result = _event_study(factor, returns, event_indices, window=3)
        assert result["pass"] is True
        assert result["t_stat"] > 1.96

    def test_too_few_returns_blocks(self, genuine_factor):
        f, _r = genuine_factor
        result = _event_study(f[:5], np.zeros(5), [2], window=10)
        assert result["pass"] is False


# ═══════════════════════════════════════════════════════
# Test 4 — Negative control
# ═══════════════════════════════════════════════════════


class TestNegativeControl:
    def test_no_negative_factors_skipped(self, genuine_factor):
        f, _ = genuine_factor
        result = _negative_control(f, {})
        assert result["pass"] is True
        assert result["skipped"] is True

    def test_uncorrelated_passes(self):
        rng = np.random.default_rng(42)
        f = rng.normal(0, 1, 200)
        neg = rng.normal(0, 1, 200)  # 독립
        result = _negative_control(f, {"placebo": neg})
        assert result["pass"] is True
        assert result["worst_abs_r"] < 0.30

    def test_strongly_correlated_fails(self):
        """LOCK-TEST: |r| > 0.30 → spurious 의심."""
        rng = np.random.default_rng(42)
        f = rng.normal(0, 1, 200)
        # neg 가 f 와 동일하게 움직임
        neg = f + rng.normal(0, 0.1, 200)  # |r| ~ 0.99
        result = _negative_control(f, {"highly_correlated": neg})
        assert result["pass"] is False
        assert result["worst_abs_r"] > 0.30
        assert result["worst_name"] == "highly_correlated"

    def test_constant_factor_zero_corr(self):
        f = np.ones(100)
        neg = np.array([float(i) for i in range(100)])
        result = _negative_control(f, {"x": neg})
        # 0/0 → 0 corr
        assert result["pass"] is True


# ═══════════════════════════════════════════════════════
# Composite certainty
# ═══════════════════════════════════════════════════════


class TestCompositeCertainty:
    def test_all_pass_max_certainty(self):
        cert = _composite_certainty(
            dag_pass=True,
            placebo={"pass": True, "placebo_t_ratio": 0.0},
            event_study={"pass": True},
            negative_control={"pass": True},
        )
        assert cert == pytest.approx(1.0, abs=1e-6)

    def test_all_fail_zero_certainty(self):
        cert = _composite_certainty(
            dag_pass=False,
            placebo={"pass": False, "placebo_t_ratio": 1.5},
            event_study={"pass": False},
            negative_control={"pass": False},
        )
        assert cert == 0.0

    def test_partial_pass_intermediate(self):
        cert = _composite_certainty(
            dag_pass=True,
            placebo={"pass": True, "placebo_t_ratio": 0.4},
            event_study={"pass": False},
            negative_control={"pass": True},
        )
        assert 0.0 < cert < 1.0


# ═══════════════════════════════════════════════════════
# Verdict mapping
# ═══════════════════════════════════════════════════════


class TestVerdictFromResults:
    def test_insufficient_when_n_obs_below_min(self):
        v = _verdict_from_results(n_obs=50, dag_pass=True, placebo={"verdict": "GENUINE"}, certainty=0.9)
        assert v == "INSUFFICIENT"

    def test_insufficient_when_dag_fails(self):
        v = _verdict_from_results(n_obs=200, dag_pass=False, placebo={"verdict": "GENUINE"}, certainty=0.9)
        assert v == "INSUFFICIENT"

    def test_mirage_when_placebo_flags(self):
        v = _verdict_from_results(n_obs=200, dag_pass=True, placebo={"verdict": "MIRAGE"}, certainty=0.9)
        assert v == "MIRAGE"

    def test_robust_when_high_certainty(self):
        v = _verdict_from_results(n_obs=200, dag_pass=True, placebo={"verdict": "GENUINE"}, certainty=0.85)
        assert v == "ROBUST"

    def test_weak_when_mid_certainty(self):
        v = _verdict_from_results(n_obs=200, dag_pass=True, placebo={"verdict": "GENUINE"}, certainty=0.5)
        assert v == "WEAK"

    def test_mirage_when_very_low_certainty(self):
        v = _verdict_from_results(n_obs=200, dag_pass=True, placebo={"verdict": "GENUINE"}, certainty=0.1)
        assert v == "MIRAGE"


# ═══════════════════════════════════════════════════════
# Action: audit — input validation + happy path
# ═══════════════════════════════════════════════════════


class TestActionAudit:
    def test_invalid_action_blocked(self, patched_db):
        result = CausalFactorAuditor().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_factor_id_blocks(self, patched_db, genuine_factor):
        f, r = genuine_factor
        result = CausalFactorAuditor().run({"action": "audit", "factor": f.tolist(), "returns": r.tolist()})
        assert result.outcome == Outcome.BLOCK

    def test_shape_mismatch_blocks(self, patched_db):
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "x",
                "factor": [1.0, 2.0],
                "returns": [1.0, 2.0, 3.0],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "shape" in result.output["error"]

    def test_nan_in_factor_blocks(self, patched_db):
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "x",
                "factor": [1.0, float("nan"), 3.0],
                "returns": [1.0, 2.0, 3.0],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "NaN" in result.output["error"] or "Inf" in result.output["error"]

    def test_2d_factor_blocks(self, patched_db):
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "x",
                "factor": [[1.0, 2.0], [3.0, 4.0]],
                "returns": [[1.0, 2.0], [3.0, 4.0]],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "1-D" in result.output["error"]

    def test_genuine_factor_audit_robust(self, patched_db, genuine_factor):
        f, r = genuine_factor
        rng = np.random.default_rng(99)
        neg = rng.normal(0, 1, len(f))
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "momentum-genuine",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "negative_factors": {"unrelated": neg.tolist()},
                "as_of_date": "2026-05-01",
                "n_placebo_runs": 50,  # speed
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["verdict"] == "ROBUST"
        assert result.output["causal_certainty"] > 0.7

    def test_random_factor_audit_mirage(self, patched_db, random_factor):
        """LOCK-TEST: 무관 factor 의 placebo > 0.80 ratio → MIRAGE → WARN."""
        f, r = random_factor
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "noise",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "as_of_date": "2026-05-01",
                "n_placebo_runs": 100,
            }
        )
        assert result.outcome == Outcome.WARN
        assert result.output["verdict"] == "MIRAGE"
        assert result.output["tests"]["placebo"]["placebo_t_ratio"] > 0.80

    def test_too_small_sample_insufficient(self, patched_db):
        """LOCK-TEST: n_obs < 100 → INSUFFICIENT."""
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "tiny",
                "factor": [1.0] * 50,
                "returns": [0.1] * 50,
                "dag_edges": [],
                "dag_nodes": [],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert result.output["verdict"] == "INSUFFICIENT"

    def test_dag_cycle_insufficient(self, patched_db, genuine_factor):
        """LOCK-TEST: DAG cycle → INSUFFICIENT."""
        f, r = genuine_factor
        result = CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "cyclic",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("a", "b"), ("b", "a")],
                "dag_nodes": ["a", "b"],
                "n_placebo_runs": 30,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert result.output["verdict"] == "INSUFFICIENT"

    def test_audit_persists_full_row(self, patched_db, genuine_factor):
        f, r = genuine_factor
        CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "persist-test",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "as_of_date": "2026-05-01",
                "n_placebo_runs": 30,
            }
        )
        rows = query(
            "SELECT * FROM causal_audits WHERE factor_id=?",
            ("persist-test",),
            db_path=patched_db,
        )
        r_dict = dict(rows[0])
        assert r_dict["verdict"] in ("ROBUST", "WEAK", "MIRAGE")
        assert r_dict["dag_pass"] == 1
        assert r_dict["test_results_json"] is not None

    def test_idempotent_upsert(self, patched_db, genuine_factor):
        f, r = genuine_factor
        actor = CausalFactorAuditor()
        for _ in range(2):
            actor.run(
                {
                    "action": "audit",
                    "factor_id": "upsert-test",
                    "factor": f.tolist(),
                    "returns": r.tolist(),
                    "dag_edges": [("factor", "returns")],
                    "dag_nodes": ["factor", "returns"],
                    "as_of_date": "2026-05-01",
                    "n_placebo_runs": 30,
                }
            )
        rows = query(
            "SELECT COUNT(*) AS c FROM causal_audits WHERE factor_id=?",
            ("upsert-test",),
            db_path=patched_db,
        )
        assert rows[0]["c"] == 1

    def test_audit_ledger_logged_layer_b(self, patched_db, genuine_factor):
        f, r = genuine_factor
        CausalFactorAuditor().run(
            {
                "action": "audit",
                "factor_id": "audit-test",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "n_placebo_runs": 30,
            }
        )
        rows = query(
            "SELECT layer FROM agent_audit_ledger WHERE actor_name='causal-factor-auditor'",
            db_path=patched_db,
        )
        assert rows[0]["layer"] == "B"


# ═══════════════════════════════════════════════════════
# Action: last_audit
# ═══════════════════════════════════════════════════════


class TestLastAudit:
    def test_no_rows_returns_warn(self, patched_db):
        result = CausalFactorAuditor().run({"action": "last_audit"})
        assert result.outcome == Outcome.WARN
        assert "no causal_audits" in result.output["error"]

    def test_returns_latest(self, patched_db, genuine_factor):
        f, r = genuine_factor
        actor = CausalFactorAuditor()
        for date in ("2026-04-30", "2026-05-01"):
            actor.run(
                {
                    "action": "audit",
                    "factor_id": "last-test",
                    "factor": f.tolist(),
                    "returns": r.tolist(),
                    "dag_edges": [("factor", "returns")],
                    "dag_nodes": ["factor", "returns"],
                    "as_of_date": date,
                    "n_placebo_runs": 30,
                }
            )
        result = actor.run({"action": "last_audit", "factor_id": "last-test"})
        assert result.outcome == Outcome.PASS
        assert result.output["as_of_date"] == "2026-05-01"

    def test_filters_by_factor_id(self, patched_db, genuine_factor):
        f, r = genuine_factor
        actor = CausalFactorAuditor()
        actor.run(
            {
                "action": "audit",
                "factor_id": "test-A",
                "factor": f.tolist(),
                "returns": r.tolist(),
                "dag_edges": [("factor", "returns")],
                "dag_nodes": ["factor", "returns"],
                "n_placebo_runs": 30,
            }
        )
        result = actor.run({"action": "last_audit", "factor_id": "nonexistent"})
        assert result.outcome == Outcome.WARN


# ═══════════════════════════════════════════════════════
# Discord publish — MIRAGE alert
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    def test_mirage_stages_to_rollout(self, patched_db, random_factor):
        """MIRAGE → outbox stage_rollout (PR3 Codex Round 6)."""
        f, r = random_factor
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            CausalFactorAuditor().run(
                {
                    "action": "audit",
                    "factor_id": "mirage-test",
                    "factor": f.tolist(),
                    "returns": r.tolist(),
                    "dag_edges": [("factor", "returns")],
                    "dag_nodes": ["factor", "returns"],
                    "n_placebo_runs": 100,
                }
            )
            mock_stage.assert_called_once()
            kw = mock_stage.call_args.kwargs
            assert kw["actor_name"] == "causal-factor-auditor"
            assert kw["payload"]["kind"] == "factor_mirage"

    def test_robust_does_not_stage(self, patched_db, genuine_factor):
        f, r = genuine_factor
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            CausalFactorAuditor().run(
                {
                    "action": "audit",
                    "factor_id": "genuine-test",
                    "factor": f.tolist(),
                    "returns": r.tolist(),
                    "dag_edges": [("factor", "returns")],
                    "dag_nodes": ["factor", "returns"],
                    "n_placebo_runs": 30,
                }
            )
            mock_stage.assert_not_called()

    def test_publish_failure_does_not_block_actor(self, patched_db, random_factor):
        f, r = random_factor
        with patch(
            "nuri.agents.discord.outbox.stage_rollout",
            side_effect=RuntimeError("outbox down"),
        ):
            result = CausalFactorAuditor().run(
                {
                    "action": "audit",
                    "factor_id": "test-publish-fail",
                    "factor": f.tolist(),
                    "returns": r.tolist(),
                    "dag_edges": [("factor", "returns")],
                    "dag_nodes": ["factor", "returns"],
                    "n_placebo_runs": 100,
                }
            )
            assert result.outcome == Outcome.WARN  # MIRAGE still
            assert result.output["verdict"] == "MIRAGE"


# ═══════════════════════════════════════════════════════
# DB helper direct lock-tests
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    def test_invalid_verdict_rejected(self, db_path):
        with pytest.raises(ValueError, match="verdict must be"):
            log_causal_audit(
                factor_id="x",
                as_of_date="2026-05-01",
                n_obs=100,
                verdict="BOGUS",
                causal_certainty=0.5,
                dag_pass=True,
                placebo_pass=True,
                event_study_pass=True,
                negative_control_pass=True,
                test_results={},
                db_path=db_path,
            )

    def test_certainty_out_of_range_rejected(self, db_path):
        with pytest.raises(ValueError, match="causal_certainty must be in"):
            log_causal_audit(
                factor_id="x",
                as_of_date="2026-05-01",
                n_obs=100,
                verdict="WEAK",
                causal_certainty=1.5,
                dag_pass=True,
                placebo_pass=True,
                event_study_pass=True,
                negative_control_pass=True,
                test_results={},
                db_path=db_path,
            )

    def test_negative_n_obs_rejected(self, db_path):
        with pytest.raises(ValueError, match="n_obs must be >= 0"):
            log_causal_audit(
                factor_id="x",
                as_of_date="2026-05-01",
                n_obs=-1,
                verdict="WEAK",
                causal_certainty=0.5,
                dag_pass=True,
                placebo_pass=True,
                event_study_pass=True,
                negative_control_pass=True,
                test_results={},
                db_path=db_path,
            )


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_last_audit_no_data(self, patched_db, capsys):
        from nuri.agents.actors.causal_factor_auditor import main

        rc = main(["last_audit"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no causal_audits" in out

    def test_cli_with_factor_id_filter(self, patched_db, capsys):
        from nuri.agents.actors.causal_factor_auditor import main

        rc = main(["last_audit", "--factor-id", "nonexistent"])
        assert rc == 0
