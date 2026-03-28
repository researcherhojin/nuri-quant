"""Wall Street 에이전트 + 캐시 테스트."""
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


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
        from datetime import datetime
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
        # BULL is in SKIP_TICKERS, use a non-skip ticker
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
