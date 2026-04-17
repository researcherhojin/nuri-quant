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


class TestRiskAgentA3PerAccountThreshold:
    """A-3 Unified sell engine — risk_agent 가 ticker 보유 계좌의 strategy 기반
    threshold 를 사용하는지 검증. 이전 동작: 전 계좌 STOCK_STOP_LOSS=-7 고정.
    Regression lock: threshold 가 다시 global 로 돌아가면 이 테스트들이 fail."""

    def _setup_portfolio_yaml(self, tmp_path, strategy: str):
        from unittest.mock import patch as _patch

        import yaml as _yaml

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(_yaml.dump({"accounts": {"TestAcct": {"strategy": strategy}}}))
        real_open = open

        def _opener(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        return _patch("builtins.open", side_effect=_opener)

    def _seed_ticker_with_loss(self, db_path, ticker, account, avg_price, current_price):
        """Portfolio + 30-day price series 가 current_price 로 끝나게 seed."""
        dates = pd.bdate_range("2026-01-01", periods=30)
        close = np.linspace(avg_price, current_price, 30)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close, "high": close, "low": close, "close": close,
            "volume": [100] * 30, "adj_close": close,
        })
        from nuri.core.db import get_db as _get_db
        from nuri.core.db import upsert_prices as _upsert_prices
        with _get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                (account, ticker, 10, avg_price, "USD"),
            )
        _upsert_prices(df, db_path)

    def test_long_term_account_at_minus_10_does_not_fire_stop_loss(self, db_path, tmp_path):
        """long_term 계좌(-20) 의 -10% 손실 → 손절선 돌파 NOT 발동.
        이전 동작(-7 global): 돌파 발동 (잘못). A-3 fix: holding row 의 account
        (TestAcct → long_term) 로 threshold 조회 → -20 이므로 -10% 는 breach 아님."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "LTMX", "TestAcct", avg_price=100.0, current_price=90.0)
        with self._setup_portfolio_yaml(tmp_path, "long_term"):
            v = RiskAgent().analyze("LTMX", db_path=db_path)

        assert "손절선 돌파" not in v.reasoning
        # -10% 는 loss_threshold (-10) 과 동률이므로 "손실 중" 경로도 안 탐
        assert v.action in ("HOLD", "BUY")

    def test_long_term_account_at_minus_22_fires_stop_loss(self, db_path, tmp_path):
        """long_term(-20) 계좌 -22% 손실 → 실제 breach 이므로 손절선 돌파 발동 (A-3 operator: <)."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "LTMX", "TestAcct", avg_price=100.0, current_price=78.0)
        with self._setup_portfolio_yaml(tmp_path, "long_term"):
            v = RiskAgent().analyze("LTMX", db_path=db_path)

        assert "손절선 돌파" in v.reasoning
        assert v.action == "SELL"

    def test_core_account_at_minus_8_still_fires(self, db_path, tmp_path):
        """core(-7) 계좌 -8% → breach (pnl < threshold), 기존 동작 유지."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "CORE1", "TestAcct", avg_price=100.0, current_price=92.0)
        with self._setup_portfolio_yaml(tmp_path, "core"):
            v = RiskAgent().analyze("CORE1", db_path=db_path)

        assert "손절선 돌파" in v.reasoning
        assert v.action == "SELL"

    def test_safely_above_threshold_does_not_fire(self, db_path, tmp_path):
        """core(-7) 계좌 -5% (threshold 대비 여유) → 손절선 돌파 안 함.
        A-3 operator 가 `<` 임을 확인 (이전은 `<=`). 정확한 -7.0 boundary 는 float
        imprecision 으로 불안정 (93.0/100*100 = -7.000000000000001) → 안전 마진."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "CORE1", "TestAcct", avg_price=100.0, current_price=95.0)
        with self._setup_portfolio_yaml(tmp_path, "core"):
            v = RiskAgent().analyze("CORE1", db_path=db_path)

        assert "손절선 돌파" not in v.reasoning
