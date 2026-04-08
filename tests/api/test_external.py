"""Tests for external — split from test_api_all.py."""
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


class TestExternalAPI:
    def test_external(self, client):
        r = client.get("/api/external")
        assert r.status_code == 200

    def test_external_ticker(self, client):
        r = client.get("/api/external/AAPL")
        assert r.status_code == 200


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
