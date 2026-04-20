"""E4-0a — SIEGE certification persistence regression tests.

certify() 가 certifications 테이블에 실행 기록을 남기는지 검증. 이전에는 엔진이
return-only 였어서 "지난 30일 SIEGE 가 몇 번 REJECTED 였나" 같은 질문에 답이
불가능했음. 이 테스트 군이 persist wiring 을 lock-in 한다.

중요 invariant:
- persist=True (default) → row 1개 생성
- persist=False (test opt-out) → row 0개
- Persist 실패는 non-fatal — cert 는 정상 반환 (API caller 안전)
- regime / portfolio_hash / caller 가 row 에 함께 기록됨
"""

import json
from unittest.mock import patch

import pytest

from nuri.core.db import query
from nuri.trading.engine.certification import (
    CertCondition,
    Certificate,
    _compute_portfolio_hash,
    _persist_certification,
    certify,
)


class TestCertifyPersistDefault:
    """certify() 는 default 로 persist 한다 (opt-in 실수 방지)."""

    def test_certify_persists_row(self, populated_db_cert):
        """certify() 호출 → certifications 테이블에 1 row."""
        certify(db_path=populated_db_cert, caller="test")
        rows = query("SELECT * FROM certifications", db_path=populated_db_cert)
        assert len(rows) == 1

    def test_certify_records_caller(self, populated_db_cert):
        """caller 태그가 row 에 기록."""
        certify(db_path=populated_db_cert, caller="test:caller:example")
        rows = query("SELECT caller FROM certifications", db_path=populated_db_cert)
        assert rows[0]["caller"] == "test:caller:example"

    def test_multiple_certify_calls_accumulate(self, populated_db_cert):
        """2회 certify → 2 rows (dedup 없음, 각 실행은 distinct moment)."""
        certify(db_path=populated_db_cert, caller="test")
        certify(db_path=populated_db_cert, caller="test")
        rows = query("SELECT COUNT(*) AS c FROM certifications", db_path=populated_db_cert)
        assert rows[0]["c"] == 2


class TestCertifyPersistOptOut:
    """persist=False 는 read-only certification (테스트 격리, dry-run verify)."""

    def test_persist_false_skips_insert(self, populated_db_cert):
        """persist=False → row 0 (cert 객체는 그대로 반환)."""
        cert = certify(db_path=populated_db_cert, persist=False)
        rows = query("SELECT COUNT(*) AS c FROM certifications", db_path=populated_db_cert)
        assert rows[0]["c"] == 0
        # cert 자체는 정상 생성
        assert isinstance(cert, Certificate)
        assert cert.total_conditions > 0


class TestCertifyPersistResilience:
    """Persist 실패는 certify() 정상 반환을 깨지 않는다 (API caller 안전)."""

    def test_persist_failure_is_non_fatal(self, populated_db_cert):
        """insert_certification 이 raise 해도 cert 반환은 정상."""
        with patch(
            "nuri.trading.engine.certification.insert_certification",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            # raise 하지 않아야 함
            cert = certify(db_path=populated_db_cert, caller="test")
        assert isinstance(cert, Certificate)
        # DB 에는 0 row (persist 가 fail 했으므로)
        rows = query("SELECT COUNT(*) AS c FROM certifications", db_path=populated_db_cert)
        assert rows[0]["c"] == 0


class TestPersistCaptures:
    """Persist row 가 필수 context (conditions / regime / hash) 를 보존한다."""

    def test_conditions_json_roundtrip(self, populated_db_cert):
        """conditions_json 이 유효한 JSON 이며 list of CertCondition shape."""
        certify(db_path=populated_db_cert, caller="test")
        rows = query("SELECT conditions_json FROM certifications", db_path=populated_db_cert)
        payload = json.loads(rows[0]["conditions_json"])
        assert isinstance(payload, list)
        assert len(payload) > 0
        # 각 entry 가 CertCondition 필드 포함
        first = payload[0]
        assert "id" in first
        assert "passed" in first
        assert "severity" in first

    def test_portfolio_hash_stable_for_same_snapshot(self, populated_db_cert):
        """동일 portfolio 상태에서 2회 호출 → portfolio_hash 같음."""
        certify(db_path=populated_db_cert, caller="test")
        certify(db_path=populated_db_cert, caller="test")
        rows = query(
            "SELECT portfolio_hash FROM certifications ORDER BY id",
            db_path=populated_db_cert,
        )
        assert rows[0]["portfolio_hash"] is not None
        assert rows[0]["portfolio_hash"] == rows[1]["portfolio_hash"]

    def test_portfolio_hash_differs_after_mutation(self, populated_db_cert):
        """Portfolio 가 바뀌면 hash 도 바뀐다 (qty 변경)."""
        from nuri.core.db import get_db

        certify(db_path=populated_db_cert, caller="test")
        with get_db(populated_db_cert) as conn:
            conn.execute("UPDATE portfolio SET quantity = quantity + 100 WHERE ticker = 'AAPL'")
        certify(db_path=populated_db_cert, caller="test")

        rows = query(
            "SELECT portfolio_hash FROM certifications ORDER BY id",
            db_path=populated_db_cert,
        )
        assert rows[0]["portfolio_hash"] != rows[1]["portfolio_hash"]


class TestComputePortfolioHash:
    """_compute_portfolio_hash helper invariants."""

    def test_empty_portfolio_returns_none(self, db_path):
        """빈 portfolio → None (§2.4 empty ≠ error, 의미있는 구분)."""
        assert _compute_portfolio_hash(db_path=db_path) is None

    def test_deterministic(self, populated_db_cert):
        """같은 상태에서 2번 호출 → 같은 hash."""
        h1 = _compute_portfolio_hash(db_path=populated_db_cert)
        h2 = _compute_portfolio_hash(db_path=populated_db_cert)
        assert h1 == h2
        assert isinstance(h1, str)
        assert len(h1) == 64  # sha256 hex


class TestPersistCertificationHelper:
    """_persist_certification 을 직접 호출하는 경로 (caller path 재사용 용)."""

    def test_direct_call_inserts_row(self, db_path):
        """_persist_certification 직접 호출 → row 1개 생성."""
        cert = Certificate(
            timestamp="2026-04-20T10:00:00+09:00",
            total_conditions=11,
            passed=10,
            failed=0,
            warnings=1,
            certified=True,
            conditions=[
                CertCondition(
                    id="test_gate",
                    description="test",
                    passed=True,
                    detail="ok",
                    severity="error",
                )
            ],
            score=90.9,
        )
        _persist_certification(cert, db_path=db_path, caller="direct")
        rows = query("SELECT caller, certified FROM certifications", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["caller"] == "direct"
        assert rows[0]["certified"] == 1


class TestSchemaMigrationIdempotent:
    """init_db 재실행이 certifications 스키마를 깨지 않는다 (E3-3c pattern)."""

    def test_rerun_init_preserves_rows(self, populated_db_cert):
        """init_db 재호출 → 기존 row 유지, 스키마 동일."""
        from nuri.core.db import init_db

        certify(db_path=populated_db_cert, caller="test")
        before = query("SELECT COUNT(*) AS c FROM certifications", db_path=populated_db_cert)[0]["c"]

        init_db(populated_db_cert)

        after = query("SELECT COUNT(*) AS c FROM certifications", db_path=populated_db_cert)[0]["c"]
        assert before == after == 1


@pytest.fixture
def db_path(tmp_path):
    """TestComputePortfolioHash 전용 empty DB."""
    from nuri.core.db import init_db

    path = tmp_path / "test.db"
    init_db(path)
    return path
