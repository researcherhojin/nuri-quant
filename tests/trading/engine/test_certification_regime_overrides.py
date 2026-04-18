"""E3-3c regime-adaptive position cap — siege_gates.regime_overrides tests.

Stage 2 (#402) PASS verdict justifies regime-adaptive sizing on per_position_max.
This test suite locks the override semantics:

- Multiplier loader (config → dict)
- Apply per-account / per-regime
- Neutral / None / missing-config fallback to 1.0
- Absolute cap protection
- _check_position_limits integration (pass + fail under override)
- Hard veto preserved (volatility_gate orthogonal to position_limit)

Reference: STRATEGY §3.6 + #402 codex Round 1 verdict ("ship narrowly for
per_position_max only, sector cap stays out").
"""
from unittest.mock import patch

import pandas as pd
import pytest


class TestGetPositionMultiplier:
    """siege_gates.regime_overrides[regime].per_position_max_multiplier lookup."""

    def test_aggressive_regimes_return_1_2(self):
        from nuri.trading.engine.certification import _get_position_multiplier
        assert _get_position_multiplier("bull_low_vol") == 1.2
        assert _get_position_multiplier("recovery") == 1.2

    def test_conservative_regimes_return_0_8(self):
        from nuri.trading.engine.certification import _get_position_multiplier
        assert _get_position_multiplier("bear_high_vol") == 0.8
        assert _get_position_multiplier("bull_high_vol") == 0.8
        assert _get_position_multiplier("stagflation") == 0.8
        assert _get_position_multiplier("euphoria") == 0.8

    def test_neutral_regimes_default_to_1_0(self):
        """Neutral regime 은 YAML 에 미등록 → 1.0."""
        from nuri.trading.engine.certification import _get_position_multiplier
        for regime in ["sideways_low_vol", "sideways_high_vol", "bear_low_vol",
                       "sector_rotation"]:
            assert _get_position_multiplier(regime) == 1.0, f"{regime} should be 1.0"

    def test_none_regime_returns_1_0(self):
        """classify_regime 실패 → 1.0 fallback."""
        from nuri.trading.engine.certification import _get_position_multiplier
        assert _get_position_multiplier(None) == 1.0

    def test_unknown_regime_returns_1_0(self):
        """존재하지 않는 regime label → 1.0 fallback."""
        from nuri.trading.engine.certification import _get_position_multiplier
        assert _get_position_multiplier("nonexistent_regime") == 1.0


class TestApplyPositionMultiplier:
    """base × multiplier with absolute cap clip."""

    def test_aggressive_raises_position_pct(self):
        """active 25% × 1.2 = 30%."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        assert _apply_position_multiplier(0.25, "bull_low_vol") == pytest.approx(0.30)

    def test_conservative_lowers_position_pct(self):
        """core 15% × 0.8 = 12%."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        assert _apply_position_multiplier(0.15, "bear_high_vol") == pytest.approx(0.12)

    def test_neutral_unchanged(self):
        from nuri.trading.engine.certification import _apply_position_multiplier
        assert _apply_position_multiplier(0.15, "sideways_low_vol") == 0.15

    def test_pension_aggressive_within_cap(self):
        """pension 40% × 1.2 = 48%, cap=50% → 48% (no clip)."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        assert _apply_position_multiplier(0.40, "bull_low_vol") == pytest.approx(0.48)

    def test_aggressive_clipped_at_absolute_cap(self):
        """Force base 0.45 × 1.2 = 0.54 → clipped to 0.50."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        result = _apply_position_multiplier(0.45, "bull_low_vol")
        assert result == pytest.approx(0.50)

    def test_conservative_does_not_use_cap(self):
        """0.8× lowers, never inflates → cap path 안 탐 (base 보존, lower)."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        # active 25% × 0.8 = 20% (cap 50% irrelevant)
        assert _apply_position_multiplier(0.25, "bear_high_vol") == pytest.approx(0.20)

    def test_base_above_cap_neutral_returns_base(self):
        """Strategy 자체가 cap 보다 크면 multiplier=1.0 path 에서 base 보존 — 침해하지 않음."""
        from nuri.trading.engine.certification import _apply_position_multiplier
        # 60% base × 1.0 = 60% (cap 적용 안 함, neutral path)
        assert _apply_position_multiplier(0.60, "sideways_low_vol") == 0.60


class TestGetMultiplierGracefulFallback:
    """Config 부재 / 손상 시 graceful 1.0 fallback."""

    def test_missing_regime_overrides_key_falls_back_to_1(self):
        """siege_gates.regime_overrides 자체 부재 → 1.0."""
        from nuri.trading.engine import certification as cert_mod
        with patch.object(cert_mod, "RULES", {"siege_gates": {}}):
            assert cert_mod._get_position_multiplier("bull_low_vol") == 1.0

    def test_missing_siege_gates_key_falls_back_to_1(self):
        from nuri.trading.engine import certification as cert_mod
        with patch.object(cert_mod, "RULES", {}):
            assert cert_mod._get_position_multiplier("recovery") == 1.0

    def test_missing_multiplier_field_falls_back_to_1(self):
        """regime entry 는 있지만 per_position_max_multiplier 누락 → 1.0."""
        from nuri.trading.engine import certification as cert_mod
        with patch.object(cert_mod, "RULES", {
            "siege_gates": {"regime_overrides": {"bull_low_vol": {}}}
        }):
            assert cert_mod._get_position_multiplier("bull_low_vol") == 1.0


class TestCurrentRegime:
    """_current_regime() 의 graceful fallback (None) — classify 실패 시."""

    def test_returns_regime_string_on_success(self):
        from nuri.trading.engine import certification as cert_mod
        # MockRegimeState
        class MockState:
            regime = "bull_low_vol"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=MockState()):
            assert cert_mod._current_regime() == "bull_low_vol"

    def test_returns_none_when_classify_returns_none(self):
        from nuri.trading.engine import certification as cert_mod
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            assert cert_mod._current_regime() is None

    def test_returns_none_on_exception(self):
        """Data gap 등으로 classify 가 throw 해도 None 반환 (graceful)."""
        from nuri.trading.engine import certification as cert_mod
        with patch("nuri.quant.regime.classifier.classify_regime",
                   side_effect=RuntimeError("DB gap")):
            assert cert_mod._current_regime() is None


class TestCheckPositionLimitsWithOverride:
    """_check_position_limits 가 regime override 를 적용하는 통합 path."""

    def _seed_portfolio(self, db_path, holdings):
        """holdings: list of dict {ticker, account, qty, avg_price}."""
        from nuri.core.db import upsert_portfolio
        rows = [
            {"ticker": h["ticker"], "account": h["account"], "qty": h["qty"],
             "avg_price": h["avg_price"], "currency": "USD",
             "name": h["ticker"], "sector": "Tech"}
            for h in holdings
        ]
        upsert_portfolio(rows, db_path=db_path)

    def test_pass_under_aggressive_regime_when_baseline_would_fail(self, monkeypatch, tmp_path):
        """regime=bull_low_vol 18% cap → 16% holding PASS (baseline 15% 였으면 FAIL)."""
        from nuri.trading.engine import certification as cert_mod

        # Mock analyze_portfolio: single AAPL at 16% under core (15% baseline).
        df = pd.DataFrame([{"ticker": "AAPL", "weight_pct": 16.0,
                            "account": "core_account", "sector": "Tech"}])

        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df), \
             patch.object(cert_mod, "_current_regime", return_value="bull_low_vol"):
            result = cert_mod._check_position_limits()
        assert result.passed is True, f"expected PASS under bull_low_vol×1.2, got: {result.detail}"
        assert "regime=bull_low_vol" in result.detail

    def test_fail_under_conservative_regime_when_baseline_would_pass(self, monkeypatch):
        """regime=bear_high_vol 12% cap → 13% holding FAIL (baseline 15% 였으면 PASS)."""
        from nuri.trading.engine import certification as cert_mod

        df = pd.DataFrame([{"ticker": "AAPL", "weight_pct": 13.0,
                            "account": "core_account", "sector": "Tech"}])

        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df), \
             patch.object(cert_mod, "_current_regime", return_value="bear_high_vol"):
            result = cert_mod._check_position_limits()
        assert result.passed is False, f"expected FAIL under bear_high_vol×0.8, got: {result.detail}"
        assert "regime=bear_high_vol" in result.detail

    def test_neutral_regime_baseline_behavior(self, monkeypatch):
        """regime=sideways_low_vol → multiplier 1.0 → baseline behavior preserved.

        15% holding under core (15% baseline) → exactly at limit, NOT > 0.15 → PASS.
        Regime tag 표시 안 됨 (multiplier == 1.0 → no `(regime=...)` suffix)."""
        from nuri.trading.engine import certification as cert_mod

        df = pd.DataFrame([{"ticker": "AAPL", "weight_pct": 15.0,
                            "account": "core_account", "sector": "Tech"}])

        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df), \
             patch.object(cert_mod, "_current_regime", return_value="sideways_low_vol"):
            result = cert_mod._check_position_limits()
        assert result.passed is True
        assert "regime=" not in result.detail  # neutral → no tag

    def test_none_regime_baseline_behavior(self):
        """classify failed (regime=None) → multiplier 1.0 → baseline behavior."""
        from nuri.trading.engine import certification as cert_mod

        df = pd.DataFrame([{"ticker": "AAPL", "weight_pct": 16.0,
                            "account": "core_account", "sector": "Tech"}])

        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df), \
             patch.object(cert_mod, "_current_regime", return_value=None):
            result = cert_mod._check_position_limits()
        # 16% > 15% (core baseline) → FAIL
        assert result.passed is False
        assert "regime=" not in result.detail

    def test_empty_portfolio_returns_pass(self):
        from nuri.trading.engine import certification as cert_mod
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   return_value=pd.DataFrame()), \
             patch.object(cert_mod, "_current_regime", return_value="bull_low_vol"):
            result = cert_mod._check_position_limits()
        assert result.passed is True
        assert "비어있음" in result.detail


class TestHardVetoPreserved:
    """Hard veto (VIX>30 신규 매수 차단) 는 volatility_gate 에 그대로 — position_limit
    은 직교. 이 test 는 두 path 가 분리됨을 lock-in."""

    def test_position_override_does_not_touch_volatility_gate(self):
        """regime_override 가 _check_volatility_for_class 의 threshold 변경 안 함."""
        from nuri.core.rules import RULES
        gates = RULES.get("siege_gates", {})
        # us_equity volatility threshold = 30 (Hard veto VIX>30)
        us = gates.get("asset_classes", {}).get("us_equity", {})
        assert us.get("volatility_primary_threshold") == 30, \
            "Hard veto VIX>30 threshold must be untouched by regime_override"

    def test_regime_overrides_only_specifies_per_position_max(self):
        """E3-3c scope: per_position_max_multiplier ONLY.
        sector / stop_loss / leverage_ban override 는 미정의 (codex narrow scope)."""
        from nuri.core.rules import RULES
        overrides = RULES.get("siege_gates", {}).get("regime_overrides", {})
        for regime, spec in overrides.items():
            keys = set(spec.keys())
            allowed = {"per_position_max_multiplier"}
            extra = keys - allowed
            assert not extra, (
                f"{regime} has out-of-scope override keys: {extra}. "
                "E3-3c is narrow — sector/stop_loss/leverage_ban are E3-4 follow-up."
            )
