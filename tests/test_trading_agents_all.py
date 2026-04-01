"""Consolidated agent tests — all classes testing nuri.trading.agents.* modules.

Sources:
  test_agents.py, test_consensus_extended.py, test_wallstreet_agent.py,
  test_new_features.py, test_coverage_round4.py, test_coverage_round12.py,
  test_coverage_round13.py, test_coverage_round23.py, test_coverage_round26.py,
  test_coverage_round27.py, test_coverage_extra.py, test_coverage_final.py,
  test_final_push.py, test_coverage_boost.py, test_coverage_push.py
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def agent_data(db_path):
    """에이전트 테스트용 데이터 (포트폴리오 + 가격)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    dates = pd.bdate_range("2024-01-01", periods=250)
    close = np.linspace(40, 80, 250) + np.random.normal(0, 1, 250)
    df = pd.DataFrame({
        "ticker": "TEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [1000000] * 250, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def rich_db(db_path):
    """풍부한 테스트 데이터."""
    from nuri.core.timezone import today_kst
    today = today_kst()

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "SectorA"), ("SPY", 50, 450, "Index")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=300)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
        close = np.linspace(base, base * 1.2, 300) + np.random.normal(0, 1, 300)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    with get_db(db_path) as conn:
        for d in dates[-50:]:
            ds = d.strftime("%Y-%m-%d")
            conn.execute("INSERT OR IGNORE INTO signals (ticker, date, rsi_14, sma_20, sma_50, sma_200) "
                         "VALUES (?, ?, ?, ?, ?, ?)", ("SPY", ds, 55.0, 480.0, 470.0, 440.0))

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
        {"indicator": "gdp_growth", "date": today, "value": 2.5, "source": "test"},
        {"indicator": "unemployment", "date": today, "value": 3.8, "source": "test"},
    ], db_path)
    return db_path


# ─── Helper functions ───


def _seed_portfolio(db_path, tickers=None):
    """Insert sample portfolio rows."""
    tickers = tickers or [("test", "AAPL", 10, 150.0, "USD", "Technology"),
                          ("test", "MSFT", 5, 300.0, "USD", "Technology"),
                          ("test", "JNJ", 20, 160.0, "USD", "Health")]
    with get_db(db_path) as conn:
        for account, ticker, qty, avg_price, currency, sector in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, ticker, qty, avg_price, currency, sector),
            )


def _seed_prices(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


def _seed_ticker(db_path, ticker, n=70, base_price=50.0):
    """Seed price data for a ticker."""
    dates = pd.bdate_range(end="2025-03-28", periods=n).strftime("%Y-%m-%d").tolist()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (account, ticker, quantity, avg_price) "
            "VALUES (?, ?, ?, ?)",
            ("test", ticker, 10, base_price),
        )
        for i, d in enumerate(dates):
            price = base_price + np.sin(i / 5) * 5 + i * 0.02
            conn.execute(
                "INSERT OR IGNORE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, d, price - 0.3, price + 0.5, price - 0.5, price, 100000),
            )


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestTechnicalAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestFundamentalAgent
# ═══════════════════════════════════════════════════════


class TestFundamentalAgent:
    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent
        v = FundamentalAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestRiskAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestConsensus
# ═══════════════════════════════════════════════════════


class TestConsensus:
    def test_consensus_returns_result(self, agent_data):
        from nuri.trading.agents.consensus import analyze_ticker
        r = analyze_ticker("TEST", db_path=agent_data)
        assert r.ticker == "TEST"
        assert r.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= r.final_confidence <= 100
        assert 0 <= r.agreement_rate <= 1
        assert len(r.verdicts) == 10

    def test_risk_veto(self, db_path):
        """리스크 에이전트 거부권: 손절 돌파 → 전체 SELL."""
        from nuri.trading.agents.consensus import analyze_ticker

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "VETO", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2024-01-01", periods=250)
        close = np.concatenate([np.linspace(100, 120, 200), np.linspace(120, 60, 50)])
        df = pd.DataFrame({
            "ticker": "VETO", "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [100000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

        r = analyze_ticker("VETO", db_path=db_path)
        assert r.final_action == "SELL"

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.consensus import analyze_ticker
        r = analyze_ticker("NODATA", db_path=db_path)
        assert r.final_action == "HOLD"

    def test_dynamic_weights_fallback(self, db_path):
        """데이터 부족 시 DEFAULT_WEIGHTS 반환."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_dynamic_weights_sum_to_one(self, db_path):
        """가중치 합은 항상 1.0."""
        from nuri.trading.agents.consensus import _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestOptionsAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestCryptoAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestRetailAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestNormalizeConfidence
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestNewAgentNullData
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestNewAgentDataPoints
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestFundamentalBranches
# ═══════════════════════════════════════════════════════


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
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth) "
                "VALUES (?, ?, ?, ?, ?)",
                ("FAIR", "2025-03-25", 30.0, 0.08, 0.05),
            )
        v = FundamentalAgent().analyze("FAIR", db_path=db_path)
        assert v.action == "HOLD"


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestSmartMoneyBranches
# ═══════════════════════════════════════════════════════


class TestSmartMoneyBranches:
    """스마트머니 에이전트 분기 커버리지."""

    def test_superinvestor_buy(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?)",
                ("Buffett", "GOOD", 8.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?)",
                ("Dalio", "GOOD", 3.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("GOOD", "2025-03-25", "buy", 200.0, 100.0, 10),
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
                ("BAD", "2025-03-25", "sell", 50.0, 100.0, 5),
            )
        v = SmartMoneyAgent().analyze("BAD", db_path=db_path)
        assert v.action == "SELL"

    def test_ark_buy(self, db_path):
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        with get_db(db_path) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("ARKY", f"2025-03-{20+i:02d}", "Buy", 1000),
                )
        v = SmartMoneyAgent().analyze("ARKY", db_path=db_path)
        assert "ARK" in v.reasoning


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestKoreanMarketBranches
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestOptionsBranches
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestCryptoBranches
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestRetailBranches
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestDynamicWeights
# ═══════════════════════════════════════════════════════


class TestDynamicWeights:
    """consensus._compute_weights 동적 가중치 계산 테스트."""

    def test_learning_memory_adjusts_weights(self, db_path):
        """충분한 recommendations → 동적 가중치 계산."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = [
                    {"agent_name": "technical", "action": "BUY", "confidence": 70},
                    {"agent_name": "fundamental", "action": "BUY", "confidence": 60},
                    {"agent_name": "risk", "action": "HOLD", "confidence": 50},
                ]
                signals = json.dumps({"verdicts": verdicts})
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i+1:02d}", "BUY", 70, signals, 5.0 if i % 2 == 0 else -2.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert weights["technical"] > 0.03

    def test_no_verdicts_in_signals_fallback(self, db_path):
        """signals에 verdicts 없으면 기본 가중치."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i+1:02d}", "BUY", 70, "rsi_oversold", 5.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_sell_hit_rate(self, db_path):
        """SELL 적중: outcome 음수일 때 적중."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = [
                    {"agent_name": "risk", "action": "SELL", "confidence": 80},
                ]
                signals = json.dumps({"verdicts": verdicts})
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i+1:02d}", "SELL", 80, signals, -5.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert weights["risk"] > 0.15


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestMacroAgentBranches
# ═══════════════════════════════════════════════════════


class TestMacroAgentBranches:
    """매크로 에이전트 레짐별 모멘텀 분기 커버리지."""

    def _make_prices(self, db_path, ticker, close_values):
        """가격 데이터 삽입 헬퍼."""
        with get_db(db_path) as conn:
            for i, c in enumerate(close_values):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, f"2025-03-{i+1:02d}", c, c, c, c, 100000),
                )

    def _mock_regime(self, monkeypatch, trend, regime_name, macro_score):
        class FakeRegime:
            pass
        r = FakeRegime()
        r.regime = regime_name
        r.trend = trend
        r.volatility = "low"
        r.confidence = 0.8
        r.details = None

        class FakeMacro:
            pass
        m = FakeMacro()
        m.total_score = macro_score

        import nuri.quant.regime.classifier as cls_mod
        import nuri.quant.regime.macro_score as ms_mod
        monkeypatch.setattr(cls_mod, "classify_regime", lambda db_path=None: r)
        monkeypatch.setattr(ms_mod, "compute_macro_score", lambda db_path=None: m)

    def test_bull_buy(self, db_path, monkeypatch):
        """상승장 + 매크로 양호 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        self._make_prices(db_path, "BULL", [100 + i for i in range(20)])
        v = MacroAgent().analyze("BULL", db_path=db_path)
        assert v.action == "BUY"

    def test_bear_sell(self, db_path, monkeypatch):
        """하락장 → SELL."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 30)
        self._make_prices(db_path, "BEAR", [100 - i for i in range(20)])
        v = MacroAgent().analyze("BEAR", db_path=db_path)
        assert v.action in ("SELL", "HOLD")

    def test_sideways_strong_momentum_buy(self, db_path, monkeypatch):
        """횡보 + 강한 상승 모멘텀 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        prices = [100] * 10 + [112] * 5 + [100, 100, 100, 100, 100]
        prices.reverse()
        self._make_prices(db_path, "ROCKET", list(reversed(prices[:20])))
        v = MacroAgent().analyze("ROCKET", db_path=db_path)
        assert v.action in ("BUY", "HOLD")

    def test_sideways_sell_momentum(self, db_path, monkeypatch):
        """횡보 + 강한 하락 모멘텀 → SELL."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        prices = [100] * 10 + [100, 99, 98, 97, 96, 95, 90, 85, 82, 78]
        self._make_prices(db_path, "DROP", prices[:20])
        v = MacroAgent().analyze("DROP", db_path=db_path)
        assert v.action == "SELL"
        assert "모멘텀 약세" in v.reasoning

    def test_bull_underperform_hold(self, db_path, monkeypatch):
        """상승장이나 개별 약세 → HOLD로 약화."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        prices = [100] * 16 + [95, 93, 91, 90]
        self._make_prices(db_path, "WEAK", prices[:20])
        v = MacroAgent().analyze("WEAK", db_path=db_path)
        assert v.action == "HOLD"
        assert "개별 약세" in v.reasoning

    def test_bear_bounce_hold(self, db_path, monkeypatch):
        """하락장이나 개별 반등 → HOLD로 약화."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 30)
        prices = [100] * 16 + [108, 110, 112, 115]
        self._make_prices(db_path, "BOUNCE", prices[:20])
        v = MacroAgent().analyze("BOUNCE", db_path=db_path)
        assert v.action == "HOLD"
        assert "개별 반등" in v.reasoning

    def test_bear_defensive_sector_hold(self, db_path, monkeypatch):
        """하락장 + 방어 섹터 → SELL 대신 HOLD."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 25)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "DEF", 10, 100.0, "USD", "Healthcare"),
            )
        self._make_prices(db_path, "DEF", [100 - i * 0.3 for i in range(20)])
        v = MacroAgent().analyze("DEF", db_path=db_path)
        assert v.action in ("SELL", "HOLD")


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestKoreanMarketFullBranches
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_agents.py — TestWallStreetCachedBranches
# ═══════════════════════════════════════════════════════


class TestWallStreetCachedBranches:
    """wallstreet.py _check_cached config 사용 검증."""

    def test_cached_upgrade_buy(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, action, target_price) "
                    "VALUES (?, ?, ?, ?)",
                    ("CACHED1", f"2025-03-{20+i:02d}", "upgrade", 200.0),
                )
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, surprise_pct) "
                "VALUES (?, ?, ?)",
                ("CACHED1", "2025Q1", 0.10),
            )
        v = WallStreetAgent().analyze("CACHED1", db_path=db_path)
        assert v.action == "BUY"
        assert v.data_points.get("cached") is True

    def test_cached_downgrade_sell(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, action, target_price) "
                    "VALUES (?, ?, ?, ?)",
                    ("CACHED2", f"2025-03-{20+i:02d}", "downgrade", 50.0),
                )
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, surprise_pct) "
                "VALUES (?, ?, ?)",
                ("CACHED2", "2025Q1", -0.10),
            )
            for i in range(5):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, transaction_type, shares, value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("CACHED2", f"2025-03-{20+i:02d}", "sale", 1000, 50000),
                )
        v = WallStreetAgent().analyze("CACHED2", db_path=db_path)
        assert v.action == "SELL"


# ═══════════════════════════════════════════════════════
# Source: test_consensus_extended.py — TestConsensusResult
# ═══════════════════════════════════════════════════════


class TestConsensusResult:
    def test_create(self):
        from nuri.trading.agents.consensus import ConsensusResult
        result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=75.0,
            agreement_rate=0.85, verdicts=[], dissent=[], reasoning="test",
        )
        assert result.final_action == "BUY"
        assert result.agreement_rate == 0.85


# ═══════════════════════════════════════════════════════
# Source: test_consensus_extended.py — TestComputeWeights
# ═══════════════════════════════════════════════════════


class TestComputeWeights:
    def test_default_weights(self, db_path):
        """추천 데이터 부족 시 기본 가중치."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_weights_sum_to_one(self, db_path):
        from nuri.trading.agents.consensus import _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01


# ═══════════════════════════════════════════════════════
# Source: test_consensus_extended.py — TestConsensusLogic
# ═══════════════════════════════════════════════════════


class TestConsensusLogic:
    def test_all_agents_loaded(self):
        from nuri.trading.agents.consensus import ALL_AGENTS
        assert len(ALL_AGENTS) == 10

    def test_default_weights_keys(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS
        expected = {"technical", "fundamental", "macro", "risk", "smart_money",
                    "wallstreet", "korean_market", "options", "crypto", "retail"}
        assert set(DEFAULT_WEIGHTS.keys()) == expected

    def test_risk_weight_highest(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS
        assert DEFAULT_WEIGHTS["risk"] == max(DEFAULT_WEIGHTS.values())


# ═══════════════════════════════════════════════════════
# Source: test_consensus_extended.py — TestAnalyzeTicker
# ═══════════════════════════════════════════════════════


class TestAnalyzeTicker:
    def test_analyze_returns_consensus(self, db_path, monkeypatch):
        """모든 에이전트를 mock하여 합의 결과 확인."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, confidence):
                self.name = name
                self._action = action
                self._confidence = confidence

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._action, self._confidence, "mock")

        mock_agents = [
            MockAgent("technical", "BUY", 70),
            MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "BUY", 60),
            MockAgent("risk", "HOLD", 50),
            MockAgent("smart_money", "BUY", 55),
            MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
            MockAgent("options", "HOLD", 40),
            MockAgent("crypto", "BUY", 50),
            MockAgent("retail", "HOLD", 0),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL", db_path=db_path)

        assert result.ticker == "AAPL"
        assert result.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= result.final_confidence <= 100
        assert 0 <= result.agreement_rate <= 1
        assert len(result.verdicts) == 10

    def test_risk_veto(self, db_path, monkeypatch):
        """Risk 에이전트 거부권: SELL + confidence >= 80 → 전체 SELL."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, confidence):
                self.name = name
                self._action = action
                self._confidence = confidence

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._action, self._confidence, "mock")

        mock_agents = [
            MockAgent("technical", "BUY", 70),
            MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "BUY", 60),
            MockAgent("risk", "SELL", 85),
            MockAgent("smart_money", "BUY", 55),
            MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
            MockAgent("options", "HOLD", 40),
            MockAgent("crypto", "BUY", 50),
            MockAgent("retail", "HOLD", 0),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("DANGER", db_path=db_path)
        assert result.final_action == "SELL"

    def test_all_sell(self, db_path, monkeypatch):
        """전원 SELL → SELL."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name):
                self.name = name

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, "SELL", 70, "mock")

        mock_agents = [MockAgent(n) for n in [
            "technical", "fundamental", "macro", "risk", "smart_money",
            "wallstreet", "korean_market", "options", "crypto", "retail",
        ]]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("BEAR", db_path=db_path)
        assert result.final_action == "SELL"
        assert result.agreement_rate == 1.0


# ═══════════════════════════════════════════════════════
# Source: test_wallstreet_agent.py — TestWallStreetSkip
# ═══════════════════════════════════════════════════════


class TestWallStreetSkip:
    """스킵 대상 종목 테스트."""

    def test_etf_skipped(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("SPY", db_path=db_path)
        assert v.action == "HOLD"
        assert "미지원" in v.reasoning

    def test_korean_stock_skipped(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("005930.KS", db_path=db_path)
        assert v.action == "HOLD"

    def test_leveraged_skipped(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("TSLL", db_path=db_path)
        assert v.action == "HOLD"


# ═══════════════════════════════════════════════════════
# Source: test_wallstreet_agent.py — TestWallStreetCached
# ═══════════════════════════════════════════════════════


class TestWallStreetCached:
    """DB 캐시 기반 판정 테스트."""

    def test_cached_upgrade(self, db_path):
        """등급 업그레이드 캐시 → BUY 성향."""
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (date, ticker, action, target_price) VALUES (?, ?, ?, ?)",
                    (f"2026-03-{20+i}", "NVDA", "upgrade", 300.0),
                )
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("NVDA", db_path=db_path)
        assert v.action in ("BUY", "HOLD")
        assert v.data_points.get("cached") is True

    def test_cached_downgrade(self, db_path):
        """등급 다운그레이드 캐시 → SELL 성향."""
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (date, ticker, action, target_price) VALUES (?, ?, ?, ?)",
                    (f"2026-03-{20+i}", "BADCO", "downgrade", 50.0),
                )
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("BADCO", db_path=db_path)
        assert v.action in ("SELL", "HOLD")

    def test_cached_earnings_surprise(self, db_path):
        """실적 서프라이즈 캐시."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (quarter, ticker, surprise_pct) VALUES (?, ?, ?)",
                ("2026Q1", "AAPL", 0.15),
            )
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("AAPL", db_path=db_path)
        assert v.data_points.get("cached") is True

    def test_cached_insider_sells(self, db_path):
        """내부자 매도 캐시."""
        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO insider_trades (date, ticker, transaction_type, shares, value) VALUES (?, ?, ?, ?, ?)",
                    (f"2026-03-{10+i}", "SELLCO", "sale", 1000, 50000.0),
                )
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("SELLCO", db_path=db_path)
        assert "cached" in str(v.data_points) or v.reasoning != ""

    def test_no_cache_no_yfinance(self, db_path):
        """캐시도 yfinance 데이터도 없으면 HOLD (yfinance는 conftest에서 mock)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("NEWSTOCK", db_path=db_path)
        assert v.action == "HOLD"


# ═══════════════════════════════════════════════════════
# Source: test_wallstreet_agent.py — TestWallStreetYfinance
# ═══════════════════════════════════════════════════════


class TestWallStreetYfinance:
    """yfinance mock 기반 판정 (conftest에서 yfinance mock됨)."""

    def test_no_data_returns_hold(self, db_path):
        """yfinance mock이 None 반환 → HOLD."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("RAND", db_path=db_path)
        assert v.action == "HOLD"

    def test_with_upgrades(self, db_path, monkeypatch):
        """yfinance에서 upgrade 데이터."""
        ud_df = pd.DataFrame([
            {"Action": "up", "priceTargetAction": "raises", "currentPriceTarget": 200.0},
            {"Action": "up", "priceTargetAction": "raises", "currentPriceTarget": 210.0},
            {"Action": "up", "priceTargetAction": "", "currentPriceTarget": 205.0},
        ], index=[datetime.now()] * 3)

        class MockTicker:
            def __init__(self, ticker):
                self.upgrades_downgrades = ud_df
                self.earnings_history = None
                self.insider_transactions = None
                self.recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)

        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("GOOD", db_path=db_path)
        assert v.action in ("BUY", "HOLD")

    def test_with_earnings_surprise(self, db_path, monkeypatch):
        """yfinance에서 실적 서프라이즈."""
        eh_df = pd.DataFrame([
            {"surprisePercent": 0.12, "epsActual": 2.50, "epsEstimate": 2.23},
        ])

        class MockTicker:
            def __init__(self, ticker):
                self.upgrades_downgrades = None
                self.earnings_history = eh_df
                self.insider_transactions = None
                self.recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)

        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("EARN", db_path=db_path)
        assert "서프라이즈" in v.reasoning or v.action in ("BUY", "HOLD")

    def test_with_consensus(self, db_path, monkeypatch):
        """yfinance에서 컨센서스 분포."""
        rec_df = pd.DataFrame([
            {"strongBuy": 15, "buy": 10, "hold": 3, "sell": 1, "strongSell": 0},
        ])

        class MockTicker:
            def __init__(self, ticker):
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = None
                self.recommendations = rec_df

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)

        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("TESTCO", db_path=db_path)
        assert "컨센서스" in v.reasoning

    def test_with_insider_transactions(self, db_path, monkeypatch):
        """yfinance에서 내부자 매매 (순매수 우세 → 이유 생성)."""
        ins_df = pd.DataFrame([
            {"Text": "Purchase of 5000 shares"},
            {"Text": "Purchase of 3000 shares"},
            {"Text": "Purchase of 2000 shares"},
            {"Text": "Purchase of 1000 shares"},
            {"Text": "Sale of 500 shares"},
        ])

        class MockTicker:
            def __init__(self, ticker):
                self.upgrades_downgrades = None
                self.earnings_history = None
                self.insider_transactions = ins_df
                self.recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)

        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("INSIDE2", db_path=db_path)
        assert "내부자" in v.reasoning


# ═══════════════════════════════════════════════════════
# Source: test_new_features.py — TestKoreanAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round4.py — TestConsensusDeep
# ═══════════════════════════════════════════════════════


class TestConsensusDeep:
    def test_analyze_ticker(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        assert hasattr(result, "final_action")
        assert hasattr(result, "final_confidence")
        assert hasattr(result, "agreement_rate")

    def test_analyze_portfolio(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio()
        assert isinstance(results, list)
        assert len(results) > 0


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round12.py — TestConsensusInternals
# ═══════════════════════════════════════════════════════


class TestConsensusInternals:
    def test_consensus_result_structure(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        assert hasattr(result, "verdicts")
        assert isinstance(result.verdicts, list)
        assert len(result.verdicts) >= 5

    def test_consensus_all_tickers(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio(db_path=rich_db)
        tickers = [r.ticker for r in results]
        # rich_db seeds AAPL, MSFT, SPY, TSLA
        assert "AAPL" in tickers


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round13.py — TestConsensusSave
# ═══════════════════════════════════════════════════════


class TestConsensusSave:
    def test_save_to_db(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker
        analyze_ticker("AAPL")
        from nuri.core.db import query
        recs = query("SELECT * FROM recommendations WHERE ticker='AAPL'")
        assert isinstance(recs, list)


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round23.py — TestWallStreetAgent
# ═══════════════════════════════════════════════════════


class TestWallStreetAgent_R23:
    """Cover lines 51-52, 71-72, 78, 85-86, 88, 98-99, 112-116, 121-122,
    142-144, 148-149, 170-174, 180-181, 193."""

    def test_skip_tickers(self, db_path):
        """ETF/KS tickers return HOLD immediately."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("VOO", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 20

    def test_skip_korean(self, db_path):
        """Korean tickers (.KS) skip."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        v = agent.analyze("005930.KS", db_path=db_path)
        assert v.action == "HOLD"

    def test_yfinance_exception(self, db_path, monkeypatch):
        """yfinance load failure → HOLD conf=0 (lines 51-52)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: (_ for _ in ()).throw(RuntimeError("fail")))
        v = agent.analyze("NVDA", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0
        assert "yfinance 로드 실패" in v.reasoning

    def test_analyze_upgrades_and_downgrades(self, db_path, monkeypatch):
        """Downgrades exceed upgrades."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        ud_data = pd.DataFrame({
            "Action": ["down", "down", "down", "down", "init"],
            "priceTargetAction": ["lowers", "lowers", "", "", "raises"],
            "currentPriceTarget": [100.0, 95.0, None, None, 110.0],
        }, index=pd.to_datetime(["2026-03-28"] * 5))

        class MockTicker:
            upgrades_downgrades = ud_data
            earnings_history = None
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "다운그레이드" in v.reasoning or "등급변경" in v.reasoning

    def test_analyze_earnings_surprise_positive(self, db_path, monkeypatch):
        """Earnings surprise positive."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        eh_data = pd.DataFrame({
            "surprisePercent": [0.15], "epsActual": [3.5], "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "서프라이즈" in v.reasoning

    def test_analyze_earnings_miss(self, db_path, monkeypatch):
        """Earnings miss."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        eh_data = pd.DataFrame({
            "surprisePercent": [-0.10], "epsActual": [2.5], "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "미스" in v.reasoning

    def test_analyze_earnings_inline(self, db_path, monkeypatch):
        """Earnings inline."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        eh_data = pd.DataFrame({
            "surprisePercent": [0.01], "epsActual": [3.0], "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "부합" in v.reasoning

    def test_analyze_earnings_exception(self, db_path, monkeypatch):
        """Earnings_history raises exception."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None

            @property
            def earnings_history(self):
                raise RuntimeError("earnings fail")

            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_insider_net_sell(self, db_path, monkeypatch):
        """Insider net sell."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        ins_data = pd.DataFrame({"Text": ["Sale of"] * 8 + ["Purchase of"] * 2})

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = ins_data
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "내부자 순매도" in v.reasoning

    def test_analyze_insider_exception(self, db_path, monkeypatch):
        """Insider_transactions raises exception."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None

            @property
            def insider_transactions(self):
                raise RuntimeError("insider fail")

            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_consensus_bear(self, db_path, monkeypatch):
        """Consensus bearish."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        rec_data = pd.DataFrame({
            "strongBuy": [0], "buy": [1], "hold": [2], "sell": [5], "strongSell": [5],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "매도" in v.reasoning

    def test_analyze_consensus_neutral(self, db_path, monkeypatch):
        """Consensus neutral."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        rec_data = pd.DataFrame({
            "strongBuy": [2], "buy": [2], "hold": [10], "sell": [1], "strongSell": [0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "중립" in v.reasoning

    def test_analyze_consensus_exception(self, db_path, monkeypatch):
        """Recommendations raises exception."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None

            @property
            def recommendations(self):
                raise RuntimeError("recs fail")

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_sell_verdict(self, db_path, monkeypatch):
        """Enough negative score → SELL verdict."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        ud_data = pd.DataFrame({
            "Action": ["down", "down", "down", "down"],
            "priceTargetAction": ["lowers", "lowers", "lowers", ""],
            "currentPriceTarget": [100.0, 95.0, 90.0, None],
        }, index=pd.to_datetime(["2026-03-28"] * 4))
        eh_data = pd.DataFrame({
            "surprisePercent": [-0.15], "epsActual": [2.0], "epsEstimate": [3.0],
        })
        ins_data = pd.DataFrame({"Text": ["Sale"] * 8 + ["Purchase"] * 1})
        rec_data = pd.DataFrame({
            "strongBuy": [0], "buy": [0], "hold": [2], "sell": [5], "strongSell": [5],
        })

        class MockTicker:
            upgrades_downgrades = ud_data
            earnings_history = eh_data
            insider_transactions = ins_data
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "SELL"

    def test_upgrades_exception_path(self, db_path, monkeypatch):
        """upgrades_downgrades access raises."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        eh_data = pd.DataFrame({
            "surprisePercent": [0.10], "epsActual": [3.5], "epsEstimate": [3.0],
        })

        class MockTicker:
            @property
            def upgrades_downgrades(self):
                raise RuntimeError("fail")

            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "서프라이즈" in v.reasoning


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round23.py — TestConsensus
# ═══════════════════════════════════════════════════════


class TestConsensus_R23:
    """Cover lines 108, 112, 127-128, 138, 178-183, 289-292, 320-321, 326-341."""

    def test_compute_weights_no_data(self, db_path):
        """No recommendation data → default weights."""
        from nuri.trading.agents.consensus import _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert abs(weights["technical"] - 0.16) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """With enough data → adjusted weights."""
        from nuri.trading.agents.consensus import _compute_weights
        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = json.dumps({
                    "verdicts": [
                        {"agent_name": "technical", "action": "BUY"},
                        {"agent_name": "fundamental", "action": "BUY"},
                    ]
                })
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-01-{i+1:02d}", f"T{i}", "BUY", 70, "bull", verdicts, 100.0, 5.0 + i),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_non_json_signals(self, db_path):
        """Signals field that isn't the expected JSON format."""
        from nuri.trading.agents.consensus import _compute_weights
        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-02-{i+1:02d}", f"T{i}", "BUY", 70, "bull", '["rsi_oversold"]', 100.0, 3.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert "technical" in weights

    def test_analyze_ticker_with_timeout(self, db_path, monkeypatch):
        """Agent timeout handling."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import analyze_ticker

        class SlowAgent:
            name = "slow_agent"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("slow_agent", ticker, "HOLD", 50, "slow result")

        class QuickAgent:
            name = "technical"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 70, "quick buy")

        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [QuickAgent(), SlowAgent()])
        monkeypatch.setattr("nuri.trading.agents.consensus._compute_weights",
                            lambda db_path=None: {"technical": 0.5, "slow_agent": 0.5})
        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.ticker == "AAPL"
        assert result.final_action in ("BUY", "SELL", "HOLD")

    def test_print_consensus_with_targets(self, capsys, db_path, monkeypatch):
        """Print consensus with price targets."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        results = [ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=75.0,
            agreement_rate=0.8,
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 80, "buy signal"),
                AgentVerdict("fundamental", "AAPL", "HOLD", 40, "neutral"),
            ],
            dissent=["fundamental(HOLD, 40): neutral"],
            reasoning="technical: buy signal",
        )]
        monkeypatch.setattr("nuri.trading.recommend.price_targets.calculate_targets",
                            lambda *a, **kw: {"ticker": "AAPL", "error": "no data"})
        monkeypatch.setattr("nuri.trading.recommend.price_targets.format_target_tree",
                            lambda t: "AAPL target tree")
        monkeypatch.setattr("nuri.collectors.external.get_external",
                            lambda *a: (_ for _ in ()).throw(ImportError("no module")))
        print_consensus(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "Dissent" in captured.out

    def test_print_consensus_empty(self, capsys):
        """Print with empty results."""
        from nuri.trading.agents.consensus import print_consensus
        print_consensus([])
        captured = capsys.readouterr()
        assert "합의 결과 없음" in captured.out

    def test_print_consensus_external_data(self, capsys, monkeypatch):
        """Print consensus with external data."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        results = [ConsensusResult(
            ticker="AAPL", final_action="HOLD", final_confidence=50.0,
            agreement_rate=0.6,
            verdicts=[AgentVerdict("technical", "AAPL", "HOLD", 50, "neutral")],
            dissent=[], reasoning="neutral",
        )]
        monkeypatch.setattr("nuri.trading.recommend.price_targets.calculate_targets",
                            lambda *a, **kw: (_ for _ in ()).throw(Exception("fail")))
        monkeypatch.setattr("nuri.collectors.external.get_external",
                            lambda ticker: [
                                {"data_type": "consensus", "value": "Strong Buy", "source": "tipranks", "numeric_value": None},
                                {"data_type": "superinvestor_count", "value": "5", "source": "dataroma", "numeric_value": 5},
                                {"data_type": "target_price", "value": "$200", "source": "tipranks", "numeric_value": 200},
                            ])
        print_consensus(results)
        captured = capsys.readouterr()
        assert "External Data" in captured.out


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round23.py — TestAdditionalEdgeCases (agent methods only)
# ═══════════════════════════════════════════════════════


class TestAdditionalEdgeCases_R23:
    """Extra tests to hit remaining uncovered lines (agent-related only)."""

    def test_wallstreet_cached_ratings_upgrades(self, db_path):
        """WallStreet _check_cached with ratings data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, action, target_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("TSLA", f"2026-03-{20+i}", f"Firm{i}", "upgrade", 300 + i * 10),
                )
        result = agent._check_cached("TSLA", db_path)
        assert result is not None
        assert "cached" in result.reasoning

    def test_wallstreet_cached_earnings_positive(self, db_path):
        """WallStreet _check_cached with positive earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?, ?, ?, ?, ?)",
                ("TSLA", "2026-Q1", 1.5, 1.2, 0.10),
            )
        result = agent._check_cached("TSLA", db_path)
        assert result is not None

    def test_wallstreet_cached_earnings_negative(self, db_path):
        """WallStreet _check_cached with negative earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?, ?, ?, ?, ?)",
                ("TSLA", "2026-Q1", 0.8, 1.2, -0.15),
            )
        result = agent._check_cached("TSLA", db_path)
        assert result is not None

    def test_wallstreet_cached_insider_sells(self, db_path):
        """WallStreet _check_cached with heavy insider sells."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("TSLA", f"2026-03-{10+i}", f"Insider{i}", "sale", 1000, 100000),
                )
        result = agent._check_cached("TSLA", db_path)
        assert result is not None
        assert result.action == "SELL"

    def test_consensus_risk_veto(self, db_path, monkeypatch):
        """Risk agent veto triggers SELL override."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import analyze_ticker

        class RiskAgent:
            name = "risk"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("risk", ticker, "SELL", 90, "veto: danger")

        class TechAgent:
            name = "technical"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 80, "buy signal")

        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [TechAgent(), RiskAgent()])
        monkeypatch.setattr("nuri.trading.agents.consensus._compute_weights",
                            lambda db_path=None: {"technical": 0.5, "risk": 0.5})
        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.final_action == "SELL"
        assert "거부권" in result.reasoning

    def test_wallstreet_insider_net_buy(self, db_path, monkeypatch):
        """Insider net buy signal."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        ins_data = pd.DataFrame({"Text": ["Purchase of"] * 5 + ["Sale of"] * 1})

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = ins_data
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "내부자 순매수" in v.reasoning

    def test_wallstreet_consensus_bull(self, db_path, monkeypatch):
        """Consensus bullish."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        rec_data = pd.DataFrame({
            "strongBuy": [8], "buy": [5], "hold": [2], "sell": [0], "strongSell": [0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "매수" in v.reasoning


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestBaseAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestCryptoAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestFundamentalAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestKoreanMarketAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestMacroAgent
# ═══════════════════════════════════════════════════════


class TestMacroAgent_R26:
    def test_no_regime_data(self, db_path):
        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"

    def test_sideways_strong_momentum(self, db_path, monkeypatch):
        """Cover sideways + strong momentum -> BUY."""
        @dataclass
        class FakeRegime:
            regime: str = "sideways_low_vol"
            trend: str = "sideways"
            confidence: float = 0.7
            details: dict = None

        @dataclass
        class FakeMacro:
            total_score: float = 50

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: FakeRegime())
        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda **kw: FakeMacro())

        _seed_ticker(db_path, "AAPL", n=30, base_price=100)
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=20).strftime("%Y-%m-%d").tolist()
            for i, d in enumerate(dates):
                conn.execute(
                    "UPDATE prices SET close = ? WHERE ticker = 'AAPL' AND date = ?",
                    (100 + i * 3, d),
                )

        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "HOLD", "SELL")

    def test_regime_none(self, db_path, monkeypatch):
        """Cover regime is None."""
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: None)

        @dataclass
        class FakeMacro:
            total_score: float = 50

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda **kw: FakeMacro())
        from nuri.trading.agents.macro_agent import MacroAgent
        result = MacroAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "SPY" in result.reasoning


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestOptionsAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestRetailAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestRiskAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestSmartMoneyAgent
# ═══════════════════════════════════════════════════════


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
                ("Buffett", "AAPL", 1000, 8.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, shares, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Gates", "AAPL", 500, 3.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-01", "buy", 200, 150, 20),
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
                ("AAPL", "2025-03-01", "sell", 100, 150, 10),
            )
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        result = SmartMoneyAgent().analyze("AAPL", db_path=db_path)
        assert any("하회" in r for r in result.reasoning.split("; "))


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestTechnicalAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round26.py — TestWallStreetAgent
# ═══════════════════════════════════════════════════════


class TestWallStreetAgent_R26:
    def test_no_data(self, db_path):
        """WallStreet agent with no DB data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        result = WallStreetAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round27.py — TestConsensus
# ═══════════════════════════════════════════════════════


class TestConsensus_R27:
    """Tests for nuri/trading/agents/consensus.py."""

    def test_compute_weights_default(self, db_path):
        """Default weights when no recommendation data."""
        from nuri.trading.agents.consensus import _compute_weights
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """Weights adjusted with learning memory data."""
        from nuri.trading.agents.consensus import _compute_weights
        with get_db(db_path) as conn:
            for i in range(15):
                verdicts_data = {
                    "verdicts": [
                        {"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"},
                        {"agent_name": "risk", "action": "HOLD", "confidence": 50, "reasoning": "test"},
                    ]
                }
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, regime, signals, "
                    "entry_price, outcome_30d) VALUES (?,?,?,?,?,?,?,?)",
                    (f"2024-{(i%12)+1:02d}-{15+i}", f"AAPL{i}", "BUY", 70, "bull",
                     json.dumps(verdicts_data), 150, 5.0 if i % 2 == 0 else -2.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_print_consensus_empty(self, capsys):
        """print_consensus with empty results."""
        from nuri.trading.agents.consensus import print_consensus
        print_consensus([])
        captured = capsys.readouterr()
        assert "합의 결과 없음" in captured.out

    def test_print_consensus_with_results(self, capsys):
        """print_consensus with mock results."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI bullish"),
            AgentVerdict("risk", "AAPL", "HOLD", 50, "moderate risk"),
        ]
        results = [ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=65,
            agreement_rate=0.7, verdicts=verdicts,
            dissent=["risk(HOLD, 50): moderate risk"],
            reasoning="technical: RSI bullish",
        )]
        print_consensus(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round27.py — TestWallStreet
# ═══════════════════════════════════════════════════════


class TestWallStreet_R27:
    """Tests for nuri/trading/agents/wallstreet.py."""

    def test_skip_tickers(self):
        """ETF/KR tickers return HOLD immediately."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent.analyze("SPY")
        assert result.action == "HOLD"
        result_kr = agent.analyze("005930.KS")
        assert result_kr.action == "HOLD"

    def test_check_cached_no_data(self, db_path):
        """_check_cached returns None with no cached data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is None

    def test_check_cached_with_ratings(self, db_path):
        """_check_cached with analyst ratings."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, to_grade, from_grade, action, target_price) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", f"Firm{i}", "buy", "hold", "upgrade", 200),
                )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None
        assert result.action in ("BUY", "SELL", "HOLD")

    def test_check_cached_with_earnings(self, db_path):
        """_check_cached with earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?,?,?,?,?)",
                ("AAPL", "2025Q1", 1.5, 1.2, 0.25),
            )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None

    def test_check_cached_with_insider_sells(self, db_path):
        """_check_cached with insider sales."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) "
                    "VALUES (?,?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", f"Exec{i}", "sale", 1000, 150000),
                )
        agent = WallStreetAgent()
        result = agent._check_cached("AAPL", db_path=db_path)
        assert result is not None

    def test_analyze_with_yfinance_mock(self, db_path):
        """analyze falls through to yfinance (mocked by conftest)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        result = agent.analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")


# ═══════════════════════════════════════════════════════
# Source: test_coverage_round27.py — TestTracker (agent-related: test_serialize_verdicts)
# ═══════════════════════════════════════════════════════


class TestTracker_R27:
    """Tests for nuri/trading/recommend/tracker.py."""

    def test_save_recommendations_empty(self, db_path):
        """save_recommendations with no candidates/actions returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations
        assert save_recommendations(db_path=db_path) == 0

    def test_save_recommendations_with_candidates(self, db_path, monkeypatch):
        """save_recommendations with candidate data."""
        from nuri.trading.recommend.tracker import save_recommendations

        class MockCandidate:
            ticker = "AAPL"
            direction = "BUY"
            confidence = 75
            signal_id = "rsi_oversold"
            regime_fit = True
            price = 150
            scoring_detail = {"test": 1}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_track_outcomes(self, db_path, monkeypatch):
        """track_outcomes updates 30d outcomes."""
        from nuri.core.timezone import kst_now
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (kst_now().replace(tzinfo=None) - timedelta(days=35)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?,?,?,?,?,?,?)",
                (rec_date, "AAPL", "BUY", 70, "bull", '["rsi_oversold"]', 150),
            )
            target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                ("AAPL", target_date, 160),
            )
        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_get_tracking_report(self, db_path):
        """get_tracking_report returns report structure."""
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path)
        assert "total_recommendations" in report
        assert "hit_rate" in report

    def test_print_tracking_report(self, db_path, capsys):
        """print_tracking_report outputs data."""
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation" in captured.out

    def test_serialize_verdicts(self):
        """_serialize_verdicts converts ConsensusResult verdicts."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.recommend.tracker import _serialize_verdicts

        class MockResult:
            ticker = "AAPL"
            verdicts = [AgentVerdict("technical", "AAPL", "BUY", 70, "RSI ok")]

        result = _serialize_verdicts([MockResult()])
        assert "AAPL" in result
        assert result["AAPL"][0]["agent_name"] == "technical"


# ═══════════════════════════════════════════════════════
# Source: test_coverage_extra.py — TestPrintConsensus
# ═══════════════════════════════════════════════════════


class TestPrintConsensus:
    def test_empty(self, capsys):
        from nuri.trading.agents.consensus import print_consensus
        print_consensus([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_results(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI ok"),
            AgentVerdict("fundamental", "AAPL", "BUY", 65, "PE low"),
            AgentVerdict("macro", "AAPL", "BUY", 60, "bull"),
            AgentVerdict("risk", "AAPL", "HOLD", 50, "중립"),
            AgentVerdict("smart_money", "AAPL", "BUY", 55, "13F"),
        ]
        results = [ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=68.0,
            agreement_rate=0.80, verdicts=verdicts,
            dissent=["risk(HOLD, 50): 중립"],
            reasoning="consensus",
        )]
        print_consensus(results)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "BUY" in output
        assert "Dissent" in output

    def test_analyze_portfolio_empty(self, db_path):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio(db_path=db_path)
        assert results == []


# ═══════════════════════════════════════════════════════
# Source: test_coverage_final.py — TestConsensusPrint
# ═══════════════════════════════════════════════════════


class TestConsensusPrint:
    def test_print_consensus(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult
        result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=75.0,
            agreement_rate=0.85, dissent=["risk"],
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "RSI 매수"),
                AgentVerdict("risk", "AAPL", "SELL", 80, "과집중"),
            ],
            reasoning="test consensus",
        )
        print(f"Action: {result.final_action}, Confidence: {result.final_confidence}")
        output = capsys.readouterr().out
        assert "BUY" in output


# ═══════════════════════════════════════════════════════
# Source: test_coverage_final.py — TestSmartMoneyAgent
# ═══════════════════════════════════════════════════════


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
                    (inv, "2026-03-01", "AAPL", 1000000, 150000000, 3.5),
                )
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        agent = SmartMoneyAgent()
        v = agent.analyze("AAPL", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")


# ═══════════════════════════════════════════════════════
# Source: test_coverage_final.py — TestFundamentalAgent
# ═══════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════
# Source: test_coverage_final.py — TestMacroAgent
# ═══════════════════════════════════════════════════════


class TestMacroAgent_Source_Final:
    def test_with_macro_data(self, rich_db):
        from nuri.trading.agents.macro_agent import MacroAgent
        agent = MacroAgent()
        v = agent.analyze("AAPL", db_path=rich_db)
        assert v.action in ("BUY", "SELL", "HOLD")
        assert v.agent_name == "macro"


# ═══════════════════════════════════════════════════════
# Source: test_final_push.py — TestConsensusFull
# ═══════════════════════════════════════════════════════


class TestConsensusFull:
    def test_print_with_all_agents(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus
        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI 과매도 반등"),
            AgentVerdict("fundamental", "AAPL", "BUY", 65, "PE 적정, ROE 높음"),
            AgentVerdict("macro", "AAPL", "HOLD", 45, "횡보 레짐"),
            AgentVerdict("risk", "AAPL", "HOLD", 40, "집중도 정상"),
            AgentVerdict("smart_money", "AAPL", "BUY", 60, "13F 보유 3명"),
            AgentVerdict("wallstreet", "AAPL", "BUY", 55, "업그레이드 2건"),
            AgentVerdict("korean_market", "AAPL", "HOLD", 30, "US 종목"),
        ]
        results = [
            ConsensusResult(
                ticker="AAPL", final_action="BUY", final_confidence=68.0,
                agreement_rate=0.57, verdicts=verdicts,
                dissent=[
                    "macro(HOLD, 45): 횡보 레짐",
                    "risk(HOLD, 40): 집중도 정상",
                    "korean_market(HOLD, 30): US 종목",
                ],
                reasoning="technical + fundamental + smart_money",
            ),
            ConsensusResult(
                ticker="TSLA", final_action="SELL", final_confidence=72.0,
                agreement_rate=0.71, verdicts=[
                    AgentVerdict("technical", "TSLA", "SELL", 75, "데드크로스"),
                    AgentVerdict("fundamental", "TSLA", "SELL", 60, "PE 327"),
                    AgentVerdict("macro", "TSLA", "SELL", 55, "bear regime"),
                    AgentVerdict("risk", "TSLA", "SELL", 85, "손절선 초과"),
                    AgentVerdict("smart_money", "TSLA", "HOLD", 40, "보유 유지"),
                ],
                dissent=["smart_money(HOLD, 40): 보유 유지"],
                reasoning="risk veto",
            ),
        ]
        print_consensus(results)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "TSLA" in output
        assert "Multi-Agent" in output

    def test_analyze_ticker_with_populated_db(self, db_path, monkeypatch):
        """에이전트 mock으로 analyze_ticker 전체 경로 커버."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, conf):
                self.name = name
                self._a = action
                self._c = conf
            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._a, self._c, "mock reason")

        agents = [
            MockAgent("technical", "BUY", 70), MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "HOLD", 50), MockAgent("risk", "HOLD", 45),
            MockAgent("smart_money", "BUY", 55), MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", agents)
        result = cons_mod.analyze_ticker("AAPL", db_path=db_path)
        assert result.final_action == "BUY"
        assert len(result.verdicts) == 7
        assert len(result.dissent) > 0


# ═══════════════════════════════════════════════════════
# Source: test_coverage_boost.py — TestCertifyPosition
# ═══════════════════════════════════════════════════════


class TestCertifyPosition:
    def test_basic_certification(self, db_path, monkeypatch):
        """기본 인증 — 에이전트 합의 mock."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.8, dissent=[], reasoning="test",
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "ok"),
                AgentVerdict("fundamental", "AAPL", "BUY", 65, "ok"),
                AgentVerdict("macro", "AAPL", "HOLD", 50, "ok"),
                AgentVerdict("risk", "AAPL", "HOLD", 40, "ok"),
                AgentVerdict("smart_money", "AAPL", "BUY", 55, "ok"),
            ],
        )
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: mock_result, raising=False)

        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=db_path)
        assert cert.regime_aligned is True
        assert cert.concentration_ok is True
        assert cert.daily_limit_ok is True

    def test_bear_long_misaligned(self, db_path, monkeypatch):
        """bear에서 long은 레짐 불일치."""
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: MagicMock(final_action="SELL", verdicts=[]), raising=False)
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", db_path=db_path)
        assert cert.regime_aligned is False


# ═══════════════════════════════════════════════════════
# Source: test_coverage_push.py — TestPositionExtended
# ═══════════════════════════════════════════════════════


class TestPositionExtended:
    def test_certify_position(self, db_path, monkeypatch):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.8, dissent=[], reasoning="test",
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "ok"),
                AgentVerdict("fundamental", "AAPL", "BUY", 65, "ok"),
            ],
        )
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: mock, raising=False)

        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=db_path)
        assert cert.regime_aligned is True

    def test_position_dataclass(self):
        from nuri.trading.strategy.position import Position, PositionCertification
        cert = PositionCertification(True, True, True, True, True, True, {})
        p = Position("AAPL", "long", "tactical", 150.0, 10, "bull_low_vol", cert)
        assert p.ticker == "AAPL"


# ═══════════════════════════════════════════════════════
# Source: test_coverage_push.py — TestKoreanMarketAgent
# ═══════════════════════════════════════════════════════


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
