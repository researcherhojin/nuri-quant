"""Tests for candidates — split from test_trading_recommend_all.py."""
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


class TestCandidates:
    """From test_recommend.py."""

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


class TestCandidatesDeep:
    """From test_sixty_percent.py."""

    def test_screen_with_signals(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=full_db)
        assert isinstance(candidates, list)

    def test_confidence_range(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=full_db)
        for c in candidates:
            assert 0 <= c.confidence <= 100

    def test_print_candidates(self, full_db, capsys):
        from nuri.trading.recommend.candidates import Candidate, print_candidates
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2026-03-28", "BUY", 75.0, 0.65, 2.1, True, 155.0, "test"),
            Candidate("TSLA", "macd_golden", "2026-03-28", "BUY", 60.0, 0.55, 1.5, True, 350.0, "test"),
        ]
        print_candidates(candidates)
        output = capsys.readouterr().out
        assert "AAPL" in output


class TestCandidates_R10:
    """From test_coverage_round10.py."""

    def test_screen_candidates(self, rich_db):
        from nuri.trading.recommend.candidates import screen_candidates
        result = screen_candidates()
        assert isinstance(result, list)

    def test_tracker_save(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        count = save_recommendations([])
        assert count == 0


class TestCandidatesExtended:
    """From test_coverage_extra.py."""

    def test_candidate_dataclass(self):
        from nuri.trading.recommend.candidates import Candidate
        c = Candidate("AAPL", "rsi_oversold", "2026-03-28", "BUY", 75.0, 0.65, 2.1, True, 155.0, "test")
        assert c.ticker == "AAPL"
        assert c.direction == "BUY"
        assert c.confidence == 75.0

    def test_screen_with_data(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10, db_path=full_db)
        assert isinstance(candidates, list)


class TestCandidatesVixGate:
    """VIX gate logic in candidates (from test_coverage_round18)."""

    def test_vix_blocked(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 35.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "blocked"
        assert result["vix"] == 35.0

    def test_vix_caution(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 27.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "caution"

    def test_vix_normal(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 15.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"

    def test_vix_no_data(self, tmp_path, monkeypatch):
        """No VIX data => value 0 => normal."""
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"
        assert result["vix"] == 0.0


class TestCandidatesDriftMultipliers:
    """DRIFT_MULTIPLIERS sanity (from test_coverage_round18)."""

    def test_drift_multiplier_values(self):
        from nuri.trading.recommend.candidates import DRIFT_MULTIPLIERS

        assert DRIFT_MULTIPLIERS["critical"] == 0.3
        assert DRIFT_MULTIPLIERS["degrading"] == 0.6
        assert DRIFT_MULTIPLIERS["improving"] == 1.1
        assert DRIFT_MULTIPLIERS["stable"] == 1.0


class TestScreenCandidates:
    """screen_candidates integration with mocked regime and scorecard (from test_coverage_round18)."""

    def test_empty_portfolio_returns_empty(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import screen_candidates

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    candidates = screen_candidates(lookback_days=5, db_path=path)

        assert candidates == []

    def test_screen_with_regime_avoid(self, rich_db):
        """Signals in avoid list get regime_fit=False and confidence penalty."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bear_high_vol",
            "recommended": [],
            "avoid": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce",
                       "volume_spike", "gap_up", "vix_reversal", "pcr_reversal",
                       "yield_curve_recovery", "insider_cluster", "short_squeeze"],
            "position": "minimal",
            "regime_stats": {},
        }
        scorecard = {
            "rsi_oversold": {"win_rate": 0.6, "profit_factor": 2.0, "avg_return": 3.0, "total_trades": 20},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=(scorecard, 1)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        avoided = [c for c in candidates if not c.regime_fit]
        for c in avoided:
            assert c.confidence < 50

    def test_screen_with_drift_penalty(self, rich_db):
        """Signals with critical drift get heavily penalized."""
        from nuri.trading.recommend.candidates import screen_candidates

        drift_map = {
            "rsi_oversold": {"status": "critical", "drift_pct": -50},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value=drift_map):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        critical = [c for c in candidates if c.drift_status == "critical"]
        for c in critical:
            assert c.scoring_detail is not None
            assert c.scoring_detail["drift_multiplier"] == 0.3


class TestScoringDetailDiscriminator:
    """A-2b-pre — candidates scoring_detail 에 `source="candidate"`/`schema_version=1`
    discriminator 가 박혀야 consensus scoring_detail (source="consensus") 와 구분됨.

    STRATEGY §5.3.1 Gotcha-Test Pair — discriminator 를 실수로 제거하면 A-2b API
    가 두 schema 를 key-sniffing 으로 분기하게 되어 brittle.
    """

    def test_candidate_scoring_detail_has_discriminator(self, rich_db):
        """candidates 의 모든 scoring_detail 에 source + schema_version 포함."""
        from unittest.mock import patch

        from nuri.trading.recommend.candidates import screen_candidates

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        assert candidates, "fixture 가 최소 1 개 candidate 생성"
        for c in candidates:
            assert c.scoring_detail is not None
            assert c.scoring_detail.get("source") == "candidate", (
                "A-2b-pre regression: candidates scoring_detail 에 source 가 없으면 "
                "A-2b API 가 consensus 와 구분할 수 없음"
            )
            assert c.scoring_detail.get("schema_version") == 1

    def test_vix_gate_syncs_scoring_detail_final_confidence(self, rich_db):
        """A-2b-pre (codex Medium fix) — VIX gate 가 c.confidence 를 업데이트하면
        scoring_detail["final_confidence"] 도 동기화. A-2b 가 audit source 로
        scoring_detail 을 쓸 때 stale 방지.

        STRATEGY §5.3.1 Gotcha-Test Pair: VIX gate 에서 scoring_detail 업데이트를
        제거하면 test fail — candidate.confidence=0 (blocked) 인데 scoring_detail
        에는 pre-VIX 값이 남아 있는 모순 상태 lock-in.
        """
        from unittest.mock import patch

        from nuri.trading.recommend.candidates import screen_candidates

        # VIX blocked — 모든 BUY 후보 confidence 0
        vix_blocked = {"gate": "blocked", "msg": "VIX > 30", "vix": 35.0}
        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        with patch("nuri.trading.recommend.candidates._check_vix_gate", return_value=vix_blocked):
                            candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        buys = [c for c in candidates if c.direction == "BUY"]
        assert buys, "fixture 가 BUY 후보 생성"
        for c in buys:
            assert c.confidence == 0, "VIX blocked 는 BUY confidence=0"
            assert c.scoring_detail is not None
            assert c.scoring_detail["final_confidence"] == 0.0, (
                "scoring_detail['final_confidence'] 도 0 으로 동기화 — audit trail 일관성"
            )
            assert c.scoring_detail["vix_penalty"] == 0.0

    def test_vix_caution_syncs_scoring_detail_final_confidence(self, rich_db):
        """VIX caution (25~30) 경로도 scoring_detail 동기화 — codex Round 2 residual
        gap. confidence × 0.5 discount 가 scoring_detail['final_confidence'] 에도
        반영되는지 확인."""
        from unittest.mock import patch

        from nuri.trading.recommend.candidates import screen_candidates

        vix_caution = {"gate": "caution", "msg": "VIX 25~30", "vix": 27.5}
        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        with patch("nuri.trading.recommend.candidates._check_vix_gate", return_value=vix_caution):
                            candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        buys = [c for c in candidates if c.direction == "BUY"]
        assert buys, "fixture 가 BUY 후보 생성"
        for c in buys:
            assert c.scoring_detail is not None
            assert c.scoring_detail["vix_penalty"] == 0.5
            # scoring_detail["final_confidence"] == c.confidence (round 차이 허용)
            assert abs(c.scoring_detail["final_confidence"] - c.confidence) < 0.1


class TestLoadScorecard:
    """_load_scorecard with and without CSV files (from test_coverage_round18)."""

    def test_no_report_dir(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        monkeypatch.setattr(cand_mod, "REPORT_DIR", tmp_path / "nonexistent")
        data, age = cand_mod._load_scorecard()
        assert data == {}
        assert age is None

    def test_with_scorecard_csv(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2026-03-30"
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        csv_content += ",macd_golden,0.55,1.5,2.0,20\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert "rsi_oversold" in data
        assert data["rsi_oversold"]["win_rate"] == 0.65
        assert age is not None

    def test_stale_scorecard_warning(self, tmp_path, monkeypatch):
        """Scorecard older than 7 days triggers warning."""
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2025-01-01"
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert age is not None and age > 7
        assert "rsi_oversold" in data


class TestGetRegimeContext:
    """_get_regime_context with mocked regime classifier (from test_coverage_round18)."""

    def test_regime_returns_context(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        mock_regime = MagicMock(regime="bull_low_vol")
        mock_strategy = MagicMock(
            recommended_signals=["rsi_oversold"],
            avoid_signals=["rsi_overbought"],
            position_sizing="normal",
            signal_regime_stats={"rsi_oversold": {"win_rate": 0.7, "pf": 2.0, "trades": 10}},
        )

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            with patch("nuri.quant.regime.strategy_map.map_regime_to_strategy", return_value=mock_strategy):
                ctx = _get_regime_context(rich_db)

        assert ctx is not None
        assert ctx["regime"] == "bull_low_vol"
        assert "rsi_oversold" in ctx["recommended"]
        assert ctx["regime_stats"]["rsi_oversold"]["win_rate"] == 0.7

    def test_regime_none_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            ctx = _get_regime_context(rich_db)

        assert ctx is None

    def test_regime_exception_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            ctx = _get_regime_context(rich_db)

        assert ctx is None


class TestPrintCandidates:
    """print_candidates output formatting (from test_coverage_round18)."""

    def test_print_empty(self, capsys):
        from nuri.trading.recommend.candidates import print_candidates

        print_candidates([])
        out = capsys.readouterr().out
        assert "매매 후보 없음" in out

    def test_print_with_candidates(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=75.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="과거 20건",
                drift_status="", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="NVDA", signal_id="macd_dead", signal_date="2026-03-30",
                direction="SELL", confidence=60.0, win_rate=0.55, profit_factor=1.5,
                regime_fit=True, price=900.0, notes="",
                drift_status="degrading", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="AAPL", signal_id="rsi_overbought", signal_date="2026-03-30",
                direction="SELL", confidence=30.0, win_rate=0.45, profit_factor=0.8,
                regime_fit=False, price=180.0, notes="레짐에서 비추천",
                drift_status="critical", conflict="direction_conflict", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 15, "gate": "normal", "msg": ""}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "Signal-Based Candidates" in out
        assert "AAPL" in out

    def test_print_vix_blocked(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=0.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="VIX > 30",
                drift_status="", conflict="", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 35, "gate": "blocked", "msg": "VIX 35.0 > 30 -> block"}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "VIX" in out


class TestCandidatesConflictDetection:
    """Conflict detection in screen_candidates (from test_coverage_round18)."""

    def test_conflict_penalty_applied(self, rich_db):
        """When detect_conflicts returns high severity, confidence is halved."""
        from nuri.trading.engine.conflicts import SignalConflict
        from nuri.trading.recommend.candidates import screen_candidates

        conflicts = [
            SignalConflict(
                ticker="AAPL",
                conflict_type="direction_conflict",
                severity="high",
                buy_signals=["rsi_oversold"],
                sell_signals=["rsi_overbought"],
                detail="방향 충돌",
                recommendation="관망",
            ),
        ]

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=conflicts):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        aapl_conflicted = [c for c in candidates if c.ticker == "AAPL" and c.conflict]
        for c in aapl_conflicted:
            assert c.conflict == "direction_conflict"
            if c.scoring_detail:
                assert c.scoring_detail.get("conflict_penalty") == 0.5


class TestCandidatesRegimeStats:
    """Test regime-specific stats path in confidence calculation (from test_coverage_round18)."""

    def test_regime_stats_used_when_available(self, rich_db):
        """When regime_stats has enough trades, uses regime-specific win_rate."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bull_low_vol",
            "recommended": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce", "volume_spike"],
            "avoid": [],
            "position": "normal",
            "regime_stats": {
                "rsi_oversold": {"win_rate": 0.8, "pf": 3.0, "trades": 15},
                "macd_golden": {"win_rate": 0.7, "pf": 2.5, "trades": 12},
            },
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        rsi_cands = [c for c in candidates if c.signal_id == "rsi_oversold"]
        for c in rsi_cands:
            if c.scoring_detail:
                assert "regime_win_rate" in c.scoring_detail


class TestCandidates_R27:
    """From test_coverage_round27.py."""

    def test_load_scorecard_no_reports(self, monkeypatch):
        """_load_scorecard with no report directory."""
        import nuri.trading.recommend.candidates as cand_mod
        from nuri.trading.recommend.candidates import _load_scorecard
        monkeypatch.setattr(cand_mod, "REPORT_DIR", Path("/nonexistent/path"))
        data, age = _load_scorecard()
        assert data == {}
        assert age is None

    def test_get_drift_map_exception(self, monkeypatch):
        """_get_drift_map handles exception."""
        from nuri.trading.recommend.candidates import _get_drift_map
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift",
                            MagicMock(side_effect=Exception("no data")))
        result = _get_drift_map()
        assert result == {}

    def test_check_vix_gate_normal(self, db_path):
        """VIX gate normal when VIX is low."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 18.5))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "normal"

    def test_check_vix_gate_blocked(self, db_path):
        """VIX gate blocked when VIX > 30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 35.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "blocked"

    def test_check_vix_gate_caution(self, db_path):
        """VIX gate caution when VIX 25-30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 27.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "caution"

    def test_print_candidates_empty(self, capsys, monkeypatch):
        """print_candidates with no candidates."""
        from nuri.trading.recommend.candidates import print_candidates
        monkeypatch.setattr("nuri.trading.recommend.candidates._check_vix_gate",
                            lambda **kw: {"vix": 18, "gate": "normal", "msg": ""})
        print_candidates([])
        captured = capsys.readouterr()
        assert "매매 후보 없음" in captured.out


class TestScorecardStaleness:
    """From test_data_integrity.py — scorecard freshness check."""

    def test_stale_scorecard_adds_note(self, tmp_path, db_path):
        """7일 초과 스코어카드 → 후보 노트에 경고 문구."""
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        report_dir = tmp_path / "reports" / stale_date
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None, None],
            "signal_id": ["rsi_oversold", "macd_golden"],
            "win_rate": [0.6, 0.55],
            "profit_factor": [2.0, 1.5],
            "avg_return": [0.05, 0.03],
            "total_trades": [100, 80],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days >= 9
            assert len(data) > 0
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_fresh_scorecard_no_warning(self, tmp_path):
        """7일 이내 스코어카드 → 경고 없음."""
        today = today_kst()
        report_dir = tmp_path / "reports" / today
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None],
            "signal_id": ["rsi_oversold"],
            "win_rate": [0.6],
            "profit_factor": [2.0],
            "avg_return": [0.05],
            "total_trades": [100],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days <= 7
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_no_scorecard_returns_none_age(self, tmp_path):
        """스코어카드 파일 없으면 age_days=None."""
        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "nonexistent"
            data, age_days = cand_module._load_scorecard()
            assert data == {}
            assert age_days is None
        finally:
            cand_module.REPORT_DIR = original_report_dir
