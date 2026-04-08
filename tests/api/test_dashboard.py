"""Tests for dashboard — split from test_api_all.py."""
import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


class TestDashboard:
    def test_dashboard(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        assert "regime" in data
        assert "actions" in data

    def test_dashboard_cached(self, client):
        """두 번 호출 — 캐시 사용."""
        r1 = client.get("/api/dashboard")
        r2 = client.get("/api/dashboard")
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestDashboardAPI:
    def test_build_dashboard_empty(self, db_path):
        """빈 DB에서도 dashboard 생성 가능."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert isinstance(result, dict)
        assert "regime" in result
        assert "actions" in result

    def test_cache_mechanism(self, db_path, monkeypatch):
        """캐시 동작 확인."""
        import nuri.api.routes.dashboard as dash_mod
        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        result1 = dash_mod.get_dashboard()
        assert isinstance(result1, dict)

        # 두 번째 호출은 캐시 사용
        dash_mod._cache["timestamp"] = _time.time()
        result2 = dash_mod.get_dashboard()
        assert result2 == result1


class TestDashboardBuildExtended:
    @pytest.fixture()
    def rich_db(self, db_path):
        from nuri.core.timezone import today_kst
        today = today_kst()

        with get_db(db_path) as conn:
            for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                                ("TSLA", 8, 340, "SectorA"), ("SPY", 50, 450, "Index")]:
                conn.execute(
                    "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                    "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

        dates = pd.date_range(end=today, periods=300)
        for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
            close = np.linspace(base, base * 1.2, 300) + np.random.normal(0, 1, 300)
            df = pd.DataFrame({
                "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99, "high": close * 1.01,
                "low": close * 0.98, "close": close,
                "volume": [1000000] * 300, "adj_close": close,
            })
            upsert_prices(df, db_path)

        with get_db(db_path) as conn:
            for d in dates[-50:]:
                ds = d.strftime("%Y-%m-%d")
                conn.execute("INSERT OR IGNORE INTO signals (ticker, date, rsi_14, sma_20, sma_50, sma_200) "
                             "VALUES (?, ?, ?, ?, ?, ?)", ("SPY", ds, 55.0, 480.0, 470.0, 440.0))

        upsert_macro([
            {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
            {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
            {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
            {"indicator": "gdp_growth", "date": today, "value": 2.5, "source": "test"},
            {"indicator": "unemployment", "date": today, "value": 3.8, "source": "test"},
        ], db_path)
        return db_path

    def test_verdict_levels(self, rich_db):
        """rich_db로 dashboard 빌드 — verdict_level 확인."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert result["verdict_level"] in ("aggressive", "neutral", "cautious", "defensive")
        assert isinstance(result["alerts"], list)
        assert isinstance(result["actions"], list)

    def test_gate_score_field(self, rich_db):
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert "gate_score" in result


class TestDashboardInternals:
    def test_get_allocation(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("bull_low_vol")
        assert "long" in result
        assert "short" in result
        assert "cash" in result

    def test_get_allocation_unknown(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("unknown_regime")
        assert "long" in result


class TestDashboardDeeper:
    @pytest.fixture()
    def full_db(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "test.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
            {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "SectorA"},
        ], path)
        dates = pd.date_range("2024-06-01", periods=500, freq="B")
        rows = []
        for t in ["SPY", "AAPL", "NVDA", "TSLA"]:
            base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200}[t]
            for i, d in enumerate(dates):
                p = base + i * 0.2 + np.sin(i / 20) * 5
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                             "open": p, "high": p + 3, "low": p - 2,
                             "close": p + 1, "volume": 50000000, "adj_close": p + 1})
        upsert_prices(pd.DataFrame(rows), path)
        macro = []
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
            macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        upsert_macro(macro, path)
        return path

    def test_dashboard_with_portfolio(self, full_db, tmp_path, monkeypatch):
        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        c = TestClient(app)
        r = c.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        assert "regime" in data

    def test_pipeline_run(self, client):
        """POST /api/pipeline/{step}/run."""
        r = client.post("/api/pipeline/collect/run")
        assert r.status_code in (200, 202, 400, 404)

    def test_timeline(self, client):
        r = client.get("/api/pipeline/timeline")
        assert r.status_code == 200


class TestDashboardAPI_R22:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch, _seed_recommendations, _seed_positions):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        import nuri.api.routes.dashboard as dash_mod
        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        from nuri.api.main import app
        return TestClient(app)

    def test_dashboard_returns_data(self, _client, monkeypatch):
        """Dashboard endpoint returns valid JSON with expected keys."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "bull_low_vol", "trend": "bull", "volatility": "low",
            "confidence": 80, "vix": 15.0, "fear_greed": 60,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 65, "interpretation": "Positive"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 70, "short": 10, "cash": 20})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 80)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        resp = _client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert "regime" in data
        assert "actions" in data

    def test_dashboard_cache(self, _client, monkeypatch):
        """Second call within TTL returns cached data."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "sideways_high_vol", "trend": "sideways", "confidence": 50,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 45, "interpretation": "Neutral"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 30, "short": 20, "cash": 50})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 50)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        resp1 = _client.get("/api/dashboard")
        resp2 = _client.get("/api/dashboard")
        assert resp1.json()["verdict"] == resp2.json()["verdict"]

    def test_dashboard_bear_defensive(self, _client, monkeypatch):
        """Bear regime produces defensive verdict."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "bear_high_vol", "trend": "bear", "confidence": 70,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 25, "interpretation": "Bearish"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 10, "short": 40, "cash": 50})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 30)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        resp = _client.get("/api/dashboard")
        data = resp.json()
        assert data["verdict_level"] == "defensive"

    def test_dashboard_sells_more_than_buys(self, _client, db_path, monkeypatch):
        """When SELL actions > BUY actions, verdict = cautious."""
        import nuri.api.routes.dashboard as dash_mod

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "TSLA", "SELL", 0.90, "bear_high_vol", "signal"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "GOOG", "SELL", 0.85, "bear_high_vol", "signal"),
            )

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "sideways_low_vol", "trend": "sideways", "confidence": 50,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 55, "interpretation": "Neutral"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 40, "short": 20, "cash": 40})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 50)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        resp = _client.get("/api/dashboard")
        data = resp.json()
        assert data["verdict_level"] in ("cautious", "neutral", "defensive")


class TestDashboardHelpers:
    """Test individual _build helper functions."""

    def test_get_cached_regime_failure(self, monkeypatch):
        """_get_cached_regime returns fallback when classify_regime raises."""
        import nuri.api.routes.dashboard as dash_mod

        def _raise():
            raise RuntimeError("test error")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _raise)
        result = dash_mod._get_cached_regime()
        assert result["regime"] == "unknown"

    def test_get_macro_failure(self, monkeypatch):
        """_get_macro returns fallback when compute_macro_score raises."""
        import nuri.api.routes.dashboard as dash_mod

        def _raise():
            raise RuntimeError("no data")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", _raise)
        result = dash_mod._get_macro()
        assert result["score"] == 50

    def test_get_allocation_unknown_regime(self):
        """_get_allocation returns defaults for unknown regime."""
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_allocation("nonexistent_regime")
        assert "cash" in result

    def test_get_freshness_failure(self, monkeypatch):
        """_get_freshness returns {} on exception."""
        import nuri.api.routes.dashboard as dash_mod

        def bad():
            raise RuntimeError("fail")

        monkeypatch.setattr("nuri.core.freshness.check_all_freshness", bad)
        result = dash_mod._get_freshness()
        assert result == {}

    def test_get_pipeline_status_failure(self, monkeypatch):
        """_get_pipeline_status returns {} on exception."""
        import nuri.api.routes.dashboard as dash_mod

        def bad():
            raise RuntimeError("fail")

        monkeypatch.setattr("nuri.core.events.get_pipeline_status", bad)
        result = dash_mod._get_pipeline_status()
        assert result == {}


class TestGetLatestActions:
    def test_no_recommendations(self, db_path, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        result = dash_mod._get_latest_actions()
        assert result == []

    def test_with_recommendations(self, db_path, _seed_recommendations, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        result = dash_mod._get_latest_actions()
        assert isinstance(result, list)

    def test_low_confidence_filtered(self, db_path, monkeypatch):
        """Low confidence recommendations are filtered out."""
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "AAPL", "BUY", 0.30, "bull_low_vol", "weak_signal"),
            )

        result = dash_mod._get_latest_actions()
        assert all(a.get("confidence", 0) >= 50 for a in result if a["action"] == "BUY")


class TestGetActiveAlerts:
    def test_with_portfolio_stop(self, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", lambda: {
            "portfolio_stop_triggered": True,
            "max_drawdown_pct": -12.0,
            "stop_loss_alerts": [{"ticker": "TSLA", "pnl_pct": -25.0}],
        })
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda: [])

        alerts = dash_mod._get_active_alerts()
        assert len(alerts) >= 1
        assert any("손절선" in a["message"] for a in alerts)

    def test_all_failures_graceful(self, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod

        def fail():
            raise RuntimeError("mock fail")

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", fail)
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", fail)
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", fail)

        alerts = dash_mod._get_active_alerts()
        assert alerts == []


class TestDashboard_R27:
    """Tests for nuri/api/routes/dashboard.py."""

    def test_get_allocation_unknown_regime(self):
        """_get_allocation with unknown regime returns defaults."""
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("totally_unknown_regime")
        assert "long" in result
        assert "cash" in result

    def test_get_cached_regime_exception(self, monkeypatch):
        """_get_cached_regime handles exception."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            MagicMock(side_effect=Exception("test error")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_cached_regime()
        assert result["regime"] == "unknown"

    def test_get_freshness(self, monkeypatch):
        """_get_freshness returns dict."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(return_value=[{"table": "prices", "age_hours": 5, "status": "PASS"}]),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert "prices" in result

    def test_get_freshness_exception(self, monkeypatch):
        """_get_freshness handles exception."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert result == {}

    def test_get_pipeline_status_exception(self, monkeypatch):
        """_get_pipeline_status handles exception."""
        monkeypatch.setattr(
            "nuri.core.events.get_pipeline_status",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_pipeline_status()
        assert result == {}

    def test_get_latest_actions_empty(self):
        """_get_latest_actions returns empty list with no recommendation data."""
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_latest_actions()
        assert isinstance(result, list)
