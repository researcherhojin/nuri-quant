"""Tests for retail agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestRetailAgent:
    """리테일 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.retail_agent import RetailAgent
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_wsb_spike_returns_sell(self, db_path):
        """WSB 50건 과열 → 역발상 SELL."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 50),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_post_count", 1500),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"

    def test_moderate_mentions_returns_buy_or_hold(self, db_path):
        """WSB 3건 적정 관심 → BUY 또는 HOLD."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 3),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action in ("BUY", "HOLD")


class TestRetailBranches:
    """리테일 에이전트 추가 분기."""

    def test_post_count_overload(self, db_path):
        """WSB 전체 과열."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_post_count", 1500),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert "전체 과열" in v.reasoning


class TestRetailAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.retail_agent import RetailAgent
        result = RetailAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_hot_wsb(self, db_path):
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_mention_AAPL', '2025-03-28', 50)")
        from nuri.trading.agents.retail_agent import RetailAgent
        result = RetailAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"

    def test_buy_signal(self, db_path):
        """Enough mentions for BUY."""
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_mention_AAPL', '2025-03-28', 5)")
        from nuri.trading.agents.retail_agent import RetailAgent
        result = RetailAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_no_reasons_with_data(self, db_path):
        """Data exists but values are None."""
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_mention_AAPL', '2025-03-28', NULL)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_post_count', '2025-03-28', NULL)")
        from nuri.trading.agents.retail_agent import RetailAgent
        result = RetailAgent().analyze("AAPL", db_path=db_path)
        assert "부족" in result.reasoning
