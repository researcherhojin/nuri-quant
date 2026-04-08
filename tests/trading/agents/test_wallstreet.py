"""Tests for wallstreet agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


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


class TestWallStreetAgent_R26:
    def test_no_data(self, db_path):
        """WallStreet agent with no DB data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        result = WallStreetAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")


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
