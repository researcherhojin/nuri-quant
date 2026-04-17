"""Tests for nuri.trading.engine.conflicts.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_engine.py, test_coverage_round10.py, test_coverage_round16.py,
test_coverage_round26.py.
"""
from dataclasses import dataclass
from unittest.mock import MagicMock, patch


class TestConflicts:
    """From test_engine.py."""

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


class TestConflicts_R10:
    """From test_coverage_round10.py."""

    def test_detect_conflicts(self, rich_db):
        from nuri.trading.engine.conflicts import detect_conflicts
        result = detect_conflicts()
        assert isinstance(result, list)


class TestConflicts_R26:
    """From test_coverage_round26.py."""

    def test_no_candidates(self, db_path):
        from nuri.trading.engine.conflicts import detect_conflicts
        result = detect_conflicts(candidates=[], db_path=db_path)
        assert result == []

    def test_direction_conflict(self):
        from nuri.trading.engine.conflicts import detect_conflicts

        @dataclass
        class MockCand:
            ticker: str
            direction: str
            signal_id: str
            regime_fit: bool
            profit_factor: float
            confidence: float = 50
            notes: str = ""
            conflict: str = ""
            scoring_detail: dict = None
            tier: str = "actionable"

        candidates = [
            MockCand("AAPL", "BUY", "rsi_oversold", True, 2.0),
            MockCand("AAPL", "SELL", "macd_dead", True, 1.5),
        ]
        conflicts = detect_conflicts(candidates=candidates)
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == "direction_conflict"

    def test_strength_mismatch(self):
        from nuri.trading.engine.conflicts import detect_conflicts

        @dataclass
        class MockCand:
            ticker: str
            direction: str
            signal_id: str
            regime_fit: bool
            profit_factor: float
            confidence: float = 50
            notes: str = ""
            conflict: str = ""
            scoring_detail: dict = None
            tier: str = "actionable"

        candidates = [
            MockCand("AAPL", "BUY", "rsi_oversold", True, 5.0),
            MockCand("AAPL", "BUY", "volume_spike", True, 1.0),
        ]
        conflicts = detect_conflicts(candidates=candidates)
        strength = [c for c in conflicts if c.conflict_type == "strength_mismatch"]
        assert len(strength) >= 1

    def test_print_conflicts(self, capsys):
        from nuri.trading.engine.conflicts import SignalConflict, print_conflicts
        conflicts = [
            SignalConflict("AAPL", "direction_conflict", "high", ["rsi"], ["macd"], "detail", "rec"),
        ]
        print_conflicts(conflicts)
        out = capsys.readouterr().out
        assert "AAPL" in out

    def test_print_conflicts_empty(self, capsys):
        from nuri.trading.engine.conflicts import print_conflicts
        print_conflicts([])
        out = capsys.readouterr().out
        assert "없음" in out


class TestConflictsStrengthMismatch:
    """From test_coverage_round16.py."""

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
    """From test_coverage_round16.py."""

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
    """From test_coverage_round16.py."""

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


class TestConflictsPrint:
    """From test_coverage_round16.py."""

    def test_no_conflicts(self, capsys):
        from nuri.trading.engine.conflicts import print_conflicts
        print_conflicts([])
        out = capsys.readouterr().out
        assert "시그널 충돌 없음" in out

    def test_with_conflicts(self, capsys):
        from nuri.trading.engine.conflicts import SignalConflict, print_conflicts
        conflicts = [
            SignalConflict(
                ticker="TSLA", conflict_type="direction_conflict", severity="high",
                buy_signals=["bb_bounce"], sell_signals=["macd_dead"],
                detail="BUY와 SELL 동시 발생", recommendation="관망 권장"),
            SignalConflict(
                ticker="AAPL", conflict_type="strength_mismatch", severity="low",
                buy_signals=["rsi_oversold"], sell_signals=[],
                detail="강한/약한 시그널 공존", recommendation="강한 시그널 우선"),
        ]
        print_conflicts(conflicts)
        out = capsys.readouterr().out
        assert "Signal Conflicts (2건)" in out
        assert "[!!!]" in out
        assert "TSLA" in out
