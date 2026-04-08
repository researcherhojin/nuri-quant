"""Tests for options agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestOptionsAgent:
    """옵션 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_high_pcr_returns_buy(self, db_path):
        """PCR 1.3 (극도 공포) → 역발상 BUY."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 1.3),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "BUY"
        assert v.confidence > 0

    def test_low_pcr_returns_sell(self, db_path):
        """PCR 0.5 (과도한 낙관) → 경계 SELL."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 0.5),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"
        assert v.confidence > 0


class TestOptionsBranches:
    """옵션 에이전트 추가 분기."""

    def test_neutral_pcr(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 0.9),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert "중립" in v.reasoning

    def test_pcr_trend(self, db_path):
        """PCR 상승 추세 감지."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i, val in enumerate([1.5, 0.9, 0.9, 0.9, 0.9]):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{25-i:02d}", "put_call_ratio", val),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert "상승 추세" in v.reasoning or "공포" in v.reasoning


class TestOptionsAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent
        result = OptionsAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_high_pcr_buy(self, db_path):
        with get_db(db_path) as conn:
            for i in range(5):
                d = f"2025-03-{24 + i}"
                conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('put_call_ratio', ?, ?)", (d, 1.3))
        from nuri.trading.agents.options_agent import OptionsAgent
        result = OptionsAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "BUY"

    def test_low_pcr_sell(self, db_path):
        with get_db(db_path) as conn:
            for i in range(5):
                d = f"2025-03-{24 + i}"
                conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('put_call_ratio', ?, ?)", (d, 0.6))
        from nuri.trading.agents.options_agent import OptionsAgent
        result = OptionsAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"

    def test_pcr_trend_rising(self, db_path):
        """Cover PCR trend rising."""
        with get_db(db_path) as conn:
            values = [1.0, 0.9, 0.85, 1.2, 1.4]
            for i, val in enumerate(values):
                d = f"2025-03-{24 + i}"
                conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('put_call_ratio', ?, ?)", (d, val))
        from nuri.trading.agents.options_agent import OptionsAgent
        result = OptionsAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "HOLD")

    def test_pcr_neutral_with_trend(self, db_path):
        """Neutral PCR with falling trend."""
        with get_db(db_path) as conn:
            values = [0.85, 0.9, 0.92, 0.88, 0.7]
            for i, val in enumerate(values):
                d = f"2025-03-{24 + i}"
                conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('put_call_ratio', ?, ?)", (d, val))
        from nuri.trading.agents.options_agent import OptionsAgent
        OptionsAgent().analyze("AAPL", db_path=db_path)
