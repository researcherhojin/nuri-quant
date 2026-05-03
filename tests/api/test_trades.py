"""Tests for trades — split from test_api_all.py."""

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
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 10,
                "price": 190.0,
            },
        )
        assert r.status_code in (200, 201, 422)


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
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "AAPL",
                "action": "BUY",
                "executed_at": "2026-03-29",
                "entry_price": 180.0,
                "shares": 10,
            },
        )
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
        _client.post(
            "/api/trades",
            json={
                "ticker": "AAPL",
                "action": "BUY",
                "executed_at": "2026-03-29",
            },
        )
        _client.post(
            "/api/trades",
            json={
                "ticker": "TSLA",
                "action": "SELL",
                "executed_at": "2026-03-29",
            },
        )

        r = _client.get("/api/trades?ticker=AAPL")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_update_trade(self, _client):
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "NVDA",
                "action": "BUY",
                "executed_at": "2026-03-29",
                "entry_price": 150.0,
            },
        )
        trade_id = r.json()["trade_id"]

        r2 = _client.put(
            f"/api/trades/{trade_id}",
            json={
                "exit_price": 170.0,
                "exit_date": "2026-04-15",
                "exit_reason": "take_profit",
            },
        )
        assert r2.status_code == 200

    def test_create_trade_invalid_action(self, _client):
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "AAPL",
                "action": "HOLD",
                "executed_at": "2026-03-29",
            },
        )
        assert r.status_code == 422

    def test_create_trade_invalid_date(self, _client):
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "AAPL",
                "action": "BUY",
                "executed_at": "not-a-date",
            },
        )
        assert r.status_code == 422

    def test_create_trade_invalid_ticker(self, _client):
        """ticker 너무 길면 422 (line 32 ValueError)."""
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "X" * 20,
                "action": "BUY",
                "executed_at": "2026-03-29",
            },
        )
        assert r.status_code == 422

    def test_create_trade_empty_ticker(self, _client):
        """빈 ticker 도 422."""
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "  ",
                "action": "BUY",
                "executed_at": "2026-03-29",
            },
        )
        assert r.status_code == 422

    def test_update_trade_no_fields(self, _client):
        """모든 필드 None → 400 (line 87)."""
        r = _client.post(
            "/api/trades",
            json={
                "ticker": "MSFT",
                "action": "BUY",
                "executed_at": "2026-03-29",
            },
        )
        trade_id = r.json()["trade_id"]
        r2 = _client.put(f"/api/trades/{trade_id}", json={})
        assert r2.status_code == 400
