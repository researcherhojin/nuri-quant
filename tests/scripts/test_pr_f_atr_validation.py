"""PR F ATR validation script — unit tests for stop-exit simulation + metric math.

Tests the math correctness of the sim pieces, not the live verdict (which
depends on DB state with 5Y price coverage). E3-3b testing pattern.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pr_f_atr_validation.py"
_spec = importlib.util.spec_from_file_location("pr_f_atr_validation", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
v = importlib.util.module_from_spec(_spec)
sys.modules["pr_f_atr_validation"] = v
_spec.loader.exec_module(v)


class TestSimulateStop:
    """_simulate_stop exit logic — first close ≤ stop → exit, else horizon exit."""

    def test_no_stop_hit_exits_at_horizon(self):
        forward = [{"close": 105}, {"close": 103}, {"close": 108}]
        ret, hold, stopped = v._simulate_stop(forward, entry_price=100, stop_price=90, horizon=3)
        # No row ≤ 90 → exit at last close 108
        assert ret == 8.0
        assert hold == 3
        assert stopped is False

    def test_stop_hit_on_first_breach(self):
        forward = [{"close": 95}, {"close": 88}, {"close": 92}]  # idx 1 breaches 90
        ret, hold, stopped = v._simulate_stop(forward, entry_price=100, stop_price=90, horizon=3)
        assert ret == -12.0  # (88 - 100) / 100 * 100
        assert hold == 2     # exited on day 2
        assert stopped is True

    def test_stop_hit_immediately(self):
        forward = [{"close": 85}]
        ret, hold, stopped = v._simulate_stop(forward, entry_price=100, stop_price=90, horizon=3)
        assert ret == -15.0
        assert hold == 1
        assert stopped is True

    def test_empty_forward_safe(self):
        ret, hold, stopped = v._simulate_stop([], entry_price=100, stop_price=90, horizon=30)
        assert (ret, hold, stopped) == (0.0, 0, False)

    def test_horizon_clamps_window(self):
        # 5 rows but horizon=3 → only first 3 considered
        forward = [{"close": 95}, {"close": 93}, {"close": 92}, {"close": 85}, {"close": 80}]
        ret, hold, stopped = v._simulate_stop(forward, entry_price=100, stop_price=90, horizon=3)
        # Days 1-3: closes 95, 93, 92 — none ≤ 90 → exit at idx 2 = 92
        assert ret == -8.0
        assert hold == 3
        assert stopped is False


class TestBootstrapCI:
    def test_constant_values_yield_near_zero_width(self):
        lo, hi = v.bootstrap_ci([1.0] * 100, n_iter=500)
        assert abs(hi - lo) < 0.01  # all identical → CI collapses

    def test_returns_nan_for_insufficient_data(self):
        import math
        lo, hi = v.bootstrap_ci([], n_iter=100)
        assert math.isnan(lo) and math.isnan(hi)

    def test_positive_mean_has_positive_ci(self):
        # N(+5, σ=1) should produce CI well above 0 with n=100
        import random
        rng = random.Random(42)
        values = [5.0 + rng.gauss(0, 1) for _ in range(100)]
        lo, hi = v.bootstrap_ci(values, n_iter=1000)
        assert lo > 0 and hi > lo


class TestComputeMetrics:
    def test_all_positive_returns_high_hit_rate(self):
        m = v.compute_metrics([5.0, 10.0, 15.0], [30, 30, 30], [False, False, False])
        assert m["n"] == 3
        assert m["hit_rate"] == 100.0
        assert m["turnover"] == 0.0
        assert m["ulcer"] == 0.0  # no negative returns
        assert m["max_dd"] == 5.0  # worst (but positive) return

    def test_mixed_returns_ulcer_nonzero(self):
        m = v.compute_metrics([10.0, -5.0, -3.0], [30, 30, 30], [False, True, True])
        assert m["n"] == 3
        assert m["turnover"] == pytest.approx(2 / 3 * 100, rel=1e-6)
        # Ulcer = sqrt(mean((-5)² + (-3)²)) = sqrt((25+9)/2) = sqrt(17) ≈ 4.12
        assert abs(m["ulcer"] - (17.0 ** 0.5)) < 0.01

    def test_empty_returns_n_zero(self):
        m = v.compute_metrics([], [], [])
        assert m["n"] == 0


class TestScoreVsBaseline:
    def test_all_wins(self):
        baseline = {
            "n": 10, "cagr": 5.0, "max_dd": -20.0, "ulcer": 5.0,
            "turnover": 50.0, "tax_drag": 90.0, "hit_rate": 50.0,
        }
        treatment = {
            "n": 10, "cagr": 10.0, "max_dd": -10.0, "ulcer": 3.0,
            "turnover": 30.0, "tax_drag": 70.0, "hit_rate": 70.0,
        }
        score, wins = v.score_vs_baseline(treatment, baseline)
        assert score == 6
        assert set(wins) == {"CAGR", "MaxDD", "Ulcer", "Turnover", "TaxDrag", "HitRate"}

    def test_all_losses(self):
        baseline = {
            "n": 10, "cagr": 10.0, "max_dd": -5.0, "ulcer": 2.0,
            "turnover": 10.0, "tax_drag": 50.0, "hit_rate": 70.0,
        }
        treatment = {
            "n": 10, "cagr": 5.0, "max_dd": -15.0, "ulcer": 4.0,
            "turnover": 20.0, "tax_drag": 80.0, "hit_rate": 50.0,
        }
        score, wins = v.score_vs_baseline(treatment, baseline)
        assert score == 0
        assert wins == []

    def test_insufficient_sample_returns_zero(self):
        score, _ = v.score_vs_baseline({"n": 0}, {"n": 10, "cagr": 5})
        assert score == 0


class TestGridFrozen:
    """Grid + regime_mult test values frozen — STRATEGY 개정 PR 필요 on change."""

    def test_k_grid_parity_with_atr_module(self):
        from nuri.quant.exits.atr import K_GRID
        assert v.K_GRID == K_GRID, (
            "validation script K_GRID drifted from atr module — "
            "paired counterfactual 재생산 불가"
        )

    def test_regime_mult_test_matches_e3_3c(self):
        # E3-3c aggressive/conservative + neutral boundary values
        assert v.REGIME_MULT_TEST == [0.8, 1.0, 1.3]


class TestPairedDeltas:
    """paired_deltas — treatment 와 baseline 모두 있을 때만 pair."""

    def _trade(self, ticker: str, baseline_ret: float | None,
               treat_ret: float | None, k: float = 2.0, mult: float = 1.0) -> v.Trade:
        return v.Trade(
            ticker=ticker, entry_date="2024-01-15", entry_price=100.0,
            regime="neutral", atr_at_entry=3.0,
            baseline_return_pct={60: baseline_ret},
            baseline_holding_days={60: 30 if baseline_ret is not None else None},
            baseline_stopped={60: False},
            treatment={(k, mult): {60: {"return_pct": treat_ret,
                                         "holding_days": 30 if treat_ret is not None else None,
                                         "stopped": False}}},
        )

    def test_only_fully_paired_count(self):
        trades = [
            self._trade("A", 5.0, 8.0),    # paired
            self._trade("B", None, 6.0),   # baseline missing
            self._trade("C", 3.0, None),   # treatment missing
            self._trade("D", -2.0, 1.0),   # paired
        ]
        deltas = v.paired_deltas(trades, k=2.0, regime_mult=1.0, horizon=60)
        assert deltas == [3.0, 3.0]  # (8-5), (1-(-2))

    def test_empty_when_no_trades(self):
        assert v.paired_deltas([], k=2.0, regime_mult=1.0, horizon=60) == []


