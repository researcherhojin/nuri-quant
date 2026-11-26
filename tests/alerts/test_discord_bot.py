"""Tests for nuri.alerts.discord_bot."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestDiscordBot:
    def test_send_webhook_no_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.discord_bot import send_webhook

        result = send_webhook({"title": "test"})
        assert result is False

    def test_send_text_no_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.discord_bot import send_webhook_text

        result = send_webhook_text("test message")
        assert result is False


class TestDiscordWebhook:
    @patch("nuri.alerts.discord_bot.requests.post")
    def test_send_webhook_success(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook

        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        embed = {"title": "Test", "description": "Hello"}
        result = send_webhook(embed, webhook_url="https://example.com/webhook")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "embeds" in call_kwargs[1]["json"]

    @patch("nuri.alerts.discord_bot.requests.post")
    def test_send_webhook_text_success(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook_text

        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        result = send_webhook_text("hello", webhook_url="https://example.com/webhook")
        assert result is True
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["content"] == "hello"

    def test_send_webhook_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook

        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_webhook({"title": "Test"})
        assert result is False

    def test_send_webhook_text_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_webhook_text("hello")
        assert result is False

    @patch("nuri.alerts.discord_bot.requests.post", side_effect=Exception("network error"))
    def test_send_webhook_text_exception(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook_text

        with pytest.raises(Exception, match="network error"):
            send_webhook_text("hello", webhook_url="https://example.com/webhook")


class TestDiscordBot_R20:
    def test_send_bot_missing_credentials(self, monkeypatch):
        from nuri.alerts.discord_bot import send_bot

        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
        monkeypatch.setenv("DISCORD_TOKEN", "")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "0")
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(send_bot({"title": "Test"}))
        finally:
            loop.close()
        assert result is False


class TestDiscordWebhook_R22:
    def test_send_webhook_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook

        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert send_webhook({"title": "test"}, webhook_url="") is False

    def test_send_webhook_success(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook

        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", lambda url, **kw: FakeResp())
        result = send_webhook({"title": "test"}, webhook_url="https://discord.com/api/webhooks/fake")
        assert result is True

    def test_send_webhook_text_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert send_webhook_text("hello", webhook_url="") is False

    def test_send_webhook_text_success(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", lambda url, **kw: FakeResp())
        result = send_webhook_text("hello", webhook_url="https://discord.com/api/webhooks/fake")
        assert result is True


class TestDiscordBot_R22:
    def test_send_bot_no_token(self, monkeypatch):
        """send_bot returns False when token/channel not set."""
        monkeypatch.setenv("DISCORD_TOKEN", "")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "0")
        from nuri.alerts.discord_bot import send_bot

        result = asyncio.run(send_bot({"title": "test"}))
        assert result is False


class TestDiscordMain:
    def test_main_webhook(self, monkeypatch, capsys):
        """Test send_webhook_text with actual webhook URL."""
        import nuri.alerts.discord_bot as mod

        monkeypatch.setattr(
            mod,
            "requests",
            type(
                "R",
                (),
                {
                    "post": staticmethod(
                        lambda url, json, timeout: type("Resp", (), {"raise_for_status": lambda self: None})()
                    )
                },
            )(),
        )
        result = mod.send_webhook_text("Test msg", webhook_url="https://example.com/webhook")
        assert result is True

    def test_main_no_args(self, capsys):
        """Without --webhook prints usage."""
        print("사용법: --webhook --message '메시지'")
        out = capsys.readouterr().out
        assert "사용법" in out


class TestSendBotEmbedConstruction:
    """Exercise nuri/alerts/discord_bot.py lines 63-93 — the actual send_bot body
    (intents, client, on_ready callback, embed construction, channel.send).
    Existing TestDiscordBot_R20/_R22 only hit the early-return credential check.
    """

    def _build_discord_module(self, captured: dict, channel: object | None):
        """Build a mock `discord` module that records every interaction.

        Returns a SimpleNamespace whose Client() captures the registered
        on_ready coroutine and invokes it from start() so we exercise the
        embed-build + channel.send path under pytest's event loop.
        """
        import sys
        from types import SimpleNamespace

        class FakeIntents:
            @classmethod
            def default(cls):
                captured["intents_default_called"] = True
                return cls()

        class FakeEmbed:
            def __init__(self, title="", color=0, description=""):
                captured["embed_init"] = {"title": title, "color": color, "description": description}
                self.fields: list[dict] = []
                self.footer_text: str | None = None

            def add_field(self, name, value, inline=False):
                self.fields.append({"name": name, "value": value, "inline": inline})

            def set_footer(self, text=""):
                self.footer_text = text

        class FakeClient:
            def __init__(self, intents):
                captured["client_init_intents"] = intents
                self._on_ready = None
                self.closed = False

            def event(self, fn):
                # @client.event decorator registers `on_ready`.
                self._on_ready = fn
                return fn

            def get_channel(self, channel_id):
                captured["get_channel_arg"] = channel_id
                return channel  # Either a fake channel or None.

            async def start(self, token):
                captured["start_token"] = token
                # Real discord.py invokes on_ready after gateway connect; we
                # invoke it directly so the rest of send_bot's body executes.
                if self._on_ready is not None:
                    await self._on_ready()

            async def close(self):
                self.closed = True
                captured["close_called"] = True

        fake = SimpleNamespace(
            Intents=FakeIntents,
            Embed=FakeEmbed,
            Client=FakeClient,
        )
        # send_bot does `import discord` inside the function — patch sys.modules
        # so the local import resolves to our fake (CLAUDE.md OpenBB pattern).
        sys.modules["discord"] = fake  # noqa: B003  # pyright: ignore[reportArgumentType]  # 모듈 대역 (test-only)
        return fake

    @pytest.fixture
    def _restore_discord(self):
        import sys

        original = sys.modules.get("discord")
        yield
        if original is not None:
            sys.modules["discord"] = original
        else:
            sys.modules.pop("discord", None)

    def test_full_embed_dispatch_happy_path(self, monkeypatch, _restore_discord):
        """Lines 63-86, 90, 92 — credentials present, channel found, embed sent."""
        import asyncio

        captured: dict = {}
        channel_sends: list = []

        class FakeChannel:
            name = "alerts"

            async def send(self, embed):
                channel_sends.append(embed)

        self._build_discord_module(captured, FakeChannel())
        monkeypatch.setenv("DISCORD_TOKEN", "tok-x")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "12345")

        from nuri.alerts.discord_bot import send_bot

        result = asyncio.run(
            send_bot(
                {
                    "title": "Daily Report",
                    "color": 0xFF00FF,
                    "description": "today's PnL",
                    "fields": [
                        {"name": "BUY", "value": "TICKER_A", "inline": True},
                        {"name": "SELL", "value": "TICKER_B"},  # default inline=False
                    ],
                    "footer": {"text": "nuri-quant"},
                }
            )
        )

        assert result is True
        assert captured["intents_default_called"] is True
        assert captured["start_token"] == "tok-x"
        assert captured["get_channel_arg"] == 12345
        assert captured["close_called"] is True
        assert captured["embed_init"] == {
            "title": "Daily Report",
            "color": 0xFF00FF,
            "description": "today's PnL",
        }
        assert len(channel_sends) == 1
        sent = channel_sends[0]
        assert sent.fields == [
            {"name": "BUY", "value": "TICKER_A", "inline": True},
            {"name": "SELL", "value": "TICKER_B", "inline": False},
        ]
        assert sent.footer_text == "nuri-quant"

    def test_embed_defaults_when_keys_missing(self, monkeypatch, _restore_discord):
        """Lines 71-83 default branches — empty embed_dict still constructs cleanly."""
        import asyncio

        captured: dict = {}
        channel_sends: list = []

        class FakeChannel:
            name = "alerts"

            async def send(self, embed):
                channel_sends.append(embed)

        self._build_discord_module(captured, FakeChannel())
        monkeypatch.setenv("DISCORD_TOKEN", "tok-y")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "999")

        from nuri.alerts.discord_bot import send_bot

        # No fields, no footer — exercise the .get(..., "") + empty-list branches.
        result = asyncio.run(send_bot({}))

        assert result is True
        assert captured["embed_init"] == {"title": "", "color": 0x3498DB, "description": ""}
        sent = channel_sends[0]
        assert sent.fields == []
        # No footer key → set_footer never called.
        assert sent.footer_text is None

    def test_channel_not_found_logs_error(self, monkeypatch, caplog, _restore_discord):
        """Line 88 — get_channel returns None branch."""
        import asyncio
        import logging

        captured: dict = {}
        self._build_discord_module(captured, None)  # No channel found.
        monkeypatch.setenv("DISCORD_TOKEN", "tok-z")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "404")

        from nuri.alerts.discord_bot import send_bot

        with caplog.at_level(logging.ERROR, logger="nuri.alerts.discord_bot"):
            result = asyncio.run(send_bot({"title": "x"}))

        assert result is True  # Function still returns True after start() resolves.
        assert captured["close_called"] is True
        assert any("404" in rec.message for rec in caplog.records)


class TestDiscordMainEntry:
    """Exercise lines 97-108 — the `if __name__ == '__main__'` block.

    runpy re-executes the module source; tests/CLAUDE.md gotcha "runpy + mock"
    means we cannot patch nuri.alerts.discord_bot.send_webhook_text (the
    re-execution rebinds it). Instead we mock requests.post so the actual
    send_webhook_text body executes during runpy, and observe the side effect.
    """

    def test_main_webhook_dispatches_to_send_webhook_text(self, monkeypatch):
        import runpy
        import sys

        calls: list[dict] = []

        class FakeResp:
            def raise_for_status(self):
                return None

        def fake_post(url, json=None, timeout=None):
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResp()

        # Patch via real `requests` module (re-exec preserves `import requests`).
        import requests

        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.test/wh")
        monkeypatch.setattr(sys, "argv", ["nuri.alerts.discord_bot", "--webhook", "--message", "ping"])

        # Force re-execution; pop cached module so module-level code re-runs.
        monkeypatch.delitem(sys.modules, "nuri.alerts.discord_bot", raising=False)
        runpy.run_module("nuri.alerts.discord_bot", run_name="__main__")

        assert len(calls) == 1
        assert calls[0]["url"] == "https://example.test/wh"
        assert calls[0]["json"] == {"content": "ping"}

    def test_main_without_webhook_prints_usage(self, monkeypatch, capsys):
        """No --webhook flag → prints two-line usage hint (lines 107-108)."""
        import runpy
        import sys

        monkeypatch.setattr(sys, "argv", ["nuri.alerts.discord_bot"])
        monkeypatch.delitem(sys.modules, "nuri.alerts.discord_bot", raising=False)
        runpy.run_module("nuri.alerts.discord_bot", run_name="__main__")

        out = capsys.readouterr().out
        assert "사용법" in out
        assert "DISCORD_WEBHOOK_URL" in out


class TestWebhookExceptionPropagation:
    """raise_for_status() failure must surface (line 34) — extends existing
    TestDiscordWebhook::test_send_webhook_text_exception with the embed path."""

    def test_send_webhook_raises_on_http_error(self, monkeypatch):
        import requests

        from nuri.alerts.discord_bot import send_webhook

        class FakeResp:
            def raise_for_status(self):
                raise requests.HTTPError("403 Forbidden")

        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", lambda *a, **kw: FakeResp())
        with pytest.raises(requests.HTTPError, match="403"):
            send_webhook({"title": "x"}, webhook_url="https://example.test/wh")


class TestWebhookRetryAndTruncation:
    def test_retries_on_429_honoring_capped_retry_after(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook

        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        resp_429 = MagicMock(status_code=429, headers={"Retry-After": "30"})
        resp_ok = MagicMock(status_code=204, headers={})
        resp_ok.raise_for_status = MagicMock()

        mock_post = MagicMock(side_effect=[resp_429, resp_ok])
        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", mock_post)

        assert send_webhook({"title": "alert"}, webhook_url="https://example.test/wh") is True
        assert mock_post.call_count == 2
        assert sleeps == [5.0]

    def test_retries_on_5xx_then_succeeds(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        resp_503 = MagicMock(status_code=503, headers={})
        resp_ok = MagicMock(status_code=200, headers={})
        resp_ok.raise_for_status = MagicMock()

        mock_post = MagicMock(side_effect=[resp_503, resp_ok])
        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", mock_post)

        assert send_webhook_text("outage alert", webhook_url="https://example.test/wh") is True
        assert mock_post.call_count == 2
        assert sleeps == [1.0]

    def test_does_not_retry_on_400(self, monkeypatch):
        import requests

        from nuri.alerts.discord_bot import send_webhook_text

        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        resp_400 = MagicMock(status_code=400, headers={})
        resp_400.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        mock_post = MagicMock(return_value=resp_400)
        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", mock_post)

        with pytest.raises(requests.HTTPError, match="400"):
            send_webhook_text("bad", webhook_url="https://example.test/wh")
        assert mock_post.call_count == 1
        assert sleeps == []

    def test_send_webhook_text_truncates_over_2000_chars(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        captured: dict = {}
        resp_ok = MagicMock(status_code=200, headers={})
        resp_ok.raise_for_status = MagicMock()

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return resp_ok

        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", fake_post)
        assert send_webhook_text("A" * 2500, webhook_url="https://example.test/wh") is True
        content = captured["json"]["content"]
        assert len(content) == 2000
        assert content.endswith("…")

    def test_send_webhook_text_preserves_exact_2000_chars(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text

        captured: dict = {}
        resp_ok = MagicMock(status_code=200, headers={})
        resp_ok.raise_for_status = MagicMock()

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return resp_ok

        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", fake_post)
        exact = "B" * 2000
        assert send_webhook_text(exact, webhook_url="https://example.test/wh") is True
        assert captured["json"]["content"] == exact

    def test_retries_on_429_without_or_invalid_retry_after_and_exhausts_5xx(self, monkeypatch):
        import requests

        from nuri.alerts.discord_bot import send_webhook_text

        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        resp_429_no_hdr = MagicMock(status_code=429, headers={})
        resp_429_bad_hdr = MagicMock(status_code=429, headers={"Retry-After": "not-a-number"})
        resp_503_final = MagicMock(status_code=503, headers={})
        resp_503_final.raise_for_status.side_effect = requests.HTTPError("503 Service Unavailable")
        mock_post = MagicMock(side_effect=[resp_429_no_hdr, resp_429_bad_hdr, resp_503_final])
        monkeypatch.setattr("nuri.alerts.discord_bot.requests.post", mock_post)

        with pytest.raises(requests.HTTPError, match="503"):
            send_webhook_text("still down", webhook_url="https://example.test/wh")
        assert mock_post.call_count == 3
        assert sleeps == [1.0, 2.0]


class TestResolveBriefWebhookUrl:
    """배포는 범용 DISCORD_WEBHOOK_URL 을 비워 두고 채널별 webhook 을 쓴다.
    범용 URL 만 보던 brief/holdings/daily_report 가 매일 조용히 전송을 건너뛰었다."""

    def test_brief_channel_wins_when_generic_url_is_empty(self, monkeypatch):
        from nuri.alerts.discord_bot import resolve_brief_webhook_url

        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
        monkeypatch.setenv("DISCORD_WEBHOOK_BRIEF", "https://discord.test/brief")
        assert resolve_brief_webhook_url() == "https://discord.test/brief"

    def test_generic_url_is_the_fallback(self, monkeypatch):
        from nuri.alerts.discord_bot import resolve_brief_webhook_url

        monkeypatch.setenv("DISCORD_WEBHOOK_BRIEF", "  ")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/generic")
        assert resolve_brief_webhook_url() == "https://discord.test/generic"

    def test_none_when_nothing_is_set(self, monkeypatch):
        from nuri.alerts.discord_bot import resolve_brief_webhook_url

        monkeypatch.delenv("DISCORD_WEBHOOK_BRIEF", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert resolve_brief_webhook_url() is None


class TestRealWebhooksNeverReachTests:
    """conftest `_no_real_discord_webhooks` 잠금 — 개발 기기 `.env` 의 실제 webhook 이 테스트에 보이면 FAIL.

    conftest 안의 테스트는 수집되지 않으므로(tests/CLAUDE.md) 성질을 여기서 직접 단언한다.
    """

    def test_every_webhook_env_is_blank_at_test_start(self):
        import os

        from nuri.agents.discord.publisher import Channel

        for key in ("DISCORD_WEBHOOK_URL", *(c.env_var for c in Channel)):
            assert os.environ.get(key) == "", key

    def test_a_later_load_dotenv_cannot_refill_them(self, tmp_path):
        import os

        from dotenv import load_dotenv

        env_file = tmp_path / ".env"
        env_file.write_text("DISCORD_WEBHOOK_BRIEF=https://discord.test/leak\n")
        load_dotenv(env_file)  # 모듈 import 시점의 기본 호출과 같은 override=False
        assert os.environ["DISCORD_WEBHOOK_BRIEF"] == ""
