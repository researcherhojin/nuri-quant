"""Tests for base agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestNormalizeConfidence:
    """confidence 정규화 테스트."""

    def test_normalization_enabled(self):
        from nuri.trading.agents.technical import TechnicalAgent
        agent = TechnicalAgent()
        assert agent.normalize_confidence(90) == 100.0
        assert agent.normalize_confidence(0) == 0.0
        assert agent.normalize_confidence(45) == 50.0

    def test_korean_market_identity(self):
        """Korean market (0-100 → 0-100) 변환 없음."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        assert agent.normalize_confidence(50) == 50.0
        assert agent.normalize_confidence(100) == 100.0

    def test_clamp_bounds(self):
        """범위 밖 값은 0-100으로 클램핑."""
        from nuri.trading.agents.fundamental import FundamentalAgent
        agent = FundamentalAgent()
        assert agent.normalize_confidence(100) == 100.0
        assert agent.normalize_confidence(-10) == 0.0

    def test_disabled_normalization(self, monkeypatch):
        """정규화 비활성화 시 원본 반환."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": False, "scales": {"technical": {"raw_min": 0, "raw_max": 90}}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(45) == 45

    def test_agent_missing_from_scales(self, monkeypatch):
        """scales에 에이전트 없으면 원본 반환."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": True, "scales": {}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(70) == 70

    def test_zero_range_returns_raw(self, monkeypatch):
        """raw_min == raw_max 시 원본 반환 (0 나누기 방지)."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": True, "scales": {"technical": {"raw_min": 50, "raw_max": 50}}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(50) == 50


class TestNewAgentNullData:
    """새 에이전트 NULL 데이터 처리 테스트."""

    def test_options_null_pcr_value(self, db_path):
        """PCR 값이 NULL인 경우 graceful HOLD."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "put_call_ratio", None),
            )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_crypto_null_change_value(self, db_path):
        """BTC 변화율이 NULL인 경우 graceful HOLD."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", None),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_retail_null_mentions(self, db_path):
        """WSB 언급 값이 NULL인 경우 graceful HOLD."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", None),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


class TestNewAgentDataPoints:
    """새 에이전트 data_points 검증."""

    def test_options_data_points(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 1.0),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert "pcr_avg" in v.data_points
        assert "pcr_latest" in v.data_points
        assert "lookback_count" in v.data_points

    def test_crypto_data_points(self, db_path):
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 5.0),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_dominance", 55.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert "btc_24h_change" in v.data_points
        assert "btc_dominance" in v.data_points

    def test_retail_data_points(self, db_path):
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 5),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert "wsb_mentions" in v.data_points


class TestBaseAgent:
    def test_safe_query_exception(self, db_path, monkeypatch):
        from nuri.trading.agents.base import BaseAgent
        class DummyAgent(BaseAgent):
            def analyze(self, ticker, db_path=None):
                return None
        agent = DummyAgent("test")
        monkeypatch.setattr("nuri.core.db.query", MagicMock(side_effect=Exception("db error")))
        result = agent._safe_query("SELECT 1")
        assert result == []

    def test_normalize_confidence_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "nuri.trading.agents.base._load_norm_config",
            lambda: {"enabled": False},
        )
        from nuri.trading.agents.base import BaseAgent
        class DummyAgent(BaseAgent):
            def analyze(self, ticker, db_path=None):
                return None
        agent = DummyAgent("test")
        assert agent.normalize_confidence(75.0) == 75.0

    def test_normalize_confidence_no_scale(self, monkeypatch):
        monkeypatch.setattr(
            "nuri.trading.agents.base._load_norm_config",
            lambda: {"enabled": True, "scales": {}},
        )
        from nuri.trading.agents.base import BaseAgent
        class DummyAgent(BaseAgent):
            def analyze(self, ticker, db_path=None):
                return None
        agent = DummyAgent("test")
        assert agent.normalize_confidence(75.0) == 75.0

    def test_normalize_confidence_equal_range(self, monkeypatch):
        """raw_max == raw_min -> return raw."""
        monkeypatch.setattr(
            "nuri.trading.agents.base._load_norm_config",
            lambda: {"enabled": True, "scales": {"test": {"raw_min": 50, "raw_max": 50}}},
        )
        from nuri.trading.agents.base import BaseAgent
        class DummyAgent(BaseAgent):
            def analyze(self, ticker, db_path=None):
                return None
        agent = DummyAgent("test")
        assert agent.normalize_confidence(75.0) == 75.0
