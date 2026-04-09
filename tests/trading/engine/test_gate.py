"""Tests for nuri.trading.engine.gate.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_engine.py, test_coverage_round10.py, test_coverage_round23.py.
"""
from nuri.core.db import get_db


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
