"""Tests for tracker — split from test_trading_recommend_all.py."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY", 75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        n = save_recommendations(candidates, db_path=market_data)
        assert n == 1

        report = get_tracking_report(db_path=market_data)
        assert report["total_recommendations"] == 1

    def test_duplicate_ignored(self, market_data):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY", 75.0, 0.6, 2.0, True, 100.0, "test"),
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
            Candidate("TEST1", "macd_golden", "2025-03-01", "BUY", 30.0, 0.4, 0.8, False, 100.0, "레짐 비적합"),
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "date": target_date,
                    "open": 160,
                    "high": 165,
                    "low": 158,
                    "close": 162.0,
                    "volume": 1000000,
                    "adj_close": 162.0,
                }
            ]
        )
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

        prices = pd.DataFrame(
            [
                {
                    "ticker": "MSFT",
                    "date": d30,
                    "open": 340,
                    "high": 345,
                    "low": 338,
                    "close": 340.0,
                    "volume": 1000000,
                    "adj_close": 340.0,
                },
                {
                    "ticker": "MSFT",
                    "date": d60,
                    "open": 330,
                    "high": 335,
                    "low": 325,
                    "close": 330.0,
                    "volume": 1000000,
                    "adj_close": 330.0,
                },
            ]
        )
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes

        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 1

    def test_sell_hit_negative_return(self, db_path_with_dbmod):
        """SELL 추천 + 가격 하락 -> hit=True."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "BAD", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [
                {
                    "ticker": "BAD",
                    "date": d30,
                    "open": 90,
                    "high": 92,
                    "low": 88,
                    "close": 90.0,
                    "volume": 1000000,
                    "adj_close": 90.0,
                }
            ]
        )
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
            conn.execute("UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'")

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
            conn.execute("UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'")

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
        verdicts = {
            "AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 80, "reasoning": "RSI oversold"}]
        }
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
                (rec_date, "AAPL", "BUY", 75.0, "bull", "[]", 170.0),
            )
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
                (rec_date, "TSLA", "SELL", 60.0, "bear", "[]", 250.0),
            )
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", target_date, 200, 205, 195, 200, 1000000),
            )

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
                ("2025-01-01", "AAPL", "BUY", 80, "bull", "[]", 170.0, 12.5, 1),
            )
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
            scoring_detail: dict | None = None
            tier: str = "actionable"

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
            scoring_detail: dict | None = None
            tier: str = "actionable"

            def __post_init__(self):
                self.scoring_detail = {"base": 50, "drift": 1.0}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_save_preserves_empty_scoring_detail_dict(self, db_path):
        """A-2b-pre — 빈 dict `{}` 도 persist (falsy guard 제거).

        STRATEGY §5.3.1 Gotcha-Test Pair: `if c.scoring_detail:` 로 revert 하면
        empty dict 이 silently drop 되어 DB 에 NULL 로 저장 — downstream 이 "아직
        scoring 없음" 과 "빈 compute 결과" 를 구분할 수 없음. consensus A-2a Round 2
        P3 와 동일 semantic.
        """
        import json

        from nuri.core.db import query
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "EMPT"
            direction: str = "BUY"
            confidence: float = 50.0
            signal_id: str = "test"
            price: float = 100.0
            regime_fit: bool = True
            tier: str = "actionable"
            # 일부러 빈 dict — empty compute 결과 시뮬레이션
            scoring_detail: dict = field(default_factory=dict)

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

        row = query(
            "SELECT scoring_detail FROM recommendations WHERE ticker='EMPT'",
            db_path=db_path,
        )[0]
        assert row["scoring_detail"] is not None, "A-2b-pre regression: 빈 dict 이 NULL 로 drop 되면 안 됨"
        assert json.loads(row["scoring_detail"]) == {}

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
            scoring_detail: dict | None = None
            tier: str = "actionable"

        @dataclass
        class MockAction:
            ticker: str = "AAPL"
            action: str = "BUY"
            signals: list | None = None
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
            tier = "actionable"

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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "GOOD",
                    "date": d30,
                    "open": 107,
                    "high": 110,
                    "low": 106,
                    "close": 108.0,
                    "volume": 1000000,
                    "adj_close": 108.0,
                }
            ]
        )
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "MEH",
                    "date": d30,
                    "open": 102,
                    "high": 104,
                    "low": 101,
                    "close": 103.0,
                    "volume": 1000000,
                    "adj_close": 103.0,
                }
            ]
        )
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "LOSS",
                    "date": d30,
                    "open": 94,
                    "high": 96,
                    "low": 93,
                    "close": 95.0,
                    "volume": 1000000,
                    "adj_close": 95.0,
                }
            ]
        )
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "DROP",
                    "date": d30,
                    "open": 96,
                    "high": 97,
                    "low": 94,
                    "close": 95.0,
                    "volume": 1000000,
                    "adj_close": 95.0,
                }
            ]
        )
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "FLAT",
                    "date": d30,
                    "open": 99.5,
                    "high": 100,
                    "low": 98.5,
                    "close": 99.0,
                    "volume": 1000000,
                    "adj_close": 99.0,
                }
            ]
        )
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
        prices = pd.DataFrame(
            [
                {
                    "ticker": "UP",
                    "date": d30,
                    "open": 104,
                    "high": 106,
                    "low": 103,
                    "close": 105.0,
                    "volume": 1000000,
                    "adj_close": 105.0,
                }
            ]
        )
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
            Candidate("TEST1", "rsi_oversold", "2026-03-29", "BUY", 75.0, 0.6, 2.0, True, 100.0, "test"),
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
            Candidate("TEST1", "macd_golden", "2026-03-29", "BUY", 65.0, 0.5, 1.5, True, 90.0, "no verdicts"),
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
            "TEST",
            "rsi_oversold",
            "2026-03-29",
            "BUY",
            75.0,
            0.6,
            2.0,
            True,
            100.0,
            "test",
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
                "TEST1",
                "rsi_oversold",
                "2026-03-29",
                "BUY",
                75.0,
                0.6,
                2.0,
                True,
                100.0,
                "test",
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


class TestShortHorizonTracking:
    """#468 codex Plan consult Round 1 — multi-horizon outcomes (7d/14d/21d)."""

    def test_outcome_7d_filled_when_elapsed_7(self, db_path):
        """7일 경과 → outcome_7d 채워짐. 30일 미만이면 outcome_30d=NULL."""
        rec_date = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "AAA", "BUY", 100.0)
        d7 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "date": d7,
                    "open": 102,
                    "high": 104,
                    "low": 101,
                    "close": 103.0,
                    "volume": 1000000,
                    "adj_close": 103.0,
                }
            ]
        )
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path)
        rows = query(
            "SELECT outcome_7d, outcome_14d, outcome_21d, outcome_30d FROM recommendations",
            db_path=db_path,
        )
        assert rows[0]["outcome_7d"] == 3.0
        assert rows[0]["outcome_14d"] is None
        assert rows[0]["outcome_21d"] is None
        assert rows[0]["outcome_30d"] is None

    def test_outcome_21d_filled_when_elapsed_22(self, db_path):
        """21일 경과 → outcome_7/14/21 채워짐, 30 은 NULL."""
        rec_date = (datetime.now() - timedelta(days=22)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "BBB", "BUY", 100.0)
        # 7/14/21 각각 다른 가격
        rows_to_seed = []
        for h, c in [(7, 105.0), (14, 110.0), (21, 115.0)]:
            d = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=h)).strftime("%Y-%m-%d")
            rows_to_seed.append(
                {
                    "ticker": "BBB",
                    "date": d,
                    "open": c - 1,
                    "high": c + 1,
                    "low": c - 2,
                    "close": c,
                    "volume": 1000000,
                    "adj_close": c,
                }
            )
        upsert_prices(pd.DataFrame(rows_to_seed), db_path)
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path)
        rows = query(
            "SELECT outcome_7d, outcome_14d, outcome_21d, outcome_30d FROM recommendations",
            db_path=db_path,
        )
        assert rows[0]["outcome_7d"] == 5.0
        assert rows[0]["outcome_14d"] == 10.0
        assert rows[0]["outcome_21d"] == 15.0
        assert rows[0]["outcome_30d"] is None

    def test_short_horizons_do_not_set_hit(self, db_path):
        """7/14/21d 채워져도 hit/hit_quality 는 NULL (canonical 30d 만 hit 판정)."""
        rec_date = (datetime.now() - timedelta(days=22)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "CCC", "BUY", 100.0)
        d21 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=21)).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [
                {
                    "ticker": "CCC",
                    "date": d21,
                    "open": 119,
                    "high": 121,
                    "low": 118,
                    "close": 120.0,
                    "volume": 1000000,
                    "adj_close": 120.0,
                }
            ]
        )
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path)
        rows = query(
            "SELECT outcome_21d, hit, hit_quality FROM recommendations",
            db_path=db_path,
        )
        assert rows[0]["outcome_21d"] == 20.0
        assert rows[0]["hit"] is None  # canonical 30d 미경과
        assert rows[0]["hit_quality"] is None


class TestOutcomeImmutability:
    """#468 codex Round 1 #5 — non-null outcome 절대 overwrite 금지."""

    def test_existing_outcome_not_overwritten_by_default(self, db_path):
        """기존 outcome_30d 값이 있으면 track_outcomes 가 덮어쓰지 않음."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "IMM", "BUY", 100.0)
        # 먼저 +8% outcome_30d 직접 set (예: 이전 run 결과)
        with get_db(db_path) as conn:
            conn.execute("UPDATE recommendations SET outcome_30d = 8.0, hit = 1 WHERE ticker = 'IMM'")
        # 그 후 prices 가 다른 값으로 수정됐다고 가정
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [
                {
                    "ticker": "IMM",
                    "date": d30,
                    "open": 89,
                    "high": 91,
                    "low": 88,
                    "close": 90.0,
                    "volume": 1000000,
                    "adj_close": 90.0,  # 가격이 -10% 로 revised
                }
            ]
        )
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path)  # recompute=False (default)
        rows = query("SELECT outcome_30d, hit FROM recommendations", db_path=db_path)
        # 기존 +8% 그대로 유지 (vendor revision 으로부터 보호)
        assert rows[0]["outcome_30d"] == 8.0
        assert rows[0]["hit"] == 1

    def test_recompute_true_overwrites_outcome(self, db_path):
        """recompute=True 명시 시에는 overwrite 허용."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "RECMP", "BUY", 100.0)
        with get_db(db_path) as conn:
            conn.execute("UPDATE recommendations SET outcome_30d = 8.0 WHERE ticker = 'RECMP'")
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [
                {
                    "ticker": "RECMP",
                    "date": d30,
                    "open": 89,
                    "high": 91,
                    "low": 88,
                    "close": 90.0,
                    "volume": 1000000,
                    "adj_close": 90.0,
                }
            ]
        )
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path, recompute=True)
        rows = query("SELECT outcome_30d FROM recommendations", db_path=db_path)
        # recompute 로 새 값 반영
        assert rows[0]["outcome_30d"] == -10.0

    def test_partial_outcomes_no_overwrite_only_fills_null(self, db_path):
        """outcome_7d 가 이미 있고 outcome_30d 는 NULL 인 row → 30d 만 새로 채움."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "PART", "BUY", 100.0)
        with get_db(db_path) as conn:
            conn.execute("UPDATE recommendations SET outcome_7d = 2.0 WHERE ticker = 'PART'")
        # 7d 와 30d 모두 prices 시드
        for h, c in [(7, 99.0), (30, 110.0)]:
            d = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=h)).strftime("%Y-%m-%d")
            upsert_prices(
                pd.DataFrame(
                    [
                        {
                            "ticker": "PART",
                            "date": d,
                            "open": c,
                            "high": c,
                            "low": c,
                            "close": c,
                            "volume": 1000000,
                            "adj_close": c,
                        }
                    ]
                ),
                db_path,
            )
        from nuri.trading.recommend.tracker import track_outcomes

        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_7d, outcome_30d FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_7d"] == 2.0  # 보존 (immutable)
        assert rows[0]["outcome_30d"] == 10.0  # 신규


class TestForwardCloseHelper:
    """#468 codex Round 1 #5 — _forward_close_at_horizon deterministic rule."""

    def test_returns_close_on_target_date(self, db_path):
        from nuri.trading.recommend.tracker import _forward_close_at_horizon

        entry = datetime(2026, 4, 1)
        target = (entry + timedelta(days=21)).strftime("%Y-%m-%d")
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "FWD",
                        "date": target,
                        "open": 100,
                        "high": 100,
                        "low": 100,
                        "close": 100.0,
                        "volume": 0,
                        "adj_close": 100.0,
                    }
                ]
            ),
            db_path,
        )
        assert _forward_close_at_horizon("FWD", entry, 21, db_path=db_path) == 100.0

    def test_returns_most_recent_close_on_or_before_target(self, db_path):
        """target 일 close 가 없으면 그 이전 가장 최근 trading day."""
        from nuri.trading.recommend.tracker import _forward_close_at_horizon

        entry = datetime(2026, 4, 1)
        # target = 4-22, 마지막 trading day = 4-19
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "FWD",
                        "date": "2026-04-19",
                        "open": 99,
                        "high": 99,
                        "low": 99,
                        "close": 99.0,
                        "volume": 0,
                        "adj_close": 99.0,
                    },
                ]
            ),
            db_path,
        )
        assert _forward_close_at_horizon("FWD", entry, 21, db_path=db_path) == 99.0

    def test_delisted_ticker_returns_none(self, db_path):
        """ticker 자체가 prices 에 없으면 None (graceful degrade)."""
        from nuri.trading.recommend.tracker import _forward_close_at_horizon

        entry = datetime(2026, 4, 1)
        assert _forward_close_at_horizon("DELISTED", entry, 30, db_path=db_path) is None

    def test_pre_horizon_delisted_returns_none_not_stale_close(self, db_path):
        """codex Review P2 — horizon 훨씬 이전에 거래 중단된 ticker 의 day-1 close 가
        day-21 outcome 으로 잘못 채워지지 않아야 한다 (tolerance window lower bound).
        """
        from nuri.trading.recommend.tracker import _forward_close_at_horizon

        entry = datetime(2026, 4, 1)
        # entry+1 일에만 거래 (그 이후 delisting). horizon=21 (target = 4-22) 시
        # tolerance window = 4-15 ~ 4-22. day-1 close (4-2) 는 window 밖 → None.
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "PREDEL",
                        "date": "2026-04-02",
                        "open": 100,
                        "high": 100,
                        "low": 100,
                        "close": 100.0,
                        "volume": 0,
                        "adj_close": 100.0,
                    },
                ]
            ),
            db_path,
        )
        assert _forward_close_at_horizon("PREDEL", entry, 21, db_path=db_path) is None

    def test_close_within_tolerance_window_accepted(self, db_path):
        """target 보다 며칠 이전이지만 tolerance window 안 → close 반환."""
        from nuri.trading.recommend.tracker import _forward_close_at_horizon

        entry = datetime(2026, 4, 1)
        # target = 4-22, tolerance 7일 → 4-15 ~ 4-22. 4-18 close 는 valid.
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "TOL",
                        "date": "2026-04-18",
                        "open": 100,
                        "high": 100,
                        "low": 100,
                        "close": 105.0,
                        "volume": 0,
                        "adj_close": 105.0,
                    },
                ]
            ),
            db_path,
        )
        assert _forward_close_at_horizon("TOL", entry, 21, db_path=db_path) == 105.0


# ─── tracker.track_outcomes line 259 — entry<=0 guard ─────────────────────


class TestTrackOutcomesEntryZeroGuard:
    """SQL `WHERE entry_price > 0` 가 일반 path 를 차단하지만 Python 측 defensive guard
    (line 258-259) 가 살아있다 — query() 를 monkeypatch 해 entry=0 row 를 강제로
    주입하면 `if entry <= 0: continue` 분기가 진입한다.
    """

    def test_entry_zero_row_skipped_via_python_guard(self, monkeypatch, tmp_path):
        from nuri.core.db import init_db
        from nuri.trading.recommend import tracker as tracker_mod

        db = tmp_path / "tracker.db"
        init_db(db)

        # Bypass SQL filter: query() 가 entry=0 row 를 반환하도록 강제
        crafted_row = {
            "id": 1,
            "date": "2026-04-01",
            "ticker": "ZERO",
            "action": "BUY",
            "entry_price": 0.0,  # <= 0 → defensive guard 적중
            "outcome_7d": None,
            "outcome_14d": None,
            "outcome_21d": None,
            "outcome_30d": None,
            "outcome_60d": None,
            "outcome_90d": None,
        }
        monkeypatch.setattr(tracker_mod, "query", lambda *a, **kw: [crafted_row])
        # 다른 의존도 안전하게 mocking — get_db / _forward_close 등 호출 차단
        # entry<=0 분기에서 즉시 continue 하므로 다른 함수가 호출되지 않아야 한다.

        updated = tracker_mod.track_outcomes(db_path=db)
        assert updated == 0  # entry=0 → continue → no update


class TestRegimeLabelEmit:
    """#832 Gotcha-Test Pair: save_recommendations 의 regime 라벨 저장 회귀 방지.

    기존 E-1 경로는 `"regime": ""`, E-2 경로는 free-text `regime_note` 를 그대로
    persist 해 라벨 커버리지 3% 의 원인이었음. batch classify + canonical guard 로
    되돌아가면 (regime="" / regime=regime_note 복원) 이 테스트가 fail.
    진단 전용 라벨 — STRATEGY §3.11 이 regime 을 판정 축에서 제외.
    """

    @staticmethod
    def _regime_state(regime: str):
        from nuri.quant.regime.classifier import RegimeState

        return RegimeState(date="2026-01-02", trend="bull", volatility="low", regime=regime, confidence=0.8, details={})

    def test_e1_candidate_saves_canonical_regime(self, rich_db):
        """E-1 후보 저장 시 batch classify 라벨이 regime 컬럼에 기록 ("" 회귀 방지)."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        with patch(
            "nuri.quant.regime.classifier.classify_regime",
            return_value=self._regime_state("bull_low_vol"),
        ):
            candidates = [
                Candidate("AAPL", "rsi_oversold", "2026-01-02", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
            ]
            assert save_recommendations(candidates=candidates, db_path=rich_db) == 1

        row = query("SELECT regime FROM recommendations WHERE ticker='AAPL'", db_path=rich_db)[0]
        assert row["regime"] == "bull_low_vol"

    def test_e2_action_never_saves_freetext_regime_note(self, rich_db):
        """E-2 액션의 free-text regime_note 가 regime 컬럼에 유입되지 않음."""
        from nuri.trading.recommend.tracker import save_recommendations

        action = MagicMock()
        action.ticker = "AAPL"
        action.action = "BUY"
        action.signals = ["rebalance"]
        action.regime_note = "[recovery] 비중 축소"

        with patch(
            "nuri.quant.regime.classifier.classify_regime",
            return_value=self._regime_state("recovery"),
        ):
            assert save_recommendations(actions=[action], db_path=rich_db) == 1

        row = query("SELECT regime FROM recommendations WHERE ticker='AAPL'", db_path=rich_db)[0]
        assert row["regime"] == "recovery"

    def test_classify_failure_keeps_null_not_empty_string(self, rich_db):
        """classify 실패(None) 시 regime 은 NULL — "" 나 'unknown' 금지."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            candidates = [
                Candidate("AAPL", "rsi_oversold", "2026-01-02", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
            ]
            assert save_recommendations(candidates=candidates, db_path=rich_db) == 1

        row = query("SELECT regime FROM recommendations WHERE ticker='AAPL'", db_path=rich_db)[0]
        assert row["regime"] is None


class TestSaveBuyCandidates:
    """`buy_candidate_emitter` 산출물 영속화 (#1078).

    이 emitter 의 실행에는 지금까지 **아무것도 남지 않았다** — 후보를 발행하고 브리핑에
    렌더한 뒤 `EmitResult` 를 통째로 버렸다. 그래서 tracker 백필 · `decision_outcomes` ·
    `/api/alpha` 로 이어지는 체인이 이 경로에 대해서만 비어 있었다.
    """

    @staticmethod
    def _result(*tickers):
        from nuri.trading.recommend.buy_candidate_emitter import BuyCandidate, EmitResult

        return EmitResult(
            candidates=[
                BuyCandidate(
                    ticker=t,
                    score=85.0,
                    deploy_pct=6.0,
                    entry=100.0,
                    stop=93.0,
                    tp1=120.0,
                    tp2=140.0,
                    why_now="breakout",
                    sources={"factor": 0.8},
                )
                for t in tickers
            ],
            regime="bull_low_vol",
        )

    def test_writes_rows_tagged_with_the_emit_source(self, db_path):
        """Mutation lock: `source` 를 안 찍으면 §3.11 표본에서 걸러낼 수가 없어 FAIL."""
        from nuri.trading.recommend.tracker import BUY_CANDIDATE_SOURCE, save_buy_candidates

        n = save_buy_candidates(self._result("AAA", "BBB"), db_path=db_path)
        assert n == 2

        rows = query("SELECT ticker, action, source, entry_price FROM recommendations", db_path=db_path)
        assert {r["ticker"] for r in rows} == {"AAA", "BBB"}
        assert all(r["action"] == "BUY" for r in rows)
        assert all(r["source"] == BUY_CANDIDATE_SOURCE for r in rows)
        assert all(r["entry_price"] == 100.0 for r in rows)

    def test_price_levels_survive_in_scoring_detail(self, db_path):
        """stop/TP 는 `recommendations` 에 컬럼이 없다 — 사후 재구성이 가능해야 한다."""
        from nuri.trading.recommend.tracker import save_buy_candidates

        save_buy_candidates(self._result("AAA"), db_path=db_path)
        detail = json.loads(query("SELECT scoring_detail FROM recommendations", db_path=db_path)[0]["scoring_detail"])
        assert detail["stop"] == 93.0
        assert detail["tp1"] == 120.0
        assert detail["tp2"] == 140.0

    def test_unique_collision_is_reported_not_silently_counted(self, db_path):
        """같은 날 합의가 먼저 쓴 ticker 는 조용히 드롭된다 — 반환값이 그걸 반영해야 한다.

        `recommendations` 는 `UNIQUE(date, ticker)` + `INSERT OR IGNORE` 다. `len(records)`
        를 그대로 돌려주면 "저장했다" 와 "저장된 척했다" 가 구분되지 않는다.

        Mutation lock: `rowcount` 대신 `len(records)` 를 돌려주면 FAIL.
        """
        from nuri.trading.recommend.tracker import save_buy_candidates

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES (?, ?, 'BUY', 60.0)",
                (today_kst(), "AAA"),
            )

        n = save_buy_candidates(self._result("AAA", "BBB"), db_path=db_path)
        assert n == 1, "드롭된 행까지 저장했다고 셌다"
        assert query("SELECT COUNT(*) c FROM recommendations", db_path=db_path)[0]["c"] == 2

    def test_empty_result_writes_nothing(self, db_path):
        from nuri.trading.recommend.buy_candidate_emitter import EmitResult
        from nuri.trading.recommend.tracker import save_buy_candidates

        assert save_buy_candidates(EmitResult(blocked_reason="VIX 35 > 30"), db_path=db_path) == 0
        assert query("SELECT COUNT(*) c FROM recommendations", db_path=db_path)[0]["c"] == 0

    def test_regime_classify_failure_does_not_block_persistence(self, db_path, monkeypatch):
        """레짐 분류가 터져도 후보는 저장된다 — regime 만 NULL 로 남는다.

        관측(레짐 라벨)이 본 작업(원장 기록)을 게이트하면 안 된다 (#894). 이 emitter 의
        기록이 없어서 체인 전체가 비어 있었던 게 #1078 의 출발점인데, 라벨 하나 때문에
        다시 비면 같은 자리로 돌아간다.
        """
        import nuri.quant.regime.classifier as clf

        def boom(*a, **k):
            raise RuntimeError("regime down")

        monkeypatch.setattr(clf, "classify_regime", boom)

        from nuri.trading.recommend.tracker import save_buy_candidates

        assert save_buy_candidates(self._result("AAA"), db_path=db_path) == 1
        row = query("SELECT ticker, regime FROM recommendations", db_path=db_path)[0]
        assert row["ticker"] == "AAA"
        assert row["regime"] is None

    @pytest.mark.parametrize(
        ("classified", "expected"),
        [
            ("bull_low_vol", "bull_low_vol"),  # canonical → 그대로 행에 박힌다
            ("[recovery] 비중 축소", None),  # free-text → NULL (#832)
        ],
    )
    def test_regime_label_is_canonical_or_null(self, db_path, monkeypatch, classified, expected):
        """분류가 성공하면 라벨이 행에 남되, canonical 10종이 아니면 NULL 이다.

        실패 경로만 잠그면 `canonical_regime_or_none` 을 벗겨도(=`rr.regime` 을 그대로
        대입해도) 초록이다. free-text 유입이 라벨 커버리지를 3% 로 만든 게 #832 였다.
        """
        import nuri.quant.regime.classifier as clf

        monkeypatch.setattr(clf, "classify_regime", lambda **k: SimpleNamespace(regime=classified))

        from nuri.trading.recommend.tracker import save_buy_candidates

        assert save_buy_candidates(self._result("AAA"), db_path=db_path) == 1
        row = query("SELECT regime FROM recommendations", db_path=db_path)[0]
        assert row["regime"] == expected

    def test_portfolio_action_stays_null(self, db_path):
        """축 분리 (#429) — 이건 alpha 축 신호지 포트폴리오 룰이 아니다."""
        from nuri.trading.recommend.tracker import save_buy_candidates

        save_buy_candidates(self._result("AAA"), db_path=db_path)
        row = query("SELECT alpha_action, portfolio_action FROM recommendations", db_path=db_path)[0]
        assert row["alpha_action"] == "LONG"
        assert row["portfolio_action"] is None
