"""Tests for fundamental agent — split from test_trading_agents_all.py."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestFundamentalAgent:
    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        v = FundamentalAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


class TestFundamentalBranches:
    """펀더멘탈 에이전트 PE/ROE 분기 커버리지."""

    def test_undervalued_buy(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("CHEAP", "2025-03-25", 10.0, 0.25, 0.30, 1.0),
            )
        v = FundamentalAgent().analyze("CHEAP", db_path=db_path)
        assert v.action == "BUY"
        assert "저평가" in v.reasoning

    def test_overvalued_sell(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("EXPENSIVE", "2025-03-25", 50.0, -0.05, -0.15, 3.0),
            )
        v = FundamentalAgent().analyze("EXPENSIVE", db_path=db_path)
        assert v.action == "SELL"

    def test_fair_value_hold(self, db_path):
        """PE 30 (적정~고) + ROE 8% (보통) → HOLD."""
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth) VALUES (?, ?, ?, ?, ?)",
                ("FAIR", "2025-03-25", 30.0, 0.08, 0.05),
            )
        v = FundamentalAgent().analyze("FAIR", db_path=db_path)
        assert v.action == "HOLD"


class TestFundamentalAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        result = FundamentalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "없음" in result.reasoning

    def test_overvalued_negative_roe(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-28", 50, -0.05, -0.15, 3.0),
            )
        from nuri.trading.agents.fundamental import FundamentalAgent

        result = FundamentalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"

    def test_strong_buy(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-28", 10, 0.25, 0.30, 0.5),
            )
        from nuri.trading.agents.fundamental import FundamentalAgent

        result = FundamentalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "BUY"


class TestFundamentalAgent_Source_Final:
    def test_no_data(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        agent = FundamentalAgent()
        v = agent.analyze("FAKE", db_path=db_path)
        assert v.action == "HOLD"

    def test_with_fundamentals(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (date, ticker, pe_ratio, roe, revenue_growth, debt_to_equity, operating_margin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2026-03-28", "NVDA", 37.0, 0.85, 0.55, 0.30, 0.55),
            )
        from nuri.trading.agents.fundamental import FundamentalAgent

        agent = FundamentalAgent()
        v = agent.analyze("NVDA", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")


# ─── Phase 3-D #616: branch coverage ──────────────────────────────────


class TestFundamentalAgentBranches:
    def test_no_pe_skips_pe_block(self, db_path):
        """35→49: pe NULL/0 → if False → roe block 으로."""
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe) VALUES (?, ?, ?, ?)",
                ("NOPE", "2026-05-06", None, 0.25),  # pe 없음, roe 있음
            )
        v = FundamentalAgent().analyze("NOPE", db_path=db_path)
        assert "PE" not in v.reasoning  # PE 분기 skip 됨
        assert "ROE" in v.reasoning  # ROE 분기는 진입

    def test_no_roe_skips_roe_block(self, db_path):
        """51→63: roe NULL → if False → growth block 으로."""
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth) VALUES (?, ?, ?, ?, ?)",
                ("NOROE", "2026-05-06", 15.0, None, 0.30),
            )
        v = FundamentalAgent().analyze("NOROE", db_path=db_path)
        assert "ROE" not in v.reasoning
        assert "매출성장" in v.reasoning

    def test_no_growth_skips_growth_block(self, db_path):
        """65→74: growth NULL → if False → debt block 으로."""
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?)",
                ("NOGROWTH", "2026-05-06", 15.0, None, 3.0),
            )
        v = FundamentalAgent().analyze("NOGROWTH", db_path=db_path)
        assert "매출" not in v.reasoning  # growth 분기 skip
        assert "부채비율" in v.reasoning  # debt block 진입
