"""Tests for nuri.llm.openai_client — #152 Step 1.

Network-free. The OpenAI SDK is monkeypatched per-test. The audit log
table is created in tmp DBs via the standard init_db fixture pattern.

The wrapper's contract is verified at three levels:

1. **Behavior** — chat_json returns parsed JSON, audit row written
2. **Failure modes** — opt-out, missing creds, network error, JSON parse error
3. **Privacy invariant** — content is never written to the audit log row
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nuri.core.db import init_db, query


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Isolated DB with migration #13 applied."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture()
def fake_openai_success(monkeypatch):
    """Replace openai.OpenAI() with a mock that returns a parseable JSON body.

    Patches the lazy import path so the SDK is never actually constructed.
    """
    fake_message = MagicMock()
    fake_message.content = '{"category": "fed_dovish", "sentiment": 0.4, "confidence": 0.9}'
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = MagicMock(prompt_tokens=42, completion_tokens=18)

    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.return_value = fake_resp

    fake_module = MagicMock()
    fake_module.OpenAI = MagicMock(return_value=fake_sdk)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)

    # Reset singleton so each test gets a fresh client wrapping the fake
    import nuri.llm.openai_client as mod
    mod._singleton = None

    return fake_sdk


class TestStateChecks:
    def test_is_disabled_default_false(self, monkeypatch):
        from nuri.llm.openai_client import is_disabled
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)
        assert is_disabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "ON"])
    def test_is_disabled_truthy_values(self, monkeypatch, value):
        from nuri.llm.openai_client import is_disabled
        monkeypatch.setenv("NURI_DISABLE_EXTERNAL_LLM", value)
        assert is_disabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_is_disabled_falsy_values(self, monkeypatch, value):
        from nuri.llm.openai_client import is_disabled
        monkeypatch.setenv("NURI_DISABLE_EXTERNAL_LLM", value)
        assert is_disabled() is False

    def test_has_credentials_present(self, monkeypatch):
        from nuri.llm.openai_client import has_credentials
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-x")
        assert has_credentials() is True

    def test_has_credentials_missing(self, monkeypatch):
        from nuri.llm.openai_client import has_credentials
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert has_credentials() is False


class TestChatJsonSuccess:
    def test_returns_parsed_json(self, fake_openai_success, db_path):
        from nuri.llm.openai_client import OpenAIClient
        client = OpenAIClient()
        result = client.chat_json(system="sys", user="usr", db_path=db_path)
        assert result == {
            "category": "fed_dovish",
            "sentiment": 0.4,
            "confidence": 0.9,
        }

    def test_writes_audit_row(self, fake_openai_success, db_path):
        from nuri.llm.openai_client import OpenAIClient
        OpenAIClient().chat_json(system="sys", user="usr", db_path=db_path)
        rows = query("SELECT * FROM external_llm_calls", db_path=db_path)
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-5.4-nano"
        assert row["endpoint"] == "chat.completions"
        assert row["prompt_tokens"] == 42
        assert row["completion_tokens"] == 18
        assert row["latency_ms"] is not None
        assert row["latency_ms"] >= 0
        assert row["success"] == 1
        assert row["error_type"] is None

    def test_audit_row_does_not_contain_content(
        self, fake_openai_success, db_path
    ):
        """Content invariant — neither prompt nor response in DB."""
        from nuri.llm.openai_client import OpenAIClient
        OpenAIClient().chat_json(
            system="this is a secret system prompt",
            user="this is a secret user message",
            db_path=db_path,
        )
        rows = query("SELECT * FROM external_llm_calls", db_path=db_path)
        row_str = json.dumps([dict(r) for r in rows])
        assert "secret system prompt" not in row_str
        assert "secret user message" not in row_str
        assert "fed_dovish" not in row_str  # response content not stored either

    def test_uses_default_model_when_unspecified(
        self, fake_openai_success, db_path
    ):
        from nuri.llm.openai_client import DEFAULT_MODEL, OpenAIClient
        OpenAIClient().chat_json(system="s", user="u", db_path=db_path)
        call = fake_openai_success.chat.completions.create.call_args
        assert call.kwargs["model"] == DEFAULT_MODEL

    def test_uses_explicit_model_override(
        self, fake_openai_success, db_path
    ):
        from nuri.llm.openai_client import OpenAIClient
        OpenAIClient().chat_json(
            system="s", user="u", model="gpt-5.4-mini", db_path=db_path,
        )
        call = fake_openai_success.chat.completions.create.call_args
        assert call.kwargs["model"] == "gpt-5.4-mini"

    def test_uses_max_completion_tokens_not_max_tokens(
        self, fake_openai_success, db_path
    ):
        """gpt-5.x series renamed the parameter; regression guard."""
        from nuri.llm.openai_client import OpenAIClient
        OpenAIClient().chat_json(system="s", user="u", db_path=db_path)
        call = fake_openai_success.chat.completions.create.call_args
        assert "max_completion_tokens" in call.kwargs
        assert "max_tokens" not in call.kwargs


class TestOptOut:
    def test_disabled_raises_external_llm_disabled(
        self, monkeypatch, db_path
    ):
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import (
            ExternalLLMDisabled,
            OpenAIClient,
        )
        mod._singleton = None
        monkeypatch.setenv("NURI_DISABLE_EXTERNAL_LLM", "1")
        client = OpenAIClient()
        with pytest.raises(ExternalLLMDisabled):
            client.chat_json(system="s", user="u", db_path=db_path)

    def test_disabled_does_not_write_audit_row(
        self, monkeypatch, db_path
    ):
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import (
            ExternalLLMDisabled,
            OpenAIClient,
        )
        mod._singleton = None
        monkeypatch.setenv("NURI_DISABLE_EXTERNAL_LLM", "1")
        client = OpenAIClient()
        with pytest.raises(ExternalLLMDisabled):
            client.chat_json(system="s", user="u", db_path=db_path)
        rows = query("SELECT * FROM external_llm_calls", db_path=db_path)
        # Opt-out means no call was attempted, so no audit row.
        assert len(rows) == 0


class TestMissingCredentials:
    def test_missing_key_raises_unavailable(
        self, monkeypatch, db_path
    ):
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import (
            ExternalLLMUnavailable,
            OpenAIClient,
        )
        mod._singleton = None
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)
        client = OpenAIClient()
        with pytest.raises(ExternalLLMUnavailable):
            client.chat_json(system="s", user="u", db_path=db_path)


class TestNetworkFailure:
    def test_sdk_exception_raises_unavailable_and_logs_failure(
        self, monkeypatch, db_path
    ):
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import (
            ExternalLLMUnavailable,
            OpenAIClient,
        )
        mod._singleton = None
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)

        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create.side_effect = ConnectionError("network down")
        fake_module = MagicMock()
        fake_module.OpenAI = MagicMock(return_value=fake_sdk)
        monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)

        client = OpenAIClient()
        with pytest.raises(ExternalLLMUnavailable, match="ConnectionError"):
            client.chat_json(system="s", user="u", db_path=db_path)

        # Failure should still write an audit row with success=0
        rows = query("SELECT success, error_type FROM external_llm_calls", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error_type"] == "ConnectionError"


class TestMalformedResponse:
    def test_invalid_json_raises_response_error(
        self, monkeypatch, db_path
    ):
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import (
            ExternalLLMResponseError,
            OpenAIClient,
        )
        mod._singleton = None
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)

        fake_message = MagicMock()
        fake_message.content = "this is not valid json {{{"
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=fake_message)]
        fake_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create.return_value = fake_resp
        fake_module = MagicMock()
        fake_module.OpenAI = MagicMock(return_value=fake_sdk)
        monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)

        client = OpenAIClient()
        with pytest.raises(ExternalLLMResponseError, match="non-JSON"):
            client.chat_json(system="s", user="u", db_path=db_path)

        # Successful HTTP call but unparseable body — audit row marked success=1
        # because the network worked. Caller's job to retry / fall back.
        rows = query("SELECT success FROM external_llm_calls", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["success"] == 1


class TestSingleton:
    def test_get_client_returns_same_instance(self, monkeypatch):
        import nuri.llm.openai_client as mod
        mod._singleton = None
        from nuri.llm.openai_client import get_client
        a = get_client()
        b = get_client()
        assert a is b
