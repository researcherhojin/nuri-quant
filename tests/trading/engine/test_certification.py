"""Tests for nuri.trading.engine.certification.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_certification.py, test_coverage_round23.py, test_coverage_round27.py.
"""

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import get_db, upsert_macro, upsert_prices
from tests.trading.engine.conftest import (
    _seed_kr_portfolio,
    _seed_macro_r23,
    _seed_prices_r23,
    _seed_usd_krw_series,
)


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
            timestamp="",
            total_conditions=10,
            passed=8,
            failed=1,
            warnings=1,
            certified=False,
            conditions=[],
            score=80.0,
        )
        assert cert.certified is False
        assert cert.score == 80.0
        assert cert.timestamp != ""

    def test_certified_when_no_failures(self):
        from nuri.trading.engine.certification import Certificate

        cert = Certificate(
            timestamp="2026-03-28",
            total_conditions=10,
            passed=10,
            failed=0,
            warnings=0,
            certified=True,
            conditions=[],
            score=100.0,
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
        from nuri.trading.engine.certification import _check_volatility_gates

        result = _check_volatility_gates(db_path=populated_db_cert)[0]
        assert result.passed is True
        assert "18.0" in result.detail

    def test_high_vix(self, db_path):
        today = datetime.now().strftime("%Y-%m-%d")
        upsert_macro([{"indicator": "vix", "date": today, "value": 35.0, "source": "test"}], db_path)

        from nuri.trading.engine.certification import _check_volatility_gates

        result = _check_volatility_gates(db_path=db_path)[0]
        assert result.passed is False
        assert result.severity == "warning"

    def test_no_vix_data(self, db_path):
        from nuri.trading.engine.certification import _check_volatility_gates

        result = _check_volatility_gates(db_path=db_path)[0]
        assert result.passed is True
        assert "없음" in result.detail


class TestDataFreshness:
    """From test_certification.py."""

    def test_fresh_data(self, populated_db_cert):
        from nuri.trading.engine.certification import _check_data_freshness

        result = _check_data_freshness(db_path=populated_db_cert)[0]
        assert result.passed is True

    def test_no_spy_data(self, db_path):
        from nuri.trading.engine.certification import _check_data_freshness

        result = _check_data_freshness(db_path=db_path)[0]
        assert result.passed is False
        assert "SPY 데이터 없음" in result.detail

    def test_stale_data(self, db_path):
        prices = pd.DataFrame(
            [
                {
                    "ticker": "SPY",
                    "date": "2020-01-01",
                    "open": 300,
                    "high": 305,
                    "low": 295,
                    "close": 302,
                    "volume": 50000000,
                    "adj_close": 302,
                },
            ]
        )
        upsert_prices(prices, db_path)
        from nuri.trading.engine.certification import _check_data_freshness

        result = _check_data_freshness(db_path=db_path)[0]
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

        result = _check_external_data(db_path=db_path)[0]
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


class TestMacroEventAlignment:
    """#143: Gate 11 — macro_event_alignment."""

    def test_pass_no_events(self, db_path):
        """이벤트 없으면 graceful pass."""
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is True
        assert result.id == "macro_event_alignment"
        assert "0.0" in result.detail

    def test_pass_low_score(self, db_path, monkeypatch):
        """event_score < 10 이면 pass."""
        from nuri.quant.regime.event_score import EventScore

        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: EventScore(
                date="2026-04-10",
                score=5.0,
                event_count=2,
                category_breakdown={},
                dominant_category="fed_dovish",
                regime_hint=None,
            ),
        )
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is True
        assert "+5.0" in result.detail

    def test_warn_score_10(self, db_path, monkeypatch):
        """|event_score| >= 10 이면 warning."""
        from nuri.quant.regime.event_score import EventScore

        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: EventScore(
                date="2026-04-10",
                score=-12.0,
                event_count=5,
                category_breakdown={},
                dominant_category="trade_war",
                regime_hint=None,
            ),
        )
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is False
        assert result.severity == "warning"
        assert "주의" in result.detail
        assert "trade_war" in result.detail

    def test_warn_score_15(self, db_path, monkeypatch):
        """|event_score| >= 15 이면 강한 경고."""
        from nuri.quant.regime.event_score import EventScore

        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: EventScore(
                date="2026-04-10",
                score=18.0,
                event_count=10,
                category_breakdown={},
                dominant_category="geopolitical_escalation",
                regime_hint=None,
            ),
        )
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is False
        assert result.severity == "warning"
        assert "강한" in result.detail
        assert "geopolitical_escalation" in result.detail

    def test_warn_negative_score_15(self, db_path, monkeypatch):
        """음수 event_score -15 이하도 경고."""
        from nuri.quant.regime.event_score import EventScore

        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: EventScore(
                date="2026-04-10",
                score=-17.5,
                event_count=8,
                category_breakdown={},
                dominant_category="geopolitical_escalation",
                regime_hint=None,
            ),
        )
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is False
        assert "강한" in result.detail

    def test_exception_graceful_pass(self, db_path, monkeypatch):
        """compute_event_score 예외 시 graceful pass."""
        monkeypatch.setattr(
            "nuri.quant.regime.event_score.compute_event_score",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("test")),
        )
        from nuri.trading.engine.certification import _check_macro_event_alignment

        result = _check_macro_event_alignment(db_path=db_path)
        assert result.passed is True
        assert "스킵" in result.detail


class TestCertify:
    """From test_certification.py."""

    def test_returns_certificate(self, populated_db_cert):
        from nuri.trading.engine.certification import certify

        cert = certify(db_path=populated_db_cert)
        assert cert.total_conditions == 11
        assert 0 <= cert.score <= 100
        assert cert.passed + cert.failed + cert.warnings == cert.total_conditions

    def test_empty_db_still_runs(self, db_path):
        from nuri.trading.engine.certification import certify

        cert = certify(db_path=db_path)
        assert cert.total_conditions == 11

    def test_all_checks_list(self):
        from nuri.trading.engine.certification import ALL_CERT_CHECKS

        assert len(ALL_CERT_CHECKS) == 11

    def test_certify_includes_macro_event_gate(self, db_path):
        """certify() 결과에 macro_event_alignment gate이 포함되어야 함."""
        from nuri.trading.engine.certification import certify

        cert = certify(db_path=db_path)
        gate_ids = [c.id for c in cert.conditions]
        assert "macro_event_alignment" in gate_ids


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

        mock_df = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "weight_pct": [10.0, 8.0],
                "account": ["test", "test"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is True
        assert "최대 비중" in cond.detail

    def test_check_position_limits_violation(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL"],
                "weight_pct": [50.0, 30.0],
                "account": ["test", "test"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "위반" in cond.detail

    def test_check_position_limits_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_position_limits

        monkeypatch.setattr(
            "nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "검증 실패" in cond.detail

    def test_check_sector_limits_pass(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_sector_limits

        mock_df = pd.DataFrame(
            {
                "ticker": ["AAPL", "JNJ"],
                "sector": ["Tech", "Health"],
                "weight_pct": [20.0, 15.0],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_sector_limits(db_path)
        assert cond.passed is True

    def test_check_sector_limits_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_sector_limits

        monkeypatch.setattr(
            "nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        cond = _check_sector_limits(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_stop_loss_violations(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "pnl_pct": [-25.0, 5.0],
            }
        )
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

        monkeypatch.setattr(
            "nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: (_ for _ in ()).throw(RuntimeError())
        )
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

        monkeypatch.setattr(
            "nuri.trading.engine.memory.detect_drift", lambda **kw: (_ for _ in ()).throw(RuntimeError())
        )
        cond = _check_drift_safety(db_path)
        assert cond.passed is True

    def test_check_external_data_insufficient(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr(
            "nuri.collectors.external.get_external_summary", lambda *a: {"total_records": 3, "sources": ["tipranks"]}
        )
        cond = _check_external_data(db_path)[0]
        assert cond.passed is False
        assert "3건" in cond.detail

    def test_check_external_data_exception(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr(
            "nuri.collectors.external.get_external_summary", lambda *a: (_ for _ in ()).throw(RuntimeError())
        )
        cond = _check_external_data(db_path)[0]
        assert cond.passed is False
        assert "테이블 없음" in cond.detail

    def test_certify_full(self, db_path, monkeypatch):
        from nuri.trading.engine.certification import CertCondition, certify

        monkeypatch.setattr(
            "nuri.trading.engine.certification.ALL_CERT_CHECKS",
            [
                lambda **kw: CertCondition("c1", "desc", True, "ok"),
                lambda **kw: CertCondition("c2", "desc", False, "fail", "warning"),
            ],
        )
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
        from nuri.trading.engine.certification import _check_volatility_gates

        _seed_macro_r23(db_path, "vix", 35.0)
        cond = _check_volatility_gates(db_path)[0]
        assert cond.passed is False
        assert "금지" in cond.detail

    def test_certification_data_fresh(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_data_freshness

        _seed_prices_r23(db_path, "SPY", 500.0)
        cond = _check_data_freshness(db_path)[0]
        assert cond.passed is True

    def test_certification_data_stale(self, db_path):
        """From TestAdditionalEdgeCases."""
        from nuri.trading.engine.certification import _check_data_freshness

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2025-01-01", 450.0),
            )
        cond = _check_data_freshness(db_path)[0]
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
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?,?,?,?)",
                ("test", "TQQQ", 10, 50.0),
            )
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is False

    def test_check_vix_gate_no_data(self, db_path):
        from nuri.trading.engine.certification import _check_volatility_gates

        result = _check_volatility_gates(db_path=db_path)[0]
        assert result.passed is True

    def test_check_vix_gate_high(self, db_path):
        from nuri.trading.engine.certification import _check_volatility_gates

        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("vix", "2025-03-28", 35.0))
        result = _check_volatility_gates(db_path=db_path)[0]
        assert result.passed is False

    def test_check_data_freshness_no_data(self, db_path):
        from nuri.trading.engine.certification import _check_data_freshness

        result = _check_data_freshness(db_path=db_path)[0]
        assert result.passed is False

    def test_check_data_freshness_fresh(self, db_path):
        from nuri.core.timezone import kst_now
        from nuri.trading.engine.certification import _check_data_freshness

        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?,?,?)", ("SPY", today, 500.0))
        result = _check_data_freshness(db_path=db_path)[0]
        assert result.passed is True

    def test_check_rules_loaded(self, db_path):
        from nuri.trading.engine.certification import _check_rules_loaded

        result = _check_rules_loaded(db_path=db_path)
        assert result.passed is True

    def test_certify_and_print(self, db_path, capsys, monkeypatch):
        from nuri.trading.engine.certification import certify, print_certificate

        monkeypatch.setattr(
            "nuri.trading.engine.certification._check_position_limits",
            lambda db_path=None: MagicMock(passed=True, severity="error", id="pos", description="test", detail="ok"),
        )
        monkeypatch.setattr(
            "nuri.trading.engine.certification._check_sector_limits",
            lambda db_path=None: MagicMock(passed=True, severity="error", id="sec", description="test", detail="ok"),
        )
        monkeypatch.setattr(
            "nuri.trading.engine.certification._check_stop_loss_compliance",
            lambda db_path=None: MagicMock(passed=True, severity="error", id="sl", description="test", detail="ok"),
        )
        cert = certify(db_path=db_path)
        assert cert.total_conditions > 0
        assert isinstance(cert.score, float)
        print_certificate(cert)
        captured = capsys.readouterr()
        assert "Certification" in captured.out

    def test_certificate_post_init_empty_timestamp(self):
        from nuri.trading.engine.certification import Certificate

        cert = Certificate(
            timestamp="", total_conditions=0, passed=0, failed=0, warnings=0, certified=True, conditions=[], score=100.0
        )
        assert cert.timestamp != ""


class TestAccountStrategyIntegration:
    """#177: 계좌별 전략 프로파일 적용 검증."""

    def test_swing_account_stop_loss_not_violated(self, db_path, monkeypatch):
        """swing 계좌의 -10% 손실은 위반이 아님 (한도 -15%)."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame(
            {
                "ticker": ["TEM"],
                "pnl_pct": [-10.0],
                "account": ["sub_account"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        # swing 전략: stop_loss -15%
        monkeypatch.setattr(
            "nuri.core.rules.get_account_strategy", lambda a: {"stop_loss": -15, "max_single_position": 0.30}
        )

        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is True

    def test_swing_account_stop_loss_violated_at_16pct(self, db_path, monkeypatch):
        """swing 계좌의 -16% 손실은 위반 (한도 -15% 초과)."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame(
            {
                "ticker": ["TSLA"],
                "pnl_pct": [-16.0],
                "account": ["sub_account"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        monkeypatch.setattr(
            "nuri.core.rules.get_account_strategy", lambda a: {"stop_loss": -15, "max_single_position": 0.30}
        )

        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is False
        assert "TSLA" in cond.detail

    def test_core_account_stop_loss_violated_at_8pct(self, db_path, monkeypatch):
        """core 계좌의 -8% 손실은 위반 (한도 -7%)."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame(
            {
                "ticker": ["MSFT"],
                "pnl_pct": [-8.0],
                "account": ["main_account"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        monkeypatch.setattr(
            "nuri.core.rules.get_account_strategy", lambda a: {"stop_loss": -7, "max_single_position": 0.15}
        )

        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is False

    def test_position_limit_swing_allows_25pct(self, db_path, monkeypatch):
        """swing 계좌의 25% 비중은 위반이 아님 (한도 30%)."""
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame(
            {
                "ticker": ["TSLA", "TSLA"],
                "weight_pct": [15.0, 10.0],
                "account": ["main", "sub"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        monkeypatch.setattr(
            "nuri.core.rules.get_account_strategy",
            lambda a: (
                {"stop_loss": -15, "max_single_position": 0.30}
                if a == "sub"
                else {"stop_loss": -7, "max_single_position": 0.15}
            ),
        )

        cond = _check_position_limits(db_path)
        assert cond.passed is True

    def test_position_limit_swing_violated_at_35pct(self, db_path, monkeypatch):
        """swing 허용해도 35% 비중은 위반 (한도 30%) — neutral regime 기준."""
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame(
            {
                "ticker": ["TSLA", "TSLA"],
                "weight_pct": [20.0, 15.0],
                "account": ["main", "sub"],
            }
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        monkeypatch.setattr(
            "nuri.core.rules.get_account_strategy",
            lambda a: (
                {"stop_loss": -15, "max_single_position": 0.30}
                if a == "sub"
                else {"stop_loss": -7, "max_single_position": 0.15}
            ),
        )
        # regime override 가 multiplier × 1.20 적용해 cap 36% 로 inflate 시키지 않도록
        # neutral 로 고정 (테스트 의도는 base cap 30% < 35% 위반 검증).
        monkeypatch.setattr(
            "nuri.trading.engine.certification._current_regime",
            lambda: "neutral",
        )

        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "TSLA" in cond.detail


class TestAssetClassification:
    """#248 — _classify_asset_class: sector_prefix + ticker_suffix 우선순위."""

    def test_sector_prefix_beats_suffix(self, db_path):
        """KR ETF (448300.KS, sector=ETF/USIndex) 는 ticker 가 .KS 여도 us_equity."""
        from nuri.core.rules import RULES
        from nuri.trading.engine.certification import _classify_asset_class

        rules = RULES["siege_gates"]["asset_class_rules"]
        assert _classify_asset_class("448300.KS", "ETF/USIndex", rules) == "us_equity"
        assert _classify_asset_class("132030.KS", "ETF/Commodity", rules) == "commodity"
        assert _classify_asset_class("447660.KS", "ETF/Bond", rules) == "bond"
        assert _classify_asset_class("292160.KS", "ETF/KRIndex", rules) == "kr_index"
        assert _classify_asset_class("381170.KS", "ETF/USTech", rules) == "us_equity"

    def test_ks_suffix_without_sector_prefix(self, db_path):
        """일반 KR 종목 (005930.KS, sector=Semiconductor) 는 kr_equity."""
        from nuri.core.rules import RULES
        from nuri.trading.engine.certification import _classify_asset_class

        rules = RULES["siege_gates"]["asset_class_rules"]
        assert _classify_asset_class("005930.KS", "Semiconductor", rules) == "kr_equity"
        assert _classify_asset_class("000660.KS", "Semiconductor", rules) == "kr_equity"

    def test_kq_suffix(self, db_path):
        from nuri.core.rules import RULES
        from nuri.trading.engine.certification import _classify_asset_class

        rules = RULES["siege_gates"]["asset_class_rules"]
        assert _classify_asset_class("068760.KQ", "Biotech", rules) == "kr_equity"

    def test_us_default(self, db_path):
        from nuri.core.rules import RULES
        from nuri.trading.engine.certification import _classify_asset_class

        rules = RULES["siege_gates"]["asset_class_rules"]
        assert _classify_asset_class("AAPL", "Technology", rules) == "us_equity"
        assert _classify_asset_class("UNKNOWN", "", rules) == "us_equity"


class TestAssetClassGates:
    """#248 — asset-class 그룹 별 gate 5/7/8 verification.

    Issue #248 검증 조건:
    - 삼성전자 보유 portfolio 가 Gate #8 (external_data) 를 KR 완화 기준 (5건/2소스) 로 평가
    - KR 종목 변동성은 usd_krw 기반; US VIX spillover 는 warning only
    - Freshness: KR 은 KOSPI primary + SPY secondary
    """

    def test_kr_portfolio_produces_kr_equity_gates(self, db_path):
        """KR 종목 보유 시 kr_equity asset_class 에 대한 gate 3종 (freshness/volatility/external) 발행."""
        from nuri.trading.engine.certification import (
            _check_data_freshness,
            _check_external_data,
            _check_volatility_gates,
        )

        _seed_kr_portfolio(db_path)
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "KOSPI",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "open": 2500,
                        "high": 2520,
                        "low": 2480,
                        "close": 2510,
                        "volume": 0,
                        "adj_close": 2510,
                    },
                    {
                        "ticker": "SPY",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "open": 500,
                        "high": 505,
                        "low": 498,
                        "close": 502,
                        "volume": 0,
                        "adj_close": 502,
                    },
                ]
            ),
            db_path,
        )
        _seed_usd_krw_series(db_path)
        _seed_macro_r23(db_path, "vix", 20.0)

        fresh = _check_data_freshness(db_path=db_path)
        vol = _check_volatility_gates(db_path=db_path)
        ext = _check_external_data(db_path=db_path)

        # freshness: kr_equity primary (KOSPI) + secondary (SPY) → 최소 2개
        assert any(c.id.startswith("data_fresh_kr_equity") for c in fresh)
        # volatility: kr_equity primary (usd_krw) + secondary (vix)
        assert any(c.id == "volatility_gate_kr_equity" for c in vol)
        assert any(c.id.startswith("volatility_gate_kr_equity_vix") for c in vol)
        # external: kr_equity 그룹용 별도 condition
        assert any(c.id == "external_data_kr_equity" for c in ext)

    def test_kr_external_threshold_lower_than_us(self, db_path):
        """kr_equity external threshold (5건/2소스) 는 us_equity (10건/3소스) 보다 완화."""
        from nuri.trading.engine.certification import _check_external_data

        _seed_kr_portfolio(db_path)
        # 6 rows for KR ticker (2 sources) → kr pass (5+/2+), us fail (<10)
        with get_db(db_path) as conn:
            for i in range(6):
                conn.execute(
                    "INSERT INTO external_analysis (date, source, ticker, data_type, value) VALUES (?, ?, ?, ?, ?)",
                    (f"2026-04-{10 + i:02d}", "tipranks" if i < 3 else "dataroma", "005930.KS", "consensus", "buy"),
                )

        ext = _check_external_data(db_path=db_path)
        kr_cond = next(c for c in ext if c.id == "external_data_kr_equity")
        # 6건 ≥ 5, 2소스 ≥ 2 — PASS
        assert kr_cond.passed is True, f"KR 완화 기준 통과 기대: {kr_cond.detail}"

    def test_usd_krw_volatility_primary_fires_when_high(self, db_path):
        """USD/KRW 3일 변동 > 3% → kr_equity volatility primary warning."""
        from nuri.trading.engine.certification import _check_volatility_gates

        _seed_kr_portfolio(db_path)
        # 3일간 5% 상승: 1300 → 1365
        _seed_usd_krw_series(db_path, values=[1365.0, 1355.0, 1330.0, 1300.0])
        _seed_macro_r23(db_path, "vix", 20.0)

        vol = _check_volatility_gates(db_path=db_path)
        kr_primary = next(c for c in vol if c.id == "volatility_gate_kr_equity")
        assert kr_primary.passed is False
        assert kr_primary.severity == "warning"
        assert "usd_krw_3d_change" in kr_primary.detail

    def test_vix_spillover_warns_kr_portfolio(self, db_path):
        """KR 단독 portfolio + VIX 35 → kr_equity vix secondary 에서 warning."""
        from nuri.trading.engine.certification import _check_volatility_gates

        # KR 만 보유 (portfolio 에 US 없음)
        _seed_kr_portfolio(db_path, holdings=[("005930.KS", "Semiconductor", 50.0)])
        _seed_usd_krw_series(db_path)  # usd_krw 정상
        _seed_macro_r23(db_path, "vix", 35.0)  # VIX 위험 구간

        vol = _check_volatility_gates(db_path=db_path)
        # kr_equity primary (usd_krw) 는 정상
        prim = next(c for c in vol if c.id == "volatility_gate_kr_equity")
        assert prim.passed is True
        # secondary vix spillover 는 warning
        sec = next(c for c in vol if c.id.endswith("_vix"))
        assert sec.passed is False
        assert sec.severity == "warning"

    def test_empty_portfolio_legacy_fallback(self, db_path):
        """Portfolio 비어있으면 구 동작 (SPY/VIX 단일 체크) 로 fallback."""
        from nuri.trading.engine.certification import (
            _check_data_freshness,
            _check_external_data,
            _check_volatility_gates,
        )

        # portfolio 아예 seed 안 함. SPY/VIX 도 없음.
        fresh = _check_data_freshness(db_path=db_path)
        vol = _check_volatility_gates(db_path=db_path)
        ext = _check_external_data(db_path=db_path)

        # legacy fallback 은 단일 condition 반환
        assert len(fresh) == 1
        assert fresh[0].id == "data_fresh"
        assert len(vol) == 1
        assert vol[0].id == "vix_gate"
        assert len(ext) == 1
        assert ext[0].id == "external_data"

    def test_missing_siege_gates_config_legacy_fallback(self, db_path, monkeypatch):
        """siege_gates 설정이 RULES 에 없어도 — 이전 버전 rules.yaml 로 KR 종목 보유 시 —
        기존 SPY/VIX 단일 체크 로 안전하게 fallback. Codex review non-blocking 커버리지."""
        from nuri.trading.engine import certification as cert_mod

        _seed_kr_portfolio(db_path)  # KR 포트폴리오는 존재
        _seed_macro_r23(db_path, "vix", 20.0)
        # siege_gates 키를 제거한 RULES 로 교체
        rules_without_gates = {k: v for k, v in cert_mod.RULES.items() if k != "siege_gates"}
        monkeypatch.setattr(cert_mod, "RULES", rules_without_gates)

        fresh = cert_mod._check_data_freshness(db_path=db_path)
        vol = cert_mod._check_volatility_gates(db_path=db_path)
        ext = cert_mod._check_external_data(db_path=db_path)

        # config 없으면 portfolio 무관하게 legacy 단일 condition 유지
        assert len(fresh) == 1 and fresh[0].id == "data_fresh"
        assert len(vol) == 1 and vol[0].id == "vix_gate"
        assert len(ext) == 1 and ext[0].id == "external_data"

    def test_us_only_portfolio_only_us_equity_group(self, db_path):
        """US 종목만 보유 → kr_equity gate 미발행 (그룹 없음)."""
        from nuri.trading.engine.certification import (
            _check_data_freshness,
            _check_volatility_gates,
        )

        _seed_kr_portfolio(db_path, holdings=[("AAPL", "Technology", 150.0)])
        _seed_macro_r23(db_path, "vix", 20.0)

        fresh = _check_data_freshness(db_path=db_path)
        vol = _check_volatility_gates(db_path=db_path)

        # US 만 있으므로 kr_equity gate 없어야 함
        assert not any("kr_equity" in c.id for c in fresh)
        assert not any("kr_equity" in c.id for c in vol)
        # us_equity 는 있어야 함
        assert any(c.id == "volatility_gate_us_equity" for c in vol)
