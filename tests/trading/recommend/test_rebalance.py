"""Tests for rebalance — split from test_trading_recommend_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.trading.recommend._helpers import (  # noqa: F401
    _seed_estimates_nm,
    _seed_fundamentals_nm,
    _seed_macro_r23,
    _seed_portfolio_nm,
    _seed_portfolio_r23,
    _seed_prices_nm,
    _seed_prices_r23,
    _seed_recommendation,
)


class TestSectorClassify:
    """From test_recommend.py."""

    def test_growth_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_defensive_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Consumer Staples") == "defensive"

    def test_neutral_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"


class TestClassifySector:
    """From test_rebalance_regime.py."""

    def test_defensive_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Real Estate") == "defensive"
        assert _classify_sector("Pharma") == "defensive"
        assert _classify_sector("Defense") == "defensive"

    def test_growth_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("Software") == "growth"

    def test_neutral(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"

    def test_case_insensitive(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("TECHNOLOGY") == "growth"
        assert _classify_sector("health care") == "defensive"


class TestSectorClassification:
    """From test_regime.py."""

    def test_classify_sector(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Consumer Staples") == "defensive"
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Semiconductor") == "growth"


class TestRebalanceAction:
    """From test_rebalance_regime.py."""

    def test_create(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="AAPL", sector="Technology", action="BUY",
            current_weight=5.0, target_weight=10.0, trade_value=5000,
            signals=["rsi_oversold(BUY)"], regime_note="[bull_strong]",
        )
        assert a.action == "BUY"
        assert a.trade_value == 5000

    def test_hold_action(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="MSFT", sector="Software", action="HOLD",
            current_weight=10.0, target_weight=10.0, trade_value=0,
            signals=[], regime_note="[bull_strong]",
        )
        assert a.action == "HOLD"


class TestCashTargets:
    """From test_rebalance_regime.py."""

    def test_values(self):
        from nuri.trading.recommend.rebalance import CASH_TARGETS
        assert CASH_TARGETS["aggressive"] == 0.0
        assert CASH_TARGETS["minimal"] == 0.40
        assert CASH_TARGETS["defensive"] == 0.20
        assert CASH_TARGETS["normal"] == 0.05


class TestPrintRebalance:
    """From test_rebalance_regime.py."""

    def test_empty(self, capsys):
        from nuri.trading.recommend.rebalance import print_rebalance
        print_rebalance([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_actions(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "BUY", 5.0, 10.0, 5000, ["rsi(BUY)"], "[bull_strong]"),
            RebalanceAction("MSFT", "Software", "HOLD", 10.0, 10.0, 0, [], "[bull_strong]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "Rebalancing" in output

    def test_all_hold(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "HOLD", 10.0, 10.0, 0, [], "[bull]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "불필요" in output


class TestRebalanceDeep:
    """From test_coverage_round7.py."""

    def test_regime_aware_rebalance(self, rich_db):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        result = regime_aware_rebalance()
        assert isinstance(result, list)


class TestRebalanceRegimeAware:
    """From test_coverage_round8.py."""

    def test_with_gate_open(self, rich_db):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        with patch("nuri.trading.engine.gate.check_gate") as mock_gate:
            mock_gate.return_value = {"status": "OPEN"}
            result = regime_aware_rebalance()
        assert isinstance(result, list)


class TestRebalance_R23:
    """From test_coverage_round23.py."""

    def test_classify_sector_defensive(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Finance") == "neutral"

    def test_classify_sector_growth(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_regime_aware_rebalance_with_mocks(self, db_path, monkeypatch):
        """Full rebalance flow with mocked dependencies."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockGateResult:
            ready: bool = False
            conditions: list = None

            def __post_init__(self):
                if self.conditions is None:
                    self.conditions = []

        @dataclass
        class MockGateCond:
            id: str = "test"
            passed: bool = False

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "minimal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT", "JNJ"],
            "sector": ["Technology", "Technology", "Health"],
            "current_weight": [30.0, 25.0, 15.0],
            "optimal_weight": [20.0, 18.0, 22.0],
            "trade_value_usd": [-5000, -3500, 3500],
            "action": ["SELL", "REDUCE", "BUY"],
        })

        monkeypatch.setattr("nuri.trading.engine.gate.check_gate",
                            lambda *a, **kw: MockGateResult(ready=False, conditions=[MockGateCond(id="prices_data", passed=False)]))
        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(method="rp", db_path=db_path)
        assert len(actions) == 3
        jnj = [a for a in actions if a.ticker == "JNJ"][0]
        assert jnj.action == "HOLD"

    def test_regime_aware_rebalance_with_conflicts(self, db_path, monkeypatch):
        """Conflict tickers forced HOLD."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        @dataclass
        class MockConflict:
            ticker: str = "AAPL"
            conflict_type: str = "direction_conflict"
            severity: str = "high"

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [MockConflict()])

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"
        assert "충돌" in actions[0].regime_note

    def test_rebalance_empty_base(self, db_path, monkeypatch):
        """Empty base_df returns empty list."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: pd.DataFrame())
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: None)

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions == []

    def test_print_rebalance_no_actions(self, capsys):
        """Print empty rebalance."""
        from nuri.trading.recommend.rebalance import print_rebalance

        print_rebalance([])
        captured = capsys.readouterr()
        assert "리밸런싱 데이터 없음" in captured.out

    def test_print_rebalance_with_actions(self, capsys):
        """Print with actionable items."""
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance

        actions = [
            RebalanceAction("AAPL", "Tech", "SELL", 30.0, 20.0, -5000.0, ["signal1"], "[bear_high_vol]"),
            RebalanceAction("MSFT", "Tech", "HOLD", 15.0, 15.0, 0.0, [], "[bear_high_vol]"),
        ]
        print_rebalance(actions)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "HOLD: MSFT" in captured.out

    def test_defensive_sector_tilt(self, db_path, monkeypatch):
        """Defensive sector tilt in minimal regime."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "defensive"

        base_df = pd.DataFrame({
            "ticker": ["JNJ", "NVDA"],
            "sector": ["Health Care", "Semiconductor"],
            "current_weight": [10.0, 10.0],
            "optimal_weight": [10.0, 10.0],
            "trade_value_usd": [0, 0],
            "action": ["HOLD", "HOLD"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 2

    def test_hold_action_small_diff(self, db_path, monkeypatch):
        """Small weight difference -> HOLD."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "sideways_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [15.0],
            "optimal_weight": [15.5],
            "trade_value_usd": [200],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"

    def test_rebalance_screen_exception(self, db_path, monkeypatch):
        """Screen candidates throws but rebalance continues."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("fail")))

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 1
        assert actions[0].action == "BUY"
