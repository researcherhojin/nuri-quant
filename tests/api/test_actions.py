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
        for key in ("urgent", "check", "hold"):
            assert key in data
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
            assert result == {"urgent": [], "check": [], "hold": []}

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
    def _run(self, recs, siege=None, targets=None, portfolio=None, short=None):
        with patch("nuri.api.routes.actions._get_recommendations", return_value=recs), \
             patch("nuri.api.routes.actions._get_siege_violations", return_value=siege or []), \
             patch("nuri.api.routes.actions._get_targets_status", return_value=targets or {}), \
             patch("nuri.api.routes.actions._get_portfolio_map", return_value=portfolio or {}), \
             patch("nuri.api.routes.actions._get_short_interest", return_value=short):
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

    def test_siege_violation_urgent(self):
        result = self._run(
            [{"ticker": "TSLA", "action": "SELL", "confidence": 46, "agreement": 20}],
            siege=[{"ticker": "TSLA", "detail": "SIEGE: 한도 — TSLA(15.4%>15%)", "condition_id": "position_limit"}],
            portfolio={"TSLA": self._pf(349, 343, 1.6, 15.4)},
        )
        assert len(result["urgent"]) == 1
        assert result["urgent"][0]["ticker"] == "TSLA"

    def test_sell_with_loss_urgent(self):
        result = self._run(
            [{"ticker": "BAD", "action": "SELL", "confidence": 70, "agreement": 50}],
            portfolio={"BAD": self._pf(90, 100, -10, 5)},
        )
        assert len(result["urgent"]) == 1
        assert "손절선 근접" in result["urgent"][0]["reasons"][1]

    def test_sell_without_loss_check(self):
        result = self._run(
            [{"ticker": "MEH", "action": "SELL", "confidence": 50, "agreement": 20}],
            portfolio={"MEH": self._pf(105, 100, 5, 3)},
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
             }):
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
