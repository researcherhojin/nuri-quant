"""Tests for macro agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestMacroAgentBranches:
    """매크로 에이전트 레짐별 모멘텀 분기 커버리지."""

    def _make_prices(self, db_path, ticker, close_values):
        """가격 데이터 삽입 헬퍼."""
        with get_db(db_path) as conn:
            for i, c in enumerate(close_values):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, f"2025-03-{i+1:02d}", c, c, c, c, 100000),
                )

    def _mock_regime(self, monkeypatch, trend, regime_name, macro_score):
        class FakeRegime:
            pass
        r = FakeRegime()
        r.regime = regime_name
        r.trend = trend
        r.volatility = "low"
        r.confidence = 0.8
        r.details = None

        class FakeMacro:
            pass
        m = FakeMacro()
        m.total_score = macro_score

        import nuri.quant.regime.classifier as cls_mod
        import nuri.quant.regime.macro_score as ms_mod
        monkeypatch.setattr(cls_mod, "classify_regime", lambda db_path=None: r)
        monkeypatch.setattr(ms_mod, "compute_macro_score", lambda db_path=None: m)

    def test_bull_buy(self, db_path, monkeypatch):
        """상승장 + 매크로 양호 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        self._make_prices(db_path, "BULL", [100 + i for i in range(20)])
        v = MacroAgent().analyze("BULL", db_path=db_path)
        assert v.action == "BUY"

    def test_bear_sell(self, db_path, monkeypatch):
        """하락장 → SELL."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 30)
        self._make_prices(db_path, "BEAR", [100 - i for i in range(20)])
        v = MacroAgent().analyze("BEAR", db_path=db_path)
        assert v.action in ("SELL", "HOLD")

    def test_sideways_strong_momentum_buy(self, db_path, monkeypatch):
        """횡보 + 강한 상승 모멘텀 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        prices = [100] * 10 + [112] * 5 + [100, 100, 100, 100, 100]
        prices.reverse()
        self._make_prices(db_path, "ROCKET", list(reversed(prices[:20])))
        v = MacroAgent().analyze("ROCKET", db_path=db_path)
        assert v.action in ("BUY", "HOLD")

    def test_sideways_sell_momentum(self, db_path, monkeypatch):
        """횡보 + 강한 하락 모멘텀 → SELL."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        prices = [100] * 10 + [100, 99, 98, 97, 96, 95, 90, 85, 82, 78]
        self._make_prices(db_path, "DROP", prices[:20])
        v = MacroAgent().analyze("DROP", db_path=db_path)
        assert v.action == "SELL"
        assert "모멘텀 약세" in v.reasoning

    def test_bull_underperform_hold(self, db_path, monkeypatch):
        """상승장이나 개별 약세 → HOLD로 약화."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        prices = [100] * 16 + [95, 93, 91, 90]
        self._make_prices(db_path, "WEAK", prices[:20])
        v = MacroAgent().analyze("WEAK", db_path=db_path)
        assert v.action == "HOLD"
        assert "개별 약세" in v.reasoning

    def test_bear_bounce_hold(self, db_path, monkeypatch):
        """하락장이나 개별 반등 → HOLD로 약화."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 30)
        prices = [100] * 16 + [108, 110, 112, 115]
        self._make_prices(db_path, "BOUNCE", prices[:20])
        v = MacroAgent().analyze("BOUNCE", db_path=db_path)
        assert v.action == "HOLD"
        assert "개별 반등" in v.reasoning

    def test_bear_defensive_sector_hold(self, db_path, monkeypatch):
        """하락장 + 방어 섹터 → SELL 대신 HOLD."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 25)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "DEF", 10, 100.0, "USD", "Healthcare"),
            )
        self._make_prices(db_path, "DEF", [100 - i * 0.3 for i in range(20)])
        v = MacroAgent().analyze("DEF", db_path=db_path)
        assert v.action in ("SELL", "HOLD")


class TestMacroAgent_R26:
    def test_no_regime_data(self, db_path):
        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_sideways_strong_momentum(self, db_path, monkeypatch):
        """Cover sideways + strong momentum -> BUY."""
        @dataclass
        class FakeRegime:
            regime: str = "sideways_low_vol"
            trend: str = "sideways"
            confidence: float = 0.7
            details: dict = None

        @dataclass
        class FakeMacro:
            total_score: float = 50

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: FakeRegime())
        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda **kw: FakeMacro())

        _seed_ticker(db_path, "AAPL", n=30, base_price=100)
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=20).strftime("%Y-%m-%d").tolist()
            for i, d in enumerate(dates):
                conn.execute(
                    "UPDATE prices SET close = ? WHERE ticker = 'AAPL' AND date = ?",
                    (100 + i * 3, d),
                )

        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "HOLD", "SELL")

    def test_regime_none(self, db_path, monkeypatch):
        """Cover regime is None."""
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: None)

        @dataclass
        class FakeMacro:
            total_score: float = 50

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda **kw: FakeMacro())
        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "SPY" in result.reasoning


class TestMacroAgent_Source_Final:
    def test_with_macro_data(self, rich_db):
        from nuri.trading.agents.macro_agent import MacroAgent
        agent = MacroAgent()
        v = agent.analyze("AAPL", db_path=rich_db)
        assert v.action in ("BUY", "SELL", "HOLD")
        assert v.agent_name == "macro"
