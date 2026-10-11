"""SAA drift 리포트의 권고 문구 분기 — 리밸런싱이 아니면 권고가 없고, behavior gap 경고는 플래그가 있을 때만."""

from __future__ import annotations

from nuri.trading.strategy.strategic_allocation import format_report


def _result(action, **extra):
    return {
        "strategy": "core",
        "cadence": "quarterly",
        "targets": {"us_equity": 60, "cash_min": 5},
        "current": {"us_equity": 61.0},
        "drift": {"us_equity": 1.0},
        "violations": [],
        "action": action,
        **extra,
    }


def test_a_hold_report_carries_no_rebalance_advice():
    report = format_report(_result("HOLD"))

    assert "✅ **action: HOLD**" in report
    assert "권고" not in report and "behavior gap" not in report


def test_a_rebalance_without_the_gap_flag_carries_advice_but_no_gap_warning():
    report = format_report(_result("REBALANCE"))

    assert "🔴 **action: REBALANCE**" in report
    assert "portfolio_action=REBALANCE" in report
    assert "behavior gap" not in report
