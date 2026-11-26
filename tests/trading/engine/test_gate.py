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


class TestSignalScorecardCheckIsHermetic:
    """`_check_signal_scorecard` 는 레포의 `data/reports/` 를 본다 — 테스트가 실제 레포를 읽으면 결과가
    기기마다 달라진다 (CI 는 폴더가 없어 한 분기만, 리포트가 있는 개발 기기는 다른 분기만 밟았다:
    2026-10-27 커버리지 실측). 모듈의 `__file__` 을 임시 트리로 돌려 세 경우를 고정한다."""

    @staticmethod
    def _check(tmp_path, monkeypatch):
        import nuri.trading.engine.gate as gate

        fake = tmp_path / "repo" / "nuri" / "trading" / "engine" / "gate.py"
        monkeypatch.setattr(gate, "__file__", str(fake))
        return gate._check_signal_scorecard(), tmp_path / "repo" / "data" / "reports"

    def test_missing_reports_dir_fails(self, tmp_path, monkeypatch):
        cond, reports = self._check(tmp_path, monkeypatch)
        assert not reports.exists()
        assert cond.passed is False

    def test_reports_without_a_scorecard_fail(self, tmp_path, monkeypatch):
        import nuri.trading.engine.gate as gate

        _, reports = self._check(tmp_path, monkeypatch)
        (reports / "2026-10-01").mkdir(parents=True)
        (reports / "2026-10-02").mkdir()
        assert gate._check_signal_scorecard().passed is False

    def test_any_dated_dir_with_a_scorecard_passes(self, tmp_path, monkeypatch):
        import nuri.trading.engine.gate as gate

        _, reports = self._check(tmp_path, monkeypatch)
        (reports / "2026-10-01").mkdir(parents=True)
        (reports / "2026-10-01" / "signal_scorecard.csv").write_text("x")
        (reports / "2026-10-02").mkdir()
        assert gate._check_signal_scorecard().passed is True


class TestCrossPhaseRequiredChecks:
    """교차 단계 필수 조건이 누락되거나 공허참(all([]))으로 통과하지 않도록 검증."""

    @staticmethod
    def _isolate_reports(tmp_path, monkeypatch, *, with_scorecard: bool = False):
        import nuri.trading.engine.gate as gate

        fake = tmp_path / "repo" / "nuri" / "trading" / "engine" / "gate.py"
        monkeypatch.setattr(gate, "__file__", str(fake))
        if with_scorecard:
            report_dir = tmp_path / "repo" / "data" / "reports" / "2026-10-01"
            report_dir.mkdir(parents=True)
            (report_dir / "signal_scorecard.csv").write_text("x")

    def test_recommend_empty_db_is_blocked_not_vacuous_pass(self, db_path, tmp_path, monkeypatch):
        from nuri.trading.engine.gate import REQUIRED_BY_PHASE, check_gate

        self._isolate_reports(tmp_path, monkeypatch, with_scorecard=False)
        result = check_gate("recommend", db_path=db_path)

        assert result.total == len(REQUIRED_BY_PHASE["recommend"])
        assert result.total > 0
        assert result.passed == 0
        assert result.ready is False
        assert {c.id for c in result.conditions} == REQUIRED_BY_PHASE["recommend"]

    def test_validate_evaluates_prices_data_and_fails_on_empty_prices(self, db_path, tmp_path, monkeypatch):
        from nuri.trading.engine.gate import check_gate

        self._isolate_reports(tmp_path, monkeypatch, with_scorecard=True)
        result = check_gate("validate", db_path=db_path)
        by_id = {c.id: c for c in result.conditions}

        assert "prices_data" in by_id
        assert by_id["prices_data"].passed is False
        assert by_id["signal_scorecard"].passed is True
        assert result.ready is False

    def test_regime_evaluates_prices_data_and_fails_on_empty_or_insufficient_prices(self, db_path, populated_db):
        from nuri.trading.engine.gate import check_gate

        empty_res = check_gate("regime", db_path=db_path)
        empty_by_id = {c.id: c for c in empty_res.conditions}
        assert "prices_data" in empty_by_id
        assert empty_by_id["prices_data"].passed is False
        assert empty_res.ready is False

        # populated_db 는 SPY 300일은 통과하지만 prices_data(1000건+, 5종목+)는 미달
        partial_res = check_gate("regime", db_path=populated_db)
        partial_by_id = {c.id: c for c in partial_res.conditions}
        assert partial_by_id["spy_data"].passed is True
        assert partial_by_id["prices_data"].passed is False
        assert partial_res.ready is False

    def test_all_required_checks_passing_yields_ready(self, rich_db, tmp_path, monkeypatch):
        from nuri.trading.engine.gate import REQUIRED_BY_PHASE, check_gate

        self._isolate_reports(tmp_path, monkeypatch, with_scorecard=True)
        for phase in ("collect", "validate", "regime", "recommend"):
            result = check_gate(phase, db_path=rich_db)
            assert result.total > 0, phase
            assert REQUIRED_BY_PHASE[phase] <= {c.id for c in result.conditions}, phase
            assert result.ready is True, phase

    def test_unregistered_required_check_never_vacuously_passes(self, rich_db, tmp_path, monkeypatch):
        import nuri.trading.engine.gate as gate

        self._isolate_reports(tmp_path, monkeypatch, with_scorecard=True)
        monkeypatch.setitem(gate.REQUIRED_BY_PHASE, "recommend", {"nonexistent_check"})
        result = gate.check_gate("recommend", db_path=rich_db)

        assert result.total == 0
        assert result.ready is False
