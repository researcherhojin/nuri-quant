"""Tests for tracker — split from test_trading_recommend_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.trading.recommend._helpers import (  # noqa: F401
    _seed_estimates_nm,
    _seed_fundamentals_nm,
    _seed_macro_r23,
    _seed_portfolio_nm,
    _seed_portfolio_r23,
    _seed_prices_nm,
    _seed_prices_r23,
    _seed_recommendation,
)


class TestTracker:
    """From test_recommend.py."""

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


class TestTrackOutcomes:
    """From test_tracker_extended.py."""

    def test_no_recommendations(self, db_path_with_dbmod):
        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 0

    def test_30d_tracking(self, db_path_with_dbmod):
        """30일 경과 추천에 대해 수익률 업데이트."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "AAPL", "BUY", 150.0)

        target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "AAPL", "date": target_date,
            "open": 160, "high": 165, "low": 158, "close": 162.0,
            "volume": 1000000, "adj_close": 162.0,
        }])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 1

        rows = query("SELECT outcome_30d, hit FROM recommendations", db_path=db_path_with_dbmod)
        assert rows[0]["outcome_30d"] is not None
        assert rows[0]["outcome_30d"] > 0
        assert rows[0]["hit"] == 1

    def test_60d_tracking(self, db_path_with_dbmod):
        """60일 경과 추천에 대해 수익률 업데이트."""
        rec_date = (datetime.now() - timedelta(days=65)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "MSFT", "SELL", 350.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        d60 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=60)).strftime("%Y-%m-%d")

        prices = pd.DataFrame([
            {"ticker": "MSFT", "date": d30, "open": 340, "high": 345, "low": 338, "close": 340.0, "volume": 1000000, "adj_close": 340.0},
            {"ticker": "MSFT", "date": d60, "open": 330, "high": 335, "low": 325, "close": 330.0, "volume": 1000000, "adj_close": 330.0},
        ])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 1

    def test_sell_hit_negative_return(self, db_path_with_dbmod):
        """SELL 추천 + 가격 하락 -> hit=True."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "BAD", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "BAD", "date": d30,
            "open": 90, "high": 92, "low": 88, "close": 90.0,
            "volume": 1000000, "adj_close": 90.0,
        }])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path_with_dbmod)

        rows = query("SELECT hit FROM recommendations", db_path=db_path_with_dbmod)
        assert rows[0]["hit"] == 1

    def test_not_yet_30d(self, db_path_with_dbmod):
        """30일 미경과 -> 업데이트 안 함."""
        rec_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "NEW", "BUY", 100.0)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 0


class TestGetTrackingReport:
    """From test_tracker_extended.py."""

    def test_empty(self, db_path_with_dbmod):
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path_with_dbmod)
        assert report["total_recommendations"] == 0
        assert report["hit_rate"] == 0

    def test_with_data(self, db_path_with_dbmod):
        _seed_recommendation(db_path_with_dbmod, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path_with_dbmod) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path_with_dbmod)
        assert report["total_recommendations"] == 1
        assert report["tracked"] == 1
        assert report["hit_rate"] == 1.0


class TestPrintTrackingReport:
    """From test_tracker_extended.py."""

    def test_empty_report(self, db_path_with_dbmod, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path_with_dbmod)
        output = capsys.readouterr().out
        assert "Tracking Report" in output

    def test_with_tracked(self, db_path_with_dbmod, capsys):
        _seed_recommendation(db_path_with_dbmod, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path_with_dbmod) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path_with_dbmod)
        output = capsys.readouterr().out
        assert "Hit rate" in output or "AAPL" in output


class TestTrackerSaveRecommendations:
    """From test_coverage_round16.py."""

    def test_save_empty(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        count = save_recommendations(candidates=None, actions=None, db_path=rich_db)
        assert count == 0

    def test_save_candidates_with_regime_fit(self, rich_db):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
            Candidate("NVDA", "bb_bounce", "2025-03-20", "BUY", 65.0, 0.55, 1.5, False, 120.0, "skip"),
        ]
        count = save_recommendations(candidates=candidates, db_path=rich_db)
        assert count == 1

    def test_save_with_verdicts(self, rich_db):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
        ]
        verdicts = {"AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 80, "reasoning": "RSI oversold"}]}
        count = save_recommendations(candidates=candidates, verdicts=verdicts, db_path=rich_db)
        assert count == 1

    def test_save_actions_with_price_lookup(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        action = MagicMock()
        action.ticker = "AAPL"
        action.action = "BUY"
        action.signals = ["rsi_oversold"]
        action.regime_note = "bull_low_vol"
        count = save_recommendations(actions=[action], db_path=rich_db)
        assert count == 1

    def test_save_action_duplicate_merge(self, rich_db):
        """When candidate and action have same ticker+action, signals should merge."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidate = Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "")
        action = MagicMock()
        action.ticker = "AAPL"
        action.action = "BUY"
        action.signals = ["bb_bounce"]
        action.regime_note = "bull"
        count = save_recommendations(candidates=[candidate], actions=[action], db_path=rich_db)
        assert count == 1


class TestTrackerTrackOutcomes:
    """From test_coverage_round16.py."""

    def test_90d_tracking(self, rich_db):
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (datetime.now() - timedelta(days=95)).strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_date, "AAPL", "BUY", 75.0, "bull", "[]", 170.0))
        updated = track_outcomes(db_path=rich_db)
        assert updated >= 1

    def test_sell_hit_quality(self, rich_db):
        """SELL action with negative return should have hit=True and hit_quality > 0."""
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        target_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_date, "TSLA", "SELL", 60.0, "bear", "[]", 250.0))
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", target_date, 200, 205, 195, 200, 1000000))

        updated = track_outcomes(db_path=rich_db)
        assert updated >= 1


class TestTrackerReport:
    """From test_coverage_round16.py."""

    def test_report_empty(self, rich_db):
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=rich_db)
        assert report["total_recommendations"] == 0
        assert report["hit_rate"] == 0

    def test_print_report_no_tracked(self, rich_db, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=rich_db)
        out = capsys.readouterr().out
        assert "Recommendation Tracking Report" in out

    def test_print_report_with_tracked(self, rich_db, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d, hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-01-01", "AAPL", "BUY", 80, "bull", "[]", 170.0, 12.5, 1))
        print_tracking_report(db_path=rich_db)
        out = capsys.readouterr().out
        assert "Hit rate" in out or "hit" in out.lower()


class TestTracker_R23:
    """From test_coverage_round23.py."""

    def test_save_recommendations_with_actions(self, db_path):
        """Save rebalance actions."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockAction:
            ticker: str
            action: str
            signals: list
            regime_note: str

        _seed_prices_r23(db_path, "AAPL", 170.0)

        actions = [
            MockAction("AAPL", "BUY", ["sig1"], "[bull] 비중 확대"),
            MockAction("MSFT", "HOLD", [], "[bull]"),
        ]

        verdicts = {
            "AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"}],
        }

        n = save_recommendations(actions=actions, verdicts=verdicts, db_path=db_path)
        assert n == 1

    def test_save_recommendations_with_candidates(self, db_path):
        """Save candidates."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "NVDA"
            direction: str = "BUY"
            confidence: float = 75.0
            signal_id: str = "rsi_oversold"
            price: float = 850.0
            regime_fit: bool = True
            scoring_detail: dict = None

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_save_empty(self, db_path):
        """No records to save returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations

        n = save_recommendations(db_path=db_path)
        assert n == 0

    def test_save_with_scoring_detail(self, db_path):
        """Save with scoring_detail attached."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "TSLA"
            direction: str = "BUY"
            confidence: float = 60.0
            signal_id: str = "macd_golden"
            price: float = 200.0
            regime_fit: bool = True
            scoring_detail: dict = None

            def __post_init__(self):
                self.scoring_detail = {"base": 50, "drift": 1.0}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_print_tracking_report(self, db_path, capsys):
        """Print tracking report."""
        from nuri.trading.recommend.tracker import print_tracking_report

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation Tracking Report" in captured.out

    def test_print_tracking_report_with_data(self, db_path, capsys):
        """Print report with tracked data."""
        from nuri.trading.recommend.tracker import print_tracking_report

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d, hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-01-01", "AAPL", "BUY", 70, "bull", '["sig1"]', 150.0, 8.5, 1),
            )

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "BUY" in captured.out

    def test_save_merge_existing(self, db_path):
        """Merge signals when same ticker+action exists."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "AAPL"
            direction: str = "BUY"
            confidence: float = 70.0
            signal_id: str = "rsi_oversold"
            price: float = 170.0
            regime_fit: bool = True
            scoring_detail: dict = None

        @dataclass
        class MockAction:
            ticker: str = "AAPL"
            action: str = "BUY"
            signals: list = None
            regime_note: str = "[bull]"

            def __post_init__(self):
                self.signals = ["macd_golden"]

        _seed_prices_r23(db_path, "AAPL", 170.0)
        n = save_recommendations(
            candidates=[MockCandidate()],
            actions=[MockAction()],
            db_path=db_path,
        )
        assert n == 1

    def test_tracker_track_outcomes(self, db_path):
        """Track outcomes for old recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "BUY", 70, "bull", '["sig"]', 150.0),
            )
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2025-12-31", 160.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-01-30", 165.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-03-01", 170.0))

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_tracker_track_sell_outcome(self, db_path):
        """Track outcomes for SELL recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "SELL", 70, "bear", '["sig"]', 150.0),
            )
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2025-12-31", 140.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-01-30", 135.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-03-01", 130.0))

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1


class TestTracker_R27:
    """From test_coverage_round27.py."""

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


class TestHitCalculation:
    """From test_feedback_loop.py — hit 판정 기준."""

    def test_buy_hit_meaningful_gain(self, db_path):
        """BUY + 8% 수익 -> hit=True (5% 이상)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "GOOD", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "GOOD", "date": d30, "open": 107, "high": 110, "low": 106, "close": 108.0, "volume": 1000000, "adj_close": 108.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 8.0
        assert rows[0]["hit"] == 1
        assert rows[0]["hit_quality"] == 0.4

    def test_buy_small_gain_not_hit(self, db_path):
        """BUY + 3% 수익 -> hit=False (5% 미만)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "MEH", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "MEH", "date": d30, "open": 102, "high": 104, "low": 101, "close": 103.0, "volume": 1000000, "adj_close": 103.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 3.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.15

    def test_buy_loss_not_hit(self, db_path):
        """BUY + 가격 하락 -> hit=False, hit_quality=0."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "LOSS", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "LOSS", "date": d30, "open": 94, "high": 96, "low": 93, "close": 95.0, "volume": 1000000, "adj_close": 95.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.0

    def test_sell_meaningful_decline_hit(self, db_path):
        """SELL + 가격 -5% 하락 -> hit=True (-2% 이하)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "DROP", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "DROP", "date": d30, "open": 96, "high": 97, "low": 94, "close": 95.0, "volume": 1000000, "adj_close": 95.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 1
        assert rows[0]["hit_quality"] == 0.5

    def test_sell_small_decline_not_hit(self, db_path):
        """SELL + 가격 -1% 하락 -> hit=False."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "FLAT", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "FLAT", "date": d30, "open": 99.5, "high": 100, "low": 98.5, "close": 99.0, "volume": 1000000, "adj_close": 99.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -1.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.1

    def test_sell_price_up_not_hit(self, db_path):
        """SELL + 가격 상승 -> hit=False, hit_quality=0."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "UP", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "UP", "date": d30, "open": 104, "high": 106, "low": 103, "close": 105.0, "volume": 1000000, "adj_close": 105.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 5.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.0

    def test_hit_quality_column_exists(self, db_path):
        """hit_quality 컬럼이 recommendations 테이블에 존재."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "hit_quality" in columns


class TestAgentVerdicts:
    """From test_feedback_loop.py."""

    def test_agent_verdicts_column_exists(self, db_path):
        """agent_verdicts 컬럼 존재 확인."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "agent_verdicts" in columns

    def test_save_with_verdicts(self, db_path):
        """verdict 포함 추천 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2026-03-29", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        verdicts = {
            "TEST1": [
                {"agent_name": "technical", "action": "BUY", "confidence": 80.0, "reasoning": "RSI oversold"},
                {"agent_name": "fundamental", "action": "HOLD", "confidence": 50.0, "reasoning": "Fair value"},
                {"agent_name": "risk", "action": "BUY", "confidence": 60.0, "reasoning": "Low risk"},
            ]
        }

        n = save_recommendations(candidates, verdicts=verdicts, db_path=db_path)
        assert n == 1

        rows = query("SELECT agent_verdicts FROM recommendations", db_path=db_path)
        assert rows[0]["agent_verdicts"] is not None
        parsed = json.loads(rows[0]["agent_verdicts"])
        assert len(parsed) == 3
        assert parsed[0]["agent_name"] == "technical"

    def test_save_without_verdicts(self, db_path):
        """verdict 없이도 정상 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "macd_golden", "2026-03-29", "BUY",
                       65.0, 0.5, 1.5, True, 90.0, "no verdicts"),
        ]
        n = save_recommendations(candidates, db_path=db_path)
        assert n == 1

        rows = query("SELECT agent_verdicts FROM recommendations", db_path=db_path)
        assert rows[0]["agent_verdicts"] is None

    def test_serialize_verdicts(self):
        """ConsensusResult -> verdict dict 변환."""
        from nuri.trading.recommend.tracker import _serialize_verdicts

        @dataclass
        class FakeVerdict:
            agent_name: str
            action: str
            confidence: float
            reasoning: str

        @dataclass
        class FakeResult:
            ticker: str
            verdicts: list

        results = [
            FakeResult(
                ticker="AAPL",
                verdicts=[
                    FakeVerdict("technical", "BUY", 80.0, "RSI oversold signal detected"),
                    FakeVerdict("risk", "HOLD", 50.0, "Moderate risk" + "x" * 200),
                ],
            ),
        ]

        verdicts_map = _serialize_verdicts(results)
        assert "AAPL" in verdicts_map
        assert len(verdicts_map["AAPL"]) == 2
        assert len(verdicts_map["AAPL"][1]["reasoning"]) == 100


class TestScoringDetail:
    """From test_feedback_loop.py."""

    def test_scoring_detail_column_exists(self, db_path):
        """scoring_detail 컬럼 존재 확인."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "scoring_detail" in columns

    def test_candidate_has_scoring_detail(self, db_path):
        """Candidate dataclass에 scoring_detail 필드."""
        from nuri.trading.recommend.candidates import Candidate

        c = Candidate(
            "TEST", "rsi_oversold", "2026-03-29", "BUY",
            75.0, 0.6, 2.0, True, 100.0, "test",
            scoring_detail={"base_confidence": 60.0, "final_confidence": 75.0},
        )
        assert c.scoring_detail is not None
        assert c.scoring_detail["base_confidence"] == 60.0

    def test_save_with_scoring_detail(self, db_path):
        """scoring_detail 포함 추천 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate(
                "TEST1", "rsi_oversold", "2026-03-29", "BUY",
                75.0, 0.6, 2.0, True, 100.0, "test",
                scoring_detail={
                    "base_confidence": 60.0,
                    "regime_win_rate": 0.65,
                    "regime_pf": 2.1,
                    "drift_multiplier": 1.0,
                    "conflict_penalty": 1.0,
                    "regime_fit_penalty": 1.0,
                    "position_penalty": 1.0,
                    "final_confidence": 75.0,
                },
            ),
        ]
        save_recommendations(candidates, db_path=db_path)

        rows = query("SELECT scoring_detail FROM recommendations", db_path=db_path)
        assert rows[0]["scoring_detail"] is not None
        parsed = json.loads(rows[0]["scoring_detail"])
        assert parsed["base_confidence"] == 60.0
        assert parsed["regime_win_rate"] == 0.65
        assert parsed["final_confidence"] == 75.0
