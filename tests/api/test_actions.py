"""Tests for /api/actions, /api/opportunities, /api/market-context endpoints.

Combines integration tests (TestClient) + unit tests (mock-based).
"""
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with isolated DB."""
    db = tmp_path / "test.db"
    with patch.dict("os.environ", {"NURI_DB_PATH": str(db)}):
        import nuri.core.db as db_mod

        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "AAPL", 10, 150.0, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "TSLA", 15, 300.0, "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-13", 155, 160, 150, 158, 1000000),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", "2026-04-13", 340, 355, 335, 348, 5000000),
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("usd_krw", "2026-04-13", 1488, "yfinance"),
            )
            conn.execute(
                "INSERT INTO recommendations (ticker, action, confidence, regime, signals, date) VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "BUY", 65, "recovery", json.dumps({"agreement_rate": 0.4}), "2026-04-13"),
            )
            conn.execute(
                "INSERT INTO recommendations (ticker, action, confidence, regime, signals, date) VALUES (?, ?, ?, ?, ?, ?)",
                ("TSLA", "SELL", 46, "recovery", json.dumps({"agreement_rate": 0.2}), "2026-04-13"),
            )
        from nuri.api.main import app
        yield TestClient(app)


@pytest.fixture()
def fast_client(client, monkeypatch):
    """TestClient with slow actions helpers stubbed for shape-only endpoint checks."""
    import nuri.api.routes.actions as actions_mod

    monkeypatch.setattr(actions_mod, "_get_siege_violations", lambda: [])
    monkeypatch.setattr(actions_mod, "_get_targets_status", lambda: {})
    monkeypatch.setattr(actions_mod, "_get_recent_scan_results", lambda: [])
    monkeypatch.setattr(actions_mod, "_get_improving_signals", lambda: set())
    monkeypatch.setattr(actions_mod, "_get_macro_events", lambda: [])
    monkeypatch.setattr(
        actions_mod,
        "_get_system_health",
        lambda: {"siege": {}, "regime": {}, "macro": {}, "freshness": {}},
    )
    return client


# ═══════════════════════════════════════════════════
# Integration tests (TestClient)
# ═══════════════════════════════════════════════════


class TestActionsEndpoint:
    def test_returns_structured_response(self, client):
        resp = client.get("/api/actions")
        assert resp.status_code == 200
        data = resp.json()
        # PR A (2026-04-21): 4-bucket shape — SIEGE 룰 위반은 portfolio bucket.
        for key in ("urgent", "check", "hold", "portfolio"):
            assert key in data, f"{key} bucket missing from /api/actions response"
            assert isinstance(data[key], list)

    def test_actions_contain_ticker_and_priority(self, fast_client):
        resp = fast_client.get("/api/actions")
        for item in resp.json()["urgent"] + resp.json()["check"] + resp.json()["hold"]:
            assert "ticker" in item
            assert "action" in item
            assert "priority" in item
            assert isinstance(item["reasons"], list)

    def test_buy_action_has_confidence(self, fast_client):
        resp = fast_client.get("/api/actions")
        data = resp.json()
        for item in data["hold"] + data["check"]:
            if item["action"] == "BUY":
                assert isinstance(item["confidence"], (int, float))


class TestOpportunitiesEndpoint:
    def test_returns_structured_response(self, fast_client):
        resp = fast_client.get("/api/opportunities")
        assert resp.status_code == 200
        assert isinstance(resp.json()["opportunities"], list)

    def test_opportunities_have_verdict(self, fast_client):
        for opp in fast_client.get("/api/opportunities").json()["opportunities"]:
            for key in ("ticker", "verdict", "verdict_level", "pros", "cons"):
                assert key in opp

    def test_excludes_portfolio_tickers(self, fast_client):
        for opp in fast_client.get("/api/opportunities").json()["opportunities"]:
            assert opp["ticker"] not in {"AAPL", "TSLA"}


class TestMarketContextEndpoint:
    def test_returns_structured_response(self, fast_client):
        resp = fast_client.get("/api/market-context")
        assert resp.status_code == 200
        data = resp.json()
        assert "macro_events" in data
        assert "system_health" in data
        assert "generated_at" in data


# ═══════════════════════════════════════════════════
# Unit tests — exception fallback + edge paths
# ═══════════════════════════════════════════════════


class TestCacheHitPaths:
    """캐시 hit 경로 테스트 — 5분 TTL 내 재호출 시 캐시된 결과 반환."""

    def _clear_caches(self):
        from nuri.api.routes import actions
        for cache in (actions._actions_cache, actions._opportunities_cache, actions._market_context_cache):
            cache["data"] = None
            cache["timestamp"] = 0

    def test_actions_cache_hit(self):
        import time

        from nuri.api.routes import actions
        self._clear_caches()
        fake_result = {"urgent": [{"ticker": "CACHED"}], "check": [], "hold": [], "generated_at": "test"}
        actions._actions_cache["data"] = fake_result
        actions._actions_cache["timestamp"] = time.time()
        result = actions.get_actions()
        assert result == fake_result

    def test_opportunities_cache_hit(self):
        import time

        from nuri.api.routes import actions
        self._clear_caches()
        fake_result = {"opportunities": [{"ticker": "CACHED"}], "generated_at": "test"}
        actions._opportunities_cache["data"] = fake_result
        actions._opportunities_cache["timestamp"] = time.time()
        result = actions.get_opportunities()
        assert result == fake_result

    def test_market_context_cache_hit(self):
        import time

        from nuri.api.routes import actions
        self._clear_caches()
        fake_result = {"macro_events": [], "system_health": {"cached": True}, "generated_at": "test"}
        actions._market_context_cache["data"] = fake_result
        actions._market_context_cache["timestamp"] = time.time()
        result = actions.get_market_context()
        assert result == fake_result

    def test_stale_cache_recomputes(self):
        import time

        from nuri.api.routes import actions
        self._clear_caches()
        actions._actions_cache["data"] = {"stale": True}
        actions._actions_cache["timestamp"] = time.time() - 600  # 10분 전 (TTL 5분 초과)
        with patch("nuri.api.routes.actions._build_actions", return_value={"urgent": [], "check": [], "hold": [], "generated_at": "fresh"}):
            result = actions.get_actions()
            assert "stale" not in result


class TestEndpointExceptionFallbacks:
    def _clear_caches(self):
        """캐시 오염 방지 — 이전 테스트의 캐시가 남아있으면 exception 경로 안 탐."""
        from nuri.api.routes import actions
        for cache in (actions._actions_cache, actions._opportunities_cache, actions._market_context_cache):
            cache["data"] = None
            cache["timestamp"] = 0

    def test_actions_exception_returns_empty(self):
        self._clear_caches()
        with patch("nuri.api.routes.actions._build_actions", side_effect=RuntimeError("boom")):
            from nuri.api.routes.actions import get_actions
            result = get_actions()
            # PR A: 4-bucket shape including portfolio — Frontend page.tsx fallback 과 일치
            assert result == {"urgent": [], "check": [], "hold": [], "portfolio": []}

    def test_opportunities_exception_returns_empty(self):
        self._clear_caches()
        with patch("nuri.api.routes.actions._build_opportunities", side_effect=RuntimeError("boom")):
            from nuri.api.routes.actions import get_opportunities
            result = get_opportunities()
            assert result == {"opportunities": []}

    def test_market_context_exception_returns_empty(self):
        self._clear_caches()
        with patch("nuri.api.routes.actions._get_macro_events", side_effect=RuntimeError("boom")):
            from nuri.api.routes.actions import get_market_context
            result = get_market_context()
            assert result["macro_events"] == []
            assert result["system_health"] == {}
            assert "generated_at" in result


class TestGetRecommendationsEdge:
    @patch("nuri.api.routes.actions.query")
    def test_malformed_signals_json(self, mock_query):
        """signals가 유효하지 않은 JSON이면 agreement=None."""
        mock_query.return_value = [
            {"ticker": "BAD", "action": "BUY", "confidence": 0.6, "signals": "not-json{{{"}
        ]
        from nuri.api.routes.actions import _get_recommendations
        result = _get_recommendations()
        assert result[0]["agreement"] is None

    @patch("nuri.api.routes.actions.query")
    def test_exposes_alpha_and_portfolio_axes(self, mock_query):
        """PR A: _get_recommendations 가 새 alpha_action/portfolio_action 컬럼을
        노출 — Frontend UI 에서 바둑돌 형태로 표시할 수 있게."""
        mock_query.return_value = [
            {
                "ticker": "BAC", "action": "HOLD", "confidence": 0.62,
                "signals": json.dumps({"agreement_rate": 0.9}),
                "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None, "portfolio_action": "REBALANCE",
            }
        ]
        from nuri.api.routes.actions import _get_recommendations
        result = _get_recommendations()
        assert result[0]["alpha_action"] is None
        assert result[0]["portfolio_action"] == "REBALANCE"


class TestPRABucketRouting:
    """PR A regression — concentration 은 portfolio bucket, stop-loss 는 urgent.
    사용자 -₩7M 손실 재발 차단 경로를 API 레벨에서 lock-in.
    """

    def _invoke_build_actions(self, *, recommendations, siege_violations, portfolio_map, targets_status=None):
        """_build_actions 를 mock 된 helper 로 실행."""
        from nuri.api.routes import actions as actions_mod

        # catalyst 항상 False → non-emergency SELL 이 자동 hold bucket 으로 강등 (A-4)
        with (
            patch.object(actions_mod, "_get_recommendations", return_value=recommendations),
            patch.object(actions_mod, "_get_siege_violations", return_value=siege_violations),
            patch.object(actions_mod, "_get_targets_status", return_value=targets_status or {}),
            patch.object(actions_mod, "_get_portfolio_map", return_value=portfolio_map),
            patch.object(actions_mod, "_get_short_interest", return_value=None),
            patch.object(actions_mod, "has_recent_catalyst", return_value=(False, "no data")),
            patch.object(actions_mod, "check_divergence", return_value=(False, 0.0, None)),
        ):
            return actions_mod._build_actions()

    def test_concentration_violation_goes_to_portfolio_bucket(self):
        """SIEGE position_limit 위반 ticker 는 portfolio bucket — urgent 아님."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "BAC", "action": "HOLD", "confidence": 62,
                "agreement": 90, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None, "portfolio_action": "REBALANCE",
            }],
            siege_violations=[{
                "ticker": "BAC", "detail": "SIEGE: 종목 비중 한도 — 위반: BAC(19.8%>15%)",
                "condition_id": "position_limit",
            }],
            portfolio_map={"BAC": {
                "current_price": 40.0, "avg_price": 40.0, "quantity": 100,
                "pnl_pct": 0.0, "position_pct": 19.8, "account": "Main",
            }},
        )
        # PR A 핵심 assertion — "매도" urgent 가 아닌 portfolio bucket
        assert len(result["urgent"]) == 0
        assert len(result["portfolio"]) == 1
        assert result["portfolio"][0]["ticker"] == "BAC"
        assert result["portfolio"][0]["priority"] == "portfolio"
        # reason 에 "리밸런스" 언어 (매도 압박 제거)
        reasons_text = " ".join(result["portfolio"][0]["reasons"])
        assert "리밸런스" in reasons_text

    def test_stop_loss_breach_still_urgent(self):
        """Stop-loss breach 는 alpha-driven → urgent bucket (기존 behavior 유지)."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "CRASH", "action": "SELL", "confidence": 85,
                "agreement": 70, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": "FLAT", "portfolio_action": None,
            }],
            siege_violations=[],
            portfolio_map={"CRASH": {
                "current_price": 70.0, "avg_price": 100.0, "quantity": 100,
                "pnl_pct": -30.0, "position_pct": 5.0, "account": "Main",
            }},
        )
        assert len(result["portfolio"]) == 0
        assert len(result["urgent"]) == 1
        assert result["urgent"][0]["ticker"] == "CRASH"

    def test_hybrid_stop_loss_dominates_hybrid_concentration(self):
        """Stop-loss + concentration 동시 → urgent bucket (stop-loss dominant).
        Codex Plan Q5-B: axes parallel, legacy action=SELL 은 stop-loss 가 결정.
        Action bucket 도 동일 — stop-loss 는 § 2.2 기계적 실행이므로 urgent.
        portfolio_action=REBALANCE 는 scoring_detail 에 병렬 surface (사용자가 매도
        대신 리밸런스 선택지 볼 수 있게)."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "HYBRID", "action": "SELL", "confidence": 85,
                "agreement": 70, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": "FLAT", "portfolio_action": "REBALANCE",
            }],
            siege_violations=[{
                "ticker": "HYBRID", "detail": "SIEGE: 종목 비중 한도 — 위반: HYBRID(22%>15%)",
                "condition_id": "position_limit",
            }],
            portfolio_map={"HYBRID": {
                "current_price": 70.0, "avg_price": 100.0, "quantity": 200,
                "pnl_pct": -30.0, "position_pct": 22.0, "account": "Main",
            }},
        )
        # stop-loss (alpha-driven, 기계적) 이 dominant → urgent
        assert len(result["urgent"]) == 1
        assert result["urgent"][0]["ticker"] == "HYBRID"
        # concentration 는 별도 bucket 추가 안 함 (urgent 로 이미 routed, continue)
        assert len(result["portfolio"]) == 0

    def test_portfolio_bucket_exposed_in_response_shape(self):
        """빈 portfolio 도 response 에 key 존재해야 함 (Frontend fallback 보장)."""
        result = self._invoke_build_actions(
            recommendations=[], siege_violations=[], portfolio_map={},
        )
        assert "portfolio" in result
        assert result["portfolio"] == []


class TestGetSiegeViolationsEdge:
    def test_position_limit_no_regex_match(self):
        """position_limit detail에 ticker%(>)% 형식이 없으면 빈 ticker로 등록."""
        from dataclasses import dataclass

        @dataclass
        class FakeCond:
            id: str = "position_limit"
            description: str = "종목 비중 한도"
            passed: bool = False
            detail: str = "데이터 없음"
            severity: str = "error"

        @dataclass
        class FakeCert:
            conditions: list[FakeCond] | None = None
            def __post_init__(self):
                self.conditions = self.conditions or [FakeCond()]

        with patch("nuri.trading.engine.certification.certify", return_value=FakeCert()):
            from nuri.api.routes.actions import _get_siege_violations
            result = _get_siege_violations()
            assert len(result) == 1
            assert result[0]["ticker"] == ""

    def test_non_position_limit_error(self):
        """position_limit 이외의 error condition도 등록."""
        from dataclasses import dataclass

        @dataclass
        class FakeCond:
            id: str = "leverage_ban"
            description: str = "레버리지 ETF"
            passed: bool = False
            detail: str = "TQQQ 보유"
            severity: str = "error"

        @dataclass
        class FakeCert:
            conditions: list[FakeCond] | None = None
            def __post_init__(self):
                self.conditions = self.conditions or [FakeCond()]

        with patch("nuri.trading.engine.certification.certify", return_value=FakeCert()):
            from nuri.api.routes.actions import _get_siege_violations
            result = _get_siege_violations()
            assert len(result) == 1
            assert "레버리지" in result[0]["detail"]


# ═══════════════════════════════════════════════════
# Unit tests — _compute_verdict
# ═══════════════════════════════════════════════════


class TestComputeVerdict:
    def setup_method(self):
        from nuri.api.routes.actions import _compute_verdict
        self._verdict = _compute_verdict

    def test_extreme_drop_danger(self):
        _, level = self._verdict(["good"], ["bad"], {"score": 10, "rsi": 15, "change_5d": -25})
        assert level == "danger"

    def test_no_pros_with_cons_danger(self):
        text, level = self._verdict([], ["risky"], {"score": 20, "rsi": 50, "change_5d": -5})
        assert level == "danger"
        assert "근거 부족" in text

    def test_strong_positive(self):
        text, level = self._verdict(["a", "b"], [], {"score": 50, "rsi": 50, "change_5d": 5})
        assert level == "positive"
        assert "매수 고려" in text

    def test_mixed_signals_neutral(self):
        _, level = self._verdict(["good"], ["bad"], {"score": 30, "rsi": 50, "change_5d": 5})
        assert level == "neutral"

    def test_overbought_neutral(self):
        text, level = self._verdict(["one"], [], {"score": 20, "rsi": 50, "change_5d": 18})
        assert level == "neutral"
        assert "눌림목" in text

    def test_empty_muted(self):
        _, level = self._verdict([], [], {"score": 5, "rsi": 50, "change_5d": 0})
        assert level == "muted"

    def test_positive_needs_high_score(self):
        _, level = self._verdict(["a", "b"], [], {"score": 30, "rsi": 50, "change_5d": 5})
        assert level != "positive"  # score 30 < 40 threshold


# ═══════════════════════════════════════════════════
# Unit tests — SIEGE violation regex parsing
# ═══════════════════════════════════════════════════


class TestSiegeViolationParsing:
    def test_single_violation(self):
        import re
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", "위반: TSLA(15.4%>15%)")
        assert matches == ["TSLA"]

    def test_multiple_violations(self):
        import re
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", "위반: TSLA(15.4%>15%), NBIS(16.0%>15%)")
        assert matches == ["TSLA", "NBIS"]

    def test_no_match(self):
        import re
        matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", "모든 종목 15% 이하")
        assert matches == []

    def test_handles_certify_exception(self):
        with patch("nuri.trading.engine.certification.certify", side_effect=Exception("DB")):
            from nuri.api.routes.actions import _get_siege_violations
            assert _get_siege_violations() == []


# ═══════════════════════════════════════════════════
# Unit tests — helper functions (mock-based)
# ═══════════════════════════════════════════════════


class TestGetTargetsStatus:
    @patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets")
    def test_returns_target_dict(self, mock_fn):
        mock_fn.return_value = [{"ticker": "AAPL", "stop_loss": 140, "target_1": 180, "target_2": 210, "trailing_stop_pct": 15, "analyst_target": 200}]
        from nuri.api.routes.actions import _get_targets_status
        result = _get_targets_status()
        assert result["AAPL"]["stop_loss"] == 140

    @patch("nuri.trading.recommend.price_targets.calculate_portfolio_targets", side_effect=Exception)
    def test_handles_exception(self, _):
        from nuri.api.routes.actions import _get_targets_status
        assert _get_targets_status() == {}


class TestGetImprovingSignals:
    @patch("nuri.trading.engine.memory.detect_drift")
    def test_returns_improving_set(self, mock_fn):
        mock_fn.return_value = [
            SimpleNamespace(signal_id="rsi_oversold", status="improving"),
            SimpleNamespace(signal_id="bb_bounce", status="critical"),
        ]
        from nuri.api.routes.actions import _get_improving_signals
        result = _get_improving_signals()
        assert "rsi_oversold" in result
        assert "bb_bounce" not in result

    @patch("nuri.trading.engine.memory.detect_drift", side_effect=Exception)
    def test_handles_exception(self, _):
        from nuri.api.routes.actions import _get_improving_signals
        assert _get_improving_signals() == set()


class TestGetRecentScanResults:
    def setup_method(self):
        """각 test 전 scan cache 초기화 — test 간 상호 오염 방지."""
        import nuri.api.routes.actions as mod
        mod._scan_results_cache["data"] = None
        mod._scan_results_cache["timestamp"] = 0.0

    @patch("nuri.trading.swing.scanner.scan_market")
    def test_returns_scan_dicts(self, mock_fn):
        mock_fn.return_value = [SimpleNamespace(ticker="MRVL", price=128, change_1d=7, change_5d=20, volume_ratio=1.7, rsi=83, signal="breakout", score=69)]
        from nuri.api.routes.actions import _get_recent_scan_results
        result = _get_recent_scan_results()
        assert result[0]["ticker"] == "MRVL"

    @patch("nuri.trading.swing.scanner.scan_market", side_effect=Exception)
    def test_handles_exception(self, _):
        from nuri.api.routes.actions import _get_recent_scan_results
        assert _get_recent_scan_results() == []


class TestGetSystemHealth:
    @patch("nuri.api.routes.actions.query", return_value=[])
    def test_returns_all_sections(self, _):
        @dataclass
        class FakeCert:
            score: float = 54.0
            certified: bool = False
            passed: int = 6
            failed: int = 1
            warnings: int = 4
            total_conditions: int = 11
            conditions: list | None = None

            def __post_init__(self):
                self.conditions = self.conditions or []

        with patch("nuri.trading.engine.certification.certify", return_value=FakeCert()), \
             patch("nuri.quant.regime.classifier.classify_regime", return_value=SimpleNamespace(regime="recovery", trend="sideways", volatility="high", confidence=0.75)), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", return_value=SimpleNamespace(total_score=56, interpretation="Neutral")), \
             patch("nuri.core.freshness.check_all_freshness", return_value=[{"status": "PASS"}, {"status": "WARN"}, {"status": "FAIL"}]):
            from nuri.api.routes.actions import _get_system_health
            result = _get_system_health()
            assert result["siege"]["score"] == 54
            assert result["regime"]["regime"] == "recovery"
            assert result["macro"]["score"] == 56
            assert result["freshness"]["fail_count"] == 1

    @patch("nuri.api.routes.actions.query", return_value=[])
    def test_handles_all_exceptions(self, _):
        with patch("nuri.trading.engine.certification.certify", side_effect=Exception), \
             patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception), \
             patch("nuri.core.freshness.check_all_freshness", side_effect=Exception):
            from nuri.api.routes.actions import _get_system_health
            result = _get_system_health()
            assert result["siege"] == {"score": 0, "certified": False}


# ═══════════════════════════════════════════════════
# Unit tests — _build_actions business logic
# ═══════════════════════════════════════════════════


class TestBuildActionsLogic:
    def _run(self, recs, siege=None, targets=None, portfolio=None, short=None, catalyst=None, divergence=None):
        # A-4: `has_recent_catalyst` 를 default mock — CI fresh DB 는 news/macro_events
        # 테이블 migration 전 상태 가능성 (Lesson #7). 테스트별 override 는 `catalyst`
        # 인자 또는 with 스코프 내부에서 재패치.
        # A-5: `check_divergence` 도 default mock — fetch 가 시장외 시 None 반환하도록
        # 가정. 테스트별 override 는 `divergence=(bool, pct, live_price)`.
        cat_default = catalyst if catalyst is not None else (False, "no catalyst (test default)")
        div_default = divergence if divergence is not None else (False, 0.0, None)
        with patch("nuri.api.routes.actions._get_recommendations", return_value=recs), \
             patch("nuri.api.routes.actions._get_siege_violations", return_value=siege or []), \
             patch("nuri.api.routes.actions._get_targets_status", return_value=targets or {}), \
             patch("nuri.api.routes.actions._get_portfolio_map", return_value=portfolio or {}), \
             patch("nuri.api.routes.actions._get_short_interest", return_value=short), \
             patch("nuri.api.routes.actions.has_recent_catalyst", return_value=cat_default), \
             patch("nuri.api.routes.actions.check_divergence", return_value=div_default):
            from nuri.api.routes.actions import _build_actions
            return _build_actions()

    def _pf(
        self,
        price: float = 105,
        avg: float = 100,
        pnl: float = 5,
        pos: float = 3,
    ):
        return {"current_price": price, "avg_price": avg, "quantity": 10, "pnl_pct": pnl, "position_pct": pos, "account": "Main"}

    def test_siege_violation_goes_to_portfolio_bucket(self):
        """PR A (2026-04-21): SIEGE position_limit 위반은 "매도 강제" urgent 가
        아닌 "리밸런스 권고" portfolio bucket. 이전 동작 (urgent) → 사용자 -₩7M
        손실 재발 경로. Regression lock: 다시 urgent 로 돌아가면 이 테스트 fail.

        참고: 이 시나리오는 action=SELL + no stop-loss breach (+1.6%) → SELL check
        경로에서 catalyst 없음으로 hold 강등 후 portfolio 체크에서 재분류. 코드는
        `continue` 로 bucket 간 이동 — 마지막에 assign 된 priority 가 최종.
        현 구조에서는 SELL + no-breach → hold bucket 이고, SIEGE 체크는 SELL
        check 에서 continue 로 먼저 끝남.
        → 따라서 SIEGE violation 단독 surfacing 은 action=HOLD 일 때만 성립."""
        result = self._run(
            [{"ticker": "TSLA", "action": "HOLD", "confidence": 46, "agreement": 20}],
            siege=[{"ticker": "TSLA", "detail": "SIEGE: 한도 — TSLA(15.4%>15%)", "condition_id": "position_limit"}],
            portfolio={"TSLA": self._pf(349, 343, 1.6, 15.4)},
        )
        # urgent 아님 — PR A 핵심 assertion
        assert len(result["urgent"]) == 0
        assert len(result["portfolio"]) == 1
        assert result["portfolio"][0]["ticker"] == "TSLA"
        assert "리밸런스" in " ".join(result["portfolio"][0]["reasons"])

    def test_sell_with_loss_urgent(self):
        result = self._run(
            [{"ticker": "BAD", "action": "SELL", "confidence": 70, "agreement": 50}],
            portfolio={"BAD": self._pf(90, 100, -10, 5)},
        )
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]

    def test_a3_long_term_account_minus_10_not_urgent(self):
        """A-3: long_term 계좌(-20) 의 -10% 손실은 urgent 아님.
        이전 동작(-7 하드코딩): urgent 로 분류 (pension/long_term 계좌에 잘못된 알림).
        Regression lock: threshold 가 하드코딩으로 돌아가면 이 테스트 fail."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-20):
            result = self._run(
                [{"ticker": "LTMX", "action": "SELL", "confidence": 70, "agreement": 50}],
                portfolio={"LTMX": self._pf(90, 100, -10, 5)},
                catalyst=(True, "news (1 item(s) in 14d)"),  # 원래 check 경로 유지
            )
        # -10% > -20% (덜 나쁨) → urgent 가 아닌 check (catalyst 있으니 hold 가 아닌 check)
        assert len(result["urgent"]) == 0
        assert len(result["check"]) == 1
        assert result["check"][0]["ticker"] == "LTMX"

    def test_a3_long_term_account_minus_22_urgent(self):
        """A-3: long_term(-20) 계좌 -22% 는 실제 breach → urgent."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-20):
            result = self._run(
                [{"ticker": "LTMX", "action": "SELL", "confidence": 80, "agreement": 60}],
                portfolio={"LTMX": self._pf(78, 100, -22, 5)},
            )
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]
        assert "-20%" in result["urgent"][0]["reasons"][1]

    def test_a3_core_account_minus_10_still_urgent(self):
        """A-3: core(-7) 계좌 -10% 는 기존 동작 유지 (regression 방지)."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "BAD", "action": "SELL", "confidence": 70, "agreement": 50}],
                portfolio={"BAD": self._pf(90, 100, -10, 5)},
            )
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]

    def test_a3_boundary_equality_not_urgent(self):
        """A-3 operator consistency: pnl == threshold 는 urgent 아님 (< 통일,
        certification.py:308 과 일치). A-4 이후 catalyst 없으면 hold 로 강등."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "EDGE", "action": "SELL", "confidence": 65, "agreement": 40}],
                portfolio={"EDGE": self._pf(93, 100, -7, 5)},
                catalyst=(False, "no catalyst"),
            )
        # -7 < -7 은 False → non-urgent; A-4: no-catalyst → hold bucket
        assert len(result["urgent"]) == 0
        assert len(result["hold"]) == 1

    def test_a4_sell_no_breach_no_catalyst_becomes_hold(self):
        """A-4: non-emergency SELL (pnl > stop-loss threshold) + catalyst 없음 → hold.
        이전 동작: check bucket 에 들어갔음. Regression lock: catalyst gate 제거 시 fail."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "QUIET", "action": "SELL", "confidence": 50, "agreement": 20}],
                portfolio={"QUIET": self._pf(102, 100, 2, 5)},  # +2% (no breach)
                catalyst=(False, "no ticker news + no significant macro event"),
            )
        assert len(result["urgent"]) == 0
        assert len(result["check"]) == 0
        assert len(result["hold"]) == 1
        assert "SELL 근거 없음" in result["hold"][0]["reasons"][1]

    def test_a4_sell_no_breach_with_catalyst_goes_to_check(self):
        """A-4: SELL + catalyst 있으면 check bucket (기존 동작)."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "NEWSY", "action": "SELL", "confidence": 65, "agreement": 40}],
                portfolio={"NEWSY": self._pf(98, 100, -2, 5)},  # -2% (no breach)
                catalyst=(True, "news (2 item(s) in 14d)"),
            )
        assert len(result["urgent"]) == 0
        assert len(result["check"]) == 1
        assert "catalyst: news" in result["check"][0]["reasons"][1]

    def test_a5_divergence_above_threshold_adds_reason(self):
        """A-5: live price 가 stored 대비 >3% diverge 하면 reason 에 경고 추가.
        NFLX 사례 방지 (stored $97.23 vs live $107.79)."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "NFLX", "action": "SELL", "confidence": 75, "agreement": 60}],
                portfolio={"NFLX": self._pf(97.23, 100, -2.77, 5)},
                catalyst=(True, "news (2 item(s) in 14d)"),
                divergence=(True, 10.87, 107.79),
            )
        item = (result["urgent"] + result["check"] + result["hold"])[0]
        assert item["live_price"] == 107.79
        assert item["divergence_pct"] == 10.87
        assert item["divergence_flag"] is True
        assert any("divergence" in r for r in item["reasons"])
        assert any("107.79" in r for r in item["reasons"])

    def test_a5_divergence_below_threshold_no_reason(self):
        """A-5: divergence < 3% → flag False, 경고 추가 안 함."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "QUIET", "action": "BUY", "confidence": 60, "agreement": 30}],
                portfolio={"QUIET": self._pf(100, 100, 0, 5)},
                divergence=(False, 1.2, 101.2),
            )
        item = result["hold"][0]
        assert item["divergence_flag"] is False
        assert item["live_price"] == 101.2
        assert not any("divergence" in r for r in item["reasons"])

    def test_a5_market_closed_sets_none_fields(self):
        """A-5: 시장외 fetch (live_price=None) → divergence fields 가 None/False,
        기존 reason 에 경고 추가 안 함."""
        with patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7):
            result = self._run(
                [{"ticker": "ZZZ", "action": "BUY", "confidence": 60, "agreement": 30}],
                portfolio={"ZZZ": self._pf(100, 100, 0, 5)},
                divergence=(False, 0.0, None),  # 시장외 fallback
            )
        item = result["hold"][0]
        assert item["live_price"] is None
        assert item["divergence_pct"] is None
        assert item["divergence_flag"] is False

    def test_a4_stop_loss_breach_bypasses_catalyst_check(self):
        """A-4 exemption: stop-loss breach 는 catalyst 무관하게 urgent (§2.2 mechanical).
        has_recent_catalyst 가 호출조차 되지 않아야 함."""
        # 이 테스트는 _run 기본 mock 을 피하고 직접 MagicMock 으로 assert_not_called 체크
        from unittest.mock import MagicMock
        mock_cat = MagicMock(return_value=(False, "no catalyst"))
        with patch("nuri.api.routes.actions._get_recommendations", return_value=[{"ticker": "DUMP", "action": "SELL", "confidence": 85, "agreement": 70}]), \
             patch("nuri.api.routes.actions._get_siege_violations", return_value=[]), \
             patch("nuri.api.routes.actions._get_targets_status", return_value={}), \
             patch("nuri.api.routes.actions._get_portfolio_map", return_value={"DUMP": self._pf(90, 100, -10, 5)}), \
             patch("nuri.api.routes.actions._get_short_interest", return_value=None), \
             patch("nuri.api.routes.actions.get_stop_loss_for_account", return_value=-7), \
             patch("nuri.api.routes.actions.has_recent_catalyst", mock_cat), \
             patch("nuri.api.routes.actions.check_divergence", return_value=(False, 0.0, None)):
            from nuri.api.routes.actions import _build_actions
            result = _build_actions()
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]
        # catalyst 함수 호출 자체가 없어야 함 (breach path 가 먼저 continue)
        mock_cat.assert_not_called()

    def test_sell_without_loss_check(self):
        result = self._run(
            [{"ticker": "MEH", "action": "SELL", "confidence": 50, "agreement": 20}],
            portfolio={"MEH": self._pf(105, 100, 5, 3)},
            catalyst=(True, "news (1 item(s) in 14d)"),  # catalyst 있어야 check (A-4 gate)
        )
        assert len(result["check"]) == 1

    def test_target_1_hit_check(self):
        result = self._run(
            [{"ticker": "WIN", "action": "BUY", "confidence": 70, "agreement": 40}],
            targets={"WIN": {"stop_loss": 90, "target_1": 120, "target_2": 140}},
            portfolio={"WIN": self._pf(125, 100, 25, 5)},
        )
        assert len(result["check"]) == 1
        assert "1차 익절" in result["check"][0]["reasons"][0]

    def test_target_2_hit_check(self):
        result = self._run(
            [{"ticker": "BIG", "action": "BUY", "confidence": 80, "agreement": 60}],
            targets={"BIG": {"stop_loss": 90, "target_1": 120, "target_2": 140}},
            portfolio={"BIG": self._pf(145, 100, 45, 8)},
        )
        assert "2차 익절" in result["check"][0]["reasons"][0]

    def test_high_short_interest_check(self):
        result = self._run(
            [{"ticker": "SQZ", "action": "BUY", "confidence": 60, "agreement": 40}],
            portfolio={"SQZ": self._pf(110, 100, 10, 3)},
            short=19.6,
        )
        assert "공매도" in result["check"][0]["reasons"][0]

    def test_normal_buy_hold(self):
        result = self._run(
            [{"ticker": "OK", "action": "BUY", "confidence": 60, "agreement": 30}],
            portfolio={"OK": self._pf()},
        )
        assert len(result["hold"]) == 1
        assert "BUY (conf 60)" in result["hold"][0]["reasons"][0]

    def test_pension_filtered_out(self):
        result = self._run(
            [{"ticker": "381170.KS", "action": "BUY", "confidence": 65, "agreement": 20}],
            portfolio={"381170.KS": {"current_price": 29610, "avg_price": 21450, "quantity": 1, "pnl_pct": 38, "position_pct": 12, "account": "연금"}},
        )
        assert len(result["urgent"]) == 0
        assert len(result["check"]) == 0
        assert len(result["hold"]) == 0

    def test_irp_filtered_out(self):
        result = self._run(
            [{"ticker": "448300.KS", "action": "BUY", "confidence": 72, "agreement": 20}],
            portfolio={"448300.KS": {"current_price": 19535, "avg_price": 17450, "quantity": 1, "pnl_pct": 12, "position_pct": 10, "account": "IRP"}},
        )
        assert len(result["hold"]) == 0

    def test_duplicate_ticker_deduped(self):
        result = self._run(
            [
                {"ticker": "NVDA", "action": "BUY", "confidence": 70, "agreement": 40},
                {"ticker": "NVDA", "action": "BUY", "confidence": 65, "agreement": 30},
            ],
            portfolio={"NVDA": self._pf(189, 132, 43, 8)},
        )
        # 같은 ticker가 2번 나와도 1번만 출력
        all_items = result["urgent"] + result["check"] + result["hold"]
        nvda = [i for i in all_items if i["ticker"] == "NVDA"]
        assert len(nvda) == 1

    def test_includes_ticker_name_for_kr(self):
        with patch("nuri.core.ticker_names.get_ticker_name", return_value="Samsung Electronics"):
            result = self._run(
                [{"ticker": "005930.KS", "action": "BUY", "confidence": 62, "agreement": 20}],
                portfolio={"005930.KS": {"current_price": 200750, "avg_price": 59700, "quantity": 1, "pnl_pct": 236, "position_pct": 0.4, "account": "Main"}},
            )
        all_items = result["urgent"] + result["check"] + result["hold"]
        assert len(all_items) == 1
        assert "name" in all_items[0]


# ═══════════════════════════════════════════════════
# Unit tests — _get_portfolio_map multi-account aggregation (A-6)
# ═══════════════════════════════════════════════════


class TestGetPortfolioMapAggregation:
    """A-6 codex A-4 Round 1-3 재발 flag lock — 동일 ticker 의 여러 계좌 보유 시
    worst-pnl row 를 keep 해 stop-loss masking 방지 + position_pct 합산."""

    def _run(self, portfolio_rows, rate=1400):
        from unittest.mock import MagicMock

        from nuri.api.routes.actions import _get_portfolio_map

        def _query(sql, params=None, **kw):
            s = " ".join(sql.split())
            if "SELECT p.account" in s:
                return portfolio_rows
            if "usd_krw" in s.lower() or "indicator" in s:
                return [{"value": rate}]
            return []

        with patch("nuri.api.routes.actions.query", side_effect=_query), \
             patch("nuri.api.routes.dashboard._get_account_labels", return_value={}):
            return _get_portfolio_map()

    def test_single_account_single_row_unchanged(self):
        rows = [{"account": "Main", "ticker": "AAPL", "quantity": 10, "avg_price": 100.0,
                 "currency": "USD", "current_price": 110.0}]
        result = self._run(rows)
        assert result["AAPL"]["pnl_pct"] == 10.0
        assert result["AAPL"]["account"] == "Main"

    def test_multi_account_aggregates_position_pct(self):
        """Main + Toss 양쪽 동일 ticker → position_pct 는 두 계좌 합산."""
        rows = [
            {"account": "Main", "ticker": "TSLA", "quantity": 10, "avg_price": 100.0,
             "currency": "USD", "current_price": 110.0},  # +10%
            {"account": "Toss", "ticker": "TSLA", "quantity": 10, "avg_price": 100.0,
             "currency": "USD", "current_price": 110.0},  # +10%
        ]
        result = self._run(rows)
        # 2 rows each $1100 = $2200 total; sum = 100% of portfolio
        assert result["TSLA"]["position_pct"] == pytest.approx(100.0)

    def test_multi_account_worst_pnl_wins(self):
        """codex A-4 lock: Main 계좌에서 -25% breach, Toss 계좌는 0% → worst(-25%) 가
        pnl_pct/account 를 차지해 downstream stop-loss 가 breach 감지."""
        rows = [
            {"account": "Toss", "ticker": "SHARED", "quantity": 20, "avg_price": 100.0,
             "currency": "USD", "current_price": 100.0},  # 0% pnl (non-breach)
            {"account": "Main", "ticker": "SHARED", "quantity": 10, "avg_price": 100.0,
             "currency": "USD", "current_price": 75.0},   # -25% breach
        ]
        result = self._run(rows)
        assert result["SHARED"]["pnl_pct"] == pytest.approx(-25.0)
        assert result["SHARED"]["account"] == "Main"
        assert result["SHARED"]["current_price"] == 75.0

    def test_multi_account_order_independence(self):
        """SQLite row 순서에 의존 안 함 — worst-pnl 이 첫 row 든 마지막 row 든 동일 결과."""
        worst_first = [
            {"account": "Main", "ticker": "X", "quantity": 10, "avg_price": 100, "currency": "USD", "current_price": 70},
            {"account": "Toss", "ticker": "X", "quantity": 10, "avg_price": 100, "currency": "USD", "current_price": 100},
        ]
        worst_last = list(reversed(worst_first))
        r1 = self._run(worst_first)
        r2 = self._run(worst_last)
        assert r1["X"]["pnl_pct"] == r2["X"]["pnl_pct"]
        assert r1["X"]["account"] == r2["X"]["account"] == "Main"

    def test_taxable_plus_pension_keeps_taxable_account(self):
        """A-6 codex Round 1 P2 lock: taxable + 연금 공동 보유 ticker 에서 pension
        slice 가 worst-pnl 이어도 account/threshold 는 taxable 유지 →
        _build_actions 의 pension_tickers skip 이 taxable slice 를 삼키지 않음."""
        rows = [
            {"account": "연금", "ticker": "X", "quantity": 20, "avg_price": 100, "currency": "USD", "current_price": 75},  # -25% pension
            {"account": "Main", "ticker": "X", "quantity": 10, "avg_price": 100, "currency": "USD", "current_price": 95},  # -5% taxable
        ]
        result = self._run(rows)
        assert result["X"]["account"] == "Main"
        assert result["X"]["pnl_pct"] == pytest.approx(-5.0)  # taxable side wins

    def test_pension_only_ticker_retains_pension_account(self):
        """모든 row 가 pension 이면 account 는 pension 으로 유지 — downstream
        pension skip 이 정상 작동."""
        rows = [
            {"account": "연금", "ticker": "Y", "quantity": 10, "avg_price": 100, "currency": "USD", "current_price": 90},
            {"account": "IRP", "ticker": "Y", "quantity": 5, "avg_price": 100, "currency": "USD", "current_price": 80},
        ]
        result = self._run(rows)
        assert result["Y"]["account"] in ("연금", "IRP")
        # 위에서 worst 는 IRP (-20% < -10%)
        assert result["Y"]["pnl_pct"] == pytest.approx(-20.0)
        assert result["Y"]["account"] == "IRP"


# ═══════════════════════════════════════════════════
# Unit tests — _build_opportunities business logic
# ═══════════════════════════════════════════════════


class TestBuildOpportunitiesLogic:
    def _scan(self, ticker="X", signal="momentum", score=30, change_5d=5, rsi=50, vol=1.0):
        return {"ticker": ticker, "price": 100, "change_1d": 1, "change_5d": change_5d, "volume_ratio": vol, "rsi": rsi, "signal": signal, "score": score}

    def _run(self, scans, portfolio=None, improving=None):
        with patch("nuri.api.routes.actions._get_portfolio_map", return_value=portfolio or {}), \
             patch("nuri.api.routes.actions._get_recent_scan_results", return_value=scans), \
             patch("nuri.api.routes.actions._get_improving_signals", return_value=improving or set()):
            from nuri.api.routes.actions import _build_opportunities
            return _build_opportunities()

    def test_excludes_portfolio(self):
        result = self._run([self._scan("AAPL"), self._scan("MRVL")], portfolio={"AAPL": {}})
        assert [o["ticker"] for o in result] == ["MRVL"]

    def test_breakout_pro(self):
        result = self._run([self._scan("BRK", signal="breakout", score=55)])
        assert any("breakout" in p for p in result[0]["pros"])

    def test_momentum_pro(self):
        result = self._run([self._scan("MOM", signal="momentum", change_5d=15)])
        assert any("모멘텀" in p for p in result[0]["pros"])

    def test_oversold_with_improving(self):
        result = self._run([self._scan("DIP", rsi=28, vol=2.5)], improving={"rsi_oversold"})
        assert any("승률 상승" in p for p in result[0]["pros"])

    def test_oversold_without_improving(self):
        result = self._run([self._scan("DIP2", rsi=30, vol=1.0)], improving=set())
        assert any("과매도" in p for p in result[0]["pros"])
        assert not any("승률 상승" in p for p in result[0]["pros"])

    def test_volume_spike_pro(self):
        result = self._run([self._scan("VOL", vol=2.5)])
        assert any("거래량" in p for p in result[0]["pros"])

    def test_overbought_con(self):
        result = self._run([self._scan("HOT", rsi=85)])
        assert any("과매수" in c for c in result[0]["cons"])

    def test_crash_con(self):
        result = self._run([self._scan("FALL", change_5d=-18)])
        assert any("급락" in c for c in result[0]["cons"])

    def test_chase_con(self):
        result = self._run([self._scan("RUN", change_5d=25)])
        assert any("급등" in c for c in result[0]["cons"])

    def test_volume_spike_crash_con(self):
        result = self._run([self._scan("BAD", signal="volume_spike", change_5d=-12)])
        assert any("원인 확인" in c for c in result[0]["cons"])

    def test_sorted_by_score(self):
        result = self._run([self._scan("LOW", score=10), self._scan("HIGH", score=70)])
        assert result[0]["ticker"] == "HIGH"


class TestGetRecommendationsScoringDetail:
    """A-2b — /actions `_get_recommendations` 가 scoring_detail + agent_verdicts
    pass-through. Frontend (A-2c) actions page 가 10-agent breakdown 표시에 사용.
    """

    @patch("nuri.api.routes.actions.query")
    def test_passes_scoring_detail_and_agent_verdicts(self, mock_query):
        """scoring_detail + agent_verdicts JSON → response dict 파싱 포함."""
        scoring = {
            "source": "consensus",
            "schema_version": 1,
            "basis_action": "BUY",
            "final_action_source": "weighted_sum",
        }
        verdicts = [{"agent_name": "technical", "action": "BUY", "confidence": 80}]
        mock_query.return_value = [
            {
                "ticker": "TSLA",
                "action": "BUY",
                "confidence": 0.75,
                "signals": '{"agreement_rate": 0.8}',
                "scoring_detail": json.dumps(scoring),
                "agent_verdicts": json.dumps(verdicts),
            }
        ]
        from nuri.api.routes.actions import _get_recommendations
        result = _get_recommendations()
        assert len(result) == 1
        assert "scoring_detail" in result[0], (
            "A-2b regression: /actions response 에 scoring_detail 누락"
        )
        assert result[0]["scoring_detail"]["source"] == "consensus"
        assert result[0]["scoring_detail"]["basis_action"] == "BUY"
        assert result[0]["agent_verdicts"] == verdicts

    @patch("nuri.api.routes.actions.query")
    def test_handles_null_scoring_detail(self, mock_query):
        """NULL scoring_detail/agent_verdicts → None pass-through (legacy row)."""
        mock_query.return_value = [
            {
                "ticker": "OLD",
                "action": "HOLD",
                "confidence": 0.5,
                "signals": None,
                "scoring_detail": None,
                "agent_verdicts": None,
            }
        ]
        from nuri.api.routes.actions import _get_recommendations
        result = _get_recommendations()
        assert result[0]["scoring_detail"] is None
        assert result[0]["agent_verdicts"] is None

    @patch("nuri.api.routes.actions.query")
    def test_handles_malformed_json(self, mock_query):
        """malformed JSON → None graceful degrade (crash 방지)."""
        mock_query.return_value = [
            {
                "ticker": "BAD",
                "action": "BUY",
                "confidence": 0.6,
                "signals": "{}",
                "scoring_detail": "not-json{{{",
                "agent_verdicts": "also-bad",
            }
        ]
        from nuri.api.routes.actions import _get_recommendations
        result = _get_recommendations()
        assert result[0]["scoring_detail"] is None
        assert result[0]["agent_verdicts"] is None


class TestBuildActionsScoringDetail:
    """A-2b — `_build_actions` 이 `_get_recommendations` 결과의 scoring_detail /
    agent_verdicts 를 최종 item 에 포함 (codex A-2b Round 1 HIGH — drop bug 방지).

    STRATEGY §5.3.1 Gotcha-Test Pair — `_build_actions` 이 `rec.get()` 안 하면
    endpoint response 가 두 필드 누락해 A-2c UI 가 consume 불가.
    """

    def test_build_actions_exposes_scoring_detail_per_item(self):
        """Urgent/check/hold 어느 bucket 에 들어가든 item 에 scoring_detail 포함."""
        from unittest.mock import patch

        from nuri.api.routes.actions import _build_actions

        scoring = {
            "source": "consensus",
            "schema_version": 1,
            "basis_action": "BUY",
            "final_action_source": "weighted_sum",
        }
        verdicts = [{"agent_name": "technical", "action": "BUY", "confidence": 80}]
        recs = [
            {
                "ticker": "TSLA",
                "action": "BUY",
                "confidence": 70,
                "agreement": 80,
                "scoring_detail": scoring,
                "agent_verdicts": verdicts,
            }
        ]

        with patch("nuri.api.routes.actions._get_recommendations", return_value=recs), \
             patch("nuri.api.routes.actions._get_siege_violations", return_value=[]), \
             patch("nuri.api.routes.actions._get_targets_status", return_value={}), \
             patch("nuri.api.routes.actions._get_portfolio_map", return_value={
                 "TSLA": {"account": "Main", "pnl_pct": 5, "position_pct": 10}
             }), \
             patch("nuri.api.routes.actions._get_short_interest", return_value=None):
            result = _build_actions()

        # urgent/check/hold 중 어디든 TSLA item 찾기
        all_items = result.get("urgent", []) + result.get("check", []) + result.get("hold", [])
        tsla = next((i for i in all_items if i["ticker"] == "TSLA"), None)
        assert tsla is not None, "TSLA item 이 생성돼야 함"
        assert "scoring_detail" in tsla, (
            "A-2b Round 1 HIGH regression: _build_actions 이 scoring_detail 을 drop"
        )
        assert tsla["scoring_detail"] == scoring
        assert tsla["agent_verdicts"] == verdicts


class TestScanResultsCache:
    """`_get_recent_scan_results` cache + lock — dashboard 29.2s race 방지."""

    def setup_method(self):
        """각 test 전 cache 초기화."""
        import nuri.api.routes.actions as mod
        mod._scan_results_cache["data"] = None
        mod._scan_results_cache["timestamp"] = 0.0

    def test_cache_miss_calls_scan_market(self, monkeypatch):
        """cache 비어있으면 scan_market 호출 후 결과 저장."""
        from dataclasses import dataclass

        import nuri.api.routes.actions as mod

        @dataclass
        class _R:
            ticker: str = "AAPL"
            price: float = 100.0
            change_1d: float = 1.0
            change_5d: float = 2.0
            volume_ratio: float = 1.5
            rsi: float = 60
            signal: str = "breakout"
            score: float = 55

        called = {"n": 0}

        def _fake_scan(**kw):
            called["n"] += 1
            return [_R()]

        monkeypatch.setattr("nuri.trading.swing.scanner.scan_market", _fake_scan)
        out = mod._get_recent_scan_results()
        assert called["n"] == 1
        assert len(out) == 1
        assert out[0]["ticker"] == "AAPL"
        assert out[0]["signal"] == "breakout"

    def test_cache_hit_skips_scan_market(self, monkeypatch):
        """2번째 호출은 cache hit — scan_market 호출 안 됨."""
        from dataclasses import dataclass

        import nuri.api.routes.actions as mod

        @dataclass
        class _R:
            ticker: str = "AAPL"
            price: float = 100.0
            change_1d: float = 0
            change_5d: float = 0
            volume_ratio: float = 1.0
            rsi: float = 50
            signal: str = "momentum"
            score: float = 50

        called = {"n": 0}

        def _fake_scan(**kw):
            called["n"] += 1
            return [_R()]

        monkeypatch.setattr("nuri.trading.swing.scanner.scan_market", _fake_scan)
        mod._get_recent_scan_results()  # 1st — miss
        mod._get_recent_scan_results()  # 2nd — cache hit
        mod._get_recent_scan_results()  # 3rd — cache hit
        assert called["n"] == 1, "cache 가 scan 중복을 막아야 함"

    def test_cache_expires_after_ttl(self, monkeypatch):
        """TTL 초과 시 재scan."""
        from dataclasses import dataclass

        import nuri.api.routes.actions as mod

        @dataclass
        class _R:
            ticker: str = "X"
            price: float = 1
            change_1d: float = 0
            change_5d: float = 0
            volume_ratio: float = 1
            rsi: float = 50
            signal: str = "s"
            score: float = 1

        call_count = {"n": 0}
        monkeypatch.setattr(
            "nuri.trading.swing.scanner.scan_market",
            lambda **kw: (call_count.update({"n": call_count["n"] + 1}), [_R()])[1],
        )

        mod._get_recent_scan_results()
        # TTL 초과 강제 — timestamp 를 과거로 밀어냄
        mod._scan_results_cache["timestamp"] -= (mod._SCAN_CACHE_TTL + 10)
        mod._get_recent_scan_results()
        assert call_count["n"] == 2

    def test_scan_exception_returns_empty_and_does_not_cache(self, monkeypatch):
        """scan_market 예외 시 [] 반환 + cache 에 저장 안 함."""
        import nuri.api.routes.actions as mod

        def _failing(**kw):
            raise RuntimeError("simulated scan failure")

        monkeypatch.setattr("nuri.trading.swing.scanner.scan_market", _failing)
        result = mod._get_recent_scan_results()
        assert result == []
        # cache 는 None 으로 유지 (실패 결과를 저장하면 이후 retry 불가)
        assert mod._scan_results_cache["data"] is None

    def test_double_checked_lock_prevents_concurrent_scans(self, monkeypatch):
        """2 thread 가 동시에 호출해도 scan_market 은 1회만 실행."""
        import threading as _threading
        from dataclasses import dataclass

        import nuri.api.routes.actions as mod

        @dataclass
        class _R:
            ticker: str = "X"
            price: float = 1
            change_1d: float = 0
            change_5d: float = 0
            volume_ratio: float = 1
            rsi: float = 50
            signal: str = "s"
            score: float = 1

        # scan 이 1초 걸리는 것처럼 delay — 다른 thread 가 lock 대기 상태로 진입
        import time as _time
        scan_count = {"n": 0}

        def _slow_scan(**kw):
            scan_count["n"] += 1
            _time.sleep(0.2)
            return [_R()]

        monkeypatch.setattr("nuri.trading.swing.scanner.scan_market", _slow_scan)

        barrier = _threading.Barrier(3)  # 2 worker + main
        results: list = []
        errors: list = []

        def _worker():
            barrier.wait()
            try:
                results.append(mod._get_recent_scan_results())
            except Exception as e:
                errors.append(e)

        t1 = _threading.Thread(target=_worker)
        t2 = _threading.Thread(target=_worker)
        t1.start()
        t2.start()
        barrier.wait()
        t1.join(timeout=3)
        t2.join(timeout=3)

        assert errors == []
        assert scan_count["n"] == 1, f"lock 이 concurrent scan 을 막아야 함 (실제 {scan_count['n']}회)"
        assert len(results) == 2
        # 두 thread 모두 동일 cache 결과 받음
        assert results[0] == results[1]
