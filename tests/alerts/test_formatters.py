"""Tests for nuri.alerts.formatters."""


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
