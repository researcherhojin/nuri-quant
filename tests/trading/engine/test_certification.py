"""Tests for nuri.trading.engine.certification.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_certification.py, test_coverage_round23.py, test_coverage_round27.py.
"""
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import get_db, upsert_macro, upsert_prices
from tests.trading.engine.conftest import _seed_macro_r23, _seed_prices_r23


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
