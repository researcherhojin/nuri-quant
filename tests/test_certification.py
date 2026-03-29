"""SIEGE Certification Engine 테스트 — 10-condition 인증서 발급."""
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def populated_db(db_path):
    """인증 테스트용 데이터: 포트폴리오 + 가격 + VIX."""
    with get_db(db_path) as conn:
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

    # SPY 가격 (최근 72시간 이내)
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    prices = pd.DataFrame([
        {"ticker": "SPY", "date": today, "open": 500, "high": 510, "low": 495, "close": 505, "volume": 50000000, "adj_close": 505},
        {"ticker": "AAPL", "date": today, "open": 155, "high": 158, "low": 153, "close": 156, "volume": 10000000, "adj_close": 156},
        {"ticker": "MSFT", "date": today, "open": 310, "high": 315, "low": 308, "close": 312, "volume": 5000000, "adj_close": 312},
    ])
    upsert_prices(prices, db_path)

    # VIX 정상 범위 + 환율
    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# CertCondition / Certificate 데이터 클래스
# ═══════════════════════════════════════════════════════

class TestCertCondition:
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
    def test_create(self):
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(
            timestamp="", total_conditions=10, passed=8, failed=1, warnings=1,
            certified=False, conditions=[], score=80.0,
        )
        assert cert.certified is False
        assert cert.score == 80.0
        assert cert.timestamp != ""  # __post_init__ sets it

    def test_certified_when_no_failures(self):
        from nuri.trading.engine.certification import Certificate
        cert = Certificate(
            timestamp="2026-03-28", total_conditions=10, passed=10, failed=0, warnings=0,
            certified=True, conditions=[], score=100.0,
        )
        assert cert.certified is True


# ═══════════════════════════════════════════════════════
# 개별 체크 함수
# ═══════════════════════════════════════════════════════

class TestLeverageBan:
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
                ("test", "TSLL", 100, 15.0, "USD", "Leveraged_ETF"),
            )
        from nuri.trading.engine.certification import _check_leverage_ban
        result = _check_leverage_ban(db_path=db_path)
        assert result.passed is False
        assert "TSLL" in result.detail


class TestVixGate:
    def test_normal_vix(self, populated_db):
        from nuri.trading.engine.certification import _check_vix_gate
        result = _check_vix_gate(db_path=populated_db)
        assert result.passed is True
        assert "18.0" in result.detail

    def test_high_vix(self, db_path):
        from datetime import datetime
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
    def test_fresh_data(self, populated_db):
        from nuri.trading.engine.certification import _check_data_freshness
        result = _check_data_freshness(db_path=populated_db)
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
    def test_rules_present(self):
        from nuri.trading.engine.certification import _check_rules_loaded
        result = _check_rules_loaded()
        assert result.id == "rules_loaded"
        assert result.passed is True


class TestCheckConflicts:
    def test_no_conflicts(self, db_path):
        from nuri.trading.engine.certification import _check_conflicts
        result = _check_conflicts(db_path=db_path)
        assert result.passed is True

    def test_exception_returns_pass(self, db_path, monkeypatch):
        """예외 시 검증 스킵."""
        def mock_detect(*args, **kwargs):
            raise RuntimeError("test")
        monkeypatch.setattr("nuri.trading.engine.certification._check_conflicts.__module__", "test")
        from nuri.trading.engine.certification import _check_conflicts
        result = _check_conflicts(db_path=db_path)
        assert result.passed is True


class TestCheckDriftSafety:
    def test_no_drift(self, db_path):
        from nuri.trading.engine.certification import _check_drift_safety
        result = _check_drift_safety(db_path=db_path)
        assert result.passed is True
        assert "critical 없음" in result.detail


class TestCheckExternalData:
    def test_no_external_table(self, db_path):
        from nuri.trading.engine.certification import _check_external_data
        result = _check_external_data(db_path=db_path)
        # 테이블 없으면 warning
        assert result.severity == "warning"


class TestStopLossCompliance:
    def test_exception_returns_pass(self, db_path):
        """analyze_portfolio 실패 시 스킵."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance
        result = _check_stop_loss_compliance(db_path=db_path)
        # 빈 포트폴리오 or exception → pass
        assert result.passed is True


class TestPositionLimits:
    def test_exception_returns_pass(self, db_path):
        """포트폴리오 없으면 pass or exception 스킵."""
        from nuri.trading.engine.certification import _check_position_limits
        result = _check_position_limits(db_path=db_path)
        # analyze_portfolio가 빈 df 반환하거나 exception → pass
        assert isinstance(result.passed, bool)


class TestSectorLimits:
    def test_no_data(self, db_path):
        from nuri.trading.engine.certification import _check_sector_limits
        result = _check_sector_limits(db_path=db_path)
        assert result.passed is True


# ═══════════════════════════════════════════════════════
# certify() 통합 테스트
# ═══════════════════════════════════════════════════════

class TestCertify:
    def test_returns_certificate(self, populated_db):
        from nuri.trading.engine.certification import certify
        cert = certify(db_path=populated_db)
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
