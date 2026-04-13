"""Unit tests for actions.py helper functions — mock-based, no DB dependency."""
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─── _compute_verdict ───

class TestComputeVerdict:
    def setup_method(self):
        from nuri.api.routes.actions import _compute_verdict
        self.verdict = _compute_verdict

    def test_extreme_drop_danger(self):
        v, l = self.verdict(["good"], ["bad"], {"score": 10, "rsi": 15, "change_5d": -25})
        assert l == "danger"

    def test_no_pros_with_cons_danger(self):
        v, l = self.verdict([], ["risky signal"], {"score": 20, "rsi": 50, "change_5d": -5})
        assert l == "danger"
        assert "근거 부족" in v

    def test_strong_positive(self):
        v, l = self.verdict(["a", "b"], [], {"score": 50, "rsi": 50, "change_5d": 5})
        assert l == "positive"
        assert "매수 고려" in v

    def test_mixed_signals_neutral(self):
        v, l = self.verdict(["good"], ["bad"], {"score": 30, "rsi": 50, "change_5d": 5})
        assert l == "neutral"

    def test_overbought_neutral(self):
        v, l = self.verdict(["one"], [], {"score": 20, "rsi": 50, "change_5d": 18})
        assert l == "neutral"
        assert "눌림목" in v

    def test_empty_muted(self):
        v, l = self.verdict([], [], {"score": 5, "rsi": 50, "change_5d": 0})
        assert l == "muted"

    def test_positive_needs_high_score(self):
        v, l = self.verdict(["a", "b"], [], {"score": 30, "rsi": 50, "change_5d": 5})
        # score 30 < 40 → not positive
        assert l != "positive"


# ─── _get_siege_violations ───

class TestGetSiegeViolations:
    def test_parses_position_limit_detail(self):
        """Test regex extraction from SIEGE detail string."""
        import re
        detail = "위반: TSLA(15.4%>15%)"
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", detail)
        assert matches == ["TSLA"]

    def test_parses_multiple_violations(self):
        import re
        detail = "위반: TSLA(15.4%>15%), NBIS(16.0%>15%)"
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", detail)
        assert matches == ["TSLA", "NBIS"]

    def test_no_match_returns_empty(self):
        import re
        detail = "모든 종목 15% 이하"
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", detail)
        assert matches == []

    @patch("nuri.trading.engine.certification.certify")
    def test_handles_certify_exception(self, mock_certify):
        mock_certify.side_effect = Exception("DB error")
        from nuri.api.routes.actions import _get_siege_violations
        result = _get_siege_violations()
        assert result == []


# ─── _get_targets_status ───

class TestGetTargetsStatus:
    @patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets")
    def test_returns_target_dict(self, mock_targets):
        mock_targets.return_value = [
            {"ticker": "AAPL", "stop_loss": 140, "target_1": 180, "target_2": 210, "trailing_stop_pct": 15, "analyst_target": 200},
        ]
        from nuri.api.routes.actions import _get_targets_status
        result = _get_targets_status()
        assert "AAPL" in result
        assert result["AAPL"]["stop_loss"] == 140
        assert result["AAPL"]["target_1"] == 180

    @patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets")
    def test_handles_exception(self, mock_targets):
        mock_targets.side_effect = Exception("error")
        from nuri.api.routes.actions import _get_targets_status
        result = _get_targets_status()
        assert result == {}


# ─── _get_improving_signals ───

class TestGetImprovingSignals:
    @patch("nuri.trading.engine.memory.detect_drift")
    def test_returns_improving_set(self, mock_drift):
        mock_drift.return_value = [
            SimpleNamespace(signal_id="rsi_oversold", status="improving"),
            SimpleNamespace(signal_id="bb_bounce", status="critical"),
            SimpleNamespace(signal_id="gap_down", status="improving"),
        ]
        from nuri.api.routes.actions import _get_improving_signals
        result = _get_improving_signals()
        assert "rsi_oversold" in result
        assert "gap_down" in result
        assert "bb_bounce" not in result

    @patch("nuri.trading.engine.memory.detect_drift")
    def test_handles_exception(self, mock_drift):
        mock_drift.side_effect = Exception("error")
        from nuri.api.routes.actions import _get_improving_signals
        result = _get_improving_signals()
        assert result == set()


# ─── _get_recent_scan_results ───

class TestGetRecentScanResults:
    @patch("nuri.trading.swing.scanner.scan_market")
    def test_returns_scan_dicts(self, mock_scan):
        mock_scan.return_value = [
            SimpleNamespace(ticker="MRVL", price=128, change_1d=7, change_5d=20, volume_ratio=1.7, rsi=83, signal="breakout", score=69),
        ]
        from nuri.api.routes.actions import _get_recent_scan_results
        result = _get_recent_scan_results()
        assert len(result) == 1
        assert result[0]["ticker"] == "MRVL"
        assert result[0]["score"] == 69

    @patch("nuri.trading.swing.scanner.scan_market")
    def test_handles_exception(self, mock_scan):
        mock_scan.side_effect = Exception("no data")
        from nuri.api.routes.actions import _get_recent_scan_results
        result = _get_recent_scan_results()
        assert result == []


# ─── _get_system_health ───

class TestGetSystemHealth:
    @patch("nuri.api.routes.actions.query")
    def test_returns_all_sections(self, mock_query):
        mock_query.return_value = []
        from nuri.api.routes.actions import _get_system_health
        with patch("nuri.trading.engine.certification.certify") as mock_cert, \
             patch("nuri.quant.regime.classifier.classify_regime") as mock_regime, \
             patch("nuri.quant.regime.macro_score.compute_macro_score") as mock_macro, \
             patch("nuri.core.freshness.check_all_freshness") as mock_fresh:

            @dataclass
            class FakeCert:
                score: float = 54.0
                certified: bool = False
                passed: int = 6
                failed: int = 1
                warnings: int = 4
                total_conditions: int = 11
                conditions: list = None  # type: ignore[assignment]
                def __post_init__(self):
                    self.conditions = self.conditions or []

            mock_cert.return_value = FakeCert()
            mock_regime.return_value = SimpleNamespace(regime="recovery", trend="sideways", volatility="high", confidence=0.75)
            mock_macro.return_value = SimpleNamespace(total_score=56, interpretation="Neutral")
            mock_fresh.return_value = [{"status": "PASS"}, {"status": "WARN"}, {"status": "FAIL"}]

            result = _get_system_health()

            assert result["siege"]["score"] == 54
            assert result["siege"]["certified"] is False
            assert result["regime"]["regime"] == "recovery"
            assert result["macro"]["score"] == 56
            assert result["freshness"]["status"] == "FAIL"
            assert result["freshness"]["fail_count"] == 1

    @patch("nuri.api.routes.actions.query")
    def test_handles_all_exceptions(self, mock_query):
        mock_query.return_value = []
        from nuri.api.routes.actions import _get_system_health
        with patch("nuri.trading.engine.certification.certify", side_effect=Exception), \
             patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception), \
             patch("nuri.core.freshness.check_all_freshness", side_effect=Exception):
            result = _get_system_health()
            assert result["siege"] == {"score": 0, "certified": False}
            assert result["regime"] == {}
            assert result["macro"] == {}
            assert result["freshness"] == {}


# ─── _build_actions integration logic ───

class TestBuildActionsLogic:
    """Test the business logic of _build_actions with mocked data sources."""

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_siege_violation_goes_to_urgent(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "TSLA", "action": "SELL", "confidence": 46, "agreement": 20}]
        mock_siege.return_value = [{"ticker": "TSLA", "detail": "SIEGE: 한도 — TSLA(15.4%>15%)", "condition_id": "position_limit"}]
        mock_targets.return_value = {}
        mock_pf.return_value = {"TSLA": {"current_price": 349, "avg_price": 343, "quantity": 15, "pnl_pct": 1.6, "position_pct": 15.4, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["urgent"]) == 1
        assert result["urgent"][0]["ticker"] == "TSLA"

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_sell_with_loss_goes_to_urgent(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "BAD", "action": "SELL", "confidence": 70, "agreement": 50}]
        mock_siege.return_value = []
        mock_targets.return_value = {}
        mock_pf.return_value = {"BAD": {"current_price": 90, "avg_price": 100, "quantity": 10, "pnl_pct": -10, "position_pct": 5, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_sell_without_loss_goes_to_check(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "MEH", "action": "SELL", "confidence": 50, "agreement": 20}]
        mock_siege.return_value = []
        mock_targets.return_value = {}
        mock_pf.return_value = {"MEH": {"current_price": 105, "avg_price": 100, "quantity": 10, "pnl_pct": 5, "position_pct": 3, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["check"]) == 1

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_target_1_hit_goes_to_check(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "WIN", "action": "BUY", "confidence": 70, "agreement": 40}]
        mock_siege.return_value = []
        mock_targets.return_value = {"WIN": {"stop_loss": 90, "target_1": 120, "target_2": 140}}
        mock_pf.return_value = {"WIN": {"current_price": 125, "avg_price": 100, "quantity": 10, "pnl_pct": 25, "position_pct": 5, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["check"]) == 1
        assert "1차 익절" in result["check"][0]["reasons"][0]

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_target_2_hit_goes_to_check(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "BIG", "action": "BUY", "confidence": 80, "agreement": 60}]
        mock_siege.return_value = []
        mock_targets.return_value = {"BIG": {"stop_loss": 90, "target_1": 120, "target_2": 140}}
        mock_pf.return_value = {"BIG": {"current_price": 145, "avg_price": 100, "quantity": 10, "pnl_pct": 45, "position_pct": 8, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["check"]) == 1
        assert "2차 익절" in result["check"][0]["reasons"][0]

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_high_short_interest_goes_to_check(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "SQZ", "action": "BUY", "confidence": 60, "agreement": 40}]
        mock_siege.return_value = []
        mock_targets.return_value = {}
        mock_pf.return_value = {"SQZ": {"current_price": 110, "avg_price": 100, "quantity": 10, "pnl_pct": 10, "position_pct": 3, "account": "Main"}}
        mock_short.return_value = 19.6  # > 10%

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["check"]) == 1
        assert "공매도" in result["check"][0]["reasons"][0]

    @patch("nuri.api.routes.actions._get_recommendations")
    @patch("nuri.api.routes.actions._get_siege_violations")
    @patch("nuri.api.routes.actions._get_targets_status")
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_short_interest")
    def test_normal_buy_goes_to_hold(self, mock_short, mock_pf, mock_targets, mock_siege, mock_recs):
        mock_recs.return_value = [{"ticker": "OK", "action": "BUY", "confidence": 60, "agreement": 30}]
        mock_siege.return_value = []
        mock_targets.return_value = {}
        mock_pf.return_value = {"OK": {"current_price": 105, "avg_price": 100, "quantity": 10, "pnl_pct": 5, "position_pct": 3, "account": "Main"}}
        mock_short.return_value = None

        from nuri.api.routes.actions import _build_actions
        result = _build_actions()
        assert len(result["hold"]) == 1
        assert "BUY (conf 60)" in result["hold"][0]["reasons"][0]


# ─── _build_opportunities logic ───

class TestBuildOpportunitiesLogic:
    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_excludes_portfolio_tickers(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {"AAPL": {}}
        mock_scan.return_value = [
            {"ticker": "AAPL", "price": 150, "change_1d": 1, "change_5d": 5, "volume_ratio": 1.0, "rsi": 50, "signal": "momentum", "score": 30},
            {"ticker": "MRVL", "price": 128, "change_1d": 7, "change_5d": 20, "volume_ratio": 1.7, "rsi": 83, "signal": "breakout", "score": 69},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        tickers = [o["ticker"] for o in result]
        assert "AAPL" not in tickers
        assert "MRVL" in tickers

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_breakout_generates_pro(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "BRK", "price": 100, "change_1d": 5, "change_5d": 8, "volume_ratio": 1.5, "rsi": 60, "signal": "breakout", "score": 55},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert any("breakout" in p for p in result[0]["pros"])

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_oversold_with_improving_signal(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "DIP", "price": 50, "change_1d": -3, "change_5d": -8, "volume_ratio": 2.5, "rsi": 28, "signal": "volume_spike", "score": 30},
        ]
        mock_signals.return_value = {"rsi_oversold"}

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert any("승률 상승" in p for p in result[0]["pros"])

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_volume_spike_crash_generates_con(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "CRASH", "price": 80, "change_1d": -10, "change_5d": -18, "volume_ratio": 3.0, "rsi": 20, "signal": "volume_spike", "score": 25},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert any("급락" in c for c in result[0]["cons"])

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_overbought_generates_con(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "HOT", "price": 200, "change_1d": 5, "change_5d": 25, "volume_ratio": 1.2, "rsi": 85, "signal": "momentum", "score": 40},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert any("과매수" in c for c in result[0]["cons"])
        assert any("급등" in c for c in result[0]["cons"])

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_momentum_generates_pro(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "MOM", "price": 150, "change_1d": 3, "change_5d": 15, "volume_ratio": 1.0, "rsi": 65, "signal": "momentum", "score": 35},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert any("모멘텀" in p for p in result[0]["pros"])

    @patch("nuri.api.routes.actions._get_portfolio_map")
    @patch("nuri.api.routes.actions._get_recent_scan_results")
    @patch("nuri.api.routes.actions._get_improving_signals")
    def test_sorts_by_score_descending(self, mock_signals, mock_scan, mock_pf):
        mock_pf.return_value = {}
        mock_scan.return_value = [
            {"ticker": "LOW", "price": 50, "change_1d": 1, "change_5d": 3, "volume_ratio": 1.0, "rsi": 50, "signal": "momentum", "score": 10},
            {"ticker": "HIGH", "price": 200, "change_1d": 5, "change_5d": 15, "volume_ratio": 1.5, "rsi": 60, "signal": "breakout", "score": 70},
        ]
        mock_signals.return_value = set()

        from nuri.api.routes.actions import _build_opportunities
        result = _build_opportunities()
        assert result[0]["ticker"] == "HIGH"
