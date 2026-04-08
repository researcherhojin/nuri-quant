"""Tests for misc agent — split from test_trading_agents_all.py."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


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
