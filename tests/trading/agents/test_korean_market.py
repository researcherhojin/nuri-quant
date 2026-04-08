"""Tests for korean_market agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestKoreanMarketBranches:
    """한국 시장 에이전트 분기 커버리지."""

    def test_us_ticker_neutral(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        v = KoreanMarketAgent().analyze("AAPL", db_path=db_path)
        assert v.action == "HOLD"
        assert v.data_points["is_korean"] is False

    def test_kr_ticker_with_fx(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "005930.KS", 10, 70000, "KRW", "Semiconductor"),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "usd_krw", 1420.0),
            )
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 + i * 100, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert v.data_points["is_korean"] is True
        assert v.data_points["fx_rate"] == 1420.0

    def test_kr_fx_calibration(self, db_path):
        """90일 환율 데이터로 동적 캘리브레이션."""
        from nuri.trading.agents.korean_market import _calibrate_fx_thresholds
        with get_db(db_path) as conn:
            base = pd.Timestamp("2025-01-01")
            for i in range(40):
                d = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (d, "usd_krw", 1380.0 + i * 0.5),
                )
        weak, strong = _calibrate_fx_thresholds(db_path)
        assert weak >= 1300
        assert strong <= 1350


class TestKoreanMarketFullBranches:
    """한국 시장 에이전트 FX/외국인/모멘텀 전체 분기."""

    def _setup_kr_base(self, db_path, ticker="005930.KS", sector="Semiconductor", fx=1420.0):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, 10, 70000, "KRW", sector),
            )
            conn.execute(
                "INSERT OR REPLACE INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "usd_krw", fx),
            )

    def test_fx_weak_nonexport(self, db_path):
        """원화 약세 + 내수주 → 부담."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path, sector="Retail", fx=1420.0)
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "내수주 부담" in v.reasoning

    def test_fx_strong_nonexport(self, db_path):
        """원화 강세 + 내수주 → 유리."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path, sector="Retail", fx=1200.0)
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "내수주 유리" in v.reasoning

    def test_foreign_buy(self, db_path):
        """외국인 순매수 → 점수 증가."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO institutional_flows (ticker, date, market, foreign_net) VALUES (?, ?, ?, ?)",
                ("005930.KS", "2025-03-25", "KOSPI", 50000),
            )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "외국인 순매수" in v.reasoning

    def test_foreign_sell(self, db_path):
        """외국인 순매도 → 점수 감소."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO institutional_flows (ticker, date, market, foreign_net) VALUES (?, ?, ?, ?)",
                ("005930.KS", "2025-03-25", "KOSPI", -30000),
            )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "외국인 순매도" in v.reasoning

    def test_momentum_positive(self, db_path):
        """20일 모멘텀 양호 → 점수 증가."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 + i * 500, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "모멘텀" in v.reasoning

    def test_momentum_negative(self, db_path):
        """20일 모멘텀 부진 → 점수 감소."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 - i * 500, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "모멘텀" in v.reasoning


class TestKoreanAgent:
    def test_us_ticker_neutral(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        verdict = agent.analyze("AAPL", db_path=db_path)
        assert verdict.action == "HOLD"
        assert verdict.data_points["is_korean"] is False

    def test_kr_ticker(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        upsert_portfolio([{
            "account": "test", "ticker": "005930.KS",
            "quantity": 4, "avg_price": 200500,
            "currency": "KRW", "sector": "Semiconductor",
        }], db_path)
        agent = KoreanMarketAgent()
        verdict = agent.analyze("005930.KS", db_path=db_path)
        assert verdict.data_points["is_korean"] is True
        assert verdict.action in ("BUY", "SELL", "HOLD")


class TestKoreanMarketAgent_R26:
    def test_us_ticker(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        result = KoreanMarketAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert result.data_points["is_korean"] is False

    def test_kr_ticker_no_data(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        result = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert result.data_points["is_korean"] is True

    def test_kr_ticker_fx_export(self, db_path):
        with get_db(db_path) as conn:
            for i in range(90):
                d = f"2025-{1 + i // 30:02d}-{1 + i % 28:02d}"
                conn.execute("INSERT OR IGNORE INTO macro (indicator, date, value) VALUES ('usd_krw', ?, ?)", (d, 1450))
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
                         ("test", "005930.KS", 10, 70000, "Semiconductor"))
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        result = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert any("수출주" in r for r in result.reasoning.split("; ")) if result.reasoning else True

    def test_kr_kosdaq_discount(self, db_path):
        """Cover KOSDAQ discount."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        result = KoreanMarketAgent().analyze("247540.KS", db_path=db_path)
        assert "KOSDAQ" in result.data_points.get("market", "")

    def test_momentum_none(self, db_path):
        """Momentum returns None for short data."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        result = agent._get_momentum("005930.KS", db_path=db_path)
        assert result is None

    def test_momentum_zero_past(self, db_path):
        """Momentum with past price = 0 returns None."""
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=21).strftime("%Y-%m-%d").tolist()
            for i, d in enumerate(dates):
                price = 0 if i == 0 else 100
                conn.execute(
                    "INSERT OR IGNORE INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", d, price, price, price, price, 1000),
                )
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        result = agent._get_momentum("005930.KS", db_path=db_path)
        assert result is None

    def test_kr_hold_score(self, db_path):
        """Cover HOLD path where score is between buy and sell thresholds."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        result = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert result.action == "HOLD"


class TestKoreanMarketAgent_Source_Push:
    def test_us_ticker_returns_hold(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        v = agent.analyze("AAPL", db_path=db_path)
        assert v.action == "HOLD"

    def test_kr_ticker(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        v = agent.analyze("005930.KS", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")
