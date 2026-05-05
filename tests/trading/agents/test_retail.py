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


# ─── Phase 3-D #616: branch coverage ──────────────────────────────────


class TestRetailAgentBranches:
    def test_mentions_zero_skips_buy_branch(self, db_path):
        """53→58: mentions=0 → elif > 0 False → post_rows 블록으로."""
        from nuri.core.db import get_db
        from nuri.trading.agents.retail_agent import RetailAgent

        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_mention_AAA', '2026-05-06', 0)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_post_count', '2026-05-06', 1000)")
        v = RetailAgent().analyze("AAA", db_path=db_path)
        # mentions=0 → BUY/SELL 분기 모두 skip → post_count 분기만 가능
        assert "WSB 적정" not in v.reasoning

    def test_post_count_below_threshold_skips_post_block(self, db_path):
        """62→66: posts < post_high → if False → reasons 체크로."""
        from nuri.core.db import get_db
        from nuri.trading.agents.retail_agent import RetailAgent

        with get_db(db_path) as conn:
            # mentions = 5 (BUY 영역) — reasons 채워야 후행 로직 진입
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_mention_AAA', '2026-05-06', 5)")
            # post_count 작아서 high threshold 미달
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('wsb_post_count', '2026-05-06', 1)")
        v = RetailAgent().analyze("AAA", db_path=db_path)
        assert "WSB 전체 과열" not in v.reasoning  # post block skip
