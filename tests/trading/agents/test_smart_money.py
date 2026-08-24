"""Tests for smart_money agent — split from test_trading_agents_all.py."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


def _d(days_ago: int) -> str:
    """오늘 앵커 날짜 — 고정 리터럴은 시한폭탄 (tests/CLAUDE.md Time-bomb seed dates, #1187)."""
    return (kst_now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


class TestSmartMoneyBranches:
    """스마트머니 에이전트 분기 커버리지."""

    def test_superinvestor_buy(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) VALUES (?, ?, ?, ?)",
                ("Buffett", "GOOD", 8.0, _d(30)),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) VALUES (?, ?, ?, ?)",
                ("Dalio", "GOOD", 3.0, _d(30)),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("GOOD", _d(5), "buy", 200.0, 100.0, 10),
            )
        v = SmartMoneyAgent().analyze("GOOD", db_path=db_path)
        assert v.action == "BUY"
        assert v.data_points["n_superinvestors"] == 2

    def test_analyst_sell(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("BAD", _d(5), "sell", 50.0, 100.0, 5),
            )
        v = SmartMoneyAgent().analyze("BAD", db_path=db_path)
        assert v.action == "SELL"

    def test_ark_buy(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        with get_db(db_path) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("ARKY", _d(4 - i), "Buy", 1000),
                )
        v = SmartMoneyAgent().analyze("ARKY", db_path=db_path)
        assert "ARK" in v.reasoning


class TestSmartMoneyAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        result = SmartMoneyAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "없음" in result.reasoning

    def test_superinvestors_buy(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, shares, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", 1000, 8.0, _d(30)),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, shares, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Gates", "AAPL", 500, 3.0, _d(30)),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", _d(30), "buy", 200, 150, 20),
            )
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        result = SmartMoneyAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "BUY"

    def test_analyst_sell(self, db_path):
        """Cover sell recommendation + downside target."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", _d(30), "sell", 100, 150, 10),
            )
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        result = SmartMoneyAgent().analyze("AAPL", db_path=db_path)
        assert any("하회" in r for r in result.reasoning.split("; "))


class TestSmartMoneyAgent_Source_Final:
    def test_no_data(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        agent = SmartMoneyAgent()
        v = agent.analyze("NEWCO", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")
        assert 0 <= v.confidence <= 100

    def test_with_superinvestor_data(self, db_path):
        with get_db(db_path) as conn:
            for inv in ["Buffett", "Gates", "Dalio"]:
                conn.execute(
                    "INSERT INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (inv, _d(30), "AAPL", 1000000, 150000000, 3.5),
                )
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        agent = SmartMoneyAgent()
        v = agent.analyze("AAPL", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")
