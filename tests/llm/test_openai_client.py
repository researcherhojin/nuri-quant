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

    def test_audit_row_does_not_contain_content(self, fake_openai_success, db_path):
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

    def test_uses_default_model_when_unspecified(self, fake_openai_success, db_path):
        from nuri.llm.openai_client import DEFAULT_MODEL, OpenAIClient

        OpenAIClient().chat_json(system="s", user="u", db_path=db_path)
        call = fake_openai_success.chat.completions.create.call_args
        assert call.kwargs["model"] == DEFAULT_MODEL

    def test_uses_explicit_model_override(self, fake_openai_success, db_path):
        from nuri.llm.openai_client import OpenAIClient

        OpenAIClient().chat_json(
            system="s",
            user="u",
            model="gpt-5.4-mini",
            db_path=db_path,
        )
        call = fake_openai_success.chat.completions.create.call_args
        assert call.kwargs["model"] == "gpt-5.4-mini"

    def test_uses_max_completion_tokens_not_max_tokens(self, fake_openai_success, db_path):
        """gpt-5.x series renamed the parameter; regression guard."""
        from nuri.llm.openai_client import OpenAIClient

        OpenAIClient().chat_json(system="s", user="u", db_path=db_path)
        call = fake_openai_success.chat.completions.create.call_args
        assert "max_completion_tokens" in call.kwargs
        assert "max_tokens" not in call.kwargs


class TestOptOut:
    def test_disabled_raises_external_llm_disabled(self, monkeypatch, db_path):
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

    def test_disabled_does_not_write_audit_row(self, monkeypatch, db_path):
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
    def test_missing_key_raises_unavailable(self, monkeypatch, db_path):
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
    def test_sdk_exception_raises_unavailable_and_logs_failure(self, monkeypatch, db_path):
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
    def test_invalid_json_raises_response_error(self, monkeypatch, db_path):
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


class TestCostEstimation:
    """estimate_cost_usd + INFO log emission per call (#152 user request)."""

    def test_estimate_cost_known_model(self):
        from nuri.llm.openai_client import estimate_cost_usd

        # gpt-5.4-nano: $0.20/1M in, $1.25/1M out
        # 1000 prompt + 500 completion = 0.001*0.20 + 0.0005*1.25 = $0.000825
        cost = estimate_cost_usd("gpt-5.4-nano", 1000, 500)
        assert cost is not None
        assert abs(cost - 0.000825) < 1e-9

    def test_estimate_cost_unknown_model_returns_none(self):
        from nuri.llm.openai_client import estimate_cost_usd

        assert estimate_cost_usd("nonexistent-model-x", 100, 100) is None

    def test_estimate_cost_zero_tokens(self):
        from nuri.llm.openai_client import estimate_cost_usd

        assert estimate_cost_usd("gpt-5.4-nano", 0, 0) == 0.0

    def test_chat_json_emits_info_log_with_cost(self, fake_openai_success, db_path, caplog):
        """Every successful call must produce one INFO line with the cost."""
        import logging

        from nuri.llm.openai_client import OpenAIClient

        with caplog.at_level(logging.INFO, logger="nuri.llm.openai_client"):
            OpenAIClient().chat_json(system="s", user="u", db_path=db_path)

        # Find the external_llm log line
        external_lines = [r for r in caplog.records if "[external_llm]" in r.getMessage()]
        assert len(external_lines) == 1, f"expected 1 external_llm log, got {len(external_lines)}"
        msg = external_lines[0].getMessage()
        # Format: "[external_llm] openai/gpt-5.4-nano: 42→18 tokens, Nms, $0.xxxxxx"
        assert "openai/gpt-5.4-nano" in msg
        assert "42" in msg  # prompt tokens from fixture
        assert "18" in msg  # completion tokens from fixture
        assert "tokens" in msg
        assert "$0." in msg  # cost present

    def test_chat_json_log_uses_unknown_marker_for_unpriced_model(self, fake_openai_success, db_path, caplog):
        import logging

        from nuri.llm.openai_client import OpenAIClient

        # Override default model to one not in MODEL_PRICING_USD_PER_1M
        with caplog.at_level(logging.INFO, logger="nuri.llm.openai_client"):
            OpenAIClient().chat_json(
                system="s",
                user="u",
                model="hypothetical-future-v9",
                db_path=db_path,
            )

        msgs = [r.getMessage() for r in caplog.records if "[external_llm]" in r.getMessage()]
        assert len(msgs) == 1
        assert "hypothetical-future-v9" in msgs[0]
        assert "$?(unknown model)" in msgs[0]


# ═══════════════════════════════════════════════════════
# chat_text (plain text completion + ZDR / tier gate)
# ═══════════════════════════════════════════════════════


@pytest.fixture()
def fake_openai_text_success(monkeypatch):
    """Replace openai.OpenAI() with a mock that returns plain-text content."""
    fake_message = MagicMock()
    fake_message.content = "## 1. 데이터 완성도\n리포트 본문"
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.return_value = fake_resp

    fake_module = MagicMock()
    fake_module.OpenAI = MagicMock(return_value=fake_sdk)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)

    import nuri.llm.openai_client as mod

    mod._singleton = None

    return fake_sdk


class TestZdrApproved:
    def test_zdr_approved_default_false(self, monkeypatch):
        from nuri.llm.openai_client import zdr_approved

        monkeypatch.delenv("OPENAI_ZDR_APPROVED", raising=False)
        assert zdr_approved() is False

    @pytest.mark.parametrize("value", ["1", "true", "YES"])
    def test_zdr_approved_truthy(self, monkeypatch, value):
        from nuri.llm.openai_client import zdr_approved

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", value)
        assert zdr_approved() is True


class TestChatTextTierGate:
    """STRATEGY §4.4.3 enforcement — ZDR/tier checks happen BEFORE SDK call."""

    def test_unknown_tier_raises_policy_violation(self, fake_openai_text_success, db_path):
        from nuri.llm.openai_client import ExternalLLMPolicyViolation, OpenAIClient

        with pytest.raises(ExternalLLMPolicyViolation, match="not permitted"):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier99", db_path=db_path)

    def test_tier1_not_permitted(self, fake_openai_text_success, db_path):
        """Tier 1 (narrative) explicitly rejected per current policy."""
        from nuri.llm.openai_client import ExternalLLMPolicyViolation, OpenAIClient

        with pytest.raises(ExternalLLMPolicyViolation):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier1", db_path=db_path)

    def test_tier2_without_zdr_raises(self, fake_openai_text_success, db_path, monkeypatch):
        from nuri.llm.openai_client import ExternalLLMPolicyViolation, OpenAIClient

        monkeypatch.delenv("OPENAI_ZDR_APPROVED", raising=False)
        with pytest.raises(ExternalLLMPolicyViolation, match="OPENAI_ZDR_APPROVED"):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)

    def test_tier2_with_zdr_succeeds(self, fake_openai_text_success, db_path, monkeypatch):
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        result = OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)
        assert "데이터 완성도" in result

    def test_tier0_needs_no_zdr(self, fake_openai_text_success, db_path, monkeypatch):
        """Public data (Tier 0) is freely sendable without ZDR."""
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.delenv("OPENAI_ZDR_APPROVED", raising=False)
        result = OpenAIClient().chat_text(system="s", user="u", data_tier="tier0", db_path=db_path)
        assert "리포트" in result

    def test_tier2_call_logs_endpoint_with_tier(self, fake_openai_text_success, db_path, monkeypatch):
        """Audit log endpoint should mark the tier so we can filter in monitoring."""
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)
        rows = query(
            "SELECT endpoint FROM external_llm_calls ORDER BY id DESC LIMIT 1",
            db_path=db_path,
        )
        assert rows[0]["endpoint"] == "chat.completions(tier2)"

    def test_tier_gate_runs_before_sdk_construction(self, fake_openai_text_success, db_path, monkeypatch):
        """ZDR check must fail-fast without contacting the SDK (no audit row)."""
        from nuri.llm.openai_client import ExternalLLMPolicyViolation, OpenAIClient

        monkeypatch.delenv("OPENAI_ZDR_APPROVED", raising=False)
        with pytest.raises(ExternalLLMPolicyViolation):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)
        # No audit row written — the gate ran before `_ensure_sdk`
        rows = query("SELECT COUNT(*) AS c FROM external_llm_calls", db_path=db_path)
        assert rows[0]["c"] == 0


class TestChatTextContent:
    def test_returns_plain_content(self, fake_openai_text_success, db_path, monkeypatch):
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        out = OpenAIClient().chat_text(system="sys", user="body", data_tier="tier2", db_path=db_path)
        assert out == "## 1. 데이터 완성도\n리포트 본문"

    def test_empty_content_returns_empty_string(self, fake_openai_text_success, db_path, monkeypatch):
        """OpenAI can return message.content=None (e.g., max_tokens hit early)."""
        fake_openai_text_success.chat.completions.create.return_value.choices[0].message.content = None
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        out = OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)
        assert out == ""


class TestChatTextErrorPaths:
    """Coverage for SDK exception + audit log failure branches (lines 326-341, 359-360)."""

    def test_sdk_exception_raises_unavailable_and_writes_audit(self, monkeypatch, db_path):
        """SDK call fails → wrapper raises ExternalLLMUnavailable + audit row with error_type."""
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import ExternalLLMUnavailable, OpenAIClient

        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create.side_effect = RuntimeError("boom")
        fake_module = MagicMock()
        fake_module.OpenAI = MagicMock(return_value=fake_sdk)
        monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)
        mod._singleton = None

        with pytest.raises(ExternalLLMUnavailable, match="RuntimeError"):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)

        # Audit row must record the failure (error_type, success=False)
        rows = query("SELECT * FROM external_llm_calls", db_path=db_path)
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["success"] == 0
        assert row["error_type"] == "RuntimeError"
        assert row["endpoint"] == "chat.completions(tier2)"
        # Content never written
        assert "boom" not in json.dumps(row)

    def test_sdk_exception_with_audit_failure_still_raises_unavailable(self, monkeypatch, db_path):
        """If both SDK fails AND audit log write fails, primary error still surfaces."""
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import ExternalLLMUnavailable, OpenAIClient

        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create.side_effect = RuntimeError("network down")
        fake_module = MagicMock()
        fake_module.OpenAI = MagicMock(return_value=fake_sdk)
        monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")
        monkeypatch.delenv("NURI_DISABLE_EXTERNAL_LLM", raising=False)
        mod._singleton = None

        # Make audit log itself raise — wrapper must still raise primary error
        def boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(mod, "log_external_llm_call", boom)

        with pytest.raises(ExternalLLMUnavailable, match="RuntimeError"):
            OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)

    def test_success_path_audit_failure_does_not_mask_result(self, fake_openai_text_success, db_path, monkeypatch):
        """If SDK succeeds but audit log write fails, the response still reaches the caller."""
        import nuri.llm.openai_client as mod
        from nuri.llm.openai_client import OpenAIClient

        monkeypatch.setenv("OPENAI_ZDR_APPROVED", "1")

        def boom(*a, **kw):
            raise OSError("readonly fs")

        monkeypatch.setattr(mod, "log_external_llm_call", boom)

        result = OpenAIClient().chat_text(system="s", user="u", data_tier="tier2", db_path=db_path)
        # Content returned despite audit log failure — observable contract upheld.
        assert "데이터 완성도" in result
