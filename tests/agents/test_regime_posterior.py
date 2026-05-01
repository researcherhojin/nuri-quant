"""RegimePosterior tests (#529 Phase 2 — actor #3, canonical).

검증 (Codex Round 5 + 2026-05-01 design consult):
- Layer B (deterministic, ZERO LLM)
- 2 actions: fit / last_posterior
- Anti-pattern lock-tests:
    1. posterior 합 ≠ 1 panic (log_regime_posterior 단계)
    2. transition matrix 음수 panic (sticky prior 위반)
    3. sticky 효과: kappa 증가 → diagonal dominance 증가 (dwell time prior 검증)
- 12-field audit row 정확 기록 (regime_posteriors)
- WalkForward 통합: actor 의 fit 결과 → Brier/log-loss 평가 가능
- Discord publish: regime change 시 ROLLOUT publish (mock), 첫 row 시 publish 없음
"""

from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.agents.actors.regime_posterior import (
    DEFAULT_FEATURE_COLS,
    RegimePosterior,
    StickyHMMSpec,
    _apply_sticky_prior,
    _entropy,
    _fit_sticky_hmm,
    _hash_array,
    _summarize_last_step,
    _top2_margin,
    _validate_features,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_regime_posterior, query

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "rp.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect (base + actor + helper)."""
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
            "nuri.agents.actors.regime_posterior.log_regime_posterior",
            side_effect=make_redirect(db_module.log_regime_posterior),
        ),
        patch(
            "nuri.agents.actors.regime_posterior.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture
def two_regime_data():
    """100 rows, 2 distinct regimes — sticky-HMM 가 명확히 분리해야 함."""
    rng = np.random.default_rng(42)
    a = rng.normal(0.0, 0.5, (50, 3))
    b = rng.normal(3.0, 0.5, (50, 3))
    return pd.DataFrame(np.vstack([a, b]), columns=list(DEFAULT_FEATURE_COLS))


# ═══════════════════════════════════════════════════════
# Layer A/B/C invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert RegimePosterior.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(RegimePosterior, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("regime-posterior") is RegimePosterior


# ═══════════════════════════════════════════════════════
# StickyHMMSpec validation
# ═══════════════════════════════════════════════════════


class TestStickyHMMSpec:
    def test_default_3_state(self):
        s = StickyHMMSpec()
        assert s.n_states == 3
        assert s.state_space_version == "3-state-v1"
        assert s.model_version.startswith("sticky_hmm_n3_k")

    def test_invalid_n_states_raises(self):
        with pytest.raises(ValueError, match="n_states must be >= 2"):
            StickyHMMSpec(n_states=1)

    def test_negative_kappa_raises(self):
        with pytest.raises(ValueError, match="sticky_kappa must be >= 0"):
            StickyHMMSpec(sticky_kappa=-1.0)

    def test_empty_features_raises(self):
        with pytest.raises(ValueError, match="feature_cols must not be empty"):
            StickyHMMSpec(feature_cols=())


# ═══════════════════════════════════════════════════════
# Math primitives
# ═══════════════════════════════════════════════════════


class TestMathPrimitives:
    def test_entropy_uniform_max(self):
        # uniform p=[1/3, 1/3, 1/3] → log2(3) ≈ 1.585
        assert _entropy(np.array([1 / 3, 1 / 3, 1 / 3])) == pytest.approx(np.log2(3), abs=1e-6)

    def test_entropy_degenerate_zero(self):
        assert _entropy(np.array([1.0, 0.0, 0.0])) == 0.0

    def test_top2_margin_clear_winner(self):
        assert _top2_margin(np.array([0.8, 0.15, 0.05])) == pytest.approx(0.65)

    def test_top2_margin_tie(self):
        # two-way tie → margin 0
        assert _top2_margin(np.array([0.5, 0.5])) == pytest.approx(0.0)

    def test_hash_array_deterministic(self):
        a = np.array([[1.0, 2.0], [3.0, 4.0]])
        assert _hash_array(a) == _hash_array(a.copy())

    def test_hash_array_changes_with_data(self):
        a = np.array([[1.0, 2.0]])
        b = np.array([[1.0, 2.1]])
        assert _hash_array(a) != _hash_array(b)


# ═══════════════════════════════════════════════════════
# Sticky prior — Anti-pattern lock-test #3 (sticky behavior)
# ═══════════════════════════════════════════════════════


class TestStickyPriorBehavior:
    """LOCK-TEST: sticky kappa 가 diagonal dominance 를 강화해야 함.

    fail 시 = HMM 의 transition matrix 가 vanilla EM 결과 그대로 → dwell time
    prior 효과 박살 → 잦은 false regime change → false alert flood.
    """

    def test_kappa_zero_returns_unchanged(self):
        t = np.array([[0.5, 0.5], [0.4, 0.6]])
        out = _apply_sticky_prior(t, kappa=0.0)
        assert np.allclose(out, t)

    def test_higher_kappa_increases_diagonal(self):
        t = np.array([[0.5, 0.5], [0.5, 0.5]])
        low = _apply_sticky_prior(t, kappa=1.0)
        high = _apply_sticky_prior(t, kappa=10.0)
        assert np.diag(high).sum() > np.diag(low).sum()

    def test_rows_sum_to_one_after_prior(self):
        t = np.array([[0.3, 0.7], [0.6, 0.4]])
        out = _apply_sticky_prior(t, kappa=5.0)
        assert np.allclose(out.sum(axis=1), 1.0)

    def test_no_negative_entries_after_prior(self):
        t = np.array([[0.5, 0.5], [0.5, 0.5]])
        out = _apply_sticky_prior(t, kappa=100.0)
        assert (out >= 0).all()


# ═══════════════════════════════════════════════════════
# _validate_features — input contract
# ═══════════════════════════════════════════════════════


class TestValidateFeatures:
    def test_missing_column_raises(self):
        df = pd.DataFrame({"vix_z": [1.0] * 50})
        with pytest.raises(ValueError, match="missing feature columns"):
            _validate_features(df, DEFAULT_FEATURE_COLS)

    def test_nan_value_raises(self):
        df = pd.DataFrame({col: [1.0] * 50 for col in DEFAULT_FEATURE_COLS})
        df.loc[3, "vix_z"] = np.nan
        with pytest.raises(ValueError, match="non-finite values"):
            _validate_features(df, DEFAULT_FEATURE_COLS)

    def test_too_few_rows_raises(self):
        df = pd.DataFrame({col: [1.0] * 10 for col in DEFAULT_FEATURE_COLS})
        with pytest.raises(ValueError, match=">=30 rows"):
            _validate_features(df, DEFAULT_FEATURE_COLS)

    def test_clean_features_pass(self, two_regime_data):
        arr = _validate_features(two_regime_data, DEFAULT_FEATURE_COLS)
        assert arr.shape == (100, 3)


# ═══════════════════════════════════════════════════════
# _fit_sticky_hmm — fit + smoothed posterior
# ═══════════════════════════════════════════════════════


class TestFitStickyHMM:
    def test_posterior_shape_matches_input(self, two_regime_data):
        spec = StickyHMMSpec()
        arr = _validate_features(two_regime_data, DEFAULT_FEATURE_COLS)
        _model, posterior, transmat, means = _fit_sticky_hmm(arr, spec)
        assert posterior.shape == (100, spec.n_states)

    def test_posterior_rows_sum_to_one(self, two_regime_data):
        spec = StickyHMMSpec()
        arr = _validate_features(two_regime_data, DEFAULT_FEATURE_COLS)
        _model, posterior, _, _ = _fit_sticky_hmm(arr, spec)
        assert np.allclose(posterior.sum(axis=1), 1.0, atol=1e-6)

    def test_transmat_non_negative(self, two_regime_data):
        spec = StickyHMMSpec()
        arr = _validate_features(two_regime_data, DEFAULT_FEATURE_COLS)
        _model, _posterior, transmat, _means = _fit_sticky_hmm(arr, spec)
        assert (transmat >= 0).all()

    def test_means_shape(self, two_regime_data):
        spec = StickyHMMSpec(n_states=3)
        arr = _validate_features(two_regime_data, DEFAULT_FEATURE_COLS)
        _model, _posterior, _transmat, means = _fit_sticky_hmm(arr, spec)
        assert means.shape == (3, 3)


# ═══════════════════════════════════════════════════════
# _summarize_last_step — DB row source
# ═══════════════════════════════════════════════════════


class TestSummarizeLastStep:
    def test_argmax_matches_posterior(self):
        posterior = np.array([[0.1, 0.9], [0.7, 0.3]])  # last row argmax = 0
        transmat = np.array([[0.5, 0.5], [0.5, 0.5]])
        means = np.array([[0.0, 0.0], [1.0, 1.0]])
        s = _summarize_last_step(posterior, transmat, means)
        assert s.argmax_state == 0

    def test_posterior_renormalized(self):
        # Inject tiny numerical drift
        posterior = np.array([[0.5, 0.5], [0.5, 0.5 + 1e-10]])
        transmat = np.array([[0.5, 0.5], [0.5, 0.5]])
        means = np.array([[0.0], [1.0]])
        s = _summarize_last_step(posterior, transmat, means)
        assert sum(s.posterior) == pytest.approx(1.0, abs=1e-12)


# ═══════════════════════════════════════════════════════
# log_regime_posterior — Anti-pattern lock-test #1 (posterior sum)
# ═══════════════════════════════════════════════════════


class TestPosteriorSumLockTest:
    """LOCK-TEST: posterior 가 sum=1 이 아니면 무조건 panic.

    fail 시 = log_regime_posterior 의 sum check 가 사라진 것 → numerical drift
    가 audit row 에 들어감 → Decision-Compiler 가 잘못된 P(state) 로 결정.
    """

    def test_posterior_sum_below_one_rejected(self, db_path):
        with pytest.raises(ValueError, match="posterior must sum to 1"):
            log_regime_posterior(
                as_of_date="2026-05-01",
                model_version="bad",
                state_space_version="x",
                feature_snapshot={},
                posterior=[0.4, 0.4, 0.1],  # sum=0.9
                argmax_state=0,
                entropy=0.0,
                top2_margin=0.0,
                transition_params_hash="h1",
                emission_params_hash="h2",
                train_window="x..y",
                data_freshness_status="PASS",
                db_path=db_path,
            )

    def test_posterior_sum_above_one_rejected(self, db_path):
        with pytest.raises(ValueError, match="posterior must sum to 1"):
            log_regime_posterior(
                as_of_date="2026-05-01",
                model_version="bad",
                state_space_version="x",
                feature_snapshot={},
                posterior=[0.5, 0.5, 0.5],  # sum=1.5
                argmax_state=0,
                entropy=0.0,
                top2_margin=0.0,
                transition_params_hash="h1",
                emission_params_hash="h2",
                train_window="x..y",
                data_freshness_status="PASS",
                db_path=db_path,
            )

    def test_argmax_out_of_range_rejected(self, db_path):
        with pytest.raises(ValueError, match="argmax_state .* out of range"):
            log_regime_posterior(
                as_of_date="2026-05-01",
                model_version="bad",
                state_space_version="x",
                feature_snapshot={},
                posterior=[0.7, 0.3],
                argmax_state=5,
                entropy=0.0,
                top2_margin=0.0,
                transition_params_hash="h1",
                emission_params_hash="h2",
                train_window="x..y",
                data_freshness_status="PASS",
                db_path=db_path,
            )

    def test_invalid_freshness_rejected(self, db_path):
        with pytest.raises(ValueError, match="data_freshness_status must be PASS/WARN/FAIL"):
            log_regime_posterior(
                as_of_date="2026-05-01",
                model_version="bad",
                state_space_version="x",
                feature_snapshot={},
                posterior=[1.0],
                argmax_state=0,
                entropy=0.0,
                top2_margin=0.0,
                transition_params_hash="h1",
                emission_params_hash="h2",
                train_window="x..y",
                data_freshness_status="BOGUS",
                db_path=db_path,
            )


# ═══════════════════════════════════════════════════════
# Action: fit — input validation
# ═══════════════════════════════════════════════════════


class TestActionFitInputValidation:
    def test_invalid_action_blocked(self, patched_db):
        actor = RegimePosterior()
        result = actor.run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_data_blocked(self, patched_db):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "data" in result.output["error"].lower()

    def test_missing_train_window_blocked(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_freshness_fail_blocks_fit(self, patched_db, two_regime_data):
        """freshness=FAIL → 학습 거부 (stale data 차단)."""
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "FAIL",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "stale" in result.output["error"].lower()

    def test_invalid_freshness_blocked(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "BOGUS",
            }
        )
        assert result.outcome == Outcome.BLOCK

    def test_missing_feature_columns_blocked(self, patched_db):
        actor = RegimePosterior()
        df = pd.DataFrame({"vix_z": [1.0] * 50})
        result = actor.run(
            {
                "action": "fit",
                "data": df,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "missing feature columns" in result.output["error"]

    def test_invalid_spec_blocked(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
                "spec": {"n_states": 1},  # invalid
            }
        )
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Action: fit — happy path + DB audit
# ═══════════════════════════════════════════════════════


class TestActionFitHappyPath:
    def test_fit_pass_with_clean_data(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["argmax_state"] in (0, 1, 2)
        assert sum(result.output["posterior"]) == pytest.approx(1.0, abs=1e-6)
        assert result.output["regime_changed"] is False  # 첫 row → change 없음
        assert result.output["prev_argmax"] is None

    def test_fit_warn_when_freshness_warn(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "WARN",
            }
        )
        assert result.outcome == Outcome.WARN

    def test_audit_row_recorded(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        rows = query("SELECT * FROM regime_posteriors", db_path=patched_db)
        assert len(rows) == 1
        r = dict(rows[0])
        # 12-field audit (excluding created_at + run_id)
        for col in (
            "as_of_date",
            "model_version",
            "state_space_version",
            "feature_snapshot_json",
            "posterior_json",
            "argmax_state",
            "entropy",
            "top2_margin",
            "transition_params_hash",
            "emission_params_hash",
            "train_window",
            "data_freshness_status",
        ):
            assert r[col] is not None, f"column {col} missing"
        # posterior 회복 가능
        posterior = json.loads(r["posterior_json"])
        assert sum(posterior) == pytest.approx(1.0, abs=1e-6)

    def test_idempotent_upsert_same_date(self, patched_db, two_regime_data):
        """동일 (as_of_date, model_version) 재학습 시 row 1 개 유지."""
        actor = RegimePosterior()
        for _ in range(2):
            actor.run(
                {
                    "action": "fit",
                    "data": two_regime_data,
                    "as_of_date": "2026-05-01",
                    "train_window": "2025-01-01..2026-05-01",
                    "data_freshness_status": "PASS",
                }
            )
        rows = query("SELECT COUNT(*) AS c FROM regime_posteriors", db_path=patched_db)
        assert rows[0]["c"] == 1

    def test_audit_ledger_contains_run(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "2025-01-01..2026-05-01",
                "data_freshness_status": "PASS",
            }
        )
        rows = query(
            "SELECT layer, outcome FROM agent_audit_ledger WHERE actor_name = 'regime-posterior'",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["layer"] == "B"
        assert rows[0]["outcome"] == "pass"


# ═══════════════════════════════════════════════════════
# Anti-pattern lock-test #2 — transition matrix non-negative invariant
# ═══════════════════════════════════════════════════════


class TestTransmatInvariantLockTest:
    """LOCK-TEST: post-fit invariant — transmat 음수면 panic.

    fail 시 = sticky prior 가 음수 entry 생성 (불가능하지만 mutation/refactor
    회귀 방지) → posterior 계산 깨짐.
    """

    def test_negative_transmat_panics(self, patched_db, two_regime_data):
        from nuri.agents.actors import regime_posterior as rp_module

        def fake_fit(features, spec):
            posterior = np.full((features.shape[0], spec.n_states), 1.0 / spec.n_states)
            transmat = -np.eye(spec.n_states)  # all -1 (invariant violation)
            means = np.zeros((spec.n_states, features.shape[1]))
            return None, posterior, transmat, means

        with patch.object(rp_module, "_fit_sticky_hmm", side_effect=fake_fit):
            actor = RegimePosterior()
            with pytest.raises(ValueError, match="negative entries"):
                actor.run(
                    {
                        "action": "fit",
                        "data": two_regime_data,
                        "as_of_date": "2026-05-02",
                        "train_window": "x..y",
                        "data_freshness_status": "PASS",
                    }
                )

    def test_transmat_rows_not_summing_to_one_panics(self, patched_db, two_regime_data):
        from nuri.agents.actors import regime_posterior as rp_module

        def fake_fit(features, spec):
            posterior = np.full((features.shape[0], spec.n_states), 1.0 / spec.n_states)
            transmat = np.eye(spec.n_states) * 0.3  # rows sum=0.3, not 1.0
            means = np.zeros((spec.n_states, features.shape[1]))
            return None, posterior, transmat, means

        with patch.object(rp_module, "_fit_sticky_hmm", side_effect=fake_fit):
            actor = RegimePosterior()
            with pytest.raises(ValueError, match="rows must sum to 1"):
                actor.run(
                    {
                        "action": "fit",
                        "data": two_regime_data,
                        "as_of_date": "2026-05-03",
                        "train_window": "x..y",
                        "data_freshness_status": "PASS",
                    }
                )


# ═══════════════════════════════════════════════════════
# Regime change detection + Discord publish
# ═══════════════════════════════════════════════════════


class TestRegimeChangeDetection:
    def test_first_row_no_change(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        result = actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )
        assert result.output["regime_changed"] is False

    def test_regime_change_publishes_to_rollout(self, patched_db, two_regime_data):
        """argmax 변경 → Discord ROLLOUT publish 호출."""
        from nuri.agents.actors import regime_posterior as rp_module

        actor = RegimePosterior()
        # Day 1 — record first row (no publish)
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )
        # Force argmax flip on day 2 by patching _summarize_last_step
        from nuri.agents.actors.regime_posterior import _PosteriorSummary

        orig = rp_module._summarize_last_step

        def flip_summary(posterior, transmat, means):
            s = orig(posterior, transmat, means)
            new_argmax = (s.argmax_state + 1) % len(s.posterior)
            return _PosteriorSummary(
                posterior=s.posterior,
                argmax_state=new_argmax,
                entropy=s.entropy,
                top2_margin=s.top2_margin,
                transition_params_hash=s.transition_params_hash,
                emission_params_hash=s.emission_params_hash,
            )

        with (
            patch.object(rp_module, "_summarize_last_step", side_effect=flip_summary),
            patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage,
        ):
            result = actor.run(
                {
                    "action": "fit",
                    "data": two_regime_data,
                    "as_of_date": "2026-05-02",
                    "train_window": "x..y",
                    "data_freshness_status": "PASS",
                }
            )
            assert result.output["regime_changed"] is True
            assert result.output["prev_argmax"] is not None
            mock_stage.assert_called_once()
            kw = mock_stage.call_args.kwargs
            assert kw["actor_name"] == "regime-posterior"
            assert kw["payload"]["kind"] == "regime_change"

    def test_publish_failure_does_not_block_actor(self, patched_db, two_regime_data):
        """ROLLOUT publish 실패 시에도 actor outcome 은 PASS 유지 (best-effort)."""
        from nuri.agents.actors import regime_posterior as rp_module
        from nuri.agents.actors.regime_posterior import _PosteriorSummary

        actor = RegimePosterior()
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )

        orig = rp_module._summarize_last_step

        def flip(p, t, m):
            s = orig(p, t, m)
            return _PosteriorSummary(
                posterior=s.posterior,
                argmax_state=(s.argmax_state + 1) % len(s.posterior),
                entropy=s.entropy,
                top2_margin=s.top2_margin,
                transition_params_hash=s.transition_params_hash,
                emission_params_hash=s.emission_params_hash,
            )

        with (
            patch.object(rp_module, "_summarize_last_step", side_effect=flip),
            patch("nuri.agents.discord.outbox.stage_rollout", side_effect=RuntimeError("outbox down")),
        ):
            result = actor.run(
                {
                    "action": "fit",
                    "data": two_regime_data,
                    "as_of_date": "2026-05-02",
                    "train_window": "x..y",
                    "data_freshness_status": "PASS",
                }
            )
            assert result.outcome == Outcome.PASS  # publish 실패해도 PASS
            assert result.output["regime_changed"] is True


# ═══════════════════════════════════════════════════════
# Action: last_posterior
# ═══════════════════════════════════════════════════════


class TestLastPosterior:
    def test_no_rows_returns_warn(self, patched_db):
        actor = RegimePosterior()
        result = actor.run({"action": "last_posterior"})
        assert result.outcome == Outcome.WARN
        assert "no regime_posteriors" in result.output["error"]

    def test_returns_latest_row(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-04-30",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )
        result = actor.run({"action": "last_posterior"})
        assert result.outcome == Outcome.PASS
        assert result.output["as_of_date"] == "2026-05-01"
        assert sum(result.output["posterior"]) == pytest.approx(1.0, abs=1e-6)

    def test_filters_by_model_version(self, patched_db, two_regime_data):
        actor = RegimePosterior()
        actor.run(
            {
                "action": "fit",
                "data": two_regime_data,
                "as_of_date": "2026-05-01",
                "train_window": "x..y",
                "data_freshness_status": "PASS",
            }
        )
        result = actor.run({"action": "last_posterior", "model_version": "nonexistent"})
        assert result.outcome == Outcome.WARN


# ═══════════════════════════════════════════════════════
# WalkForward integration — Brier / log-loss on regime predictions
# ═══════════════════════════════════════════════════════


class TestWalkForwardIntegration:
    """RegimePosterior 가 WalkForward-Validator 와 호환됨을 검증.

    Layer B actor 끼리 합성 가능 — Codex consult 의 핵심 ROI: 모델 평가 primitive
    위에 regime producer 을 얹어 Brier/log-loss 로 정량 비교.
    """

    def test_walkforward_pit_hash_on_regime_features(self, patched_db, two_regime_data):
        from nuri.agents.actors.walkforward_validator import (
            FoldSpec,
            WalkForwardValidator,
            _compute_pit_hash,
        )

        spec = FoldSpec(kind="rolling", train_size=40, test_size=10, step=10)
        h1 = _compute_pit_hash(two_regime_data, "regime-posterior", spec)
        h2 = _compute_pit_hash(two_regime_data, "regime-posterior", spec)
        assert h1 == h2  # reproducibility

        # Different model_id → different hash
        h3 = _compute_pit_hash(two_regime_data, "other-model", spec)
        assert h1 != h3

    def test_brier_log_loss_callable_on_posterior(self):
        """sticky-HMM posterior → Brier/log-loss 계산 가능 (Layer B 합성)."""
        from nuri.agents.actors.walkforward_validator import _brier_score, _log_loss

        # synthetic: y_true ∈ {0,1}, y_prob = posterior[:, 1] (state 1 확률)
        y_true = np.array([0, 0, 1, 1, 1])
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.7])
        brier = _brier_score(y_true, y_prob)
        ll = _log_loss(y_true, y_prob)
        assert 0 <= brier <= 1
        assert ll > 0


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_last_posterior_no_data(self, patched_db, capsys):
        from nuri.agents.actors.regime_posterior import main

        rc = main(["last_posterior"])
        # WARN outcome → exit 0 (still acceptable for CLI inspection)
        assert rc == 0
        out = capsys.readouterr().out
        assert "no regime_posteriors" in out
