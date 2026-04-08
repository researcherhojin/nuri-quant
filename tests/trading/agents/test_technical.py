"""Tests for technical agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestTechnicalAgent:
    def test_returns_verdict(self, agent_data):
        from nuri.trading.agents.technical import TechnicalAgent
        v = TechnicalAgent().analyze("TEST", db_path=agent_data)
        assert v.agent_name == "technical"
        assert v.action in ("BUY", "SELL", "HOLD")
        assert 0 <= v.confidence <= 100

    def test_no_data(self, db_path):
        from nuri.trading.agents.technical import TechnicalAgent
        v = TechnicalAgent().analyze("NONE", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0


class TestTechnicalAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "부족" in result.reasoning

    def test_with_price_data(self, db_path):
        _seed_ticker(db_path, "AAPL", n=60)
        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert result.data_points.get("rsi") is not None

    def test_yfinance_fallback_no_db_path(self, db_path, monkeypatch):
        """Cover yfinance fallback when prices table empty."""
        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("NONEXIST", db_path=db_path)
        assert result.action == "HOLD"
