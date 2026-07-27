"""Tests for main — split from test_api_all.py."""

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
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"  # A2 fix: /evidence iframe

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
    def test_cors_allows_every_mutating_method(self, client, method):
        """CORS allow_methods 는 실제 라우트가 쓰는 메서드를 전부 덮어야 한다.

        PUT 이 빠져 있으면 cross-origin preflight 가 400 (Disallowed CORS method).
        프론트는 Next rewrite 로 same-origin 이라 preflight 가 안 떠서 이 결함이
        브라우저 cross-origin 에서만 드러남 — TestClient 로 직접 잠근다.
        """
        resp = client.options(
            "/api/portfolio/main/AAPL",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
            },
        )
        assert resp.status_code == 200, f"{method} preflight rejected"
        assert method in resp.headers.get("access-control-allow-methods", "")

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
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"  # A2 fix: /evidence iframe

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


class TestApiMainRunpy:
    """`__main__` block (lines 166-171): runpy invocation with uvicorn.run mocked."""

    def test_main_module_starts_uvicorn(self, monkeypatch):
        import runpy
        import sys

        monkeypatch.setenv("API_PORT", "9999")
        # uvicorn 모듈 자체를 mock 으로 sys.modules 주입 → import uvicorn / uvicorn.run 호출 캡처
        fake_uvicorn = MagicMock()
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
        monkeypatch.setattr(sys, "argv", ["main"])

        runpy.run_module("nuri.api.main", run_name="__main__")

        fake_uvicorn.run.assert_called_once()
        kwargs = fake_uvicorn.run.call_args.kwargs
        assert kwargs.get("port") == 9999
        assert kwargs.get("host") == "0.0.0.0"
