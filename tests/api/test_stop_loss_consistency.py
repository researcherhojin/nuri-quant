"""보유 계좌에서 API와 브리프까지 실제 DB로 손절 계약을 검증한다."""

from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from nuri.alerts.risk_signals import scan_stop_breaches, stage_stop_breach_briefs
from nuri.api.routes import actions
from nuri.core.db import upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst


@pytest.fixture
def holdings(monkeypatch):
    from nuri.trading.recommend import stop_loss

    monkeypatch.setattr(actions, "_get_real_accounts", lambda: set())
    monkeypatch.setattr("nuri.api.routes.dashboard._get_account_labels", lambda: {})
    monkeypatch.setattr(actions, "_get_rule_violations", lambda: [])
    monkeypatch.setattr(actions, "_get_targets_status", lambda: {})
    monkeypatch.setattr(actions, "_get_short_interest", lambda _: None)
    monkeypatch.setattr(actions, "latest_usd_krw_value", lambda: 1300)
    monkeypatch.setattr(actions, "check_divergence", lambda *_: (False, 0, None))
    monkeypatch.setattr(stop_loss, "get_account_strategy_name", lambda a: "pension" if a == "Pension" else "core")
    monkeypatch.setattr(stop_loss, "get_stop_loss_for_account", lambda a: -20 if a == "Brokerage Beta" else -7)

    def seed(price_date, current=90):
        upsert_portfolio(
            [
                dict(account=a, ticker="TST_A", quantity=q, avg_price=100, currency="USD", sector="Tech")
                for a, q in (("Brokerage Alpha", 10), ("Brokerage Beta", 10), ("Pension", 10), ("Closed", 0))
            ]
        )
        if price_date is not None:
            upsert_prices(
                pd.DataFrame(
                    [
                        dict(
                            ticker="TST_A",
                            date=price_date,
                            open=current,
                            high=current,
                            low=current,
                            close=current,
                            volume=100,
                            adj_close=current,
                        )
                    ]
                )
            )

    return seed


@pytest.mark.parametrize("recommendation", [None, "BUY", "HOLD", "SELL"])
def test_stop_breach_is_independent_of_recommendation(holdings, monkeypatch, recommendation):
    holdings(today_kst())
    recs = [] if recommendation is None else [dict(ticker="TST_A", action=recommendation, confidence=60)]
    monkeypatch.setattr(actions, "_get_recommendations", lambda: recs)
    monkeypatch.setattr(actions, "has_recent_catalyst", lambda _: (False, "none"))
    result = actions._build_actions()
    alerts = scan_stop_breaches()
    assert [(r["ticker"], r["account"]) for r in result["urgent"]] == [(r["ticker"], r["account"]) for r in alerts]
    assert [r["account"] for r in result["urgent"]] == ["Brokerage Alpha"]
    assert result["urgent"][0]["alpha_action"] == "FLAT"
    assert result["urgent"][0]["action"] == "SELL"
    assert result["urgent"][0]["price_date"] == today_kst()
    all_items = [r for b in ("urgent", "check", "hold", "portfolio") for r in result[b]]
    assert len(all_items) == 2  # 계좌별 판정, 연금과 수량 0 제외
    assert all_items[1]["account"] == "Brokerage Beta"


@pytest.mark.parametrize("days", [None, -30, 1])
def test_unknown_price_is_review_in_both_channels(holdings, monkeypatch, days):
    price_date = None if days is None else (kst_now() + timedelta(days=days)).date().isoformat()
    holdings(price_date)
    monkeypatch.setattr(actions, "_get_recommendations", lambda: [dict(ticker="TST_A", action="BUY", confidence=60)])
    result = actions._build_actions()
    assert not result["urgent"] and not result["hold"]
    assert len(result["check"]) == 2
    assert all(r["action"] == "UNKNOWN" and r["stop_loss_status"] == "unknown" for r in result["check"])
    assert scan_stop_breaches() == []
    with patch("nuri.agents.discord.outbox.stage_brief", return_value=1) as stage:
        assert stage_stop_breach_briefs() == 2
    assert all(call.kwargs["payload"]["kind"] == "REVIEW" for call in stage.call_args_list)


@pytest.mark.parametrize("value", [None, 0, -1, float("nan"), float("inf")])
def test_invalid_price_cannot_be_classified_as_hold_or_sell(value):
    from nuri.trading.recommend.stop_loss import assess_stop_loss

    result = assess_stop_loss("Brokerage Alpha", 100, value, today_kst())
    assert result["status"] == "unknown"


def test_invalid_date_is_indeterminate():
    from nuri.trading.recommend.stop_loss import assess_stop_loss

    for price_date in ("not-a-date", None):
        assert assess_stop_loss("Brokerage Alpha", 100, 90, price_date)["status"] == "unknown"


def test_unknown_cli_does_not_claim_no_breach(holdings, capsys):
    from nuri.alerts.risk_signals import main

    holdings(None)
    assert main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "판단 불가" in output
    assert "breach 없음" not in output


def test_threshold_equality_does_not_trigger_a_breach():
    from nuri.trading.recommend.stop_loss import assess_stop_loss

    with patch("nuri.trading.recommend.stop_loss.get_stop_loss_for_account", return_value=-7):
        assert assess_stop_loss("Brokerage Alpha", 100, 93, today_kst())["status"] == "clear"
        assert assess_stop_loss("Brokerage Alpha", 100, 92.99, today_kst())["status"] == "breached"
