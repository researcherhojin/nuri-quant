"""Tests for crypto agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestCryptoAgent:
    """크립토 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.crypto_agent import CryptoAgent
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_btc_rally_returns_buy(self, db_path):
        """BTC +12% → 리스크온 BUY."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 12.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "BUY"

    def test_btc_crash_returns_sell(self, db_path):
        """BTC -12% → 리스크오프 SELL."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", -12.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"


class TestCryptoBranches:
    """크립토 에이전트 추가 분기."""

    def test_dominance_high(self, db_path):
        """BTC 지배력 높음 → 리스크오프."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_dominance", 65.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert "지배력" in v.reasoning

    def test_btc_price_recorded(self, db_path):
        """BTC 가격 data_points에 포함."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_usd_cg", 95000.0),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 1.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.data_points.get("btc_price") == 95000.0


class TestCryptoAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.crypto_agent import CryptoAgent
        result = CryptoAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_strong_rally(self, db_path):
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_24h_change_pct', '2025-03-28', 15)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_dominance', '2025-03-28', 35)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_usd_cg', '2025-03-28', 90000)")
        from nuri.trading.agents.crypto_agent import CryptoAgent
        result = CryptoAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "BUY"

    def test_severe_crash(self, db_path):
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_24h_change_pct', '2025-03-28', -12)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_dominance', '2025-03-28', 65)")
        from nuri.trading.agents.crypto_agent import CryptoAgent
        result = CryptoAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"

    def test_no_change(self, db_path):
        """Covers 'no reasons' path."""
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_24h_change_pct', '2025-03-28', 0.5)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('btc_dominance', '2025-03-28', 50)")
        from nuri.trading.agents.crypto_agent import CryptoAgent
        result = CryptoAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
