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


def _insert_finviz_signal(db_path, ticker, signal, date_str=None):
    """external_analysis에 FINVIZ 시그널 삽입 헬퍼."""
    from nuri.core.timezone import today_kst
    if date_str is None:
        date_str = today_kst()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO external_analysis "
            "(date, source, ticker, data_type, value) "
            "VALUES (?, 'FINVIZ', ?, 'finviz_signal', ?)",
            (date_str, ticker, signal),
        )


class TestTechnicalFinviz:
    """FINVIZ 스크리너 보조 시그널 통합 테스트."""

    def test_finviz_oversold_boosts_buy(self, db_path):
        """oversold_rsi FINVIZ 시그널이 buy_signals를 증가시킴."""
        _seed_ticker(db_path, "AAPL", n=60)
        _insert_finviz_signal(db_path, "AAPL", "oversold_rsi")

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert "FINVIZ oversold_rsi" in result.reasoning
        assert "finviz_signals" in result.data_points
        assert "oversold_rsi" in result.data_points["finviz_signals"]

    def test_finviz_overbought_boosts_sell(self, db_path):
        """overbought_rsi FINVIZ 시그널이 sell_signals를 증가시킴."""
        _seed_ticker(db_path, "TSLA", n=60)
        _insert_finviz_signal(db_path, "TSLA", "overbought_rsi")

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("TSLA", db_path=db_path)
        assert "FINVIZ overbought_rsi" in result.reasoning

    def test_finviz_new_high_boosts_sell(self, db_path):
        """new_high FINVIZ 시그널이 sell_signals에 가산."""
        _seed_ticker(db_path, "MSFT", n=60)
        _insert_finviz_signal(db_path, "MSFT", "new_high")

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("MSFT", db_path=db_path)
        assert "FINVIZ new_high" in result.reasoning

    def test_finviz_new_low_boosts_buy(self, db_path):
        """new_low FINVIZ 시그널이 buy_signals에 가산."""
        _seed_ticker(db_path, "GOOG", n=60)
        _insert_finviz_signal(db_path, "GOOG", "new_low")

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("GOOG", db_path=db_path)
        assert "FINVIZ new_low" in result.reasoning

    def test_finviz_no_data_graceful(self, db_path):
        """FINVIZ 데이터 없으면 기존 동작 변경 없음."""
        _seed_ticker(db_path, "NVDA", n=60)

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("NVDA", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert "FINVIZ" not in result.reasoning
        assert "finviz_signals" not in result.data_points

    def test_finviz_stale_data_ignored(self, db_path):
        """max_age_days 초과 데이터는 무시."""
        from datetime import timedelta

        from nuri.core.timezone import kst_now
        old_date = (kst_now() - timedelta(days=10)).strftime("%Y-%m-%d")
        _seed_ticker(db_path, "META", n=60)
        _insert_finviz_signal(db_path, "META", "oversold_rsi", date_str=old_date)

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("META", db_path=db_path)
        assert "FINVIZ" not in result.reasoning

    def test_finviz_neutral_signal_ignored(self, db_path):
        """unusual_volume 같은 중립 시그널은 buy/sell에 가산하지 않음."""
        _seed_ticker(db_path, "AMZN", n=60)
        _insert_finviz_signal(db_path, "AMZN", "unusual_volume")

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("AMZN", db_path=db_path)
        assert "FINVIZ unusual_volume" not in result.reasoning

    def test_finviz_multiple_signals(self, db_path):
        """복수 FINVIZ 시그널이 모두 반영됨 (다른 날짜로 저장 — UNIQUE 제약 우회)."""
        from datetime import timedelta

        from nuri.core.timezone import kst_now
        _seed_ticker(db_path, "NFLX", n=60)
        today = kst_now().strftime("%Y-%m-%d")
        yesterday = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        _insert_finviz_signal(db_path, "NFLX", "oversold_rsi", date_str=today)
        _insert_finviz_signal(db_path, "NFLX", "new_low", date_str=yesterday)

        from nuri.trading.agents.technical import TechnicalAgent
        result = TechnicalAgent().analyze("NFLX", db_path=db_path)
        assert "FINVIZ oversold_rsi" in result.reasoning
        assert "FINVIZ new_low" in result.reasoning
        assert len(result.data_points["finviz_signals"]) == 2
