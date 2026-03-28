"""Alerts 모듈 테스트 — formatters + daily_report + telegram."""
import pytest

from nuri.alerts.formatters import (
    _fear_greed_label,
    format_ark_alert,
    format_daily_report,
    format_price_alert,
)
from nuri.core.db import init_db, upsert_macro


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# Formatters (기존)
# ═══════════════════════════════════════════════════════

class TestFormatters:
    def test_daily_report_structure(self):
        embed = format_daily_report(
            portfolio_summary={"total_value_usd": 50000, "warnings": []},
            risk_metrics={"sharpe_ratio": 1.5, "max_drawdown_pct": -5.0, "var_95_daily_pct": -2.0, "stop_loss_alerts": []},
            fear_greed=45.0,
        )
        assert "title" in embed
        assert "fields" in embed
        assert any("총 평가액" in f["name"] for f in embed["fields"])

    def test_price_alert_positive(self):
        embed = format_price_alert("TSLA", 5.2, 380.0)
        assert "급등" in embed["title"]

    def test_price_alert_negative(self):
        embed = format_price_alert("NVDA", -4.1, 170.0)
        assert "급락" in embed["title"]

    def test_ark_alert(self):
        embed = format_ark_alert([
            {"ticker": "TSLA", "direction": "Buy", "shares": 50000, "fund": "ARKK"},
        ])
        assert "ARK" in embed["title"]
        assert "TSLA" in embed["description"]

    def test_fear_greed_labels(self):
        assert _fear_greed_label(10) == "극단적 공포"
        assert _fear_greed_label(30) == "공포"
        assert _fear_greed_label(50) == "중립"
        assert _fear_greed_label(70) == "탐욕"
        assert _fear_greed_label(90) == "극단적 탐욕"

    def test_daily_report_with_events(self):
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
# daily_report
# ═══════════════════════════════════════════════════════

class TestGenerateReport:
    def test_empty_portfolio(self, db_path, monkeypatch):
        """빈 포트폴리오에서도 리포트 생성."""
        import pandas as pd
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_portfolio", lambda **kw: pd.DataFrame())
        monkeypatch.setattr("nuri.alerts.daily_report.analyze_risk", lambda **kw: {})

        from nuri.alerts.daily_report import generate_report
        embed = generate_report()
        assert isinstance(embed, dict)
        assert "fields" in embed

    def test_with_data(self, db_path, monkeypatch):
        """포트폴리오 + 매크로 데이터가 있을 때."""
        from datetime import datetime

        import pandas as pd

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
        from unittest.mock import patch

        import pandas as pd

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


# ═══════════════════════════════════════════════════════
# telegram
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
