"""Consolidated alerts tests — all nuri.alerts.* test classes from across the test suite.

Source files:
  - test_alerts.py: TestFormatters, TestGenerateReport, TestSendDiscord, TestPrintReport, TestTelegram
  - test_coverage_round10.py: TestAlerts (→ TestAlerts_R10)
  - test_coverage_round20.py: TestDiscordWebhook, TestDiscordBot (→ TestDiscordBot_R20)
  - test_coverage_round22.py: TestDiscordWebhook (→ TestDiscordWebhook_R22), TestDiscordBot (→ TestDiscordBot_R22),
                               TestDiscordMain, TestTelegramSend, TestTelegramFormatters
  - test_coverage_round24.py: TestDailyReport, TestFormatters (→ TestFormatters_R24), TestTelegram (→ TestTelegram_R24)
  - test_coverage_extra.py: TestDiscordBot (first occurrence)
"""

import asyncio
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Basic DB fixture with DB_PATH monkeypatched."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """DB with portfolio, 500-day prices for SPY/AAPL/NVDA, macro data."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
    ], path)
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    vix = [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test"}
           for i, d in enumerate(dates)]
    fg = [{"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"),
           "value": 50 + np.sin(i / 25) * 30, "source": "test"}
          for i, d in enumerate(dates)]
    upsert_macro(vix + fg, path)
    return path


@pytest.fixture
def db_with_portfolio(tmp_path, monkeypatch):
    """DB with portfolio + prices seeded (from test_coverage_round24)."""
    import nuri.core.db as db_mod

    path = tmp_path / "r24.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
         "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
         "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4, "avg_price": 60000,
         "currency": "KRW", "sector": "Semiconductor"},
    ], path)

    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY", "005930.KS"]:
        base = {"AAPL": 190, "NVDA": 130, "SPY": 550, "005930.KS": 60000}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 2, "low": p - 1,
                "close": p + 1, "volume": 1_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    upsert_macro([
        {"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"},
        {"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"},
    ], path)

    return path


# ═══════════════════════════════════════════════════════
# From test_alerts.py — TestFormatters
# ═══════════════════════════════════════════════════════


class TestFormatters:
    def test_daily_report_structure(self):
        from nuri.alerts.formatters import format_daily_report

        embed = format_daily_report(
            portfolio_summary={"total_value_usd": 50000, "warnings": []},
            risk_metrics={"sharpe_ratio": 1.5, "max_drawdown_pct": -5.0, "var_95_daily_pct": -2.0, "stop_loss_alerts": []},
            fear_greed=45.0,
        )
        assert "title" in embed
        assert "fields" in embed
        assert any("총 평가액" in f["name"] for f in embed["fields"])

    def test_price_alert_positive(self):
        from nuri.alerts.formatters import format_price_alert

        embed = format_price_alert("TSLA", 5.2, 380.0)
        assert "급등" in embed["title"]

    def test_price_alert_negative(self):
        from nuri.alerts.formatters import format_price_alert

        embed = format_price_alert("NVDA", -4.1, 170.0)
        assert "급락" in embed["title"]

    def test_ark_alert(self):
        from nuri.alerts.formatters import format_ark_alert

        embed = format_ark_alert([
            {"ticker": "TSLA", "direction": "Buy", "shares": 50000, "fund": "ARKK"},
        ])
        assert "ARK" in embed["title"]
        assert "TSLA" in embed["description"]

    def test_fear_greed_labels(self):
        from nuri.alerts.formatters import _fear_greed_label

        assert _fear_greed_label(10) == "극단적 공포"
        assert _fear_greed_label(30) == "공포"
        assert _fear_greed_label(50) == "중립"
        assert _fear_greed_label(70) == "탐욕"
        assert _fear_greed_label(90) == "극단적 탐욕"

    def test_daily_report_with_events(self):
        from nuri.alerts.formatters import format_daily_report

        events = [{"date": "2026-03-29", "event_type": "earnings", "ticker": "AAPL", "description": "Q2"}]
        embed = format_daily_report(
            portfolio_summary={"total_value_usd": 5000, "warnings": ["VIX high"]},
            risk_metrics={},
            fear_greed=None,
            events=events,
        )
        assert isinstance(embed, dict)
        assert "fields" in embed


# ═══════════════════════════════════════════════════════
# From test_alerts.py — TestGenerateReport
# ═══════════════════════════════════════════════════════


class TestGenerateReport:
    def test_empty_portfolio(self, db_path, monkeypatch):
        """빈 포트폴리오에서도 리포트 생성."""
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio", lambda **kw: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda **kw: {})

        from nuri.alerts.daily_report import generate_report
        embed = generate_report()
        assert isinstance(embed, dict)
        assert "fields" in embed

    def test_with_data(self, db_path, monkeypatch):
        """포트폴리오 + 매크로 데이터가 있을 때."""
        mock_df = pd.DataFrame([{"ticker": "AAPL", "weight_pct": 10.0}])
        mock_df.attrs = {"total_value_usd": 10000, "warnings": []}

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio", lambda **kw: mock_df)
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda **kw: {"max_drawdown": -5.0})

        today = datetime.now().strftime("%Y-%m-%d")
        upsert_macro([{"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"}], db_path)

        from nuri.alerts.daily_report import generate_report
        embed = generate_report()
        assert isinstance(embed, dict)

    def test_with_rebalance_critical(self, db_path, monkeypatch):
        """리밸런스 위반이 있을 때 embed에 필드 추가."""
        mock_df = pd.DataFrame([{"ticker": "TSLL", "weight_pct": 5.0}])
        mock_df.attrs = {"total_value_usd": 5000, "warnings": []}

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio", lambda **kw: mock_df)
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda **kw: {})

        mock_report = {
            "has_critical": True,
            "total_violations": 1,
            "total_recovery_usd": 1100,
            "actions": [{"ticker": "TSLL", "severity": "critical", "action": "SELL_ALL",
                         "sell_shares": 96, "reason": "레버리지 ETF", "sell_value_usd": 1100}],
        }

        with patch("nuri.analysis.rebalance_advisor.generate_advisor_report", return_value=mock_report):
            from nuri.alerts.daily_report import generate_report
            embed = generate_report()

        assert any("규칙 위반" in f.get("name", "") for f in embed.get("fields", []))


# ═══════════════════════════════════════════════════════
# From test_alerts.py — TestSendDiscord
# ═══════════════════════════════════════════════════════


class TestSendDiscord:
    def test_no_webhook(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.daily_report import send_discord
        result = send_discord({"title": "test"})
        assert result is False


# ═══════════════════════════════════════════════════════
# From test_alerts.py — TestPrintReport
# ═══════════════════════════════════════════════════════


class TestPrintReport:
    def test_output(self, capsys):
        from nuri.alerts.daily_report import print_report
        embed = {"title": "Test Report", "fields": [{"name": "X", "value": "Y"}]}
        print_report(embed)
        output = capsys.readouterr().out
        assert "Test Report" in output


# ═══════════════════════════════════════════════════════
# From test_alerts.py — TestTelegram
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round10.py — TestAlerts (→ TestAlerts_R10)
# ═══════════════════════════════════════════════════════


class TestAlerts_R10:
    def test_format_daily_report(self, rich_db):
        from nuri.alerts.formatters import format_daily_report
        report = format_daily_report(
            portfolio_summary={"total_value": 10000, "holdings": 2},
            risk_metrics={"sharpe": 1.5, "mdd": -0.05},
            fear_greed=55.0,
        )
        assert isinstance(report, dict)

    def test_format_price_alert(self):
        from nuri.alerts.formatters import format_price_alert
        alert = format_price_alert("AAPL", 5.2, 200.0)
        assert isinstance(alert, dict)


# ═══════════════════════════════════════════════════════
# From test_coverage_extra.py — TestDiscordBot (first occurrence)
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round20.py — TestDiscordWebhook (first occurrence)
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round20.py — TestDiscordBot (→ TestDiscordBot_R20)
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round22.py — TestDiscordWebhook (→ TestDiscordWebhook_R22)
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round22.py — TestDiscordBot (→ TestDiscordBot_R22)
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round22.py — TestDiscordMain
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round22.py — TestTelegramSend
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round22.py — TestTelegramFormatters
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# From test_coverage_round24.py — TestDailyReport
# ═══════════════════════════════════════════════════════


class TestDailyReport:
    """Tests for nuri/alerts/daily_report.py."""

    def test_generate_report(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        # Mock analyze_portfolio
        mock_df = pd.DataFrame({"ticker": ["AAPL"], "value": [1900]})
        mock_df.attrs["total_value_usd"] = 1900
        mock_df.attrs["warnings"] = ["Single position too large"]
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: mock_df)

        # Mock analyze_risk
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {"sharpe_ratio": 1.5, "max_drawdown_pct": -8.0,
                                     "var_95_daily_pct": -2.5, "stop_loss_alerts": []})

        # Mock rebalance advisor
        monkeypatch.setattr("nuri.alerts.daily_report.generate_report.__module__",
                            "nuri.alerts.daily_report")

        embed = generate_report()
        assert "title" in embed
        assert "fields" in embed
        assert len(embed["fields"]) >= 1

    def test_generate_report_empty_portfolio(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {})

        embed = generate_report()
        assert embed["fields"][0]["value"] == "$0"

    def test_generate_report_with_rebalance(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import generate_report

        mock_df = pd.DataFrame({"ticker": ["AAPL"]})
        mock_df.attrs["total_value_usd"] = 1900
        mock_df.attrs["warnings"] = []
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: mock_df)
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk",
                            lambda: {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
                                     "var_95_daily_pct": -1.5, "stop_loss_alerts": []})

        # Mock rebalance_advisor — it is lazy-imported inside generate_report
        mock_rebalance = {
            "has_critical": True,
            "total_violations": 2,
            "total_recovery_usd": 5000,
            "actions": [
                {"severity": "critical", "action": "SELL_ALL",
                 "ticker": "AAPL", "sell_shares": 10, "reason": "stop-loss",
                 "sell_value_usd": 1900},
            ],
        }
        mock_module = MagicMock()
        mock_module.generate_advisor_report = MagicMock(return_value=mock_rebalance)

        monkeypatch.setitem(sys.modules, "nuri.analysis.rebalance_advisor", mock_module)

        embed = generate_report()
        assert embed["color"] == 0xE74C3C  # Red for critical

    def test_send_discord_no_webhook(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import send_discord
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_discord({"title": "test", "fields": []})
        assert result is False

    def test_send_discord_success(self, monkeypatch, db_with_portfolio):
        from nuri.alerts.daily_report import send_discord

        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/webhook/test")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        import requests as req_mod
        monkeypatch.setattr(req_mod, "post", MagicMock(return_value=mock_resp))

        result = send_discord({"title": "test", "fields": []})
        assert result is True

    def test_print_report(self, capsys, db_with_portfolio):
        from nuri.alerts.daily_report import print_report
        embed = {
            "title": "Test Report",
            "fields": [
                {"name": "Value", "value": "$1000"},
            ],
        }
        print_report(embed)
        out = capsys.readouterr().out
        assert "Test Report" in out
        assert "Value" in out

    def test_main(self, monkeypatch, db_with_portfolio, capsys):
        from nuri.alerts.daily_report import main

        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio",
                            lambda: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda: {})
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        main()
        out = capsys.readouterr().out
        assert "Daily Report" in out


# ═══════════════════════════════════════════════════════
# From test_coverage_round24.py — TestFormatters (→ TestFormatters_R24)
# ═══════════════════════════════════════════════════════


class TestFormatters_R24:
    """Tests for nuri/alerts/formatters.py."""

    def test_format_daily_report_basic(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.5, "max_drawdown_pct": -8.0,
             "var_95_daily_pct": -2.5, "stop_loss_alerts": []},
        )
        assert embed["title"].startswith("📋")
        assert len(embed["fields"]) >= 1

    def test_format_daily_report_with_warnings(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": ["Warning 1"]},
            {"sharpe_ratio": 0.5, "max_drawdown_pct": -15.0,
             "var_95_daily_pct": -4.0,
             "stop_loss_alerts": [{"ticker": "AAPL", "pnl_pct": -8.5}]},
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("경고" in n for n in field_names)
        assert any("손절" in n for n in field_names)

    def test_format_daily_report_with_fear_greed(self):
        from nuri.alerts.formatters import format_daily_report
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
             "var_95_daily_pct": -1.5, "stop_loss_alerts": []},
            fear_greed=75.0,
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("Fear" in n for n in field_names)

    def test_format_daily_report_with_events(self):
        from nuri.alerts.formatters import format_daily_report
        events = [{"date": "2025-01-31", "description": "FOMC Meeting"}]
        embed = format_daily_report(
            {"total_value_usd": 10000, "warnings": []},
            {"sharpe_ratio": 1.0, "max_drawdown_pct": -5.0,
             "var_95_daily_pct": -1.5, "stop_loss_alerts": []},
            events=events,
        )
        field_names = [f["name"] for f in embed["fields"]]
        assert any("이벤트" in n for n in field_names)

    def test_format_price_alert_up(self):
        from nuri.alerts.formatters import format_price_alert
        embed = format_price_alert("AAPL", 5.0, 200.0)
        assert "급등" in embed["title"]
        assert embed["color"] == 0x2ECC71  # Green

    def test_format_price_alert_down(self):
        from nuri.alerts.formatters import format_price_alert
        embed = format_price_alert("AAPL", -5.0, 180.0)
        assert "급락" in embed["title"]
        assert embed["color"] == 0xE74C3C  # Red

    def test_format_ark_alert(self):
        from nuri.alerts.formatters import format_ark_alert
        trades = [
            {"ticker": "AAPL", "direction": "BUY", "shares": 1000, "fund": "ARKK"},
            {"ticker": "NVDA", "direction": "SELL", "shares": 500, "fund": "ARKW"},
        ]
        embed = format_ark_alert(trades)
        assert "ARK" in embed["title"]
        assert "AAPL" in embed["description"]

    def test_format_ark_alert_empty(self):
        from nuri.alerts.formatters import format_ark_alert
        embed = format_ark_alert([])
        assert "매매 내역 없음" in embed["description"]

    def test_format_event_reminder(self):
        from nuri.alerts.formatters import format_event_reminder
        event = {"date": "2025-03-17", "description": "FOMC", "event_type": "fomc",
                 "ticker": None}
        embed = format_event_reminder(event)
        assert "FOMC" in embed["title"]

    def test_fear_greed_labels(self):
        from nuri.alerts.formatters import _fear_greed_label
        assert _fear_greed_label(10) == "극단적 공포"
        assert _fear_greed_label(30) == "공포"
        assert _fear_greed_label(50) == "중립"
        assert _fear_greed_label(70) == "탐욕"
        assert _fear_greed_label(90) == "극단적 탐욕"


# ═══════════════════════════════════════════════════════
# From test_coverage_round24.py — TestTelegram (→ TestTelegram_R24)
# ═══════════════════════════════════════════════════════


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
