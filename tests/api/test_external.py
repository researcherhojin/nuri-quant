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
        resp = _client.post(
            "/api/external",
            json={
                "source": "tipranks",
                "ticker": "AAPL",
                "data_type": "consensus",
                "value": "Strong Buy",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_save_tipranks_batch(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.collectors.external.save_tipranks", lambda **kw: True)
        resp = _client.post(
            "/api/external/tipranks",
            json=[
                {"ticker": "AAPL", "consensus": "Buy", "target_price": "200.0", "analyst_count": 30},
                {"ticker": "MSFT", "consensus": "Strong Buy", "target_price": "400.0"},
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] == 2

    def test_save_tipranks_batch_with_error(self, _client, monkeypatch):
        def bad_save(**kw):
            if kw["ticker"] == "AAPL":
                raise ValueError("fail")
            return True

        monkeypatch.setattr("nuri.collectors.external.save_tipranks", bad_save)
        resp = _client.post(
            "/api/external/tipranks",
            json=[
                {"ticker": "AAPL", "consensus": "Buy", "target_price": "200.0"},
                {"ticker": "MSFT", "consensus": "Buy", "target_price": "300.0"},
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] == 1

    def test_unparseable_research_details_are_not_republished(self, _client, db_path):
        """company_research 의 details 가 깨졌으면 원문을 그대로 흘리지 않는다 — 공개 dossier 필터를
        거칠 수 없는 값은 빈 dossier 로 바꾼다."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO external_analysis (date, source, ticker, data_type, details) VALUES (?, ?, ?, ?, ?)",
                ("2026-01-01", "yahoo_finance", "DEMO", "company_research", "PRIVATE RAW BODY {"),
            )
        resp = _client.get("/api/external/demo")
        assert resp.status_code == 200
        assert [item["details"] for item in resp.json()["data"]] == ["{}"]

    def test_rejected_write_is_reported_and_leaves_no_audit_row(self, _client, db_path):
        """저장이 거부되면(미등록 소스) ok=False 이고 감사 로그에 쓰기 흔적을 남기지 않는다."""
        from nuri.core.db import query

        def audit_rows():
            return query("SELECT ticker FROM audit_log WHERE table_name = 'external_analysis'", db_path=db_path)

        body = {"ticker": "demo", "data_type": "consensus", "value": "Buy"}
        assert _client.post("/api/external", json={"source": "tipranks", **body}).json() == {"ok": True}
        assert audit_rows() == [{"ticker": "DEMO"}]

        assert _client.post("/api/external", json={"source": "not_a_source", **body}).json() == {"ok": False}
        assert audit_rows() == [{"ticker": "DEMO"}]
        assert query("SELECT source FROM external_analysis", db_path=db_path) == [{"source": "tipranks"}]
