"""E3-3b Stage 2 paired counterfactual sim — smoke tests + invariant locks.

Tests the math correctness of the sim pieces, not the live verdict (which
depends on DB state). Verdict integration test would need full DB seed.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# Same importlib pattern as test_stage1_classifier_plausibility.py
# (scripts/ are stand-alone, not packages — Pylance / @dataclass require
# explicit dynamic load + sys.modules registration).
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "e3_3b_stage2_counterfactual.py"
_spec = importlib.util.spec_from_file_location("e3_3b_stage2_counterfactual", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
s2 = importlib.util.module_from_spec(_spec)
sys.modules["e3_3b_stage2_counterfactual"] = s2
_spec.loader.exec_module(s2)


class TestAdaptiveSize:
    """REGIME_MULTIPLIERS lookup → adaptive position pct."""

    def test_aggressive_regimes_size_up(self):
        assert s2._adaptive_size("bull_low_vol") == 18.0  # 15 × 1.2
        assert s2._adaptive_size("recovery") == 18.0

    def test_conservative_regimes_size_down(self):
        assert s2._adaptive_size("bear_high_vol") == 12.0  # 15 × 0.8
        assert s2._adaptive_size("bull_high_vol") == 12.0
        assert s2._adaptive_size("stagflation") == 12.0
        assert s2._adaptive_size("euphoria") == 12.0

    def test_neutral_regimes_unchanged(self):
        for regime in ["sideways_low_vol", "sideways_high_vol", "bear_low_vol",
                       "sector_rotation"]:
            assert s2._adaptive_size(regime) == 15.0, f"{regime} should be neutral"

    def test_none_regime_uses_baseline(self):
        """No regime classification → no adjustment, baseline size."""
        assert s2._adaptive_size(None) == 15.0


class TestPairedDeltaSignConvention:
    """paired_delta = (adaptive - baseline) × forward_return / 100. Sign verify."""

    def _make_entry(self, regime: str, forward_return: float) -> "s2.Entry":  # type: ignore[name-defined]
        baseline = 15.0
        adaptive = s2._adaptive_size(regime)
        size_diff = adaptive - baseline
        return s2.Entry(
            ticker="TEST", date="2024-01-15", regime=regime, confidence=1.0,
            baseline_size_pct=baseline, adaptive_size_pct=adaptive,
            forward_returns={30: forward_return, 60: forward_return, 90: forward_return},
            forward_mae={30: -2.0, 60: -3.0, 90: -4.0},
            paired_deltas={
                30: size_diff * forward_return / 100,
                60: size_diff * forward_return / 100,
                90: size_diff * forward_return / 100,
            },
        )

    def test_aggressive_positive_return_positive_delta(self):
        """bull_low_vol (18% > 15%) + 10% return → adaptive earns more."""
        e = self._make_entry("bull_low_vol", forward_return=10.0)
        # delta = (18-15) × 10 / 100 = +0.30
        assert e.paired_deltas[60] == pytest.approx(0.30)

    def test_aggressive_negative_return_negative_delta(self):
        """bull_low_vol (18% > 15%) + -10% return → adaptive loses more."""
        e = self._make_entry("bull_low_vol", forward_return=-10.0)
        # delta = (18-15) × -10 / 100 = -0.30
        assert e.paired_deltas[60] == pytest.approx(-0.30)

    def test_conservative_positive_return_negative_delta(self):
        """bear_high_vol (12% < 15%) + 10% return → adaptive earns less."""
        e = self._make_entry("bear_high_vol", forward_return=10.0)
        # delta = (12-15) × 10 / 100 = -0.30
        assert e.paired_deltas[60] == pytest.approx(-0.30)

    def test_conservative_negative_return_positive_delta(self):
        """bear_high_vol (12% < 15%) + -10% return → adaptive saves loss."""
        e = self._make_entry("bear_high_vol", forward_return=-10.0)
        # delta = (12-15) × -10 / 100 = +0.30
        assert e.paired_deltas[60] == pytest.approx(0.30)

    def test_neutral_zero_delta_regardless_of_return(self):
        """sideways_low_vol (15% = 15%) → delta always 0."""
        for ret in [-10.0, 0.0, 10.0]:
            e = self._make_entry("sideways_low_vol", forward_return=ret)
            assert e.paired_deltas[60] == 0.0


class TestBootstrapCI:
    """Sanity on bootstrap CI implementation."""

    def test_constant_array_zero_width_ci(self):
        """All same value → CI width ≈ 0."""
        lo, hi = s2.bootstrap_ci([1.0] * 100, n_iter=1000, seed=42)
        assert abs(hi - lo) < 0.001
        assert lo == pytest.approx(1.0)

    def test_too_few_values_returns_nan(self):
        """< 2 values → cannot bootstrap."""
        lo, hi = s2.bootstrap_ci([], n_iter=1000)
        assert lo != lo  # nan
        assert hi != hi

    def test_lower_bound_below_upper_bound(self):
        """CI is well-formed: lo ≤ hi."""
        import random
        random.seed(123)
        values = [random.gauss(0, 1) for _ in range(100)]
        lo, hi = s2.bootstrap_ci(values, n_iter=1000, seed=42)
        assert lo <= hi

    def test_seed_determinism(self):
        """Same seed → same CI (CI gate must be reproducible across runs)."""
        values = [0.1, 0.2, 0.3, -0.1, 0.5, -0.2, 0.4]
        lo1, hi1 = s2.bootstrap_ci(values, n_iter=1000, seed=42)
        lo2, hi2 = s2.bootstrap_ci(values, n_iter=1000, seed=42)
        assert lo1 == lo2 and hi1 == hi2


class TestEvaluateStage2Gate:
    """Acceptance criteria evaluation logic."""

    def _make_metrics(self, ci_lo: float, wrong_pct: float = 30.0,
                      median: float = 0.05) -> dict:
        base = {
            "n": 200, "mean_delta": 0.05, "median_delta": median,
            "ci_95_lo": ci_lo, "ci_95_hi": 0.15,
            "wrong_directional_pct": wrong_pct, "positive_pct": 35.0,
            "mae_baseline_pct": -1.5, "mae_adaptive_pct": -1.6,
            "mae_delta_pp": -0.1, "cvar_5pct": -1.0,
        }
        return {30: base.copy(), 60: base.copy(), 90: base.copy()}

    def test_pass_when_all_gates_clear(self):
        verdict, reasons = s2.evaluate_stage2_gate(self._make_metrics(ci_lo=0.01))
        assert verdict == "PASS", f"unexpected REJECTED: {reasons}"
        assert reasons == []

    def test_reject_when_60d_ci_lower_zero(self):
        """Primary gate: 60d CI lower bound > 0 strictly."""
        m = self._make_metrics(ci_lo=0.0)
        verdict, reasons = s2.evaluate_stage2_gate(m)
        assert verdict == "REJECTED"
        assert any("60d CI lower bound" in r for r in reasons)

    def test_reject_when_60d_ci_lower_negative(self):
        verdict, reasons = s2.evaluate_stage2_gate(self._make_metrics(ci_lo=-0.05))
        assert verdict == "REJECTED"

    def test_reject_when_wrong_directional_above_55(self):
        m = self._make_metrics(ci_lo=0.01, wrong_pct=56.0)
        verdict, reasons = s2.evaluate_stage2_gate(m)
        assert verdict == "REJECTED"
        assert any("wrong-directional rate" in r for r in reasons)

    def test_pass_at_55_boundary(self):
        """Gate is ≤ 55, exactly 55.0 should pass."""
        m = self._make_metrics(ci_lo=0.01, wrong_pct=55.0)
        verdict, _ = s2.evaluate_stage2_gate(m)
        assert verdict == "PASS"

    def test_reject_when_60d_median_negative(self):
        m = self._make_metrics(ci_lo=0.01, median=-0.001)
        verdict, reasons = s2.evaluate_stage2_gate(m)
        assert verdict == "REJECTED"
        assert any("median delta" in r for r in reasons)

    def test_reject_when_no_entries(self):
        verdict, reasons = s2.evaluate_stage2_gate({60: {"n": 0}})
        assert verdict == "REJECTED"
        assert "no entries" in reasons[0]


class TestAggregateMetricsInvariants:
    """aggregate_metrics output structure."""

    def _entry(self, regime, ret_30, ret_60, ret_90):
        baseline = 15.0
        adaptive = s2._adaptive_size(regime)
        size_diff = adaptive - baseline
        returns = {30: ret_30, 60: ret_60, 90: ret_90}
        return s2.Entry(
            ticker="T", date="2024-01-01", regime=regime, confidence=1.0,
            baseline_size_pct=baseline, adaptive_size_pct=adaptive,
            forward_returns=returns,
            forward_mae={30: -1.0, 60: -2.0, 90: -3.0},
            paired_deltas={h: size_diff * r / 100 for h, r in returns.items()},
        )

    def test_aggregate_emits_all_horizons(self):
        entries = [
            self._entry("bull_low_vol", 5.0, 8.0, 10.0),
            self._entry("bear_high_vol", -3.0, -2.0, 1.0),
            self._entry("sideways_low_vol", 1.0, 2.0, 3.0),
        ]
        m = s2.aggregate_metrics(entries, n_iter=500)
        for h in [30, 60, 90]:
            assert h in m
            assert m[h]["n"] == 3

    def test_wrong_directional_zero_when_neutral_only(self):
        """Neutral entries have paired_delta=0 — never < 0."""
        entries = [self._entry("sideways_low_vol", r, r, r) for r in [5, -3, 1, -2]]
        m = s2.aggregate_metrics(entries, n_iter=500)
        # All paired deltas are exactly 0 → wrong_directional_pct = 0
        # (P(d < 0) is 0 because deltas are 0, not negative)
        assert m[60]["wrong_directional_pct"] == 0.0
