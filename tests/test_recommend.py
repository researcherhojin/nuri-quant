"""Phase E 추천 모듈 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def market_data(db_path):
    """포트폴리오 + 가격 데이터."""
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("test", "TEST1", 100, 50.0, "USD", "Technology"),
                ("test", "TEST2", 50, 80.0, "USD", "Health Care"),
            ],
        )

    dates = pd.bdate_range("2025-01-01", periods=60)
    prices_down = np.linspace(100, 70, 30)
    prices_up = np.linspace(70, 110, 30)
    close1 = np.concatenate([prices_down, prices_up])
    close2 = np.concatenate([np.linspace(80, 60, 30), np.linspace(60, 90, 30)])

    for ticker, close in [("TEST1", close1), ("TEST2", close2)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": [1000000] * 60,
            "adj_close": close,
        })
        upsert_prices(df, db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# E-1: 후보 스크리너
# ═══════════════════════════════════════════════════════


class TestCandidates:

    def test_screen_returns_list(self, market_data):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10, db_path=market_data)
        assert isinstance(candidates, list)

    def test_candidates_have_confidence(self, market_data):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)
        for c in candidates:
            assert 0 <= c.confidence <= 100
            assert c.direction in ("BUY", "SELL")

    def test_candidates_sorted_by_confidence(self, market_data):
        """confidence 내림차순 정렬 확인."""
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)
        if len(candidates) >= 2:
            for i in range(len(candidates) - 1):
                assert candidates[i].confidence >= candidates[i + 1].confidence

    def test_empty_db_returns_empty(self, db_path):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(db_path=db_path)
        assert candidates == []


# ═══════════════════════════════════════════════════════
# E-2: 섹터 분류 (rebalance에서 사용)
# ═══════════════════════════════════════════════════════


class TestSectorClassify:

    def test_growth_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("EV/AI") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_defensive_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Consumer Staples") == "defensive"

    def test_neutral_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"


# ═══════════════════════════════════════════════════════
# E-3: 추적기
# ═══════════════════════════════════════════════════════


class TestTracker:

    def test_save_and_query(self, market_data):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import get_tracking_report, save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        n = save_recommendations(candidates, db_path=market_data)
        assert n == 1

        report = get_tracking_report(db_path=market_data)
        assert report["total_recommendations"] == 1

    def test_duplicate_ignored(self, market_data):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        save_recommendations(candidates, db_path=market_data)
        save_recommendations(candidates, db_path=market_data)

        # DB에 실제 1건만 존재 확인
        rows = query("SELECT COUNT(*) as c FROM recommendations", db_path=market_data)
        assert rows[0]["c"] == 1

    def test_regime_filtered_not_saved(self, market_data):
        """regime_fit=False인 후보는 저장되지 않음."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "macd_golden", "2025-03-01", "BUY",
                       30.0, 0.4, 0.8, False, 100.0, "레짐 비적합"),
        ]
        save_recommendations(candidates, db_path=market_data)
        rows = query("SELECT COUNT(*) as c FROM recommendations", db_path=market_data)
        assert rows[0]["c"] == 0
