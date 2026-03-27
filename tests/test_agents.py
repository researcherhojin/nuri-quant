"""멀티 에이전트 합의 시스템 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
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


class TestFundamentalAgent:
    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent
        v = FundamentalAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


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


class TestConsensus:
    def test_consensus_returns_result(self, agent_data):
        from nuri.trading.agents.consensus import analyze_ticker
        r = analyze_ticker("TEST", db_path=agent_data)
        assert r.ticker == "TEST"
        assert r.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= r.final_confidence <= 100
        assert 0 <= r.agreement_rate <= 1
        assert len(r.verdicts) == 7  # 7 agents including WallStreet + KoreanMarket

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
        # 기술적으로 하락 + 리스크 손절 → SELL이어야 함
        assert r.final_action == "SELL"

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.consensus import analyze_ticker
        r = analyze_ticker("NODATA", db_path=db_path)
        assert r.final_action == "HOLD"
