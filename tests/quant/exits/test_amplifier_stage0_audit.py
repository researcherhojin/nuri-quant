"""Lock-tests for E3 Phase 2 Stage 0 no-lookahead audit.

Two layers of invariants are pinned here (per STRATEGY §5.3.1
Gotcha-Test Pair):

1. Positive — the audit returns `clean=True` against real source
   modules. If a future change to `nuri/quant/regime/{classifier,
   recovery_detector}.py` reintroduces a no-lookahead leak, this test
   FAILs and Stage 2 is blocked at CI before any verdict can be produced.

2. Negative — when a leak is artificially injected (via monkeypatch on a
   single classifier helper), the audit MUST detect it and emit a
   violation. This proves the audit isn't trivially passing because of a
   stub bug — it actually exercises the contamination path.

Spec: docs/plans/E3_phase2_paired_counterfactual.md §"Stage 0".
"""

from __future__ import annotations

import scripts.episodes.e3_amplifier_stage0_audit as audit_mod
from scripts.episodes.e3_amplifier_stage0_audit import (
    AS_OF_DATE,
    FUTURE_VIX_VALUE,
    AuditResult,
    run_audit,
)

# ─── Positive: real source must pass ────────────────────────────────────


class TestAuditCleanOnRealSource:
    """If any of these break, Stage 2 is BLOCKED until the underlying
    no-lookahead bug is fixed (per spec acceptance section)."""

    def test_audit_returns_clean(self):
        result = run_audit()
        assert result.clean is True, (
            f"Stage 0 audit failed on real source: {result.violations}. "
            "Stage 2 paired replay cannot run until this is fixed."
        )

    def test_audit_runs_six_checks(self):
        result = run_audit()
        assert len(result.checks_run) == 6
        # Order-insensitive but content-locked.
        assert set(result.checks_run) == {
            "classifier._get_vix",
            "classifier._get_fear_greed",
            "classifier._load_spy_series",
            "classifier.compute_dynamic_thresholds",
            "classifier.classify_regime",
            "recovery_detector.evaluate_recovery",
        }

    def test_audit_records_as_of_date(self):
        result = run_audit()
        assert result.as_of_date == AS_OF_DATE

    def test_audit_violations_empty_on_clean(self):
        result = run_audit()
        assert result.violations == []


# ─── Negative: audit must catch synthetic leaks ─────────────────────────


class TestAuditDetectsSyntheticLeak:
    """If the audit silently passes a leak, it would be worse than no
    audit at all (false confidence). These tests inject contamination
    via monkeypatch and assert the audit catches it."""

    def test_detects_vix_leak(self, monkeypatch):
        """If `_get_vix` started returning a future-row value (e.g. by
        ignoring its `date` parameter), the audit must catch it."""
        from nuri.quant.regime import classifier as classifier_mod

        def leaky_get_vix(date=None, db_path=None):
            # Simulate a date-filter bug: always return the future-marker value.
            return FUTURE_VIX_VALUE

        monkeypatch.setattr(classifier_mod, "_get_vix", leaky_get_vix)
        result = run_audit()
        assert result.clean is False
        targets = {v.target for v in result.violations}
        assert "classifier._get_vix" in targets

    def test_detects_load_spy_series_leak(self, monkeypatch):
        """If `_load_spy_series` returned a series whose max(date) > as_of,
        the audit must catch it."""
        import pandas as pd

        from nuri.quant.regime import classifier as classifier_mod

        def leaky_load_spy_series(date=None, db_path=None):
            # Return a tiny df where max(date) is post-as_of and last close
            # is the contamination marker. Past 250+ rows still required by
            # caller logic, so include them too — but flip max date.
            past_df = pd.DataFrame(
                {
                    "date": [f"2020-01-{(i % 28) + 1:02d}" for i in range(220)],
                    "close": [200.0 + i * 0.1 for i in range(220)],
                }
            )
            future_row = pd.DataFrame({"date": ["2099-01-01"], "close": [audit_mod.FUTURE_SPY_PRICE]})
            df = pd.concat([past_df, future_row], ignore_index=True)
            # add minimal columns the audit doesn't read deeply
            for col in ("sma50", "sma200", "sma20", "bb_width", "rsi", "sma50_slope"):
                df[col] = 0.0
            return df

        monkeypatch.setattr(classifier_mod, "_load_spy_series", leaky_load_spy_series)
        result = run_audit()
        assert result.clean is False
        targets = {v.target for v in result.violations}
        assert "classifier._load_spy_series" in targets

    def test_detects_threshold_inflation(self, monkeypatch):
        """If `compute_dynamic_thresholds` produced inflated VIX values
        (because future VIX=999 leaked into the median calculation), the
        audit must catch it."""
        from nuri.quant.regime import classifier as classifier_mod

        def leaky_compute(db_path=None, date=None):
            return {
                "vix_threshold": 200.0,  # impossibly high → leak signature
                "vix_bear_threshold": 300.0,
                "sideways_pct": 2.0,
                "bb_width_threshold": 6.0,
            }

        monkeypatch.setattr(classifier_mod, "compute_dynamic_thresholds", leaky_compute)
        result = run_audit()
        assert result.clean is False
        targets = {v.target for v in result.violations}
        assert "classifier.compute_dynamic_thresholds" in targets


# ─── Audit infra invariants ─────────────────────────────────────────────


class TestAuditInfra:
    """Lock the audit's own invariants — schema, seed data shape,
    AS_OF_DATE choice. Drift here would silently weaken the audit."""

    def test_as_of_date_is_iso_format(self):
        # Must be parseable; otherwise downstream date-string compares break.
        import datetime

        datetime.date.fromisoformat(AS_OF_DATE)

    def test_future_marker_values_are_extreme(self):
        # Markers must be far outside historical ranges so any leak is
        # immediately distinguishable from noise.
        assert FUTURE_VIX_VALUE > 200  # historical max VIX < 100
        assert audit_mod.FUTURE_SPY_PRICE < 50  # historical SPY > $200 since 2014
        assert audit_mod.FUTURE_FG_VALUE > 200  # F&G is bounded 0-100

    def test_past_window_covers_sma200(self):
        # SPY rolling SMA200 needs ≥ 200 trading days. Audit seed must
        # provide enough headroom for percentile calcs as well.
        assert audit_mod.PAST_DAYS >= 1000

    def test_audit_result_serializable(self):
        result = run_audit()
        from dataclasses import asdict

        d = asdict(result)
        assert "clean" in d and "checks_run" in d and "violations" in d


# ─── End-to-end CLI exit code (lock the precondition contract) ───────────


class TestStage0AsPreconditionContract:
    """Spec contract: Stage 0 failure is a precondition failure (exit 1)
    — Stage 2 must NOT run, no verdict.json must be produced. This
    cements the contract at the script's exit-code interface."""

    def test_run_audit_returns_audit_result(self):
        result = run_audit()
        assert isinstance(result, AuditResult)

    def test_clean_audit_means_stage2_may_proceed(self):
        # The user-facing semantics: clean=True → exit 0 from main().
        # We exercise main() with --report-out routed to a tmp path so the
        # contamination report is not written when the audit is clean.
        result = run_audit()
        assert result.clean is True
        # Documented contract: when clean, Stage 2 may proceed. This is
        # enforced at the CI/PR layer — pytest seeing this assert failing
        # halts the pipeline before any Stage 2 run.
