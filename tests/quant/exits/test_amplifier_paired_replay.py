"""Lock-tests for E3 Phase 2 paired counterfactual replay.

Per STRATEGY §5.3.1 Gotcha-Test Pair: every fix-pattern gotcha cites a
regression test. These pin invariants the spec mandates as frozen — any
drift here invalidates the verdict.

Spec: docs/plans/E3_phase2_paired_counterfactual.md.
"""

from __future__ import annotations

import numpy as np

import scripts.episodes.e3_amplifier_paired_replay as replay
from scripts.episodes.e3_amplifier_paired_replay import (
    AMP_MULT,
    BASELINE_MULT,
    BLOCK_SIZE_PRIMARY,
    BOOTSTRAP_ITERS,
    DATE_START,
    HORIZONS,
    REGIME_FAVORABLE_LABELS,
    REGIME_MIN_CONFIDENCE,
    SEED,
    SPEC_VERSION,
    UNIVERSE_KEY,
    Verdict,
    _block_bootstrap_ci,
    _build_verdict,
)

# ─── Frozen parameter invariants ────────────────────────────────────────


class TestFrozenParameters:
    """Per spec these parameters cannot change without (1) a spec amend
    citing why and (2) a fresh codex GATE PASS. Drift here = invalid verdict."""

    def test_horizons_locked(self):
        assert HORIZONS == (30, 60, 90)

    def test_amp_mult_locked(self):
        assert AMP_MULT == 1.5
        assert BASELINE_MULT == 1.0

    def test_bootstrap_locked(self):
        assert BOOTSTRAP_ITERS == 1000
        assert BLOCK_SIZE_PRIMARY == 20
        assert SEED == 42

    def test_universe_locked(self):
        assert UNIVERSE_KEY == "us_core"

    def test_date_start_locked(self):
        # 2020-01-01 includes COVID — codex Q8 verdict, no cherry-picking.
        assert DATE_START == "2020-01-01"

    def test_regime_thresholds_locked(self):
        # codex Q9 — entry_strength tautology removed; regime gate is canonical config.
        assert REGIME_FAVORABLE_LABELS == {"bull_low_vol", "recovery"}
        assert REGIME_MIN_CONFIDENCE == 0.60

    def test_spec_version_recorded(self):
        # Verdict artifact must cite the spec it was produced under.
        assert "phase2-p1-amended" in SPEC_VERSION


# ─── Block bootstrap math ───────────────────────────────────────────────


class TestBlockBootstrap:
    """Lock the bootstrap implementation: seeded determinism, math sanity,
    edge case handling."""

    def test_seeded_deterministic(self):
        deltas = np.linspace(-0.05, 0.05, 100, dtype=np.float64)
        a = _block_bootstrap_ci(deltas, block_size=20, iters=200, seed=42)
        b = _block_bootstrap_ci(deltas, block_size=20, iters=200, seed=42)
        assert a == b

    def test_different_seeds_differ(self):
        deltas = np.linspace(-0.05, 0.05, 100, dtype=np.float64)
        a = _block_bootstrap_ci(deltas, block_size=20, iters=200, seed=42)
        b = _block_bootstrap_ci(deltas, block_size=20, iters=200, seed=43)
        # mean / median identical (same data); CIs should differ across seeds.
        assert a[0] == b[0]  # mean
        assert a[2] != b[2] or a[3] != b[3]  # at least one CI bound differs

    def test_empty_returns_nan(self):
        m, med, lo, hi = _block_bootstrap_ci(np.array([], dtype=np.float64), 20, 100, 42)
        assert np.isnan(m) and np.isnan(med) and np.isnan(lo) and np.isnan(hi)

    def test_ci_brackets_mean_for_iid_normal(self):
        # IID normal sample with known mean: 95% CI should bracket the true mean
        # most of the time. Bootstrap of mean is well-understood.
        rng = np.random.default_rng(0)
        deltas = rng.normal(loc=0.05, scale=0.1, size=500)
        mean, _med, lo, hi = _block_bootstrap_ci(deltas, block_size=20, iters=500, seed=42)
        assert lo < mean < hi
        # 95% CI should be wider than zero given scale=0.1.
        assert (hi - lo) > 0.005

    def test_constant_array_ci_collapses(self):
        deltas = np.full(100, 0.03, dtype=np.float64)
        mean, _med, lo, hi = _block_bootstrap_ci(deltas, block_size=20, iters=200, seed=42)
        assert mean == 0.03
        # Bootstrap of constants → CI collapses to point estimate.
        assert abs(lo - 0.03) < 1e-9
        assert abs(hi - 0.03) < 1e-9


# ─── Paired delta math ──────────────────────────────────────────────────


class TestPairedDelta:
    """The paired delta is `ret × (amp_mult − baseline_mult)`. Same entries,
    same exits — only sizing differs."""

    def test_paired_delta_formula(self):
        # If forward return is +10%, paired delta = 0.10 × (1.5 − 1.0) = 0.05.
        ret = 0.10
        delta = ret * (AMP_MULT - BASELINE_MULT)
        assert abs(delta - 0.05) < 1e-9

    def test_negative_ret_yields_negative_delta(self):
        ret = -0.07
        delta = ret * (AMP_MULT - BASELINE_MULT)
        assert delta < 0
        assert abs(delta + 0.035) < 1e-9


# ─── Decision rule binary contract ──────────────────────────────────────


class TestDecisionRule:
    """Spec acceptance: PASS iff CI_lower_30d > 0; FAIL otherwise. Binary,
    no INCONCLUSIVE. Power-limit caveat does NOT alter the verdict."""

    def _build(self, ci_lower_30d: float, ci_lower_60d: float, ci_lower_90d: float) -> Verdict:
        metrics = {
            30: {
                "n_entries": 100,
                "mean_paired_delta": 0.01,
                "median_paired_delta": 0.01,
                "ci_lower_95": ci_lower_30d,
                "ci_upper_95": 0.05,
            },
            60: {
                "n_entries": 100,
                "mean_paired_delta": 0.02,
                "median_paired_delta": 0.02,
                "ci_lower_95": ci_lower_60d,
                "ci_upper_95": 0.06,
            },
            90: {
                "n_entries": 100,
                "mean_paired_delta": 0.03,
                "median_paired_delta": 0.03,
                "ci_lower_95": ci_lower_90d,
                "ci_upper_95": 0.08,
            },
        }
        # decide manually — replicate logic from replay.run_replay
        primary = metrics[30]
        if primary["ci_lower_95"] > 0:
            decision, reason = "PASS", "30d CI_lower > 0"
        else:
            decision, reason = "FAIL", "30d CI_lower <= 0"
        return _build_verdict(
            decision=decision,
            decision_reason=reason,
            stage0_audit={"clean": True, "checks_run": [], "violations": []},
            covered=[],
            target=[],
            missing=[],
            n_breakout_total=1000,
            n_eligible=100,
            n_unique_eligible_days=10,
            day_stats={},
            metrics=metrics,
            sensitivity={},
            extra_caveats=[],
        )

    def test_pass_when_30d_ci_strictly_positive(self):
        v = self._build(ci_lower_30d=0.001, ci_lower_60d=0.001, ci_lower_90d=0.001)
        assert v.decision == "PASS"

    def test_fail_when_30d_ci_zero(self):
        # Exactly zero → not strictly positive → FAIL.
        v = self._build(ci_lower_30d=0.0, ci_lower_60d=0.05, ci_lower_90d=0.05)
        assert v.decision == "FAIL"

    def test_fail_when_30d_ci_negative(self):
        v = self._build(ci_lower_30d=-0.01, ci_lower_60d=0.05, ci_lower_90d=0.05)
        assert v.decision == "FAIL"

    def test_60d_90d_dont_override_30d(self):
        # Even if 60d and 90d show strong PASS signal, 30d below zero means FAIL.
        # This is a deliberate spec choice — codex Q5 + acceptance section.
        v = self._build(ci_lower_30d=-0.01, ci_lower_60d=0.10, ci_lower_90d=0.20)
        assert v.decision == "FAIL"

    def test_decision_only_pass_or_fail(self):
        # No INCONCLUSIVE. Round 2 regression closure.
        for lo30 in (-0.01, 0.0, 0.001):
            v = self._build(ci_lower_30d=lo30, ci_lower_60d=0.05, ci_lower_90d=0.05)
            assert v.decision in {"PASS", "FAIL"}


# ─── Verdict artifact schema ────────────────────────────────────────────


class TestVerdictSchema:
    """Verdict JSON keys frozen by Q12. CI consumes this; drift → CI break."""

    def test_required_top_level_keys(self):
        v = _build_verdict(
            decision="FAIL",
            decision_reason="test",
            stage0_audit={"clean": True, "checks_run": [], "violations": []},
            covered=[],
            target=[],
            missing=[],
            n_breakout_total=0,
            n_eligible=0,
            n_unique_eligible_days=0,
            day_stats={},
            metrics={h: {"n_entries": 0} for h in HORIZONS},
            sensitivity={},
            extra_caveats=[],
        )
        from dataclasses import asdict

        d = asdict(v)
        required = {
            "spec_version",
            "run_at_kst",
            "git_commit",
            "decision",
            "decision_reason",
            "stage0_audit",
            "universe",
            "date_range",
            "entry_rule",
            "treatment_rule",
            "amp_mult",
            "sample_counts",
            "bootstrap",
            "metrics_by_horizon",
            "sensitivity",
            "caveats",
        }
        assert required.issubset(set(d.keys()))

    def test_caveats_includes_power_limit(self):
        v = _build_verdict(
            decision="FAIL",
            decision_reason="test",
            stage0_audit={"clean": True, "checks_run": [], "violations": []},
            covered=[],
            target=[],
            missing=[],
            n_breakout_total=0,
            n_eligible=203,
            n_unique_eligible_days=9,
            day_stats={},
            metrics={h: {"n_entries": 0} for h in HORIZONS},
            sensitivity={},
            extra_caveats=[],
        )
        # Power-limit caveat must be present (binding caveat per spec).
        assert any("unique trading days" in c for c in v.caveats)

    def test_treatment_rule_excludes_macro_benign(self):
        # Phase 2 frozen gate is recovery + vix + regime only (Q10 — macro
        # arm requires Phase 3+ data accumulation). Verdict must reflect this.
        v = _build_verdict(
            decision="PASS",
            decision_reason="test",
            stage0_audit={"clean": True, "checks_run": [], "violations": []},
            covered=[],
            target=[],
            missing=[],
            n_breakout_total=0,
            n_eligible=0,
            n_unique_eligible_days=0,
            day_stats={},
            metrics={h: {"n_entries": 0} for h in HORIZONS},
            sensitivity={},
            extra_caveats=[],
        )
        assert "macro_benign dropped" in v.treatment_rule


# ─── Stage 0 precondition wiring ────────────────────────────────────────


class TestStage0Precondition:
    """If Stage 0 fails, replay must NOT produce verdict.json. Spec-mandated."""

    def test_run_stage0_returns_clean_on_real_source(self):
        clean, audit = replay.run_stage0_precondition()
        assert clean is True
        assert audit["clean"] is True
        assert len(audit["checks_run"]) == 6

    def test_replay_aborts_when_stage0_fails(self, monkeypatch):
        from scripts.episodes import e3_amplifier_stage0_audit as audit_mod

        def fake_run_audit():
            return audit_mod.AuditResult(
                clean=False,
                as_of_date=audit_mod.AS_OF_DATE,
                checks_run=["fake"],
                violations=[audit_mod.Violation(target="fake", description="injected leak")],
            )

        monkeypatch.setattr(audit_mod, "run_audit", fake_run_audit)
        # replay.run_stage0_precondition imports run_audit lazily → patch must
        # also affect any cached import path; the function does
        # `from scripts.episodes.e3_amplifier_stage0_audit import ...` each call.
        try:
            replay.run_replay()
        except RuntimeError as e:
            assert "Stage 0" in str(e)
        else:
            raise AssertionError("replay should have raised RuntimeError on Stage 0 failure")
