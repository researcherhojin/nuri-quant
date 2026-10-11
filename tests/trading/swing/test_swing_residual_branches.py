"""스윙 진입 판정·출력·유니버스 로더의 나머지 분기."""

from __future__ import annotations

from types import SimpleNamespace

import yaml

from nuri.trading.swing import rules, scanner
from nuri.trading.swing.scanner import ScanResult


def _scan(ticker="TST_A", score=None):
    return ScanResult(
        ticker=ticker,
        price=100.0,
        change_1d=1.0,
        change_5d=3.0,
        volume_ratio=2.0,
        rsi=55.0,
        bb_position=0.6,
        signal="breakout",
        score=rules.MIN_SCAN_SCORE + 10 if score is None else score,
    )


def test_a_confident_non_buy_is_rejected_for_its_action_alone(db_path, monkeypatch):
    """신뢰도는 충분한데 에이전트가 SELL 이면 거부 사유는 '에이전트 SELL' 하나다 — 신뢰도 사유를
    덧붙여 원인을 흐리지 않는다."""
    consensus = SimpleNamespace(
        final_action="SELL", final_confidence=rules.MIN_AGENT_CONFIDENCE + 20, agreement_rate=0.8
    )
    monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", lambda ticker, db_path=None: consensus)

    (entry,) = rules.evaluate_entries([_scan()], db_path=db_path)

    assert entry.approved is False
    assert "거부: 에이전트 SELL" in entry.reason
    assert "거부: 신뢰도" not in entry.reason


def test_printing_only_rejected_entries_has_no_approved_table(capsys):
    entry = rules.SwingEntry(
        ticker="TST_R",
        price=10.0,
        scan_signal="bounce",
        scan_score=70.0,
        agent_action="HOLD",
        agent_confidence=40.0,
        agent_agreement=0.5,
        approved=False,
        reason="거부: 에이전트 HOLD",
    )

    rules.print_entries([entry])

    out = capsys.readouterr().out
    assert "0 approved, 1 rejected" in out
    assert "APPROVED:" not in out
    assert "TST_R: 거부: 에이전트 HOLD" in out


def test_the_universe_loader_drops_blanks_and_repeats_across_groups(monkeypatch):
    """그룹이 겹치면 처음 본 순서대로 한 번만 — 빈 문자열과 YAML bool(ON/OFF) 은 티커가 아니다."""
    monkeypatch.setattr(
        yaml,
        "safe_load",
        lambda f: {
            "us_core": {"tickers": ["TST_A", "TST_B", "", True]},
            "us_sp500_extended": {"tickers": ["TST_B", "TST_C"]},
        },
    )

    assert scanner._load_universe(["us_core", "us_sp500_extended"]) == ["TST_A", "TST_B", "TST_C"]
