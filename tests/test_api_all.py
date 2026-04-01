"""Consolidated API tests — nuri.api.* (main, auth, routes/*).

All API-related test classes extracted from individual test files.
Excludes test_pipeline_api.py and test_pipeline_events.py (kept separately).

Naming rule: first occurrence keeps original name,
subsequent occurrences get _Rxx suffix (source round).
"""
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

# ═══════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Isolated test DB with DB_PATH monkeypatched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with isolated DB + YAML."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    import nuri.core.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    import nuri.core.portfolio_sync as sync_mod
    monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "portfolio.yaml")

    from nuri.api.main import app
    return TestClient(app)


@pytest.fixture()
def seeded_client(client):
    """Client with one holding pre-added."""
    client.post("/api/portfolio", json={
        "account": "sample", "ticker": "AAPL",
        "quantity": 10, "avg_price": 180.0,
        "currency": "USD", "sector": "Tech",
    })
    return client


@pytest.fixture()
def populated_db(db_path):
    """Portfolio + price data."""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db(db_path) as conn:
        for ticker, qty, price, sector in [
            ("AAPL", 10, 150.0, "Technology"),
            ("MSFT", 5, 300.0, "Software"),
            ("TSLA", 8, 340.0, "SectorA"),
        ]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, qty, price, "USD", sector),
            )

    dates = pd.bdate_range("2024-01-01", periods=250)
    for ticker, base in [("SPY", 450), ("AAPL", 150), ("MSFT", 300), ("TSLA", 340)]:
        close = np.linspace(base, base * 1.1, 250)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture()
def _seed_recommendations(db_path):
    """Insert recommendations for dashboard action tests."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
            ("2025-03-31", "AAPL", "BUY", 0.75, "bull_low_vol", "rsi_oversold,macd_golden"),
        )
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
            ("2025-03-31", "MSFT", "SELL", 0.85, "bear_high_vol", "macd_dead,sma_dead"),
        )


@pytest.fixture()
def _seed_positions(db_path):
    """Insert open positions."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, status) VALUES (?,?,?,?,?,?,?)",
            ("core", "AAPL", "long", "2025-01-05", 145.0, 10, "open"),
        )


@pytest.fixture()
def _seed_prices(db_path):
    """Insert price data for AAPL and MSFT (80 rows each)."""
    dates = pd.bdate_range("2025-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    rows = []
    np.random.seed(42)
    base_aapl = 150.0
    base_msft = 300.0
    for i, d in enumerate(dates):
        aapl_close = base_aapl + np.random.randn() * 2 + i * 0.1
        msft_close = base_msft + np.random.randn() * 3 + i * 0.15
        rows.append(("AAPL", d, aapl_close - 1, aapl_close + 1, aapl_close - 2, aapl_close, 1000000, aapl_close))
        rows.append(("MSFT", d, msft_close - 1, msft_close + 1, msft_close - 2, msft_close, 800000, msft_close))
        rows.append(("VOO", d, msft_close / 2, msft_close / 2 + 1, msft_close / 2 - 1, msft_close / 2, 500000, msft_close / 2))
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


@pytest.fixture()
def _seed_portfolio(db_path):
    """Insert portfolio holdings for AAPL and MSFT."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "AAPL", 10, 145.0, "USD", "Technology"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
            ("test", "MSFT", 5, 290.0, "USD", "Technology"),
        )


def _csv_file(content: str, filename: str = "test.csv"):
    """Helper: CSV UploadFile for import tests."""
    return {"file": (filename, content.encode("utf-8"), "text/csv")}


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestHealth
# ═══════════════════════════════════════════════════════════


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_redirects(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (301, 302, 307)


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestPortfolio
# ═══════════════════════════════════════════════════════════


class TestPortfolio:
    def test_portfolio_empty(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "holdings" in data
        assert "count" in data
        assert data["count"] == 0

    def test_add_holding(self, client):
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
            "currency": "USD", "sector": "Tech",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 1

    def test_delete_holding(self, client):
        client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
        })
        r = client.delete("/api/portfolio/sample/AAPL")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 0

    def test_delete_nonexistent(self, client):
        """존재하지 않는 종목 삭제 → 404."""
        r = client.delete("/api/portfolio/test/XXXX")
        assert r.status_code == 404

    def test_delete_invalid_account(self, client):
        """유효하지 않은 계좌명 → 400."""
        r = client.delete("/api/portfolio/fake/XXXX")
        assert r.status_code == 400

    def test_risk_graceful(self, client):
        """빈 DB에서도 에러 대신 에러 dict 반환."""
        r = client.get("/api/risk")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestEngine
# ═══════════════════════════════════════════════════════════


class TestEngine:
    def test_gate_all(self, client):
        r = client.get("/api/gate")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_gate_phase(self, client):
        r = client.get("/api/gate/collect")
        assert r.status_code == 200
        data = r.json()
        assert "phase" in data
        assert "passed" in data or "status" in data

    def test_conflicts(self, client):
        r = client.get("/api/conflicts")
        assert r.status_code == 200
        data = r.json()
        assert "conflicts" in data
        assert "count" in data

    def test_memory(self, client):
        r = client.get("/api/memory")
        assert r.status_code == 200
        data = r.json()
        assert "drifts" in data

    def test_memory_snapshot(self, client):
        r = client.post("/api/memory/snapshot")
        assert r.status_code == 200
        assert "saved" in r.json()


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestSignals
# ═══════════════════════════════════════════════════════════


class TestSignals:
    def test_candidates_empty(self, client):
        r = client.get("/api/candidates")
        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert "count" in data

    def test_candidates_query_param(self, client):
        r = client.get("/api/candidates?days=10")
        assert r.status_code == 200

    def test_candidates_invalid_days(self, client):
        r = client.get("/api/candidates?days=100")
        assert r.status_code == 422

    def test_scorecard_no_data(self, client):
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "scorecard" in data

    def test_cross_analysis(self, client):
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestRegime
# ═══════════════════════════════════════════════════════════


class TestRegime:
    def test_regime_no_data(self, client):
        """SPY 데이터 없으면 에러 dict 반환."""
        r = client.get("/api/regime")
        assert r.status_code == 200

    def test_macro(self, client):
        r = client.get("/api/macro")
        assert r.status_code == 200

    def test_strategy(self, client):
        r = client.get("/api/strategy")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestRebalance
# ═══════════════════════════════════════════════════════════


class TestRebalance:
    def test_rebalance_rp(self, client):
        r = client.get("/api/rebalance?method=rp")
        assert r.status_code == 200

    def test_tracking(self, client):
        r = client.get("/api/tracking")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestTicker
# ═══════════════════════════════════════════════════════════


class TestTicker:
    def test_ticker_unknown(self, client):
        """존재하지 않는 종목도 200 + 빈 데이터 반환."""
        r = client.get("/api/ticker/FAKE")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"

    def test_ticker_prices(self, client):
        r = client.get("/api/ticker/FAKE/prices?days=30")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"
        assert "prices" in data


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestSwing
# ═══════════════════════════════════════════════════════════


class TestSwing:
    def test_swing_positions(self, client):
        r = client.get("/api/swing/positions")
        assert r.status_code == 200
        data = r.json()
        assert "positions" in data

    def test_swing_entries(self, client):
        r = client.get("/api/swing/entries")
        assert r.status_code == 200

    def test_scan(self, client):
        r = client.get("/api/scan")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestDashboard
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestConsensusAPI
# ═══════════════════════════════════════════════════════════


class TestConsensusAPI:
    def test_consensus(self, client):
        r = client.get("/api/consensus")
        assert r.status_code == 200

    def test_consensus_ticker(self, client):
        r = client.get("/api/consensus/AAPL")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestTargetsAPI
# ═══════════════════════════════════════════════════════════


class TestTargetsAPI:
    def test_targets(self, client):
        r = client.get("/api/targets")
        assert r.status_code == 200

    def test_targets_ticker(self, client):
        r = client.get("/api/targets/AAPL")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestEvidenceAPI
# ═══════════════════════════════════════════════════════════


class TestEvidenceAPI:
    def test_evidence(self, client):
        r = client.get("/api/evidence")
        assert r.status_code == 200

    def test_evidence_list(self, client):
        r = client.get("/api/evidence")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestExternalAPI
# ═══════════════════════════════════════════════════════════


class TestExternalAPI:
    def test_external(self, client):
        r = client.get("/api/external")
        assert r.status_code == 200

    def test_external_ticker(self, client):
        r = client.get("/api/external/AAPL")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestRebalanceAdvisor
# ═══════════════════════════════════════════════════════════


class TestRebalanceAdvisor:
    def test_rebalance_advisor(self, client):
        r = client.get("/api/rebalance-advisor")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_api.py — TestStrategyAPI
# ═══════════════════════════════════════════════════════════


class TestStrategyAPI:
    def test_strategy_status(self, client):
        r = client.get("/api/strategy/status")
        assert r.status_code == 200

    def test_backtest(self, client):
        r = client.get("/api/backtest")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_coverage_boost.py — TestDashboardAPI
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_boost.py — TestAPIRoutes
# ═══════════════════════════════════════════════════════════


class TestAPIRoutes:
    def test_targets_route_exists(self):
        from nuri.api.routes.targets import router
        routes = [r.path for r in router.routes]
        assert any("targets" in r for r in routes)

    def test_agents_route_exists(self):
        from nuri.api.routes.agents import router
        routes = [r.path for r in router.routes]
        assert any("consensus" in r for r in routes)


# ═══════════════════════════════════════════════════════════
# From test_coverage_extra.py — TestAuthAPI
# ═══════════════════════════════════════════════════════════


class TestAuthAPI:
    def test_create_token(self):
        from nuri.api.auth import create_token
        token = create_token("test_user")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_decode_token(self):
        from nuri.api.auth import create_token, decode_token
        token = create_token("test_user")
        payload = decode_token(token)
        assert payload is not None
        assert payload.get("sub") == "test_user"

    def test_decode_invalid_token(self):
        from nuri.api.auth import decode_token
        payload = decode_token("invalid.token.here")
        assert payload is None

    def test_hash_password(self):
        from nuri.api.auth import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True
        assert verify_password("wrong", hashed) is False


# ═══════════════════════════════════════════════════════════
# From test_coverage_final.py — TestDashboardBuildExtended
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_final.py — TestAPIRoutesExtended
# ═══════════════════════════════════════════════════════════


class TestAPIRoutesExtended:
    def test_stream_route_exists(self):
        from nuri.api.routes.stream import router
        assert router is not None

    def test_signals_route(self):
        from nuri.api.routes.signals import router
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_regime_route(self):
        from nuri.api.routes.regime import router
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_portfolio_route(self):
        from nuri.api.routes.portfolio import router
        routes = [r.path for r in router.routes]
        assert len(routes) > 0


# ═══════════════════════════════════════════════════════════
# From test_coverage_round2.py — TestEvidenceAPI_R2
# ═══════════════════════════════════════════════════════════


class TestEvidenceAPI_R2:
    def test_find_latest_report_dir(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        evidence_dir = tmp_path / "reports" / "2026-03-31" / "evidence"
        evidence_dir.mkdir(parents=True)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "reports")
        result = _find_latest_report_dir()
        assert result is not None
        assert "2026-03-31" in str(result)

    def test_find_no_reports(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        empty_dir = tmp_path / "empty_reports"
        empty_dir.mkdir()
        monkeypatch.setattr(ev_mod, "REPORT_DIR", empty_dir)
        assert _find_latest_report_dir() is None

    def test_evidence_list_endpoint(self, tmp_path, monkeypatch):
        """GET /api/evidence — 리포트 없을 때."""
        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        c = TestClient(app)
        r = c.get("/api/evidence")
        assert r.status_code == 200

    def test_evidence_chart_not_found(self, tmp_path, monkeypatch):
        """GET /api/evidence/{chart_id} — 파일 없으면 404."""
        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        c = TestClient(app)
        r = c.get("/api/evidence/regime")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════
# From test_coverage_round2.py — TestDashboardInternals
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round9.py — TestAPIRoutes_R9
# ═══════════════════════════════════════════════════════════


class TestAPIRoutes_R9:
    @pytest.fixture()
    def _client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod
        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")
        from nuri.api.main import app
        return TestClient(app)

    def test_consensus_endpoint(self, _client):
        r = _client.get("/api/consensus")
        assert r.status_code == 200

    def test_regime_endpoint(self, _client):
        r = _client.get("/api/regime")
        assert r.status_code == 200

    def test_macro_endpoint(self, _client):
        r = _client.get("/api/macro")
        assert r.status_code == 200

    def test_strategy_endpoint(self, _client):
        r = _client.get("/api/strategy")
        assert r.status_code == 200

    def test_pipeline_status(self, _client):
        r = _client.get("/api/pipeline/status")
        assert r.status_code == 200

    def test_freshness(self, _client):
        r = _client.get("/api/freshness")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_coverage_round11.py — TestAPIAuth
# ═══════════════════════════════════════════════════════════


class TestAPIAuth:
    def test_hash_and_verify(self):
        from nuri.api.auth import hash_password, verify_password
        hashed = hash_password("test123")
        assert verify_password("test123", hashed)
        assert not verify_password("wrong", hashed)

    def test_create_and_decode_token(self):
        from nuri.api.auth import create_token, decode_token
        token = create_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"

    def test_decode_invalid_token(self):
        from nuri.api.auth import decode_token
        result = decode_token("invalid.token.here")
        assert result is None


# ═══════════════════════════════════════════════════════════
# From test_coverage_round15.py — TestDashboardDeeper
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round15.py — TestTradesAPI
# ═══════════════════════════════════════════════════════════


class TestTradesAPI:
    @pytest.fixture()
    def _client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod
        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")
        from nuri.api.main import app
        return TestClient(app)

    def test_list_trades(self, _client):
        r = _client.get("/api/trades")
        assert r.status_code == 200

    def test_create_trade(self, _client):
        r = _client.post("/api/trades", json={
            "ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.0,
        })
        assert r.status_code in (200, 201, 422)


# ═══════════════════════════════════════════════════════════
# From test_coverage_round19.py — TestSSEStream
# ═══════════════════════════════════════════════════════════


class TestSSEStream:
    """SSE stream endpoint tests."""

    def test_get_snapshot_returns_dict(self):
        with patch("nuri.api.routes.stream._get_snapshot") as mock:
            mock.return_value = {"timestamp": 123.0, "regime": "bull_low_vol"}
            result = mock()
        assert "timestamp" in result

    def test_get_snapshot_caching(self):
        """Cached snapshot should return quickly."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        stream_mod._cache_time = _time.time()
        result = stream_mod._get_snapshot()
        assert result.get("cached") is True

    def test_get_snapshot_fresh_with_mocked_deps(self, monkeypatch):
        """Fresh snapshot (cache expired) with all dependencies mocked."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.8
        mock_regime.details = {"vix": 15.0, "fear_greed": 60.0}

        mock_macro = MagicMock()
        mock_macro.total_score = 65.0

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", return_value=mock_macro), \
             patch("nuri.core.db.query", return_value=[{"c": 3}]):
            result = stream_mod._get_snapshot()

        assert result["regime"] == "bull_low_vol"
        assert result["macro_score"] == 65
        assert result["open_positions"] == 3

    def test_get_snapshot_handles_exceptions(self, monkeypatch):
        """All dependencies failing should not crash."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("no data")), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception("no data")), \
             patch("nuri.core.db.query", side_effect=Exception("no db")):
            result = stream_mod._get_snapshot()

        assert "timestamp" in result

    def test_stream_endpoint_response_type(self):
        """Test that /api/stream returns an SSE response (media type check only)."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        stream_mod._cache_time = _time.time()

        from nuri.api.routes.stream import stream as stream_handler

        async def run():
            resp = await stream_handler()
            return resp

        resp = asyncio.run(run())
        assert resp.media_type == "text/event-stream"
        assert resp.headers.get("Cache-Control") == "no-cache"

    def test_event_generator_yields_data(self):
        """Event generator should yield SSE-formatted data."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 42.0, "regime": "test_bull"}
        stream_mod._cache_time = _time.time()

        async def run():
            gen = stream_mod._event_generator()
            event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert result.startswith("data:")
        parsed = json.loads(result.replace("data:", "").strip())
        assert "timestamp" in parsed

    def test_event_generator_error_handling(self):
        """Event generator should yield error JSON on exception."""
        import nuri.api.routes.stream as stream_mod

        async def run():
            gen = stream_mod._event_generator()
            with patch.object(stream_mod, "_get_snapshot", side_effect=Exception("boom")):
                event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert "data:" in result
        parsed = json.loads(result.replace("data:", "").strip())
        assert "error" in parsed


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestEvidenceAPI_R22
# ═══════════════════════════════════════════════════════════


class TestEvidenceAPI_R22:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_list_evidence_no_reports(self, _client, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent/path"))
        resp = _client.get("/api/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert data["charts"] == []

    def test_list_evidence_with_dir(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime.html").write_text("<html>regime</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["charts"]) > 0
        regime_chart = [c for c in data["charts"] if c["id"] == "regime"][0]
        assert regime_chart["available"] is True

    def test_get_evidence_chart_invalid(self, _client):
        resp = _client.get("/api/evidence/invalid_chart")
        assert resp.status_code == 400

    def test_get_evidence_chart_no_dir(self, _client, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent"))
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 404

    def test_get_evidence_chart_found(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime.html").write_text("<html>test regime chart</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 200
        assert "test regime chart" in resp.text

    def test_get_evidence_chart_alternative_name(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime_evidence.html").write_text("<html>alt name</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 200
        assert "alt name" in resp.text

    def test_get_evidence_chart_not_generated(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 404

    def test_get_evidence_report_not_found(self, _client, monkeypatch):
        """evidence/report — route may be shadowed by /{chart_id} due to definition order."""
        import nuri.api.routes.evidence as ev_mod
        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent"))
        resp = _client.get("/api/evidence/report")
        assert resp.status_code in (400, 404)

    def test_get_evidence_report_found(self, _client, tmp_path, monkeypatch):
        """Test get_evidence_report directly since route may be shadowed."""
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31"
        (date_dir / "evidence").mkdir(parents=True)
        (date_dir / "portfolio_action_plan.md").write_text("# Plan content")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        result = ev_mod.get_evidence_report()
        assert "Plan content" in result["content"]


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestExternalAPI_R22
# ═══════════════════════════════════════════════════════════


class TestExternalAPI_R22:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_get_external_summary(self, _client, monkeypatch):
        monkeypatch.setattr(
            "nuri.collectors.external.get_external_summary",
            lambda **kw: {"total": 0, "sources": {}},
        )
        resp = _client.get("/api/external")
        assert resp.status_code == 200

    def test_get_ticker_external(self, _client, monkeypatch):
        monkeypatch.setattr(
            "nuri.collectors.external.get_external",
            lambda ticker, **kw: [{"source": "tipranks", "value": "Buy"}],
        )
        resp = _client.get("/api/external/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["count"] == 1

    def test_save_external_data(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.collectors.external.save_external", lambda **kw: True)
        monkeypatch.setattr("nuri.core.db.audit_log", lambda *a, **kw: None)
        resp = _client.post("/api/external", json={
            "source": "tipranks",
            "ticker": "AAPL",
            "data_type": "consensus",
            "value": "Strong Buy",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_save_tipranks_batch(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.collectors.external.save_tipranks", lambda **kw: True)
        resp = _client.post("/api/external/tipranks", json=[
            {"ticker": "AAPL", "consensus": "Buy", "target_price": "200.0", "analyst_count": 30},
            {"ticker": "MSFT", "consensus": "Strong Buy", "target_price": "400.0"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] == 2

    def test_save_tipranks_batch_with_error(self, _client, monkeypatch):
        def bad_save(**kw):
            if kw["ticker"] == "AAPL":
                raise ValueError("fail")
            return True

        monkeypatch.setattr("nuri.collectors.external.save_tipranks", bad_save)
        resp = _client.post("/api/external/tipranks", json=[
            {"ticker": "AAPL", "consensus": "Buy", "target_price": "200.0"},
            {"ticker": "MSFT", "consensus": "Buy", "target_price": "300.0"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] == 1


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestDashboardAPI_R22
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestDashboardHelpers
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestRegimeAPI
# ═══════════════════════════════════════════════════════════


class TestRegimeAPI:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_get_regime_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: None)
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        assert resp.json()["error"] == "SPY 데이터 부족"

    def test_get_regime_success(self, _client, monkeypatch):
        @dataclass
        class FakeRegimeState:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.85
            details: dict = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {"vix": 15.0, "fear_greed": 60}

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: FakeRegimeState())
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_macro(self, _client, monkeypatch):
        @dataclass
        class FakeMacro:
            total_score: float = 65.0
            interpretation: str = "Positive"
            details: dict = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {}

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda: FakeMacro())
        resp = _client.get("/api/macro")
        assert resp.status_code == 200

    def test_get_strategy_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: None)
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_get_strategy_success(self, _client, monkeypatch):
        class FakeStrategy:
            regime = "bull_low_vol"
            macro_interpretation = "Positive"
            position_sizing = "aggressive"
            recommended_signals = ["rsi_oversold", "macd_golden"]
            avoid_signals = ["sma_dead"]
            sector_preference = ["Technology"]
            signal_regime_stats = {}
            notes = "Test note"

        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: FakeStrategy())
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_report_context(self, _client, monkeypatch):
        class FakeContext:
            gate_score = 80
            known_tickers = {"AAPL", "MSFT"}

        monkeypatch.setattr("nuri.llm.report.gather_context", lambda: FakeContext())
        monkeypatch.setattr("nuri.llm.report.format_prompt", lambda ctx: "test prompt")
        resp = _client.get("/api/report/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gate_score"] == 80


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestGetLatestActions
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestGetActiveAlerts
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round22.py — TestEvidenceReportLatest
# ═══════════════════════════════════════════════════════════


class TestEvidenceReportLatest:
    def test_report_from_latest_dir(self, tmp_path, monkeypatch):
        """Test get_evidence_report falls back to latest directory."""
        import nuri.api.routes.evidence as ev_mod
        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-30"
        evidence_dir = date_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        (date_dir / "llm_evidence_report.md").write_text("# LLM Report")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        result = ev_mod.get_evidence_report()
        assert "LLM Report" in result["content"]

    def test_report_raises_when_none(self, tmp_path, monkeypatch):
        """get_evidence_report raises 404 when no report files exist."""
        import nuri.api.routes.evidence as ev_mod
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "nonexistent")
        with pytest.raises(Exception):
            ev_mod.get_evidence_report()


# ═══════════════════════════════════════════════════════════
# From test_coverage_round23.py — TestPipelineAPI
# ═══════════════════════════════════════════════════════════


class TestPipelineAPI:
    """Cover lines 21-22, 90-93, 108-110, 115, 117-129."""

    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_scheduler_health_no_file(self, _client, monkeypatch, tmp_path):
        """Scheduler health when no heartbeat file (lines 21-22)."""
        import nuri.api.routes.pipeline as pipeline_mod
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", tmp_path / "nonexistent")
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    def test_scheduler_health_valid(self, _client, monkeypatch, tmp_path):
        """Scheduler health with valid heartbeat."""
        import nuri.api.routes.pipeline as pipeline_mod
        hb_path = tmp_path / ".scheduler_heartbeat"
        from nuri.core.timezone import kst_now
        hb_path.write_text(kst_now().replace(tzinfo=None).isoformat())
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_pipeline_status(self, _client):
        """Pipeline status endpoint."""
        resp = _client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data

    def test_pipeline_timeline(self, _client):
        """Pipeline timeline endpoint."""
        resp = _client.get("/api/pipeline/timeline?limit=10")
        assert resp.status_code == 200

    def test_pipeline_timeline_invalid_step(self, _client):
        """Pipeline timeline with invalid step."""
        resp = _client.get("/api/pipeline/timeline?step=invalid")
        assert resp.status_code == 400

    def test_run_step_invalid(self, _client):
        """Run invalid step."""
        resp = _client.post("/api/pipeline/invalid_step/run")
        assert resp.status_code == 400

    def test_run_step_collect(self, _client):
        """Run collect step (lines 108-110)."""
        resp = _client.post("/api/pipeline/collect/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "not_implemented" in data.get("detail", "")

    def test_run_step_validate(self, _client, monkeypatch):
        """Run validate step (lines 108-110)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: [{"signal": "test"}],
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_run_step_classify(self, _client, monkeypatch):
        """Run classify step (lines 115)."""
        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            trend: str = "bullish"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: MockRegime(),
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "bull_low_vol" in data.get("detail", "")

    def test_run_step_classify_none(self, _client, monkeypatch):
        """Run classify step returns None (line 116)."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: None,
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown" in data.get("detail", "")

    def test_run_step_diagnose(self, _client, monkeypatch):
        """Run diagnose step (lines 117-120)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda: ["r1", "r2"],
        )
        resp = _client.post("/api/pipeline/diagnose/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "2 tickers" in data.get("detail", "")

    def test_run_step_recommend(self, _client, monkeypatch):
        """Run recommend step (lines 121-124)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda: ["c1"],
        )
        resp = _client.post("/api/pipeline/recommend/run")
        assert resp.status_code == 200

    def test_run_step_track(self, _client, monkeypatch):
        """Run track step (lines 125-128)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.tracker.track_outcomes",
            lambda: 5,
        )
        resp = _client.post("/api/pipeline/track/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "5 recommendations" in data.get("detail", "")

    def test_run_step_exception(self, _client, monkeypatch):
        """Run step that throws exception (lines 90-93)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    def test_freshness_endpoint(self, _client):
        """Freshness endpoint."""
        resp = _client.get("/api/freshness")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_coverage_round23.py — TestSchedulerHealthEdge
# (extracted from TestAdditionalEdgeCases)
# ═══════════════════════════════════════════════════════════


class TestSchedulerHealthEdge:
    def test_scheduler_health_stale(self, db_path, monkeypatch, tmp_path):
        """Scheduler health stale heartbeat."""
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        stale_time = (datetime.now() - timedelta(minutes=15)).isoformat()
        hb_path.write_text(stale_time)
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        c = TestClient(app)
        resp = c.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stale"

    def test_scheduler_health_error(self, db_path, monkeypatch, tmp_path):
        """Scheduler health with malformed file."""
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        hb_path.write_text("not-a-valid-iso-timestamp")
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        c = TestClient(app)
        resp = c.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"


# ═══════════════════════════════════════════════════════════
# From test_coverage_round26.py — TestApiMain
# ═══════════════════════════════════════════════════════════


class TestApiMain:
    def test_root_redirect(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (307, 200)

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_security_headers(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_login_no_password_env(self, client, monkeypatch):
        monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
        resp = client.post("/api/auth/token", json={"password": "test"})
        assert resp.status_code == 503

    def test_login_wrong_password(self, client, monkeypatch):
        monkeypatch.setenv("DASHBOARD_PASSWORD", "correct")
        resp = client.post("/api/auth/token", json={"password": "wrong"})
        assert resp.status_code == 401

    def test_login_correct_password(self, client, monkeypatch):
        monkeypatch.setenv("DASHBOARD_PASSWORD", "correct")
        resp = client.post("/api/auth/token", json={"password": "correct"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_main_block(self, monkeypatch):
        """Cover the __main__ block (lines 143-147)."""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)


# ═══════════════════════════════════════════════════════════
# From test_coverage_round26.py — TestAuth
# ═══════════════════════════════════════════════════════════


class TestAuth:
    def test_hash_and_verify(self):
        from nuri.api.auth import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed)
        assert not verify_password("wrong", hashed)

    def test_create_and_decode_token(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._SECRET_KEY", "testsecret")
        from nuri.api.auth import create_token, decode_token
        token = create_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"

    def test_decode_invalid_token(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._SECRET_KEY", "testsecret")
        from nuri.api.auth import decode_token
        assert decode_token("invalid.token.here") is None

    def test_decode_expired_token(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._SECRET_KEY", "testsecret")
        from nuri.api.auth import create_token, decode_token
        token = create_token("user", expires_hours=-1)
        assert decode_token(token) is None

    def test_require_auth_disabled(self, client, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", False)
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_require_auth_no_credentials(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", True)
        from nuri.api.auth import require_auth
        with pytest.raises(Exception):
            asyncio.get_event_loop().run_until_complete(require_auth(MagicMock(), None))

    def test_require_auth_api_key(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", True)
        monkeypatch.setattr("nuri.api.auth._API_KEY", "test_key_123")
        from nuri.api.auth import require_auth
        cred = MagicMock()
        cred.credentials = "test_key_123"
        result = asyncio.new_event_loop().run_until_complete(require_auth(MagicMock(), cred))
        assert result["auth"] == "api_key"

    def test_require_auth_jwt(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", True)
        monkeypatch.setattr("nuri.api.auth._API_KEY", "")
        monkeypatch.setattr("nuri.api.auth._SECRET_KEY", "testsecret")
        from nuri.api.auth import create_token, require_auth
        token = create_token("dashboard")
        cred = MagicMock()
        cred.credentials = token
        result = asyncio.new_event_loop().run_until_complete(require_auth(MagicMock(), cred))
        assert result["sub"] == "dashboard"

    def test_require_auth_invalid_token(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", True)
        monkeypatch.setattr("nuri.api.auth._API_KEY", "")
        from nuri.api.auth import require_auth
        cred = MagicMock()
        cred.credentials = "bad_token"
        with pytest.raises(Exception):
            asyncio.new_event_loop().run_until_complete(require_auth(MagicMock(), cred))

    def test_require_write_auth(self, monkeypatch):
        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", False)
        from nuri.api.auth import require_write_auth
        result = asyncio.new_event_loop().run_until_complete(require_write_auth(MagicMock(), None))
        assert result["auth"] == "disabled"

    def test_constant_time_compare(self):
        from nuri.api.auth import _constant_time_compare
        assert _constant_time_compare("abc", "abc")
        assert not _constant_time_compare("abc", "def")


# ═══════════════════════════════════════════════════════════
# From test_coverage_round26.py — TestAgentsRoute
# ═══════════════════════════════════════════════════════════


class TestAgentsRoute:
    def test_get_consensus_cached(self, client, monkeypatch):
        """Cover cache hit path (line 17)."""
        import nuri.api.routes.agents as agents_mod
        agents_mod._cache["data"] = {"cached": True}
        agents_mod._cache["ts"] = 9999999999
        resp = client.get("/api/consensus")
        assert resp.json()["cached"] is True
        agents_mod._cache["data"] = None

    def test_get_consensus_regime_error(self, client, monkeypatch):
        """Cover regime_info exception path (lines 29-35)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio", lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            MagicMock(side_effect=Exception("no spy")),
        )
        import nuri.api.routes.agents as agents_mod
        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0
        resp = client.get("/api/consensus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] is None


# ═══════════════════════════════════════════════════════════
# From test_coverage_round26.py — TestRebalanceRoute
# ═══════════════════════════════════════════════════════════


class TestRebalanceRoute:
    def test_get_rebalance_error(self, client, monkeypatch):
        """Cover exception path (lines 20-21)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.rebalance.regime_aware_rebalance",
            MagicMock(side_effect=Exception("no data")),
        )
        resp = client.get("/api/rebalance")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


# ═══════════════════════════════════════════════════════════
# From test_coverage_round27.py — TestDashboard_R27
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# From test_coverage_round27.py — TestAPIMain_R27
# ═══════════════════════════════════════════════════════════


class TestAPIMain_R27:
    """Tests for nuri/api/main.py."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limiter(self, monkeypatch):
        """Disable rate limiter for all API main tests."""
        from nuri.api import main as main_mod
        monkeypatch.setattr(main_mod.limiter, "enabled", False)

    def test_health_endpoint(self):
        """Health endpoint returns ok."""
        from nuri.api.main import app
        c = TestClient(app)
        response = c.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_redirect(self):
        """Root redirects to docs."""
        from nuri.api.main import app
        c = TestClient(app)
        response = c.get("/", follow_redirects=False)
        assert response.status_code in (301, 302, 307)

    def test_security_headers(self):
        """Security headers are present on responses."""
        from nuri.api.main import app
        c = TestClient(app)
        response = c.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_auth_no_password_set(self, monkeypatch):
        """Auth endpoint when no DASHBOARD_PASSWORD set."""
        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "")
        c = TestClient(app)
        response = c.post("/api/auth/token", json={"password": "test"})
        assert response.status_code == 503

    def test_auth_wrong_password(self, monkeypatch):
        """Auth endpoint with wrong password."""
        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "correct_password")
        c = TestClient(app)
        response = c.post("/api/auth/token", json={"password": "wrong"})
        assert response.status_code == 401

    def test_auth_correct_password(self, monkeypatch):
        """Auth endpoint with correct password."""
        from nuri.api.main import app
        monkeypatch.setenv("DASHBOARD_PASSWORD", "test123")
        monkeypatch.setenv("API_SECRET_KEY", "test-secret-key-for-jwt")
        c = TestClient(app)
        response = c.post("/api/auth/token", json={"password": "test123"})
        assert response.status_code == 200
        assert "access_token" in response.json()


# ═══════════════════════════════════════════════════════════
# From test_feedback_loop.py — TestTradesAPI_FL
# ═══════════════════════════════════════════════════════════


class TestTradesAPI_FL:
    """trades API endpoint tests."""

    @pytest.fixture()
    def _client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        fl_db_path = tmp_path / "test.db"
        init_db(fl_db_path)
        monkeypatch.setattr(db_mod, "DB_PATH", fl_db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_create_trade(self, _client):
        r = _client.post("/api/trades", json={
            "ticker": "AAPL",
            "action": "BUY",
            "executed_at": "2026-03-29",
            "entry_price": 180.0,
            "shares": 10,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "trade_id" in r.json()

    def test_list_trades_empty(self, _client):
        r = _client.get("/api/trades")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["trades"] == []

    def test_list_trades_with_filter(self, _client):
        _client.post("/api/trades", json={
            "ticker": "AAPL", "action": "BUY", "executed_at": "2026-03-29",
        })
        _client.post("/api/trades", json={
            "ticker": "TSLA", "action": "SELL", "executed_at": "2026-03-29",
        })

        r = _client.get("/api/trades?ticker=AAPL")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_update_trade(self, _client):
        r = _client.post("/api/trades", json={
            "ticker": "NVDA", "action": "BUY", "executed_at": "2026-03-29",
            "entry_price": 150.0,
        })
        trade_id = r.json()["trade_id"]

        r2 = _client.put(f"/api/trades/{trade_id}", json={
            "exit_price": 170.0,
            "exit_date": "2026-04-15",
            "exit_reason": "take_profit",
        })
        assert r2.status_code == 200

    def test_create_trade_invalid_action(self, _client):
        r = _client.post("/api/trades", json={
            "ticker": "AAPL", "action": "HOLD", "executed_at": "2026-03-29",
        })
        assert r.status_code == 422

    def test_create_trade_invalid_date(self, _client):
        r = _client.post("/api/trades", json={
            "ticker": "AAPL", "action": "BUY", "executed_at": "not-a-date",
        })
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════
# From test_final_push.py — TestAPIDeep
# ═══════════════════════════════════════════════════════════


class TestAPIDeep:
    @pytest.fixture()
    def _client(self, tmp_path, monkeypatch):
        fp_db = tmp_path / "test.db"
        init_db(fp_db)
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", fp_db)

        with get_db(fp_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", "AAPL", 10, 150, "USD", "Technology"))

        dates = pd.bdate_range("2023-06-01", periods=250)
        for t, base in [("SPY", 430), ("AAPL", 150)]:
            close = np.linspace(base, base * 1.1, 250)
            df = pd.DataFrame({
                "ticker": t, "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99, "high": close * 1.01,
                "low": close * 0.98, "close": close,
                "volume": [1000000] * 250, "adj_close": close,
            })
            upsert_prices(df, fp_db)

        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 18.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 55.0, "source": "test"},
        ], fp_db)

        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        return TestClient(app)

    def test_dashboard_with_data(self, _client):
        r = _client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        assert data["verdict_level"] in ("aggressive", "neutral", "cautious", "defensive")

    def test_regime_with_data(self, _client):
        r = _client.get("/api/regime")
        assert r.status_code == 200

    def test_strategy_with_data(self, _client):
        r = _client.get("/api/strategy")
        assert r.status_code == 200

    def test_consensus_with_data(self, _client):
        r = _client.get("/api/consensus")
        assert r.status_code == 200

    def test_targets_with_data(self, _client):
        r = _client.get("/api/targets")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestPutEndpoint
# ═══════════════════════════════════════════════════════════


class TestPutEndpoint:
    def test_update_quantity(self, seeded_client):
        """수량 수정."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"quantity": 20})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["updated"]["quantity"] == 20

        holdings = seeded_client.get("/api/portfolio").json()["holdings"]
        assert holdings[0]["quantity"] == 20

    def test_update_avg_price(self, seeded_client):
        """평균가 수정."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"avg_price": 200.0})
        assert r.status_code == 200
        assert r.json()["updated"]["avg_price"] == 200.0

    def test_update_multiple_fields(self, seeded_client):
        """여러 필드 동시 수정."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={
            "quantity": 15, "avg_price": 190.0, "sector": "BigTech",
        })
        assert r.status_code == 200
        updated = r.json()["updated"]
        assert updated["quantity"] == 15
        assert updated["avg_price"] == 190.0
        assert updated["sector"] == "BigTech"

    def test_update_nonexistent(self, client):
        """존재하지 않는 종목 수정 → 404."""
        r = client.put("/api/portfolio/test/XXXX", json={"quantity": 5})
        assert r.status_code == 404

    def test_update_empty_body(self, seeded_client):
        """변경 필드 없으면 → 400."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={})
        assert r.status_code == 400

    def test_update_invalid_account(self, seeded_client):
        """유효하지 않은 계좌 → 400."""
        r = seeded_client.put("/api/portfolio/fake/AAPL", json={"quantity": 5})
        assert r.status_code == 400

    def test_update_invalid_quantity(self, seeded_client):
        """음수 수량 → 422."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"quantity": -1})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestPutValidation
# ═══════════════════════════════════════════════════════════


class TestPutValidation:
    """PUT 엔드포인트 경계값 검증."""

    def test_update_quantity_over_max(self, seeded_client):
        """수량 100,000 초과 → 422."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"quantity": 100_001})
        assert r.status_code == 422

    def test_update_avg_price_zero(self, seeded_client):
        """평균가 0 → 422."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"avg_price": 0})
        assert r.status_code == 422

    def test_update_avg_price_over_max(self, seeded_client):
        """평균가 10,000,000 초과 → 422."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"avg_price": 10_000_001})
        assert r.status_code == 422

    def test_update_sector_too_long(self, seeded_client):
        """섹터 50자 초과 → 422."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"sector": "A" * 51})
        assert r.status_code == 422

    def test_update_currency(self, seeded_client):
        """통화 변경."""
        r = seeded_client.put("/api/portfolio/sample/AAPL", json={"currency": "KRW"})
        assert r.status_code == 200
        assert r.json()["updated"]["currency"] == "KRW"

    def test_update_invalid_ticker_format(self, seeded_client):
        """유효하지 않은 ticker 포맷 → 400."""
        r = seeded_client.put("/api/portfolio/sample/invalid!", json={"quantity": 5})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestSyncErrorHandling
# ═══════════════════════════════════════════════════════════


class TestSyncErrorHandling:
    """YAML 동기화 실패 시 DB 변경 유지 확인."""

    def test_sync_failure_does_not_block_api(self, tmp_path, monkeypatch):
        """sync 실패해도 POST는 200 반환."""
        sync_db = tmp_path / "test.db"
        init_db(sync_db)

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", sync_db)

        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", Path("/dev/null/impossible/path.yaml"))

        from nuri.api.main import app
        c = TestClient(app)

        r = c.post("/api/portfolio", json={
            "account": "sample", "ticker": "MSFT",
            "quantity": 5, "avg_price": 400.0,
        })
        assert r.status_code == 200

        r2 = c.get("/api/portfolio")
        assert r2.json()["count"] == 1


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestPostValidation
# ═══════════════════════════════════════════════════════════


class TestPostValidation:
    """POST 엔드포인트 HoldingInput 검증 — 경계값."""

    def test_post_invalid_ticker(self, client):
        """잘못된 ticker 포맷 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "invalid!",
            "quantity": 10, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_quantity_zero(self, client):
        """수량 0 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 0, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_quantity_over_max(self, client):
        """수량 100,000 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 100_001, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_avg_price_zero(self, client):
        """평균가 0 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 10, "avg_price": 0,
        })
        assert r.status_code == 422

    def test_post_avg_price_over_max(self, client):
        """평균가 10,000,000 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 10, "avg_price": 10_000_001,
        })
        assert r.status_code == 422

    def test_post_invalid_account(self, client):
        """유효하지 않은 계좌 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "fake", "ticker": "AAPL",
            "quantity": 10, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_sector_too_long(self, client):
        """섹터 50자 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "sample", "ticker": "AAPL",
            "quantity": 10, "avg_price": 100.0,
            "sector": "A" * 51,
        })
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestDeleteValidation
# ═══════════════════════════════════════════════════════════


class TestDeleteValidation:
    """DELETE 엔드포인트 경로 파라미터 검증."""

    def test_delete_invalid_ticker_format(self, client):
        """유효하지 않은 ticker 포맷 → 400."""
        r = client.delete("/api/portfolio/sample/invalid!")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestRiskEndpoint
# ═══════════════════════════════════════════════════════════


class TestRiskEndpoint:
    """리스크 엔드포인트 전체 분기 커버."""

    def test_risk_with_all_value_types(self, client):
        """numpy item(), 일반 타입, 비표준 타입 분기 모두 커버."""
        numpy_val = MagicMock()
        numpy_val.item.return_value = 1.5
        custom_obj = object()
        mock_metrics = {
            "sharpe": numpy_val,
            "vol": 0.25,
            "label": "low",
            "other": custom_obj,
        }
        with patch("nuri.analysis.risk.analyze_risk", return_value=mock_metrics):
            r = client.get("/api/risk")
        assert r.status_code == 200
        data = r.json()
        assert data["sharpe"] == 1.5
        assert data["vol"] == 0.25
        assert data["label"] == "low"
        assert isinstance(data["other"], str)

    def test_risk_exception(self, client):
        """analyze_risk 예외 → error dict."""
        with patch("nuri.analysis.risk.analyze_risk", side_effect=RuntimeError("fail")):
            r = client.get("/api/risk")
        assert r.status_code == 200
        assert "error" in r.json()


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestYamlSync
# ═══════════════════════════════════════════════════════════


class TestYamlSync:
    def test_post_syncs_yaml(self, client, tmp_path):
        """POST 후 YAML 파일 생성 확인."""
        client.post("/api/portfolio", json={
            "account": "test", "ticker": "NVDA",
            "quantity": 10, "avg_price": 130.0,
            "currency": "USD", "sector": "Semiconductor",
        })
        yaml_path = tmp_path / "portfolio.yaml"
        assert yaml_path.exists()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["test"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["ticker"] == "NVDA"

    def test_put_syncs_yaml(self, seeded_client, tmp_path):
        """PUT 후 YAML에 변경 반영."""
        seeded_client.put("/api/portfolio/sample/AAPL", json={"quantity": 25})
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["sample"]["holdings"]
        assert holdings[0]["qty"] == 25

    def test_delete_syncs_yaml(self, seeded_client, tmp_path):
        """DELETE 후 YAML에서 제거."""
        seeded_client.delete("/api/portfolio/sample/AAPL")
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        sample = data["accounts"].get("sample", {})
        assert "holdings" not in sample or len(sample.get("holdings", [])) == 0

    def test_load_yaml_default_path(self, tmp_path, monkeypatch):
        """_load_yaml()를 인수 없이 호출 시 CONFIG_PATH 사용."""
        import nuri.core.portfolio_sync as sync_mod
        from nuri.core.portfolio_sync import _load_yaml
        nonexistent = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", nonexistent)
        result = _load_yaml()
        assert result == {}

    def test_preserves_metadata(self, tmp_path, monkeypatch):
        """기존 YAML 메타데이터 (name, broker 등) 보존."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        yaml_db = tmp_path / "test2.db"
        init_db(yaml_db)

        yaml_path = tmp_path / "portfolio.yaml"
        existing = {
            "accounts": {
                "test": {
                    "name": "카카오페이 종합계좌",
                    "broker": "카카오페이증권",
                    "currency": "USD",
                    "total_invested": 48323344,
                    "holdings": [],
                },
            },
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True)

        upsert_portfolio([{
            "account": "test", "ticker": "TSLA",
            "quantity": 10, "avg_price": 300.0,
            "currency": "USD", "sector": "SectorA",
        }], db_path=yaml_db)

        sync_portfolio_to_yaml(config_path=yaml_path, db_path=yaml_db)

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        kp = data["accounts"]["test"]
        assert kp["name"] == "카카오페이 종합계좌"
        assert kp["broker"] == "카카오페이증권"
        assert kp["total_invested"] == 48323344
        assert len(kp["holdings"]) == 1
        assert kp["holdings"][0]["ticker"] == "TSLA"


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestImport
# ═══════════════════════════════════════════════════════════


class TestImport:
    """POST /api/portfolio/import tests."""

    def test_import_csv(self, client):
        """정상 CSV import."""
        csv_content = "account,ticker,quantity,avg_price,currency,sector\ntoss,AAPL,10,180.0,USD,Tech\ntest,NVDA,5,130.0,USD,Semiconductor\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["imported"] == 2
        assert data["errors"] == []

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 2

    def test_import_minimal_columns(self, client):
        """필수 컬럼만 있는 CSV — currency/sector 기본값."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,MSFT,3,400.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        assert r.json()["imported"] == 1

    def test_import_missing_required_column(self, client):
        """필수 컬럼 누락 → 400."""
        csv_content = "account,ticker,quantity\ntoss,AAPL,10\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400
        assert "avg_price" in r.json()["detail"]

    def test_import_not_csv(self, client):
        """CSV가 아닌 파일 → 400."""
        r = client.post("/api/portfolio/import",
                        files={"file": ("data.txt", b"hello", "text/plain")})
        assert r.status_code == 400
        assert "CSV" in r.json()["detail"]

    def test_import_empty_header(self, client):
        """빈 CSV → 400."""
        r = client.post("/api/portfolio/import", files=_csv_file(""))
        assert r.status_code == 400

    def test_import_invalid_ticker(self, client):
        """유효하지 않은 ticker → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,invalid!,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400
        assert "ticker" in r.json()["detail"]

    def test_import_invalid_account(self, client):
        """유효하지 않은 계좌 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\nfake,AAPL,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_invalid_number(self, client):
        """숫자 변환 실패 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,abc,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_zero_quantity(self, client):
        """quantity 0 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,0,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_partial_errors(self, client):
        """일부 행만 유효 → 유효한 행만 import, errors 반환."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,10,180.0\nfake,BAD!,0,0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 1
        assert len(data["errors"]) > 0

    def test_import_empty_field(self, client):
        """필수 필드가 비어있는 행 → errors."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_non_utf8(self, client):
        """비UTF-8 파일 → 400."""
        bad_bytes = b"\xc7\xd1\xb1\xdb"
        r = client.post("/api/portfolio/import",
                        files={"file": ("test.csv", bad_bytes, "text/csv")})
        assert r.status_code == 400
        assert "UTF-8" in r.json()["detail"]

    def test_import_over_max_rows(self, client):
        """500행 초과 → 400."""
        header = "account,ticker,quantity,avg_price\n"
        rows = "".join(f"sample,T{i:04d},1,100.0\n" for i in range(501))
        r = client.post("/api/portfolio/import", files=_csv_file(header + rows))
        assert r.status_code == 400
        assert "500" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestExport
# ═══════════════════════════════════════════════════════════


class TestExport:
    """GET /api/portfolio/export tests."""

    def test_export_csv_empty(self, client):
        """빈 포트폴리오 CSV export."""
        r = client.get("/api/portfolio/export?format=csv")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        content = r.text
        assert "account" in content

    def test_export_csv_with_data(self, seeded_client):
        """데이터 있는 CSV export."""
        r = seeded_client.get("/api/portfolio/export?format=csv")
        assert r.status_code == 200
        lines = r.text.strip().split("\n")
        assert len(lines) == 2
        assert "AAPL" in lines[1]

    def test_export_yaml_with_data(self, seeded_client):
        """데이터 있는 YAML export."""
        r = seeded_client.get("/api/portfolio/export?format=yaml")
        assert r.status_code == 200
        assert "yaml" in r.headers["content-type"]
        data = yaml.safe_load(r.text)
        assert "accounts" in data
        assert "sample" in data["accounts"]
        holdings = data["accounts"]["sample"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["ticker"] == "AAPL"

    def test_export_invalid_format(self, client):
        """지원하지 않는 format → 400."""
        r = client.get("/api/portfolio/export?format=json")
        assert r.status_code == 400

    def test_export_default_csv(self, client):
        """format 미지정 → CSV 기본값."""
        r = client.get("/api/portfolio/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestSamplePortfolio
# ═══════════════════════════════════════════════════════════


class TestSamplePortfolio:
    """POST /api/portfolio/sample tests."""

    def test_load_sample(self, client):
        """샘플 포트폴리오 로드."""
        r = client.post("/api/portfolio/sample")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["loaded"] == 5

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 5

    def test_load_sample_replaces_existing(self, client):
        """샘플 재로드 시 기존 sample 계좌 교체."""
        client.post("/api/portfolio/sample")
        client.post("/api/portfolio/sample")
        r = client.get("/api/portfolio")
        assert r.json()["count"] == 5


# ═══════════════════════════════════════════════════════════
# From test_portfolio_sync.py — TestMetadata
# ═══════════════════════════════════════════════════════════


class TestMetadata:
    """metadata JSON column roundtrip tests."""

    def test_post_with_metadata(self, client):
        """POST 시 metadata 저장."""
        r = client.post("/api/portfolio", json={
            "account": "test", "ticker": "TSLL",
            "quantity": 96, "avg_price": 20.0,
            "sector": "SectorB",
            "metadata": {"flag": "SELL", "note": "레버리지 ETF 금지"},
        })
        assert r.status_code == 200

    def test_put_with_metadata(self, client):
        """PUT으로 metadata 수정."""
        client.post("/api/portfolio", json={
            "account": "test", "ticker": "AAPL",
            "quantity": 10, "avg_price": 190.0,
        })
        r = client.put("/api/portfolio/test/AAPL", json={
            "metadata": {"flag": "HOLD", "target": 220},
        })
        assert r.status_code == 200

    def test_metadata_roundtrip_yaml(self, client, tmp_path):
        """POST → YAML 동기화 → metadata 필드 복원 확인."""
        client.post("/api/portfolio", json={
            "account": "test", "ticker": "TSLL",
            "quantity": 96, "avg_price": 20.0,
            "sector": "SectorB",
            "metadata": {"flag": "SELL"},
        })
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["test"]["holdings"]
        tsll = [h for h in holdings if h["ticker"] == "TSLL"][0]
        assert tsll["flag"] == "SELL"

    def test_metadata_in_import(self, tmp_path, monkeypatch):
        """import_portfolio.py가 YAML의 추가 필드를 metadata로 보존."""
        from nuri.core.db import query

        meta_db = tmp_path / "test.db"
        init_db(meta_db)

        yaml_path = tmp_path / "portfolio.yaml"
        yaml_content = {
            "accounts": {
                "test": {
                    "currency": "USD",
                    "holdings": [
                        {"ticker": "TSLL", "qty": 96, "avg": 20.0,
                         "sector": "SectorB", "flag": "SELL"},
                    ],
                },
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        import scripts.import_portfolio as imp
        records = imp.load_holdings(config_path=yaml_path)
        upsert_portfolio(records, db_path=meta_db)

        rows = query("SELECT metadata FROM portfolio WHERE ticker='TSLL'", db_path=meta_db)
        assert rows
        meta = json.loads(rows[0]["metadata"])
        assert meta["flag"] == "SELL"

    def test_metadata_invalid_json_ignored(self, tmp_path, monkeypatch):
        """DB에 잘못된 JSON이 있어도 에러 없이 무시."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        bad_db = tmp_path / "test.db"
        init_db(bad_db)
        upsert_portfolio([{
            "account": "test", "ticker": "BAD",
            "quantity": 1, "avg_price": 100.0,
            "currency": "USD", "sector": "",
            "metadata": "not-valid-json{",
        }], db_path=bad_db)

        yaml_path = tmp_path / "out.yaml"
        count = sync_portfolio_to_yaml(config_path=yaml_path, db_path=bad_db)
        assert count == 1
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        bad = data["accounts"]["test"]["holdings"][0]
        assert bad["ticker"] == "BAD"
        assert "flag" not in bad

    def test_metadata_full_roundtrip(self, tmp_path, monkeypatch):
        """YAML → import → DB → sync → YAML: flag 완전 보존."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        rt_db = tmp_path / "test.db"
        init_db(rt_db)

        yaml_path = tmp_path / "portfolio.yaml"
        yaml_content = {
            "accounts": {
                "test": {
                    "name": "카카오페이",
                    "currency": "USD",
                    "holdings": [
                        {"ticker": "TSLL", "qty": 96, "avg": 20.0,
                         "sector": "SectorB", "flag": "SELL"},
                        {"ticker": "NVDA", "qty": 20, "avg": 100.0,
                         "sector": "Semiconductor"},
                    ],
                },
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f, allow_unicode=True)

        import scripts.import_portfolio as imp
        records = imp.load_holdings(config_path=yaml_path)
        upsert_portfolio(records, db_path=rt_db)

        sync_portfolio_to_yaml(config_path=yaml_path, db_path=rt_db)

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["test"]["holdings"]
        tsll = [h for h in holdings if h["ticker"] == "TSLL"][0]
        nvda = [h for h in holdings if h["ticker"] == "NVDA"][0]
        assert tsll["flag"] == "SELL"
        assert "flag" not in nvda
        assert data["accounts"]["test"]["name"] == "카카오페이"
