"""engine 계층의 나머지 분기 — drift 경고 없는 메모리 출력 · 앞선 skip 사유 보존."""

from __future__ import annotations

from nuri.trading.engine.amplifier_gate import AmplifierConditions, evaluate
from nuri.trading.engine.memory import PerformanceDrift, print_memory_status


def test_memory_status_without_degrading_signals_has_no_warning_block(capsys):
    print_memory_status(
        [
            PerformanceDrift("rsi_oversold", None, 0.6, 0.62, 3.3, "stable", "within band"),
            PerformanceDrift("macd_golden", None, 0.5, 0.6, 20.0, "improving", "recent up"),
        ]
    )

    out = capsys.readouterr().out
    assert "rsi_oversold" in out and "macd_golden" in out
    assert "성과 하락" not in out


def test_a_too_low_minimum_keeps_the_earlier_skip_reason():
    """minimum<2 는 그 자체로 발화를 막지만, 이미 더 앞선 사유(비 BUY)로 걸렸으면 그 사유를 덮지 않는다 —
    원장의 skip 사유는 **처음** 막은 이유여야 한다."""
    result = evaluate(
        config={"enabled": True, "shadow_mode": False, "minimum_satisfied": 1},
        final_action="HOLD",
        final_action_source="weighted_sum",
        conditions=AmplifierConditions(recovery_confirmed=True, vix_favorable=True),
    )

    assert result.skip_reason == "non_buy_action:HOLD"
    assert (result.would_fire, result.fired) == (False, False)
