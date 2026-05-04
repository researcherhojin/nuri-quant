"""DiscordPublisher tests (#529 Phase 2 — webhook outbound).

검증:
- 4채널 enum + env routing
- httpx 200/204 → ok=True + audit row
- httpx 5xx/429 → 1회 retry
- 영구 실패 → ok=False + error 기록 (raise X)
- env 누락 → graceful skip + 'webhook missing' audit
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from nuri.agents.discord.publisher import (
    Channel,
    DiscordPublisher,
    publish,
)
from nuri.core.db import init_db, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "discord.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """publisher 의 log_agent_message 호출을 임시 db 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    with patch(
        "nuri.agents.discord.publisher.log_agent_message",
        side_effect=make_redirect(db_module.log_agent_message),
    ):
        yield db_path


@pytest.fixture
def env_webhooks(monkeypatch):
    """4채널 모두 fake URL 채움."""
    monkeypatch.setenv("DISCORD_WEBHOOK_BRIEF", "https://discord.com/api/webhooks/1/aaa")
    monkeypatch.setenv("DISCORD_WEBHOOK_OPS", "https://discord.com/api/webhooks/2/bbb")
    monkeypatch.setenv("DISCORD_WEBHOOK_INCIDENTS", "https://discord.com/api/webhooks/3/ccc")
    monkeypatch.setenv("DISCORD_WEBHOOK_ROLLOUT", "https://discord.com/api/webhooks/4/ddd")


class TestChannelEnum:
    def test_env_var_uppercase(self):
        assert Channel.BRIEF.env_var == "DISCORD_WEBHOOK_BRIEF"
        assert Channel.OPS.env_var == "DISCORD_WEBHOOK_OPS"
        assert Channel.INCIDENTS.env_var == "DISCORD_WEBHOOK_INCIDENTS"
        assert Channel.ROLLOUT.env_var == "DISCORD_WEBHOOK_ROLLOUT"
        assert Channel.AGENT_CONTROL.env_var == "DISCORD_WEBHOOK_AGENT_CONTROL"
        assert Channel.AGENT_DEV_LOG.env_var == "DISCORD_WEBHOOK_AGENT_DEV_LOG"

    def test_string_values_match_db_check(self):
        # DB CHECK constraint (migration 41 + 42): 6 채널.
        assert {c.value for c in Channel} == {
            "brief",
            "ops",
            "incidents",
            "rollout",
            "agent_control",
            "agent_dev_log",
        }


class TestEnrichEmbedPayload:
    def test_injects_author_when_actor_name_set_and_no_author(self):
        payload = {"embeds": [{"title": "Decision BLOCKED — NVDA", "description": "..."}]}
        out = DiscordPublisher._enrich_embed_payload(payload, "decision_compiler")
        assert out["embeds"][0]["author"] == {"name": "decision_compiler"}

    def test_preserves_caller_provided_author(self):
        payload = {"embeds": [{"title": "T", "author": {"name": "custom"}}]}
        out = DiscordPublisher._enrich_embed_payload(payload, "decision_compiler")
        assert out["embeds"][0]["author"] == {"name": "custom"}

    def test_noop_when_no_actor_name(self):
        payload = {"embeds": [{"title": "T"}]}
        out = DiscordPublisher._enrich_embed_payload(payload, None)
        assert out is payload  # 원본 reference 그대로

    def test_noop_when_no_embeds(self):
        payload = {"content": "text-only message"}
        out = DiscordPublisher._enrich_embed_payload(payload, "actor")
        assert out is payload

    def test_truncates_long_actor_name_to_256(self):
        payload = {"embeds": [{"title": "T"}]}
        out = DiscordPublisher._enrich_embed_payload(payload, "x" * 500)
        assert len(out["embeds"][0]["author"]["name"]) == 256

    def test_does_not_mutate_input_dict(self):
        original_embed = {"title": "T"}
        payload = {"embeds": [original_embed]}
        DiscordPublisher._enrich_embed_payload(payload, "actor")
        # caller 의 dict 가 변경되면 안 됨 (idempotency)
        assert "author" not in original_embed


class TestPublishSuccess:
    def test_text_204_records_ok_and_audit(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(204)
            pub = DiscordPublisher()
            result = pub.publish_text(Channel.BRIEF, "hello world", actor_name="cli")

        assert result.ok is True
        assert result.http_status == 204
        assert result.retry_count == 0

        rows = query(
            "SELECT channel, http_status, content_preview, retry_count FROM agent_messages",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["channel"] == "brief"
        assert rows[0]["http_status"] == 204
        assert rows[0]["retry_count"] == 0
        assert rows[0]["content_preview"] == "hello world"

    def test_embed_records_title_and_description_preview(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(200)
            pub = DiscordPublisher()
            result = pub.publish_embed(
                Channel.OPS,
                {"title": "FAIL: prices", "description": "stale 150h"},
                actor_name="freshness-gatekeeper",
            )

        assert result.ok is True
        rows = query("SELECT content_preview FROM agent_messages", db_path=patched_db)
        assert "FAIL: prices" in rows[0]["content_preview"]
        assert "stale 150h" in rows[0]["content_preview"]


class TestPublishRetry:
    def test_503_retried_once_then_success(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = [
                httpx.Response(503),
                httpx.Response(204),
            ]
            with patch("time.sleep"):
                pub = DiscordPublisher()
                result = pub.publish_text(Channel.OPS, "retry-test")

        assert result.ok is True
        assert result.retry_count == 1

    def test_503_persistent_fails(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(503, text="overloaded")
            with patch("time.sleep"):
                pub = DiscordPublisher()
                result = pub.publish_text(Channel.INCIDENTS, "die-test")

        assert result.ok is False
        assert result.http_status == 503
        assert "503" in (result.error or "")
        rows = query(
            "SELECT http_status, error_message FROM agent_messages WHERE channel='incidents'",
            db_path=patched_db,
        )
        assert rows[0]["http_status"] == 503
        assert "503" in rows[0]["error_message"]

    def test_400_not_retried(self, env_webhooks, patched_db):
        """4xx (Discord rejection) 은 retry 안함 — payload 가 잘못됐으니 재시도 무의미."""
        post_calls = 0

        def _post(*a, **kw):
            nonlocal post_calls
            post_calls += 1
            return httpx.Response(400, text="invalid embed")

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = _post
            pub = DiscordPublisher()
            result = pub.publish_text(Channel.BRIEF, "bad")

        assert result.ok is False
        assert post_calls == 1  # no retry


class TestEnvMissing:
    def test_missing_env_skips_gracefully(self, monkeypatch, patched_db):
        monkeypatch.delenv("DISCORD_WEBHOOK_BRIEF", raising=False)
        pub = DiscordPublisher()
        result = pub.publish_text(Channel.BRIEF, "no-env-test")

        assert result.ok is False
        assert result.http_status is None
        assert "missing" in (result.error or "").lower()

        rows = query(
            "SELECT error_message FROM agent_messages WHERE channel='brief'",
            db_path=patched_db,
        )
        assert "missing" in rows[0]["error_message"].lower()


class TestNetworkError:
    def test_connect_error_retried(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = [
                httpx.ConnectError("conn refused"),
                httpx.Response(204),
            ]
            with patch("time.sleep"):
                pub = DiscordPublisher()
                result = pub.publish_text(Channel.ROLLOUT, "net-flaky")

        assert result.ok is True
        assert result.retry_count == 1

    def test_connect_error_persistent_breaks_after_final_attempt(self, env_webhooks, patched_db):
        """모든 attempt 가 HTTPError → 마지막 attempt 의 break 분기 실행 (sync, line 227)."""
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = [
                httpx.ConnectError("conn refused 1"),
                httpx.ConnectError("conn refused 2"),
            ]
            with patch("time.sleep"):
                pub = DiscordPublisher()
                result = pub.publish_text(Channel.ROLLOUT, "net-dead")

        assert result.ok is False
        assert "ConnectError" in (result.error or "")
        # MAX_RETRIES + 1 = 2 attempts; retry_count records final attempt count
        assert result.retry_count == DiscordPublisher.MAX_RETRIES


class TestModulePublish:
    def test_module_publish_singleton(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(204)
            result = publish(Channel.OPS, "from module-level")
        assert result.ok is True

    def test_module_publish_accepts_string(self, env_webhooks, patched_db):
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(204)
            result = publish("brief", "string-channel")
        assert result.ok is True
        assert result.channel == Channel.BRIEF


class TestAsyncPublish:
    @staticmethod
    def _mock_async_client(*responses):
        """Build httpx.AsyncClient mock yielding given responses (or raising)."""
        from unittest.mock import AsyncMock, MagicMock

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=list(responses))
        return mock_client

    def test_async_text_success(self, env_webhooks, patched_db):
        import asyncio

        mock_client = self._mock_async_client(httpx.Response(204))
        with patch("httpx.AsyncClient", return_value=mock_client):
            pub = DiscordPublisher()
            result = asyncio.run(pub.apublish_text(Channel.BRIEF, "async-hi"))
        assert result.ok is True
        assert result.http_status == 204

    def test_async_embed_success(self, env_webhooks, patched_db):
        import asyncio

        mock_client = self._mock_async_client(httpx.Response(200))
        with patch("httpx.AsyncClient", return_value=mock_client):
            pub = DiscordPublisher()
            result = asyncio.run(pub.apublish_embed(Channel.OPS, {"title": "T", "description": "D"}))
        assert result.ok is True
        rows = query("SELECT content_preview FROM agent_messages", db_path=patched_db)
        assert "T" in rows[0]["content_preview"] and "D" in rows[0]["content_preview"]

    def test_async_503_retried_then_success(self, env_webhooks, patched_db):
        import asyncio

        mock_client = self._mock_async_client(httpx.Response(503), httpx.Response(204))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch(
                "asyncio.sleep", new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
            ):
                pub = DiscordPublisher()
                result = asyncio.run(pub.apublish_text(Channel.OPS, "async-retry"))
        assert result.ok is True
        assert result.retry_count == 1

    def test_async_503_persistent_fails(self, env_webhooks, patched_db):
        import asyncio
        from unittest.mock import AsyncMock

        mock_client = self._mock_async_client(
            httpx.Response(503, text="overloaded"),
            httpx.Response(503, text="overloaded"),
        )
        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                pub = DiscordPublisher()
                result = asyncio.run(pub.apublish_text(Channel.INCIDENTS, "async-die"))
        assert result.ok is False
        assert result.http_status == 503
        assert "503" in (result.error or "")

    def test_async_connect_error_retried_to_success(self, env_webhooks, patched_db):
        import asyncio
        from unittest.mock import AsyncMock

        mock_client = self._mock_async_client(httpx.ConnectError("nope"), httpx.Response(204))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                pub = DiscordPublisher()
                result = asyncio.run(pub.apublish_text(Channel.ROLLOUT, "async-net"))
        assert result.ok is True
        assert result.retry_count == 1

    def test_async_connect_error_persistent_breaks_after_final(self, env_webhooks, patched_db):
        """async: 모든 attempt 가 HTTPError → final break 분기 (line 285)."""
        import asyncio
        from unittest.mock import AsyncMock

        mock_client = self._mock_async_client(
            httpx.ConnectError("conn 1"),
            httpx.ConnectError("conn 2"),
        )
        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                pub = DiscordPublisher()
                result = asyncio.run(pub.apublish_text(Channel.ROLLOUT, "async-net-dead"))

        assert result.ok is False
        assert "ConnectError" in (result.error or "")
        assert result.retry_count == DiscordPublisher.MAX_RETRIES

    def test_async_missing_env_skips(self, monkeypatch, patched_db):
        import asyncio

        monkeypatch.delenv("DISCORD_WEBHOOK_BRIEF", raising=False)
        pub = DiscordPublisher()
        result = asyncio.run(pub.apublish_text(Channel.BRIEF, "async-no-env"))
        assert result.ok is False
        assert result.http_status is None
        assert "missing" in (result.error or "").lower()


class TestCli:
    def test_cli_publish_returns_0(self, env_webhooks, patched_db, capsys):
        from nuri.agents.discord.publisher import main

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = httpx.Response(204)
            rc = main(["brief", "cli-smoke"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "✅" in out

    def test_cli_publish_returns_1_on_fail(self, monkeypatch, patched_db):
        from nuri.agents.discord.publisher import main

        monkeypatch.delenv("DISCORD_WEBHOOK_OPS", raising=False)
        rc = main(["ops", "no-env"])
        assert rc == 1

    def test_publisher_runpy_main(self, monkeypatch):
        """__main__ block (lines 366-368): runpy invocation — invalid channel → argparse exit 2."""
        import io
        import runpy
        import sys

        # 잘못된 채널 → argparse choices 위반 → SystemExit(2). 외부 webhook 안 건드림.
        monkeypatch.setattr(sys, "argv", ["publisher", "not-a-channel", "smoke"])
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("nuri.agents.discord.publisher", run_name="__main__")
        assert exc.value.code == 2
