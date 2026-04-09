"""Tests for nuri.alerts.daily_report."""
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from nuri.core.db import upsert_macro


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


class TestSendDiscord:
    def test_no_webhook(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.daily_report import send_discord
        result = send_discord({"title": "test"})
        assert result is False


class TestPrintReport:
    def test_output(self, capsys):
        from nuri.alerts.daily_report import print_report
        embed = {"title": "Test Report", "fields": [{"name": "X", "value": "Y"}]}
        print_report(embed)
        output = capsys.readouterr().out
        assert "Test Report" in output


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
