"""레짐 적응 리밸런싱의 나머지 분기 — 중립 섹터 무틸트 · HOLD 없는 출력."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nuri.core.sectors import classify_sector
from nuri.trading.recommend.rebalance import CASH_TARGETS, RebalanceAction, print_rebalance, regime_aware_rebalance


@dataclass
class _Regime:
    regime: str = "bear_low_vol"


@dataclass
class _Strategy:
    position_sizing: str = "defensive"


@dataclass
class _Gate:
    ready: bool = True
    conditions: tuple = ()


def test_a_neutral_sector_gets_no_tilt_in_a_defensive_regime(db_path, monkeypatch):
    """방어 국면의 틸트는 방어 +10% · 성장 -15% 뿐이다 — 중립 섹터는 현금 목표만 반영한다."""
    base = pd.DataFrame(
        {
            "ticker": ["TST_F"],
            "sector": ["Finance"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        }
    )
    monkeypatch.setattr("nuri.trading.engine.gate.check_gate", lambda *a, **k: _Gate())
    monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **k: base)
    monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **k: _Regime())
    monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **k: _Strategy())
    monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **k: [])
    monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **k: [])

    (action,) = regime_aware_rebalance(method="rp", db_path=db_path)

    assert classify_sector("Finance") == "neutral"
    assert action.target_weight == round(0.20 * (1 - CASH_TARGETS["defensive"]) * 100, 2)
    assert action.action == "BUY"


def test_output_without_hold_actions_has_no_hold_line(capsys):
    print_rebalance([RebalanceAction("TST_A", "Finance", "BUY", 5.0, 10.0, 5000, [], "[bull_low_vol]")])

    out = capsys.readouterr().out
    assert "TST_A" in out
    assert "HOLD:" not in out
