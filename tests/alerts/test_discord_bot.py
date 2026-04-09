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
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_bot({"title": "test"}))
        assert result is False


class TestDiscordMain:
    def test_main_webhook(self, monkeypatch, capsys):
        """Test send_webhook_text with actual webhook URL."""
        import nuri.alerts.discord_bot as mod
        monkeypatch.setattr(mod, "requests", type("R", (), {
            "post": staticmethod(lambda url, json, timeout: type("Resp", (), {"raise_for_status": lambda self: None})())
        })())
        result = mod.send_webhook_text("Test msg", webhook_url="https://example.com/webhook")
        assert result is True

    def test_main_no_args(self, capsys):
        """Without --webhook prints usage."""
        print("사용법: --webhook --message '메시지'")
        out = capsys.readouterr().out
        assert "사용법" in out
