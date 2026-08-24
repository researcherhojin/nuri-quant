"""Tests for routes — split from test_api_all.py."""

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


class TestAPIRoutes:
    def test_targets_route_exists(self):
        from nuri.api.routes.targets import router

        routes = [getattr(r, "path", "") for r in router.routes]
        assert any("targets" in r for r in routes)

    def test_agents_route_exists(self):
        from nuri.api.routes.agents import router

        routes = [getattr(r, "path", "") for r in router.routes]
        assert any("consensus" in r for r in routes)


class TestAPIRoutesExtended:
    def test_stream_route_exists(self):
        from nuri.api.routes.stream import router

        assert router is not None

    def test_signals_route(self):
        from nuri.api.routes.signals import router

        routes = [getattr(r, "path", "") for r in router.routes]
        assert len(routes) > 0

    def test_regime_route(self):
        from nuri.api.routes.regime import router

        routes = [getattr(r, "path", "") for r in router.routes]
        assert len(routes) > 0

    def test_portfolio_route(self):
        from nuri.api.routes.portfolio import router

        routes = [getattr(r, "path", "") for r in router.routes]
        assert len(routes) > 0


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
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "AAPL", 10, 150, "USD", "Technology"),
            )

        dates = pd.bdate_range("2023-06-01", periods=250)
        for t, base in [("SPY", 430), ("AAPL", 150)]:
            close = np.linspace(base, base * 1.1, 250)
            df = pd.DataFrame(
                {
                    "ticker": t,
                    "date": [d.strftime("%Y-%m-%d") for d in dates],
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": [1000000] * 250,
                    "adj_close": close,
                }
            )
            upsert_prices(df, fp_db)

        upsert_macro(
            [
                {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 18.0, "source": "test"},
                {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 55.0, "source": "test"},
            ],
            fp_db,
        )

        import nuri.core.portfolio_sync as sync_mod

        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app

        return TestClient(app)

    @pytest.mark.slow
    def test_dashboard_with_data(self, _client):
        r = _client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        # "stale" 은 #1180 stale gate — 판단 입력이 낡으면 판단을 보류한다
        assert data["verdict_level"] in ("aggressive", "neutral", "cautious", "defensive", "stale")

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
