"""Tests for conflicts — split from test_trading_recommend_all.py."""
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


class TestConflictsWithCandidate:
    """From test_engine.py / test_trading_engine_all.py — uses Candidate from recommend."""

    def test_direction_conflict_detected(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate

        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 380.0, ""),
            Candidate("TSLA", "macd_dead", "2025-03-24", "SELL", 55, 0.70, 1.4, True, 380.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        assert len(conflicts) >= 1
        tsla_conflict = [c for c in conflicts if c.ticker == "TSLA" and c.conflict_type == "direction_conflict"]
        assert len(tsla_conflict) == 1
        assert tsla_conflict[0].severity == "high"

    def test_no_conflict_single_direction(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate

        candidates = [
            Candidate("NVDA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 100.0, ""),
            Candidate("NVDA", "rsi_oversold", "2025-03-24", "BUY", 60, 0.53, 1.8, True, 100.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        direction = [c for c in conflicts if c.conflict_type == "direction_conflict"]
        assert len(direction) == 0

    def test_empty_candidates(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        assert detect_conflicts([]) == []


class TestConflictsStrengthMismatch:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_strength_mismatch_detected(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-25", "BUY", 70, 0.60, 5.0, True, 170, ""),
            Candidate("AAPL", "gap_up", "2025-03-25", "BUY", 40, 0.40, 1.2, False, 170, ""),
        ]
        conflicts = detect_conflicts(candidates)
        strength = [c for c in conflicts if c.conflict_type == "strength_mismatch"]
        assert len(strength) == 1
        assert "강한 시그널" in strength[0].detail

    def test_no_strength_mismatch_when_similar(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-25", "BUY", 70, 0.60, 2.0, True, 170, ""),
            Candidate("AAPL", "bb_bounce", "2025-03-25", "BUY", 65, 0.55, 1.8, True, 170, ""),
        ]
        conflicts = detect_conflicts(candidates)
        strength = [c for c in conflicts if c.conflict_type == "strength_mismatch"]
        assert len(strength) == 0


class TestConflictsRegimeContradiction:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_buy_in_bear_market(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, False, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bear"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 1
        assert "하락장" in regime_c[0].detail

    def test_sell_in_bull_market(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "macd_dead", "2025-03-25", "SELL", 55, 0.50, 1.5, False, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bull"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 1
        assert "상승장" in regime_c[0].detail

    def test_regime_fit_buy_in_bear_skipped(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, True, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bear"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 0

    def test_classify_regime_exception_no_crash(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, False, 200, ""),
        ]
        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 0


class TestConflictsMediumSeverity:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_medium_severity_direction_conflict(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("NVDA", "rsi_oversold", "2025-03-25", "BUY", 60, 0.55, 2.0, True, 100, ""),
            Candidate("NVDA", "macd_dead", "2025-03-24", "SELL", 50, 0.45, 1.3, False, 100, ""),
        ]
        conflicts = detect_conflicts(candidates)
        dc = [c for c in conflicts if c.conflict_type == "direction_conflict"]
        assert len(dc) == 1
        assert dc[0].severity == "medium"
        assert "레짐 적합 시그널" in dc[0].recommendation
