"""E-3 추적기 확장 테스트 — track_outcomes + print_tracking_report."""
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _seed_recommendation(db_path, date, ticker, action, entry_price, confidence=70.0):
    """추천 레코드 삽입."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, entry_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (date, ticker, action, confidence, entry_price),
        )


class TestTrackOutcomes:
    def test_no_recommendations(self, db_path):
        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path)
        assert updated == 0

    def test_30d_tracking(self, db_path):
        """30일 경과 추천에 대해 수익률 업데이트."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "AAPL", "BUY", 150.0)

        # 30일 후 가격
        target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "AAPL", "date": target_date,
            "open": 160, "high": 165, "low": 158, "close": 162.0,
            "volume": 1000000, "adj_close": 162.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path)
        assert updated == 1

        # outcome_30d 확인
        from nuri.core.db import query
        rows = query("SELECT outcome_30d, hit FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] is not None
        assert rows[0]["outcome_30d"] > 0  # 150→162 = +8%
        assert rows[0]["hit"] == 1  # BUY + positive

    def test_60d_tracking(self, db_path):
        """60일 경과 추천에 대해 수익률 업데이트."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=65)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "MSFT", "SELL", 350.0)

        # 30일 후 가격
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        # 60일 후 가격
        d60 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=60)).strftime("%Y-%m-%d")

        prices = pd.DataFrame([
            {"ticker": "MSFT", "date": d30, "open": 340, "high": 345, "low": 338, "close": 340.0, "volume": 1000000, "adj_close": 340.0},
            {"ticker": "MSFT", "date": d60, "open": 330, "high": 335, "low": 325, "close": 330.0, "volume": 1000000, "adj_close": 330.0},
        ])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path)
        assert updated == 1

    def test_sell_hit_negative_return(self, db_path):
        """SELL 추천 + 가격 하락 → hit=True."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "BAD", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "BAD", "date": d30,
            "open": 90, "high": 92, "low": 88, "close": 90.0,
            "volume": 1000000, "adj_close": 90.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        from nuri.core.db import query
        rows = query("SELECT hit FROM recommendations", db_path=db_path)
        assert rows[0]["hit"] == 1  # SELL + negative = hit

    def test_not_yet_30d(self, db_path):
        """30일 미경과 → 업데이트 안 함."""
        from datetime import datetime, timedelta
        rec_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "NEW", "BUY", 100.0)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path)
        assert updated == 0


class TestGetTrackingReport:
    def test_empty(self, db_path):
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path)
        assert report["total_recommendations"] == 0
        assert report["hit_rate"] == 0

    def test_with_data(self, db_path):
        _seed_recommendation(db_path, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path)
        assert report["total_recommendations"] == 1
        assert report["tracked"] == 1
        assert report["hit_rate"] == 1.0


class TestPrintTrackingReport:
    def test_empty_report(self, db_path, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path)
        output = capsys.readouterr().out
        assert "Tracking Report" in output

    def test_with_tracked(self, db_path, capsys):
        _seed_recommendation(db_path, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path)
        output = capsys.readouterr().out
        assert "Hit rate" in output or "AAPL" in output
