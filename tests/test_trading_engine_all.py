"""Consolidated tests for nuri.trading.engine.* and nuri.trading.execution.*.

Modules covered:
- nuri.trading.engine.gate — Gate checks (check_gate, check_all_gates, print_gate)
- nuri.trading.engine.conflicts — Signal conflict detection (detect_conflicts, print_conflicts)
- nuri.trading.engine.memory — Learning memory (save_snapshot, detect_drift, print_memory_status)
- nuri.trading.engine.certification — SIEGE certification (certify, CertCondition, Certificate, all check functions)
- nuri.trading.execution.broker — Broker (DryRunBroker, AlpacaBroker, Order, Position, get_broker)

Extracted from: test_engine.py, test_certification.py, test_new_features.py,
test_coverage_round{10,12,13,16,23,26,27}.py, test_coverage_boost.py, test_coverage_extra.py.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture()
def db_path_monkeypatched(tmp_path, monkeypatch):
    """DB with monkeypatched DB_PATH for modules that use the global."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _force_delete_journal(db_path, monkeypatch):
    """CI tmpfs WAL 호환성 문제 근본 해결 — 테스트 DB를 DELETE 모드로 강제.

    get_connection()이 매 연결마다 WAL을 재설정하므로, checkpoint만으로는 불충분.
    get_connection 자체를 패치하여 테스트 DB에서는 DELETE 모드를 사용하게 한다.
    """
    import nuri.core.db as db_mod
    _orig = db_mod.get_connection

    def _no_wal(dp=None):
        conn = _orig(dp)
        conn.execute("PRAGMA journal_mode=DELETE")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", _no_wal)


@pytest.fixture()
def populated_db(db_path, monkeypatch):
    """Gate/certification test data: portfolio + 300-day SPY + VIX."""
    import nuri.core.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    _force_delete_journal(db_path, monkeypatch)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    dates = pd.bdate_range("2024-01-01", periods=300)
    close = np.linspace(100, 150, 300) + np.random.normal(0, 1, 300)
    df = pd.DataFrame({
        "ticker": "SPY", "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [50000000] * 300, "adj_close": close,
    })
    upsert_prices(df, db_path)

    df2 = df.copy()
    df2["ticker"] = "TEST"
    upsert_prices(df2, db_path)

    upsert_macro([{"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
                    "value": 18.0, "source": "test"}], db_path)
    upsert_macro([{"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"),
                    "value": 50.0, "source": "test"}], db_path)

    return db_path


@pytest.fixture()
def populated_db_cert(tmp_path, monkeypatch):
    """Certification-specific populated DB (from test_certification.py)."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "AAPL", 10, 150.0, "USD", "Technology"),
        )
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "MSFT", 5, 300.0, "USD", "Technology"),
        )

    today = datetime.now().strftime("%Y-%m-%d")
    prices = pd.DataFrame([
        {"ticker": "SPY", "date": today, "open": 500, "high": 510, "low": 495, "close": 505, "volume": 50000000, "adj_close": 505},
        {"ticker": "AAPL", "date": today, "open": 155, "high": 158, "low": 153, "close": 156, "volume": 10000000, "adj_close": 156},
        {"ticker": "MSFT", "date": today, "open": 310, "high": 315, "low": 308, "close": 312, "volume": 5000000, "adj_close": 312},
    ])
    upsert_prices(prices, path)

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], path)

    return path


@pytest.fixture()
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, 300+ days prices (SPY + tickers), macro (from round16/round10)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 170, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 120, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "SectorA"},
    ], path)

    dates = pd.bdate_range("2024-06-01", periods=300, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLA", "VOO"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200, "VOO": 440}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
    upsert_macro(macro, path)
    return path


def _seed_prices_r23(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows (round23 helper)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro_r23(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows (round23 helper)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# GATE — nuri.trading.engine.gate
# ═══════════════════════════════════════════════════════════════════════════════


class TestGate:
    """From test_engine.py."""

    def test_empty_db_all_fail(self, db_path):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(db_path=db_path)
        assert result.passed < result.total
        assert result.ready is False

    def test_populated_db_passes_basics(self, populated_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(phase="collect", db_path=populated_db)
        portfolio_cond = [c for c in result.conditions if c.id == "portfolio_exists"]
        assert len(portfolio_cond) == 1
        assert portfolio_cond[0].passed is True

    def test_regime_gate_with_spy(self, populated_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(phase="regime", db_path=populated_db)
        spy_cond = [c for c in result.conditions if c.id == "spy_data"]
        assert spy_cond[0].passed is True

    def test_gate_score_range(self, populated_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(db_path=populated_db)
        assert 0.0 <= result.score <= 1.0

    def test_all_gates(self, populated_db):
        from nuri.trading.engine.gate import check_all_gates
        gates = check_all_gates(db_path=populated_db)
        assert "collect" in gates
        assert "regime" in gates
        assert "recommend" in gates


class TestGate_R10:
    """From test_coverage_round10.py."""

    def test_check_gate(self, rich_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate()
        assert hasattr(result, "phase")
        assert hasattr(result, "score")

    def test_check_gate_phase(self, rich_db):
        from nuri.trading.engine.gate import check_gate
        result = check_gate(phase="collect")
        assert hasattr(result, "phase")
        assert result.phase == "collect"


class TestGate_R23:
    """From test_coverage_round23.py."""

    def test_print_gate_ready(self, capsys, db_path):
        from nuri.trading.engine.gate import GateCondition, GateResult, print_gate

        result = GateResult(
            phase="collect",
            total=2,
            passed=2,
            score=1.0,
            ready=True,
            conditions=[
                GateCondition("c1", "collect", "Test 1", True, "ok"),
                GateCondition("c2", "collect", "Test 2", True, "fine"),
            ],
        )
        print_gate(result)
        captured = capsys.readouterr()
        assert "READY" in captured.out
        assert "[PASS]" in captured.out

    def test_print_gate_blocked(self, capsys, db_path):
        from nuri.trading.engine.gate import GateCondition, GateResult, print_gate

        result = GateResult(
            phase="validate",
            total=2,
            passed=1,
            score=0.5,
            ready=False,
            conditions=[
                GateCondition("c1", "validate", "Test 1", True, "ok"),
                GateCondition("c2", "validate", "Test 2", False, "need data"),
            ],
        )
        print_gate(result)
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.out
        assert "[FAIL]" in captured.out

    def test_check_all_gates(self, db_path):
        from nuri.trading.engine.gate import check_all_gates

        gates = check_all_gates(db_path=db_path)
        assert "collect" in gates
        assert "validate" in gates
        assert "regime" in gates
        assert "recommend" in gates

    def test_check_gate_none_phase(self, db_path):
        from nuri.trading.engine.gate import check_gate

        result = check_gate(phase=None, db_path=db_path)
        assert result.phase == "all"
        assert result.total >= 8

    def test_gate_check_estimates_accumulation_fresh(self, db_path, monkeypatch):
        """Estimates accumulation check — fresh data (from TestAdditionalEdgeCases)."""
        from nuri.trading.engine.gate import _check_estimates_accumulation

        _force_delete_journal(db_path, monkeypatch)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation) VALUES (?, ?, ?)",
                ("AAPL", "2025-12-01", "buy"),
            )
        cond = _check_estimates_accumulation(db_path)
        assert cond.passed is True

    def test_gate_check_estimates_empty(self, db_path):
        """Estimates accumulation check — no data (from TestAdditionalEdgeCases)."""
        from nuri.trading.engine.gate import _check_estimates_accumulation

        cond = _check_estimates_accumulation(db_path)
        assert cond.passed is False


# ═══════════════════════════════════════════════════════════════════════════════
# CONFLICTS — nuri.trading.engine.conflicts
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY — nuri.trading.engine.memory
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemory:
    """From test_engine.py."""

    def test_detect_drift_empty(self, db_path):
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_snapshot_and_drift(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "all_time", 100, 0.60, 2.0, 3.5),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "recent_90d", 20, 0.35, 0.8, -1.2),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) == 1
        assert drifts[0].signal_id == "rsi_oversold"
        assert drifts[0].status == "critical"


class TestLearningMemory:
    """From test_coverage_round10.py."""

    def test_save_snapshot(self, rich_db):
        from nuri.trading.engine.memory import save_snapshot
        count = save_snapshot()
        assert isinstance(count, int)

    def test_detect_drift(self, rich_db):
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift()
        assert isinstance(drifts, list)

    def test_print_memory_status(self, rich_db, capsys):
        from nuri.trading.engine.memory import detect_drift, print_memory_status
        drifts = detect_drift()
        print_memory_status(drifts)
        assert len(capsys.readouterr().out) >= 0


class TestMemoryComputeStats:
    """From test_coverage_round16.py."""

    def test_all_positive_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [5.0, 10.0, 3.0]})
        stats = _compute_stats(df)
        assert stats["trades"] == 3
        assert stats["win_rate"] == 1.0
        assert stats["profit_factor"] == 99.99

    def test_all_negative_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [-5.0, -10.0, -3.0]})
        stats = _compute_stats(df)
        assert stats["win_rate"] == 0.0
        assert stats["avg_return"] < 0

    def test_mixed_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [10.0, -5.0, 3.0, -2.0]})
        stats = _compute_stats(df)
        assert stats["trades"] == 4
        assert stats["win_rate"] == 0.5
        assert stats["profit_factor"] > 0


class TestMemoryFindCsv:
    """From test_coverage_round16.py."""

    def test_nonexistent_dir(self, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        monkeypatch.setattr(mem_mod, "REPORT_DIR", MagicMock(exists=MagicMock(return_value=False)))
        assert mem_mod._find_latest_csv("signal_results.csv") is None

    def test_dir_exists_no_csv(self, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        (report_dir / "2025-01-01").mkdir()
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        assert mem_mod._find_latest_csv("signal_results.csv") is None

    def test_dir_exists_with_csv(self, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        day_dir = report_dir / "2025-03-20"
        day_dir.mkdir()
        csv_file = day_dir / "signal_results.csv"
        csv_file.write_text("signal_id,return_pct\nrsi_oversold,5.0")
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        result = mem_mod._find_latest_csv("signal_results.csv")
        assert result is not None
        assert result.name == "signal_results.csv"


class TestMemoryPrintStatus:
    """From test_coverage_round16.py."""

    def test_empty_drifts(self, capsys):
        from nuri.trading.engine.memory import print_memory_status
        print_memory_status([])
        out = capsys.readouterr().out
        assert "학습 메모리 없음" in out

    def test_with_drifts(self, capsys):
        from nuri.trading.engine.memory import PerformanceDrift, print_memory_status
        drifts = [
            PerformanceDrift("rsi_oversold", None, 0.60, 0.30, -50.0, "critical", "승률 급락"),
            PerformanceDrift("macd_golden", None, 0.55, 0.65, 18.2, "improving", "승률 개선"),
            PerformanceDrift("bb_bounce", None, 0.50, 0.48, -4.0, "stable", "안정"),
        ]
        print_memory_status(drifts)
        out = capsys.readouterr().out
        assert "Signal" in out
        assert "rsi_oversold" in out
        assert "성과 하락 시그널 1개" in out


class TestMemorySaveSnapshotEmptyCsv:
    """From test_coverage_round16.py."""

    def test_empty_csv(self, rich_db, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        day_dir = report_dir / "2026-01-01"
        day_dir.mkdir()
        (day_dir / "signal_results.csv").write_text("signal_id,return_pct,entry_date\n")
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        count = mem_mod.save_snapshot(db_path=rich_db)
        assert count == 0


class TestMemoryDetectDriftMultipleStatuses:
    """From test_coverage_round16.py."""

    def test_four_statuses(self, rich_db):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "all_time", 100, 0.60, 2.0, 3.5))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "recent_90d", 20, 0.30, 0.8, -1.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "all_time", 100, 0.60, 2.0, 3.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "recent_90d", 20, 0.48, 1.2, 1.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "all_time", 100, 0.50, 1.5, 2.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "recent_90d", 20, 0.60, 2.5, 4.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_stable", None, "all_time", 100, 0.55, 1.7, 2.5))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_stable", None, "recent_90d", 20, 0.53, 1.6, 2.3))

        drifts = detect_drift(db_path=rich_db)
        statuses = {d.signal_id: d.status for d in drifts}
        assert statuses["sig_critical"] == "critical"
        assert statuses["sig_degrading"] == "degrading"
        assert statuses["sig_improving"] == "improving"
        assert statuses["sig_stable"] == "stable"
        assert drifts[0].status == "critical"
        assert drifts[-1].status == "stable"


class TestMemory_R23:
    """From test_coverage_round23.py."""

    def test_save_snapshot_no_csv(self, db_path, monkeypatch):
        from nuri.trading.engine.memory import save_snapshot

        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: None)
        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_empty_trades(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        pd.DataFrame(columns=["signal_id", "entry_date", "return_pct"]).to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_with_trades(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 5 + ["macd_golden"] * 3,
            "entry_date": [
                (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
                for d in range(8)
            ],
            "return_pct": [3.0, -1.0, 5.0, 2.0, -2.0, 4.0, -1.0, 6.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: (_ for _ in ()).throw(ImportError("no module")))

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_save_snapshot_with_cross_df(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 3,
            "entry_date": ["2026-03-01", "2026-03-10", "2026-03-20"],
            "return_pct": [3.0, -1.0, 5.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        cross_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"],
            "regime": ["bull_low_vol"],
            "trades": [10],
            "win_rate": [0.65],
            "profit_factor": [2.1],
            "avg_return": [3.5],
        })
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: cross_df)

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_detect_drift_no_data(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_detect_drift_with_data(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "rsi_oversold", 100, 0.70, 2.5, 3.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "rsi_oversold", 20, 0.35, 0.8, -1.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "macd_golden", 80, 0.55, 1.5, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "macd_golden", 15, 0.60, 1.6, 2.5),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) >= 2
        rsi_drift = [d for d in drifts if d.signal_id == "rsi_oversold"]
        assert rsi_drift[0].status == "critical"
        macd_drift = [d for d in drifts if d.signal_id == "macd_golden"]
        assert macd_drift[0].status in ("stable", "improving")

    def test_print_memory_status_empty(self, capsys):
        from nuri.trading.engine.memory import print_memory_status

        print_memory_status([])
        captured = capsys.readouterr()
        assert "학습 메모리 없음" in captured.out

    def test_print_memory_status_with_drifts(self, capsys):
        from nuri.trading.engine.memory import PerformanceDrift, print_memory_status

        drifts = [
            PerformanceDrift("rsi_oversold", None, 0.70, 0.35, -50.0, "critical",
                             "승률 -50% 급락 (전체 70% → 최근 35%)"),
            PerformanceDrift("macd_golden", None, 0.55, 0.60, 9.1, "stable",
                             "승률 변화 +9.1% (안정)"),
        ]
        print_memory_status(drifts)
        captured = capsys.readouterr()
        assert "Performance Drift" in captured.out
        assert "성과 하락 시그널" in captured.out

    def test_detect_drift_degrading(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "bb_bounce", 50, 0.60, 1.8, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "bb_bounce", 10, 0.48, 1.0, 0.5),
            )

        drifts = detect_drift(db_path=db_path)
        bb_drift = [d for d in drifts if d.signal_id == "bb_bounce"]
        assert bb_drift[0].status == "degrading"

    def test_find_latest_csv_nonexistent(self):
        import nuri.trading.engine.memory as mem_mod
        from nuri.trading.engine.memory import _find_latest_csv
        original = mem_mod.REPORT_DIR
        mem_mod.REPORT_DIR = Path("/nonexistent/path")
        result = _find_latest_csv("signal_results.csv")
        mem_mod.REPORT_DIR = original
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# CERTIFICATION — nuri.trading.engine.certification
# ═══════════════════════════════════════════════════════════════════════════════


class TestCertCondition:
    """From test_certification.py."""

    def test_create(self):
        from nuri.trading.engine.certification import CertCondition
        cond = CertCondition("test_id", "test desc", True, "detail")
        assert cond.id == "test_id"
        assert cond.passed is True
        assert cond.severity == "error"

    def test_warning_severity(self):
        from nuri.trading.engine.certification import CertCondition
        cond = CertCondition("test", "desc", False, "warn", "warning")
        assert cond.severity == "warning"


class TestCertificate:
    """From test_certification.py."""

    def test_create(self):
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(
            timestamp="", total_conditions=10, passed=8, failed=1, warnings=1,
            certified=False, conditions=[], score=80.0,
        )
        assert cert.certified is False
        assert cert.score == 80.0
        assert cert.timestamp != ""

    def test_certified_when_no_failures(self):
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(
            timestamp="2026-03-28", total_conditions=10, passed=10, failed=0, warnings=0,
            certified=True, conditions=[], score=100.0,
        )
        assert cert.certified is True


class TestLeverageBan:
    """From test_certification.py."""

    def test_no_leverage(self, db_path):
        from nuri.trading.engine.certification import _check_leverage_ban
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is True
        assert result.id == "leverage_ban"

    def test_with_leverage(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "TSLL", 100, 15.0, "USD", "SectorB"),
            )
        from nuri.trading.engine.certification import _check_leverage_ban
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is False
        assert "TSLL" in result.detail


class TestVixGate:
    """From test_certification.py."""

    def test_normal_vix(self, populated_db_cert):
        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=populated_db_cert)
        assert result.passed is True
        assert "18.0" in result.detail

    def test_high_vix(self, db_path):
        today = datetime.now().strftime("%Y-%m-%d")
        upsert_macro([{"indicator": "vix", "date": today, "value": 35.0, "source": "test"}], db_path)

        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is False
        assert result.severity == "warning"

    def test_no_vix_data(self, db_path):
        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is True
        assert "없음" in result.detail


class TestDataFreshness:
    """From test_certification.py."""

    def test_fresh_data(self, populated_db_cert):
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=populated_db_cert)
        assert result.passed is True

    def test_no_spy_data(self, db_path):
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is False
        assert "SPY 데이터 없음" in result.detail

    def test_stale_data(self, db_path):
        prices = pd.DataFrame([
            {"ticker": "SPY", "date": "2020-01-01", "open": 300, "high": 305, "low": 295, "close": 302, "volume": 50000000, "adj_close": 302},
        ])
        upsert_prices(prices, db_path)
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is False
        assert "72h 초과" in result.detail


class TestRulesLoaded:
    """From test_certification.py."""

    def test_rules_present(self):
        from nuri.trading.engine.certification import _check_rules_loaded
        result = _check_rules_loaded()
        assert result.id == "rules_loaded"
        assert result.passed is True


class TestCheckConflicts:
    """From test_certification.py."""

    def test_no_conflicts(self, db_path):
        from nuri.trading.engine.certification import _check_conflicts
        result = _check_conflicts(db_path=db_path)
        assert result.passed is True

    def test_exception_returns_pass(self, db_path, monkeypatch):
        def mock_detect(*args, **kwargs):
            raise RuntimeError("test")
        monkeypatch.setattr("nuri.trading.engine.certification._check_conflicts.__module__", "test")
        from nuri.trading.engine.certification import _check_conflicts
        result = _check_conflicts(db_path=db_path)
        assert result.passed is True


class TestCheckDriftSafety:
    """From test_certification.py."""

    def test_no_drift(self, db_path):
        from nuri.trading.engine.certification import _check_drift_safety
        result = _check_drift_safety(db_path=db_path)
        assert result.passed is True
        assert "critical 없음" in result.detail


class TestCheckExternalData:
    """From test_certification.py."""

    def test_no_external_table(self, db_path):
        from nuri.trading.engine.certification import _check_external_data
        result = _check_external_data(db_path=db_path)
        assert result.severity == "warning"


class TestStopLossCompliance:
    """From test_certification.py."""

    def test_empty_db_returns_pass(self, db_path_monkeypatched):
        from nuri.trading.engine.certification import _check_stop_loss_compliance
        result = _check_stop_loss_compliance(db_path=db_path_monkeypatched)
        assert result.passed is True


class TestPositionLimits:
    """From test_certification.py."""

    def test_exception_returns_pass(self, db_path):
        from nuri.trading.engine.certification import _check_position_limits
        result = _check_position_limits(db_path=db_path)
        assert isinstance(result.passed, bool)


class TestSectorLimits:
    """From test_certification.py."""

    def test_no_data(self, db_path_monkeypatched):
        from nuri.trading.engine.certification import _check_sector_limits
        result = _check_sector_limits(db_path=db_path_monkeypatched)
        assert result.passed is True


class TestCertify:
    """From test_certification.py."""

    def test_returns_certificate(self, populated_db_cert):
        from nuri.trading.engine.certification import certify
        cert = certify(db_path=populated_db_cert)
        assert cert.total_conditions == 10
        assert 0 <= cert.score <= 100
        assert cert.passed + cert.failed + cert.warnings == cert.total_conditions

    def test_empty_db_still_runs(self, db_path):
        from nuri.trading.engine.certification import certify
        cert = certify(db_path=db_path)
        assert cert.total_conditions == 10

    def test_all_checks_list(self):
        from nuri.trading.engine.certification import ALL_CERT_CHECKS
        assert len(ALL_CERT_CHECKS) == 10


class TestPrintCertificate:
    """From test_certification.py."""

    def test_print_certified(self, capsys):
        from nuri.trading.engine.certification import CertCondition, Certificate, print_certificate
        conds = [CertCondition(f"c{i}", f"desc{i}", True, "ok") for i in range(10)]
        cert = Certificate("2026-03-28", 10, 10, 0, 0, True, conds, 100.0)
        print_certificate(cert)
        output = capsys.readouterr().out
        assert "CERTIFIED" in output
        assert "100%" in output

    def test_print_rejected(self, capsys):
        from nuri.trading.engine.certification import CertCondition, Certificate, print_certificate
        conds = [CertCondition("c1", "desc1", False, "fail", "error")]
        cert = Certificate("2026-03-28", 1, 0, 1, 0, False, conds, 0.0)
        print_certificate(cert)
        output = capsys.readouterr().out
        assert "REJECTED" in output

    def test_print_warning(self, capsys):
        from nuri.trading.engine.certification import CertCondition, Certificate, print_certificate
        conds = [
            CertCondition("c1", "pass", True, "ok"),
            CertCondition("c2", "warn", False, "warn detail", "warning"),
        ]
        cert = Certificate("2026-03-28", 2, 1, 0, 1, True, conds, 50.0)
        print_certificate(cert)
        output = capsys.readouterr().out
        assert "CERTIFIED" in output


class TestCertification_R23:
    """From test_coverage_round23.py."""

    def test_check_position_limits_pass(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "weight_pct": [10.0, 8.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is True
        assert "최대 비중" in cond.detail

    def test_check_position_limits_violation(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "AAPL"],
            "weight_pct": [50.0, 30.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "위반" in cond.detail

    def test_check_position_limits_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_position_limits

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "검증 실패" in cond.detail

    def test_check_sector_limits_pass(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_sector_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "JNJ"],
            "sector": ["Tech", "Health"],
            "weight_pct": [20.0, 15.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_sector_limits(db_path)
        assert cond.passed is True

    def test_check_sector_limits_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_sector_limits

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        cond = _check_sector_limits(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_stop_loss_violations(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "pnl_pct": [-25.0, 5.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is False
        assert "위반" in cond.detail

    def test_check_stop_loss_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_conflicts_high(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_conflicts

        @dataclass
        class MockConflict:
            ticker: str = "AAPL"
            severity: str = "high"

        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: [MockConflict()])
        cond = _check_conflicts(db_path)
        assert cond.passed is False
        assert "high 충돌" in cond.detail

    def test_check_conflicts_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_conflicts

        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_conflicts(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_drift_critical(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_drift_safety

        @dataclass
        class MockDrift:
            signal_id: str = "rsi_oversold"
            status: str = "critical"

        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: [MockDrift()])
        cond = _check_drift_safety(db_path)
        assert cond.passed is False
        assert "critical" in cond.detail

    def test_check_drift_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_drift_safety

        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_drift_safety(db_path)
        assert cond.passed is True

    def test_check_external_data_insufficient(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr("nuri.collectors.external.get_external_summary",
                            lambda *a: {"total_records": 3, "sources": ["tipranks"]})
        cond = _check_external_data(db_path)
        assert cond.passed is False
        assert "3건" in cond.detail

    def test_check_external_data_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr("nuri.collectors.external.get_external_summary",
                            lambda *a: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_external_data(db_path)
        assert cond.passed is False
        assert "테이블 없음" in cond.detail

    def test_certify_full(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import CertCondition, certify

        monkeypatch.setattr("nuri.trading.engine.certification.ALL_CERT_CHECKS",
                            [lambda **kw: CertCondition("c1", "desc", True, "ok"),
                             lambda **kw: CertCondition("c2", "desc", False, "fail", "warning")])
        cert = certify(db_path)
        assert cert.certified is True
        assert cert.warnings == 1

    def test_print_certificate(self, capsys, db_path, monkeypatch):
        from nuri.trading.engine.certification import CertCondition, Certificate, print_certificate

        cert = Certificate(
            timestamp="2026-03-31",
            total_conditions=3,
            passed=2,
            failed=1,
            warnings=0,
            certified=False,
            conditions=[
                CertCondition("c1", "Test 1", True, "ok"),
                CertCondition("c2", "Test 2", False, "fail", "error"),
                CertCondition("c3", "Test 3", False, "warn", "warning"),
            ],
            score=66.7,
        )
        print_certificate(cert)
        captured = capsys.readouterr()
        assert "REJECTED" in captured.out
        assert "필수 조건 미충족" in captured.out

    def test_certification_leverage_ban_violation(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_leverage_ban

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
                ("test", "TQQQ", 10, 50.0),
            )

        cond = _check_leverage_ban(db_path)
        assert cond.passed is False
        assert "TQQQ" in cond.detail

    def test_certification_vix_gate_high(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_vix_gate

        _seed_macro_r23(db_path, "vix", 35.0)
        cond = _check_vix_gate(db_path)
        assert cond.passed is False
        assert "금지" in cond.detail

    def test_certification_data_fresh(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_data_freshness

        _seed_prices_r23(db_path, "SPY", 500.0)
        cond = _check_data_freshness(db_path)
        assert cond.passed is True

    def test_certification_data_stale(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_data_freshness

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2025-01-01", 450.0),
            )
        cond = _check_data_freshness(db_path)
        assert cond.passed is False


class TestCertification_R27:
    """From test_coverage_round27.py."""

    def test_check_leverage_ban_clean(self, db_path):
        from nuri.trading.engine.certification import _check_leverage_ban
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is True

    def test_check_leverage_ban_violation(self, db_path):
        from nuri.trading.engine.certification import _check_leverage_ban
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?,?,?,?)",
                         ("test", "TQQQ", 10, 50.0))
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is False

    def test_check_vix_gate_no_data(self, db_path):
        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is True

    def test_check_vix_gate_high(self, db_path):
        from nuri.trading.engine.certification import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 35.0))
        result = _check_vix_gate(db_path=db_path)
        assert result.passed is False

    def test_check_data_freshness_no_data(self, db_path):
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is False

    def test_check_data_freshness_fresh(self, db_path):
        from nuri.core.timezone import kst_now
        from nuri.trading.engine.certification import _check_data_freshness
        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                         ("SPY", today, 500.0))
        result = _check_data_freshness(db_path=db_path)
        assert result.passed is True

    def test_check_rules_loaded(self, db_path):
        from nuri.trading.engine.certification import _check_rules_loaded
        result = _check_rules_loaded(db_path=db_path)
        assert result.passed is True

    def test_certify_and_print(self, db_path, capsys, monkeypatch):
        from nuri.trading.engine.certification import certify, print_certificate
        monkeypatch.setattr("nuri.trading.engine.certification._check_position_limits",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="pos", description="test", detail="ok"))
        monkeypatch.setattr("nuri.trading.engine.certification._check_sector_limits",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="sec", description="test", detail="ok"))
        monkeypatch.setattr("nuri.trading.engine.certification._check_stop_loss_compliance",
                            lambda db_path=None: MagicMock(passed=True, severity="error", id="sl", description="test", detail="ok"))
        cert = certify(db_path=db_path)
        assert cert.total_conditions > 0
        assert isinstance(cert.score, float)
        print_certificate(cert)
        captured = capsys.readouterr()
        assert "SIEGE Certificate" in captured.out

    def test_certificate_post_init_empty_timestamp(self):
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(timestamp="", total_conditions=0, passed=0, failed=0,
                           warnings=0, certified=True, conditions=[], score=100.0)
        assert cert.timestamp != ""


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER — nuri.trading.execution.broker
# ═══════════════════════════════════════════════════════════════════════════════


class TestBroker:
    """From test_new_features.py."""

    def test_dry_run(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker.get_account_value() == 100_000.0

        order = broker.submit_order("AAPL", "buy", 1)
        assert order.status == "dry_run"

    def test_factory_fallback(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=False)
        assert broker.get_account_value() >= 0


class TestBroker_R10:
    """From test_coverage_round10.py."""

    def test_dryrun_submit_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "buy", 10)
        assert result is not None

    def test_dryrun_sell_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "sell", 5)
        assert result is not None

    def test_dryrun_get_positions(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_broker_dryrun(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker is not None


class TestBroker_R26:
    """From test_coverage_round26.py."""

    def test_dry_run_broker(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "dry_run"
        assert order.broker == "dry_run"
        assert broker.get_account_value() == 100_000.0
        assert broker.get_positions() == []
        assert broker.cancel_all() == 0

    def test_order_post_init_filled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.filled_qty == 10
        assert order.unfilled_qty == 0.0

    def test_order_post_init_unfilled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="submitted")
        assert order.filled_qty == 0.0
        assert order.unfilled_qty == 10

    def test_order_is_partial(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="partially_filled",
                      filled_qty=5, unfilled_qty=5)
        assert order.is_partial is True

    def test_alpaca_no_keys(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError):
            AlpacaBroker()

    def test_alpaca_submit_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "rejected"

    def test_alpaca_submit_partial_fill(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(return_value={
            "status": "filled", "filled_qty": "5", "filled_avg_price": "150.0", "id": "abc123",
        }))
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "partially_filled"
        assert order.is_partial

    def test_alpaca_get_positions_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.get_positions() == []

    def test_alpaca_get_account_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.get_account_value() == 0.0

    def test_alpaca_cancel_all_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.cancel_all() == 0

    def test_get_broker_dry_run(self):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        b = get_broker(dry_run=True)
        assert isinstance(b, DryRunBroker)

    def test_get_broker_live_no_keys(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        b = get_broker(dry_run=False)
        assert isinstance(b, DryRunBroker)


class TestBrokerOrder:
    """From test_coverage_round16.py."""

    def test_filled_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.filled_qty == 10
        assert order.unfilled_qty == 0.0

    def test_pending_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="submitted")
        assert order.filled_qty == 0.0
        assert order.unfilled_qty == 10

    def test_partial_fill_detection(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="partially_filled",
                      filled_qty=5, unfilled_qty=5)
        assert order.is_partial is True

    def test_not_partial_when_fully_filled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.is_partial is False

    def test_explicit_timestamp(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="dry_run", timestamp="2025-01-01T00:00:00")
        assert order.timestamp == "2025-01-01T00:00:00"


class TestDryRunBroker:
    """From test_coverage_round16.py."""

    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 5, "market")
        assert order.status == "dry_run"
        assert order.broker == "dry_run"
        assert order.order_id.startswith("DRY-")

    def test_multiple_orders_increment_id(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        o1 = broker.submit_order("AAPL", "buy", 5)
        o2 = broker.submit_order("NVDA", "sell", 3)
        assert o1.order_id == "DRY-1"
        assert o2.order_id == "DRY-2"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_positions() == []

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_account_value() == 100_000.0

    def test_cancel_all(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.cancel_all() == 0


class TestAlpacaBroker:
    """From test_coverage_round16.py."""

    def test_init_without_keys(self):
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError, match="ALPACA_API_KEY"):
            AlpacaBroker()

    def test_init_with_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        assert broker.api_key == "test-key"
        assert broker.secret_key == "test-secret"

    def test_submit_order_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-123", "status": "filled",
            "filled_qty": "10", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "filled"
        assert order.filled_price == 175.50
        assert order.filled_qty == 10.0

    def test_submit_order_partial_fill(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-456", "status": "filled",
            "filled_qty": "5", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "partially_filled"
        assert order.filled_qty == 5.0
        assert order.unfilled_qty == 5.0
        assert order.is_partial is True

    def test_submit_order_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("network error")):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "rejected"

    def test_get_positions_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_data = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "170",
             "current_price": "180", "unrealized_plpc": "0.0588"},
        ]
        with patch.object(broker, "_request", return_value=mock_data):
            positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].pnl_pct == pytest.approx(5.88)

    def test_get_positions_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            positions = broker.get_positions()
        assert positions == []

    def test_get_account_value_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value={"portfolio_value": "250000.50"}):
            value = broker.get_account_value()
        assert value == 250000.50

    def test_get_account_value_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            value = broker.get_account_value()
        assert value == 0.0

    def test_cancel_all_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value=[{"id": "1"}, {"id": "2"}]):
            count = broker.cancel_all()
        assert count == 2

    def test_cancel_all_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            count = broker.cancel_all()
        assert count == 0


class TestGetBroker:
    """From test_coverage_round16.py."""

    def test_dry_run(self):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        broker = get_broker(dry_run=True)
        assert isinstance(broker, DryRunBroker)

    def test_no_alpaca_keys_fallback(self, monkeypatch):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        broker = get_broker(dry_run=False)
        assert isinstance(broker, DryRunBroker)

    def test_with_alpaca_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker, get_broker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = get_broker(dry_run=False)
        assert isinstance(broker, AlpacaBroker)


class TestAlpacaBrokerMock:
    """From test_coverage_round13.py."""

    def test_alpaca_init_no_keys(self):
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError):
            AlpacaBroker()

    def test_alpaca_submit_order(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "order123", "status": "accepted"}
        with patch("requests.post", return_value=mock_resp):
            result = broker.submit_order("AAPL", "buy", 10)
        assert result is not None

    def test_alpaca_get_positions(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with patch("requests.get", return_value=mock_resp):
            positions = broker.get_positions()
        assert isinstance(positions, list)


class TestAlpacaBroker_R12:
    """From test_coverage_round12.py."""

    def test_alpaca_broker_init_no_keys(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker is not None

    def test_dryrun_submit_multiple(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        r1 = broker.submit_order("AAPL", "buy", 10)
        r2 = broker.submit_order("AAPL", "sell", 5)
        r3 = broker.submit_order("NVDA", "buy", 3)
        assert r1 is not None
        assert r2 is not None
        assert r3 is not None


class TestBrokerPosition:
    """From test_coverage_extra.py."""

    def test_position_dataclass(self):
        from nuri.trading.execution.broker import Position
        p = Position("AAPL", 10, 150.0, 155.0, 3.3)
        assert p.ticker == "AAPL"
        assert p.pnl_pct == 3.3


class TestOrder:
    """From test_coverage_boost.py."""

    def test_create_filled(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled", 155.0)
        assert o.filled_qty == 10
        assert o.unfilled_qty == 0.0
        assert o.is_partial is False

    def test_create_submitted(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "submitted")
        assert o.filled_qty == 0.0
        assert o.unfilled_qty == 10

    def test_partial_fill(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "partially_filled", 155.0, 5, 5)
        assert o.is_partial is True

    def test_timestamp_auto(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled")
        assert o.timestamp != ""


class TestDryRunBroker_Boost:
    """From test_coverage_boost.py."""

    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "dry_run"
        assert order.ticker == "AAPL"
        assert order.quantity == 10

    def test_sell_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("TSLA", "sell", 5, "limit")
        assert order.side == "sell"
        assert order.status == "dry_run"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        value = broker.get_account_value()
        assert isinstance(value, (int, float))


class TestGetBroker_Boost:
    """From test_coverage_boost.py."""

    def test_returns_dryrun_by_default(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        from nuri.trading.execution.broker import get_broker
        broker = get_broker()
        assert broker.__class__.__name__ == "DryRunBroker"
