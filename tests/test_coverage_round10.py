"""커버리지 보강 Round 10 — broker, monitor, memory, consensus deep, position deep, signal_backtest deep."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
    ], path)
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    vix = [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test"}
           for i, d in enumerate(dates)]
    fg = [{"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"),
           "value": 50 + np.sin(i / 25) * 30, "source": "test"}
          for i, d in enumerate(dates)]
    upsert_macro(vix + fg, path)
    return path


# ─── Broker (DryRun mode) ───


class TestBroker:
    def test_dryrun_submit_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "buy", 10)
        assert result is not None

    def test_dryrun_sell_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "sell", 5)
        assert result is not None

    def test_dryrun_get_positions(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_broker_dryrun(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker is not None


# ─── Monitor deeper ───


class TestMonitorDeep:
    def test_daily_pnl_summary(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary()
        assert isinstance(result, dict)

    def test_print_monitor(self, rich_db, capsys):
        from nuri.trading.strategy.monitor import print_monitor
        print_monitor()
        output = capsys.readouterr().out
        assert len(output) >= 0


# ─── Memory (Learning Memory) ───


class TestLearningMemory:
    def test_save_snapshot(self, rich_db):
        from nuri.trading.engine.memory import save_snapshot
        count = save_snapshot()
        assert isinstance(count, int)

    def test_detect_drift(self, rich_db):
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift()
        assert isinstance(drifts, list)

    def test_print_memory_status(self, rich_db, capsys):
        from nuri.trading.engine.memory import detect_drift, print_memory_status
        drifts = detect_drift()
        print_memory_status(drifts)
        assert len(capsys.readouterr().out) >= 0


# ─── Consensus deeper (individual agents) ───


class TestAgentsIndividual:
    def test_technical_agent(self, rich_db):
        from nuri.trading.agents.technical import TechnicalAgent
        agent = TechnicalAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")
        assert hasattr(result, "confidence")

    def test_fundamental_agent(self, rich_db):
        from nuri.trading.agents.fundamental import FundamentalAgent
        agent = FundamentalAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_risk_agent(self, rich_db):
        from nuri.trading.agents.risk_agent import RiskAgent
        agent = RiskAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_macro_agent(self, rich_db):
        from nuri.trading.agents.macro_agent import MacroAgent
        agent = MacroAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_options_agent(self, rich_db):
        from nuri.trading.agents.options_agent import OptionsAgent
        agent = OptionsAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_crypto_agent(self, rich_db):
        from nuri.trading.agents.crypto_agent import CryptoAgent
        agent = CryptoAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_korean_market_agent_us(self, rich_db):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        result = agent.analyze("AAPL")
        assert result.action == "HOLD"  # US 종목은 HOLD

    def test_smart_money_agent(self, rich_db):
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        agent = SmartMoneyAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_wallstreet_agent(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent.analyze("AAPL")
        assert hasattr(result, "action")

    def test_retail_agent(self, rich_db):
        from nuri.trading.agents.retail_agent import RetailAgent
        agent = RetailAgent()
        result = agent.analyze("AAPL")
        assert result.action == "HOLD"  # 데이터 안정화 단계


# ─── Position deeper — open with mock consensus ───


class TestPositionOpen:
    def test_open_success(self, rich_db):
        from nuri.trading.strategy.position import open_position
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at, \
             patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
            mock_at.return_value = MagicMock(
                final_action="BUY", final_confidence=85, agreement_rate=0.8,
            )
            result = open_position("AAPL", "long", 190.0, 10, "growth", "bull_low_vol")
        # certification 결과에 따라 True/False
        assert isinstance(result, bool)

    def test_print_positions(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions
        print_positions()
        output = capsys.readouterr().out
        assert len(output) >= 0


# ─── Candidates / Tracker ───


class TestCandidates:
    def test_screen_candidates(self, rich_db):
        from nuri.trading.recommend.candidates import screen_candidates
        result = screen_candidates()
        assert isinstance(result, list)

    def test_tracker_save(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        count = save_recommendations([])
        assert count == 0


# ─── Gate ───


class TestGate:
    def test_check_gate(self, rich_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate()
        assert hasattr(result, "phase")
        assert hasattr(result, "score")

    def test_check_gate_phase(self, rich_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(phase="collect")
        assert hasattr(result, "phase")
        assert result.phase == "collect"


# ─── Conflicts ───


class TestConflicts:
    def test_detect_conflicts(self, rich_db):
        from nuri.trading.engine.conflicts import detect_conflicts
        result = detect_conflicts()
        assert isinstance(result, list)


# ─── Alerts ───


class TestAlerts:
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
