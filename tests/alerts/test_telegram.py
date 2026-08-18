"""Tests for nuri.alerts.telegram."""

from unittest.mock import MagicMock


class TestTelegram:
    def test_send_no_token(self):
        from nuri.alerts.telegram import send_telegram

        result = send_telegram("test message")
        assert result is False

    def test_format_regime_alert(self):
        from nuri.alerts.telegram import format_regime_alert

        msg = format_regime_alert("bull_low_vol", "sideways_high_vol", 75.0)
        assert "레짐 전환" in msg
        assert "bull_low_vol" in msg
        assert "sideways_high_vol" in msg

    def test_format_violation_alert(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [
            {"ticker": "TSLL", "severity": "critical", "reason": "레버리지 ETF"},
            {"ticker": "BAD", "severity": "warning", "violation_type": "stop_loss"},
        ]
        msg = format_violation_alert(violations)
        assert "TSLL" in msg
        assert "위반" in msg

    def test_format_violation_many(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [{"ticker": f"T{i}", "severity": "warning", "reason": "test"} for i in range(8)]
        msg = format_violation_alert(violations)
        assert "외" in msg

    def test_format_signal_alert(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("AAPL", "BUY", 75.0, 155.0)
        assert "AAPL" in msg
        assert "BUY" in msg
        assert "$155.00" in msg

    def test_format_signal_sell(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("TSLA", "SELL", 80.0, 350.0)
        assert "SELL" in msg


class TestTelegramSend:
    def test_no_token(self, monkeypatch):
        """send_telegram returns False when token not set."""
        import nuri.alerts.telegram as mod

        monkeypatch.setattr(mod, "_BOT_TOKEN", "")
        monkeypatch.setattr(mod, "_CHAT_ID", "")
        assert mod.send_telegram("test") is False

    def test_send_success(self, monkeypatch):
        """send_telegram returns True on successful POST."""
        import nuri.alerts.telegram as mod

        monkeypatch.setattr(mod, "_BOT_TOKEN", "fake_token")
        monkeypatch.setattr(mod, "_CHAT_ID", "12345")

        class FakeResp:
            def raise_for_status(self):
                pass

        import requests

        monkeypatch.setattr(requests, "post", lambda url, **kw: FakeResp())
        assert mod.send_telegram("test message") is True

    def test_send_failure(self, monkeypatch):
        """send_telegram returns False on exception."""
        import nuri.alerts.telegram as mod

        monkeypatch.setattr(mod, "_BOT_TOKEN", "fake_token")
        monkeypatch.setattr(mod, "_CHAT_ID", "12345")

        def _raise(*a, **kw):
            raise ConnectionError("fail")

        import requests

        monkeypatch.setattr(requests, "post", _raise)
        assert mod.send_telegram("test") is False

    def test_send_with_markdown(self, monkeypatch):
        """send_telegram with Markdown parse mode."""
        import nuri.alerts.telegram as mod

        monkeypatch.setattr(mod, "_BOT_TOKEN", "fake_token")
        monkeypatch.setattr(mod, "_CHAT_ID", "12345")

        posted = {}

        class FakeResp:
            def raise_for_status(self):
                pass

        import requests

        def capture_post(url, **kw):
            posted.update(kw.get("json", {}))
            return FakeResp()

        monkeypatch.setattr(requests, "post", capture_post)
        mod.send_telegram("**bold**", parse_mode="Markdown")
        assert posted.get("parse_mode") == "Markdown"


class TestTelegramFormatters:
    def test_format_regime_alert(self):
        from nuri.alerts.telegram import format_regime_alert

        msg = format_regime_alert("bull_low_vol", "bear_high_vol", 85.0)
        assert "레짐 전환" in msg
        assert "bear_high_vol" in msg
        assert "85%" in msg

    def test_format_violation_alert(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [
            {"ticker": "TSLA", "severity": "critical", "reason": "stop loss exceeded"},
            {"ticker": "AAPL", "severity": "warning", "violation_type": "position limit"},
        ]
        msg = format_violation_alert(violations)
        assert "규칙 위반" in msg
        assert "TSLA" in msg

    def test_format_violation_alert_many(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [{"ticker": f"T{i}", "severity": "warning", "reason": "test"} for i in range(8)]
        msg = format_violation_alert(violations)
        assert "외 3건" in msg

    def test_format_signal_alert_buy(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("AAPL", "BUY", 85.0, 175.50)
        assert "BUY" in msg
        assert "AAPL" in msg

    def test_format_signal_alert_sell(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("MSFT", "SELL", 70.0, 380.00)
        assert "SELL" in msg

    def test_format_signal_alert_hold(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("GOOG", "HOLD", 50.0, 150.00)
        assert "HOLD" in msg


class TestTelegram_R24:
    """Tests for nuri/alerts/telegram.py."""

    def test_send_telegram_no_config(self, monkeypatch):
        import nuri.alerts.telegram as tg

        monkeypatch.setattr(tg, "_BOT_TOKEN", "")
        monkeypatch.setattr(tg, "_CHAT_ID", "")
        result = tg.send_telegram("test message")
        assert result is False

    def test_send_telegram_success(self, monkeypatch):
        import nuri.alerts.telegram as tg

        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(req_mod, "post", MagicMock(return_value=mock_resp))

        result = tg.send_telegram("test message")
        assert result is True

    def test_send_telegram_failure(self, monkeypatch):
        import nuri.alerts.telegram as tg

        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod

        monkeypatch.setattr(req_mod, "post", MagicMock(side_effect=Exception("network error")))

        result = tg.send_telegram("test message")
        assert result is False

    def test_send_telegram_markdown_mode(self, monkeypatch):
        import nuri.alerts.telegram as tg

        monkeypatch.setattr(tg, "_BOT_TOKEN", "test_token")
        monkeypatch.setattr(tg, "_CHAT_ID", "123456")

        import requests as req_mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(req_mod, "post", mock_post)

        tg.send_telegram("**bold**", parse_mode="Markdown")
        call_args = mock_post.call_args
        assert call_args[1]["json"]["parse_mode"] == "Markdown"

    def test_format_regime_alert(self):
        from nuri.alerts.telegram import format_regime_alert

        msg = format_regime_alert("bull_low_vol", "bear_high_vol", 85.0)
        assert "레짐 전환" in msg
        assert "bull_low_vol" in msg
        assert "bear_high_vol" in msg
        assert "85" in msg

    def test_format_violation_alert(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [
            {"ticker": "AAPL", "severity": "critical", "reason": "stop-loss hit"},
            {"ticker": "NVDA", "severity": "warning", "violation_type": "position limit"},
        ]
        msg = format_violation_alert(violations)
        assert "2건" in msg
        assert "AAPL" in msg
        assert "stop-loss" in msg

    def test_format_violation_alert_many(self):
        from nuri.alerts.telegram import format_violation_alert

        violations = [{"ticker": f"T{i}", "severity": "warning", "reason": f"r{i}"} for i in range(10)]
        msg = format_violation_alert(violations)
        assert "외 5건" in msg

    def test_format_signal_alert_buy(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("AAPL", "BUY", 85.0, 190.0)
        assert "AAPL" in msg
        assert "BUY" in msg
        assert "85" in msg

    def test_format_signal_alert_sell(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("AAPL", "SELL", 70.0, 180.0)
        assert "SELL" in msg

    def test_format_signal_alert_hold(self):
        from nuri.alerts.telegram import format_signal_alert

        msg = format_signal_alert("AAPL", "HOLD", 50.0, 190.0)
        assert "HOLD" in msg
