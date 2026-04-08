"""Tests for auth — split from test_api_all.py."""
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
