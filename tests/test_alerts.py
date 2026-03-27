"""Alerts 모듈 테스트."""
from nuri.alerts.formatters import (
    _fear_greed_label,
    format_ark_alert,
    format_daily_report,
    format_price_alert,
)


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
