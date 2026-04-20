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


class TestCertifyPersistFailureLoudDefault:
    """codex R1 P1 — engine default 는 loud. Silent swallow 는 API caller opt-in.

    이유: audit layer 가 schema drift / DB corruption 에 조용히 죽으면 E4-0a
    의 instrumentation 목적이 무너짐. CLI / scheduler / remediation 은 loud 해야
    실패가 바로 surface.
    """

    def test_default_raises_on_persist_error(self, populated_db_cert):
        """insert_certification 이 raise → certify() 도 raise (engine default loud)."""
        with patch(
            "nuri.trading.engine.certification.insert_certification",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated DB failure"):
                certify(db_path=populated_db_cert, caller="test")

    def test_swallow_opt_in_returns_cert(self, populated_db_cert):
        """swallow_persist_errors=True → API-style silent fail, cert 정상 반환."""
        with patch(
            "nuri.trading.engine.certification.insert_certification",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            # swallow opt-in → raise 하지 않음
            cert = certify(
                db_path=populated_db_cert,
                caller="test",
                swallow_persist_errors=True,
            )
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

    def test_sqlite_operational_error_returns_none_with_warning(self, db_path, caplog):
        """codex R1 #5 — DB-specific 실패만 swallow (locked DB / missing table).

        R4: hash 가 자체 DB read 안 하고 _read_portfolio_raw 에 위임 → warning 은
        `portfolio_raw DB read 실패` 로 발생 (rows=None 경로 통과 시).
        """
        import sqlite3
        with patch(
            "nuri.trading.engine.certification.query",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            with caplog.at_level("WARNING"):
                result = _compute_portfolio_hash(db_path=db_path)
        assert result is None
        # R4: log 는 _read_portfolio_raw 에서 발생 (hash 는 단순 파생)
        assert any("portfolio_raw DB read 실패" in r.message for r in caplog.records)

    def test_programmer_error_propagates(self, db_path):
        """codex R1 #5 — broad Exception 은 swallow 금지 (programmer error 차단)."""
        with patch(
            "nuri.trading.engine.certification.query",
            side_effect=TypeError("programmer bug: bad argument"),
        ):
            with pytest.raises(TypeError, match="programmer bug"):
                _compute_portfolio_hash(db_path=db_path)

    def test_hash_derived_from_rows_not_db_when_given(self, db_path):
        """R4 single-source-of-truth — rows 인자 주어지면 DB read 안 함."""
        rows = [
            {"account": "a", "ticker": "AAPL", "quantity": 10, "avg_price": 150.0, "sector": "Tech"},
        ]
        with patch("nuri.trading.engine.certification.query") as mock_query:
            h = _compute_portfolio_hash(rows=rows)
        assert h is not None
        assert len(h) == 64
        assert mock_query.call_count == 0  # rows 제공 시 DB 호출 안 함

    def test_hash_changes_on_sector_only_mutation(self, db_path):
        """R5 codex Low — sector 변경도 hash 변경 trigger (audit fingerprint 완전성).

        asset_class_grouping 이 sector 기반이라 sector-only 변경도 certification
        outcome 을 바꿈. hash 는 이 axis 에서도 identity 를 제공해야 함.
        """
        rows_a = [
            {"account": "a", "ticker": "AAPL", "quantity": 10, "avg_price": 150.0, "sector": "Technology"},
        ]
        rows_b = [
            {"account": "a", "ticker": "AAPL", "quantity": 10, "avg_price": 150.0, "sector": "Communication"},
        ]
        h_a = _compute_portfolio_hash(rows=rows_a)
        h_b = _compute_portfolio_hash(rows=rows_b)
        assert h_a != h_b


class TestSnapshotInvariant:
    """codex R2 P2 full rigor — snapshot 은 certify() 시작 시 1회 capture,
    모든 gate 가 같은 state 를 본다. Audit row metadata 와 gate eval state 가
    identically 일치 (race 없음).

    Mechanism: ContextVar (`_CERT_SNAPSHOT`) 에 snapshot 설정 → `_current_regime`
    + `_snapshot_portfolio` 이 ContextVar 우선 참조. certify() 종료 시 reset.
    """

    def test_snapshot_passed_to_persist_as_kwarg(self, populated_db_cert):
        """_persist_certification 는 snapshot dataclass 을 kwarg 로 받음 (재조회 없음)."""
        from nuri.trading.engine.certification import CertSnapshot

        with patch(
            "nuri.trading.engine.certification._persist_certification"
        ) as mock_persist:
            certify(db_path=populated_db_cert, caller="test")
            assert mock_persist.called
            call = mock_persist.call_args
            assert "snapshot" in call.kwargs
            assert isinstance(call.kwargs["snapshot"], CertSnapshot)

    def test_hash_computed_once_in_snapshot(self, populated_db_cert):
        """`_compute_portfolio_hash` 는 certify() 당 1회 호출 (snapshot capture 시).
        Persist 단계에서 재호출 금지."""
        with patch(
            "nuri.trading.engine.certification._compute_portfolio_hash",
            return_value="mocked_hash_abc",
        ) as mock_hash:
            certify(db_path=populated_db_cert, caller="test")
            assert mock_hash.call_count == 1

        rows = query("SELECT portfolio_hash FROM certifications", db_path=populated_db_cert)
        assert rows[0]["portfolio_hash"] == "mocked_hash_abc"

    def test_regime_used_in_gate_matches_persisted(self, populated_db_cert):
        """codex R2 P2 핵심 — gate 가 사용한 regime == persist 된 regime.

        `_classify_regime_fresh` 를 mock 해서 cert 시작 시 고정값 return. 이후
        `_check_position_limits` 내부의 `_current_regime()` 호출이 그 값을 반환하는지
        + persist 된 row 의 regime 도 동일한지 검증.
        """
        with patch(
            "nuri.trading.engine.certification._classify_regime_fresh",
            return_value="bull_low_vol",
        ):
            certify(db_path=populated_db_cert, caller="test")

        rows = query(
            "SELECT regime FROM certifications WHERE caller='test'",
            db_path=populated_db_cert,
        )
        # Persist 된 regime 이 classify 결과와 일치 (snapshot 을 통과했으므로)
        assert rows[0]["regime"] == "bull_low_vol"

    def test_classify_regime_fresh_called_once_per_certify(self, populated_db_cert):
        """`_classify_regime_fresh` 는 certify() 당 1회만 호출 (ContextVar 우선 참조
        invariant 검증). gate 가 내부에서 `_current_regime()` 여러 번 호출해도 fresh
        DB read 는 1회만 발생.
        """
        with patch(
            "nuri.trading.engine.certification._classify_regime_fresh",
            return_value="bull_low_vol",
        ) as mock_fresh:
            certify(db_path=populated_db_cert, caller="test")
            # gate 가 `_current_regime` 을 N 번 호출해도 fresh classify 는 딱 1회
            assert mock_fresh.call_count == 1

    def test_snapshot_contextvar_reset_after_certify(self, populated_db_cert):
        """Finally clause 가 ContextVar 를 reset — certify() 밖에서 `_current_regime`
        호출 시 fresh path 로 돌아가야 함 (nested/parallel certify 안전)."""
        from nuri.trading.engine.certification import _CERT_SNAPSHOT, _current_regime

        assert _CERT_SNAPSHOT.get() is None  # pre-condition
        certify(db_path=populated_db_cert, caller="test")
        assert _CERT_SNAPSHOT.get() is None  # reset 되었어야 함

        # Fresh path 작동 확인 (mock 없이 실제 호출)
        with patch(
            "nuri.trading.engine.certification._classify_regime_fresh",
            return_value="bull_low_vol",
        ) as mock_fresh:
            result = _current_regime()
            assert result == "bull_low_vol"
            assert mock_fresh.called  # Fresh path 로 감


class TestAnalyzePortfolioFailurePreservesGateSemantics:
    """codex R3 High regression lock — analyze_portfolio() 실패가 silent PASS 로
    귀결되면 안 된다.

    Snapshot capture 단계에서 empty DF fallback 하면 `_check_position_limits` 가
    "포트폴리오 비어있음" 으로 PASS 처리 (R2 fix 의 regression). Fix: exception 저장
    + re-raise → 각 gate 의 try/except 가 기존 semantic 그대로 (position_limit 은
    error-fail, sector_limit/stop_loss 는 warning-skip).
    """

    def test_position_limit_fails_when_analyze_portfolio_raises(self, populated_db_cert):
        """analyze_portfolio 실패 시 position_limit 은 passed=False/error (기존 동작)."""
        with patch(
            "nuri.analysis.portfolio.analyze_portfolio",
            side_effect=RuntimeError("FX rate missing"),
        ):
            cert = certify(db_path=populated_db_cert, caller="test")

        position_limit = next((c for c in cert.conditions if c.id == "position_limit"), None)
        assert position_limit is not None
        assert position_limit.passed is False
        assert "검증 실패" in position_limit.detail
        assert "FX rate missing" in position_limit.detail

    def test_sector_limit_skipped_when_analyze_portfolio_raises(self, populated_db_cert):
        """sector_limit 은 기존 semantic — passed=True/warning 'skip'."""
        with patch(
            "nuri.analysis.portfolio.analyze_portfolio",
            side_effect=RuntimeError("FX rate missing"),
        ):
            cert = certify(db_path=populated_db_cert, caller="test")

        sector_limit = next((c for c in cert.conditions if c.id == "sector_limit"), None)
        assert sector_limit is not None
        assert sector_limit.passed is True
        assert "검증 스킵" in sector_limit.detail

    def test_snapshot_stores_exception_not_empty_df(self, populated_db_cert):
        """_capture_snapshot 이 analyze_portfolio 예외를 CertSnapshot.portfolio_error 에 저장."""
        from nuri.trading.engine.certification import _capture_snapshot

        with patch(
            "nuri.analysis.portfolio.analyze_portfolio",
            side_effect=RuntimeError("FX rate missing"),
        ):
            snap = _capture_snapshot(db_path=populated_db_cert)

        assert snap.portfolio_df is None
        assert snap.portfolio_error is not None
        assert isinstance(snap.portfolio_error, RuntimeError)
        assert "FX rate missing" in str(snap.portfolio_error)


class TestStopLossSkipOnAnalyzeFailure:
    """codex R4 low — R3 claim covers stop_loss semantic but test was missing.

    analyze_portfolio() 실패 시 stop_loss_compliance 는 "검증 스킵" warning 으로
    기존 semantic 유지 (position_limit 은 error-fail, sector/stop_loss 는 warning-skip).
    """

    def test_stop_loss_skipped_when_analyze_portfolio_raises(self, populated_db_cert):
        with patch(
            "nuri.analysis.portfolio.analyze_portfolio",
            side_effect=RuntimeError("FX rate missing"),
        ):
            cert = certify(db_path=populated_db_cert, caller="test")

        stop_loss = next((c for c in cert.conditions if c.id == "stop_loss"), None)
        assert stop_loss is not None
        assert stop_loss.passed is True
        assert "검증 스킵" in stop_loss.detail


class TestRawPortfolioSnapshot:
    """codex R4 — leverage_ban + asset_class_grouping + hash 가 모두 같은 raw
    read 에서 파생. Portfolio 가 certify() 중 mutate 되어도 단일 certify() 안
    모든 consumer 는 같은 state 를 본다.
    """

    def test_hash_and_raw_derived_from_same_source(self, populated_db_cert):
        """Snapshot 의 portfolio_hash 가 portfolio_raw 에서 파생된 값과 일치."""
        from nuri.trading.engine.certification import _capture_snapshot, _compute_portfolio_hash

        snap = _capture_snapshot(db_path=populated_db_cert)
        derived_hash = _compute_portfolio_hash(rows=snap.portfolio_raw)
        assert snap.portfolio_hash == derived_hash

    def test_leverage_ban_reads_from_snapshot(self, populated_db_cert):
        """certify() 중 DB 변경되어도 leverage_ban 은 snapshot 기준 판정."""
        from nuri.core.db import get_db

        # Portfolio 에 TQQQ (레버리지 금지) 추가
        with get_db(populated_db_cert) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "TQQQ", 10, 50.0, "USD", "Technology"),
            )

        # certify() 가 시작되면 snapshot 에 TQQQ 포함. gate eval 중 TQQQ 삭제해도
        # leverage_ban 은 snapshot 기준 (TQQQ 보유) 로 FAIL emit.
        from nuri.trading.engine.certification import _CERT_SNAPSHOT, _capture_snapshot

        snap = _capture_snapshot(db_path=populated_db_cert)
        tickers_in_snap = {r["ticker"] for r in snap.portfolio_raw}
        assert "TQQQ" in tickers_in_snap

        token = _CERT_SNAPSHOT.set(snap)
        try:
            # Mid-eval DB 변경 (TQQQ 삭제)
            with get_db(populated_db_cert) as conn:
                conn.execute("DELETE FROM portfolio WHERE ticker = 'TQQQ'")

            from nuri.trading.engine.certification import _check_leverage_ban
            cond = _check_leverage_ban(db_path=populated_db_cert)
            # Snapshot 에는 TQQQ 남아있어 FAIL 이어야 함
            assert cond.passed is False
            assert "TQQQ" in cond.detail
        finally:
            _CERT_SNAPSHOT.reset(token)

    def test_asset_class_grouping_reads_from_snapshot(self, populated_db_cert):
        """`_group_holdings_by_asset_class` 도 snapshot 기준 (R4)."""
        from nuri.trading.engine.certification import (
            _CERT_SNAPSHOT,
            _capture_snapshot,
            _group_holdings_by_asset_class,
        )

        snap = _capture_snapshot(db_path=populated_db_cert)
        token = _CERT_SNAPSHOT.set(snap)
        try:
            # Mid-eval DB 비우기
            from nuri.core.db import get_db
            with get_db(populated_db_cert) as conn:
                conn.execute("DELETE FROM portfolio")

            groups = _group_holdings_by_asset_class(db_path=populated_db_cert)
            # Snapshot 에 AAPL + MSFT 있었으므로 비어있으면 안됨 (us_equity 에 있어야)
            total_tickers = sum(len(v) for v in groups.values())
            assert total_tickers > 0
        finally:
            _CERT_SNAPSHOT.reset(token)


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
        import pandas as pd

        from nuri.trading.engine.certification import CertSnapshot

        snapshot = CertSnapshot(
            regime="bull_low_vol",
            portfolio_raw=[],
            portfolio_df=pd.DataFrame(),
            portfolio_hash="test_hash",
        )
        _persist_certification(
            cert,
            snapshot=snapshot,
            db_path=db_path,
            caller="direct",
        )
        rows = query("SELECT caller, certified, regime, portfolio_hash FROM certifications", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["caller"] == "direct"
        assert rows[0]["certified"] == 1
        assert rows[0]["regime"] == "bull_low_vol"
        assert rows[0]["portfolio_hash"] == "test_hash"


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
