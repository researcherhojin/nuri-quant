"""Tests for risk agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestRiskAgent:
    def test_stop_loss_detected(self, db_path):
        """손절선 돌파 시 SELL + 높은 confidence."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "CRASH", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 70, 30)
        df = pd.DataFrame({
            "ticker": "CRASH", "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close, "high": close, "low": close, "close": close,
            "volume": [100] * 30, "adj_close": close,
        })
        upsert_prices(df, db_path)

        v = RiskAgent().analyze("CRASH", db_path=db_path)
        assert v.action == "SELL"
        assert v.confidence >= 80
        assert "손절선" in v.reasoning


class TestRiskAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.risk_agent import RiskAgent
        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("HOLD", "BUY")

    def test_stop_loss_triggered(self, db_path):
        _seed_ticker(db_path, "AAPL", n=30, base_price=50)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET avg_price = 100 WHERE ticker = 'AAPL'")
        from nuri.trading.agents.risk_agent import RiskAgent
        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"
        assert "손절선" in result.reasoning

    def test_profit_positive(self, db_path):
        """Cover profit > profit_threshold path."""
        _seed_ticker(db_path, "AAPL", n=30, base_price=150)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET avg_price = 100 WHERE ticker = 'AAPL'")
        from nuri.trading.agents.risk_agent import RiskAgent
        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert "수익" in result.reasoning
