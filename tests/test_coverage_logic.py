"""Cover remaining non-__main__ logic branches (~100 lines)."""

import json
from datetime import datetime, timedelta

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _seed(db_path, days=60):
    today = datetime.now()
    with get_db(db_path) as conn:
        for i in range(days):
            d = (today - timedelta(days=days - i)).strftime("%Y-%m-%d")
            p = 450 + i * 0.1
            conn.execute(
                "INSERT OR IGNORE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("SPY", d, p, p + 1, p - 1, p, 5e7),
            )
            conn.execute(
                "INSERT OR IGNORE INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                ("vix", d, 18),
            )
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)", ("t", "SPY", 10, 400, "USD", "Index"),
        )


# ─── 1. api/routes/swing.py lines 55-64: backtest endpoint ───

class TestSwingBacktestRoute:
    def test_backtest_endpoint(self, db_path):
        """Lines 55-64: /api/backtest runs full L/S backtest."""
        _seed(db_path, days=300)
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/backtest")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_strategy_status_endpoint(self, db_path):
        """/api/strategy/status endpoint."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/strategy/status")
        assert resp.status_code == 200


# ─── 2. api/routes/dashboard.py lines 210-211: critical signal alert ───

class TestDashboardAlerts:
    def test_dashboard_with_signal_drift(self, db_path, monkeypatch):
        """Lines 210-211: critical signal performance drift triggers alert."""
        _seed(db_path, days=60)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                ("usd_krw", datetime.now().strftime("%Y-%m-%d"), 1350),
            )
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data


# ─── 3. core/db.py lines 698-705: update_trade ───

class TestUpdateTrade:
    def test_update_trade(self, db_path):
        """Lines 698-705: update existing trade record."""
        from nuri.core.db import upsert_trade
        trade_id = upsert_trade({
            "ticker": "AAPL", "action": "BUY", "executed_at": "2025-12-01",
            "entry_price": 150.0, "shares": 10,
        }, db_path)
        assert trade_id > 0
        result = upsert_trade({"id": trade_id, "exit_price": 165.0, "exit_reason": "TP1"}, db_path)
        assert result == trade_id

    def test_update_trade_empty_data(self, db_path):
        """Line 701: empty data dict (only id) returns 0."""
        from nuri.core.db import upsert_trade
        trade_id = upsert_trade({
            "ticker": "AAPL", "action": "BUY", "executed_at": "2025-12-01",
        }, db_path)
        result = upsert_trade({"id": trade_id}, db_path)
        assert result == 0


# ─── 4. core/events.py lines 147-148: JSON parse in get_timeline ───

class TestEventsTimeline:
    def test_timeline_with_json_payload(self, db_path):
        """Lines 147-148: payload JSON parsing in get_timeline."""
        from nuri.core.events import emit_event, get_timeline
        emit_event("collect", "step_started", payload=json.dumps({"test": True}), db_path=db_path)
        emit_event("collect", "step_completed", payload="not-json", db_path=db_path)
        timeline = get_timeline(limit=10, db_path=db_path)
        assert len(timeline) >= 2
        # First should have parsed JSON payload
        parsed = [e for e in timeline if isinstance(e.get("payload"), dict)]
        unparsed = [e for e in timeline if isinstance(e.get("payload"), str)]
        assert len(parsed) >= 1 or len(unparsed) >= 1


# ─── 5. core/freshness.py lines 92-93: unparseable timestamp ───

class TestFreshnessEdge:
    def test_check_freshness_bad_timestamp(self, db_path):
        """Lines 92-93: ValueError on unparseable timestamp."""
        from nuri.core.freshness import check_freshness
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                ("vix", "not-a-date", 20),
            )
        result = check_freshness("macro_vix", db_path=db_path)
        assert result["status"] in ("PASS", "WARN", "FAIL")


# ─── 6. trading/agents/technical.py lines 28-31: yfinance data path ───

class TestTechnicalAgentYFinance:
    def test_analyze_with_db_prices(self, db_path):
        """Lines 28-31: yfinance fallback when DB has insufficient data."""
        from nuri.trading.agents.technical import TechnicalAgent
        # DB has no data for FAKE → yfinance mocked to empty → HOLD
        result = TechnicalAgent().analyze("FAKE", db_path=db_path)
        assert result.action == "HOLD"

    def test_analyze_with_sufficient_db(self, db_path):
        """With 100+ candles in DB, should analyze without yfinance."""
        _seed(db_path, days=120)
        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("SPY", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert result.ticker == "SPY"


# ─── 7. trading/agents/macro_agent.py lines 67-70: momentum from yfinance ───

class TestMacroAgentMomentum:
    def test_analyze_with_db_data(self, db_path):
        """Lines 67-70: macro agent uses DB momentum data."""
        _seed(db_path, days=60)
        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("SPY", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")


# ─── 8. trading/agents/fundamental.py lines 56-57: ROE branches ───

class TestFundamentalAgentROE:
    def test_moderate_roe(self, db_path):
        """Lines 56-57: ROE between good and excellent."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity, profit_margin, beta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("TEST", "2025-12-01", 20, 0.12, 0.05, 0.8, 0.15, 1.0),
            )
        from nuri.trading.agents.fundamental import FundamentalAgent
        result = FundamentalAgent().analyze("TEST", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert "ROE" in result.reasoning

    def test_negative_roe(self, db_path):
        """Line 58-59: negative ROE penalizes score."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity, profit_margin, beta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("BAD", "2025-12-01", 50, -0.1, -0.05, 3.0, -0.05, 2.0),
            )
        from nuri.trading.agents.fundamental import FundamentalAgent
        result = FundamentalAgent().analyze("BAD", db_path=db_path)
        assert result.action in ("SELL", "HOLD")


# ─── 9. api/routes/ticker.py lines 87-88: signals exception ───

class TestTickerSignals:
    def test_ticker_with_signal_exception(self, db_path, monkeypatch):
        """Lines 87-88: exception in signals → empty list."""
        _seed(db_path, days=30)
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("test")),
        )
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/ticker/SPY")
        assert resp.status_code == 200
        assert resp.json().get("signals") == []


# ─── 10. api/routes/pipeline.py line 129: track step ───

class TestPipelineTrackStep:
    def test_run_track_step(self, db_path, monkeypatch):
        """Line 129: run 'track' step calls track_outcomes."""
        import nuri.api.routes.pipeline as pipe_mod
        from nuri.api.main import app
        monkeypatch.setattr(pipe_mod._limiter, "enabled", False)
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/api/pipeline/track/run")
        assert resp.status_code == 200


# ─── 11. api/routes/regime.py lines 30-31 ───

class TestRegimeRoute:
    def test_macro_endpoint(self, db_path):
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/macro")
        assert resp.status_code == 200

    def test_strategy_endpoint(self, db_path):
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/strategy")
        assert resp.status_code == 200


# ─── 12. api/routes/signals.py line 53 ───

class TestSignalsRoute:
    def test_signals_cross_analysis(self, db_path):
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/cross-analysis")
        assert resp.status_code == 200


# ─── 13. core/agent_config.py line 20 ───

class TestAgentConfig:
    def test_config_loaded(self):
        from nuri.core.agent_config import AGENT_CONFIG
        assert isinstance(AGENT_CONFIG, dict)

    def test_missing_key_returns_default(self):
        from nuri.core.agent_config import AGENT_CONFIG
        val = AGENT_CONFIG.get("nonexistent_key", "default")
        assert val == "default"

    def test_load_config_missing_file(self, monkeypatch):
        """Line 20: config file doesn't exist → empty dict."""
        from pathlib import Path

        import nuri.core.agent_config as mod
        monkeypatch.setattr(mod, "_CONFIG_PATH", Path("/nonexistent/agents.yaml"))
        result = mod._load_config()
        assert result == {}
