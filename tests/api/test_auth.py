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
        """credentials=None → HTTPException(401) (line 87)."""
        from fastapi import HTTPException

        monkeypatch.setattr("nuri.api.auth._AUTH_ENABLED", True)
        from nuri.api.auth import require_auth

        # 새 event loop 로 격리 — 다른 test 가 close 한 loop 영향 회피
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(HTTPException) as exc_info:
                loop.run_until_complete(require_auth(MagicMock(), None))
            assert exc_info.value.status_code == 401
        finally:
            loop.close()

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


class TestSecretKeyStartupWarning:
    """`API_SECRET_KEY` 부재는 import 시점에 경고로 표면화된다 (`nuri/api/main.py`).

    이 키는 JWT 서명 키다. 없으면 재시작마다 발급된 토큰이 전부 무효화되는데,
    증상은 "가끔 로그아웃됨" 이라 원인까지 도달하기 어렵다. 경고 한 줄이 그
    거리를 없앤다 — 그러니 그 한 줄이 실제로 나오는지 확인한다.
    """

    def _exec_main_fresh(self, env: dict, caplog):
        """`nuri/api/main.py` 를 **다른 모듈 이름으로** 새로 실행한다.

        `importlib.reload` 를 쓰면 `sys.modules["nuri.api.main"]` 의 app 객체가
        교체돼 같은 워커의 다른 테스트가 옛 app 을 들고 있게 된다. 별칭으로 로드하면
        모듈 본문(=검사 대상)은 그대로 실행되면서 캐시는 건드리지 않는다.
        `load_dotenv` 는 no-op 으로 막는다 — 안 그러면 개발 머신의 `.env` 가 방금
        지운 키를 되살려 로컬에서만 통과한다.
        """
        import importlib.util
        import logging

        import dotenv

        path = Path(__file__).resolve().parents[2] / "nuri" / "api" / "main.py"
        spec = importlib.util.spec_from_file_location("nuri_api_main_probe", path)
        module = importlib.util.module_from_spec(spec)
        with (
            patch.dict("os.environ", env, clear=False),
            patch.object(dotenv, "load_dotenv", lambda *a, **kw: False),
            caplog.at_level(logging.WARNING, logger="nuri.api"),
        ):
            spec.loader.exec_module(module)
        assert hasattr(module, "app"), "모듈 본문이 끝까지 실행되지 않음 — 아래 assert 가 공허해진다"
        return caplog.text

    def test_warns_when_secret_key_is_absent(self, caplog, monkeypatch):
        monkeypatch.delenv("API_SECRET_KEY", raising=False)
        text = self._exec_main_fresh({}, caplog)
        assert "API_SECRET_KEY" in text
        assert "JWT" in text

    def test_silent_when_secret_key_is_set(self, caplog):
        text = self._exec_main_fresh({"API_SECRET_KEY": "x" * 32}, caplog)
        assert "API_SECRET_KEY 미설정" not in text
