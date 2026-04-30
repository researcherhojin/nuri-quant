"""nuri.core.db 의 service-grade 15-actor agent infra helper 테스트 (#529 Phase 1).

Round 5 codex consult 합의 — Layer A enforcement / B compute / C interpret 분리.
Append-only audit + feature flag + run lifecycle 의 정합성·무결성 검증.
"""

import pytest

from nuri.core.db import (
    finish_agent_run,
    get_schema_version,
    init_db,
    is_feature_enabled,
    log_agent_audit,
    query,
    set_feature_flag,
    start_agent_run,
)


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처 — 각 테스트 격리."""
    path = tmp_path / "agent_infra.db"
    init_db(path)
    return path


class TestSchemaMigrations:
    """5 신규 migration (#25 audit / #26 flags / #27 runs / #28 messages / #29 walkforward_runs) 적용 확인."""

    def test_schema_version_at_29(self, db_path):
        """Phase 1+2 migrations 모두 적용 → schema version 29."""
        assert get_schema_version(db_path) == 29

    def test_audit_ledger_table_exists(self, db_path):
        """agent_audit_ledger 테이블이 생성되었는지 확인."""
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_audit_ledger'",
            db_path=db_path,
        )
        assert len(rows) == 1

    def test_feature_flags_table_exists(self, db_path):
        """feature_flags 테이블이 생성되었는지 확인."""
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='feature_flags'",
            db_path=db_path,
        )
        assert len(rows) == 1

    def test_run_ledger_table_exists(self, db_path):
        """agent_run_ledger 테이블이 생성되었는지 확인."""
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_run_ledger'",
            db_path=db_path,
        )
        assert len(rows) == 1


class TestAuditLedger:
    """append-only 보장 + Layer A/B/C 분류 + outcome enum 검증."""

    def test_log_layer_a_enforcement_decision(self, db_path):
        """Layer A enforcement 결정 — outcome 필수 시나리오."""
        log_agent_audit(
            decision_id="dec-001",
            actor_name="execution-firewall",
            actor_version="0.1.0",
            layer="A",
            input_hash="hash-abc",
            output='{"action": "block", "reason": "leverage cap"}',
            outcome="block",
            sample_n=1,
            duration_ms=2,
            db_path=db_path,
        )
        rows = query(
            "SELECT * FROM agent_audit_ledger WHERE decision_id=?",
            ("dec-001",),
            db_path=db_path,
        )
        assert len(rows) == 1
        assert rows[0]["layer"] == "A"
        assert rows[0]["outcome"] == "block"

    def test_log_layer_c_with_llm_narrative(self, db_path):
        """Layer C interpretation — LLM narrative 첨부 시나리오."""
        log_agent_audit(
            decision_id="dec-002",
            actor_name="drift-sentinel",
            actor_version="0.1.0",
            layer="C",
            input_hash="hash-def",
            output='{"psi": 0.23, "triggered": true}',
            llm_narrative="PSI 0.23 — regime shift suspected after FOMC.",
            db_path=db_path,
        )
        rows = query(
            "SELECT layer, llm_narrative FROM agent_audit_ledger WHERE decision_id=?",
            ("dec-002",),
            db_path=db_path,
        )
        assert rows[0]["layer"] == "C"
        assert "PSI" in rows[0]["llm_narrative"]

    def test_invalid_layer_rejected(self, db_path):
        """Layer 값은 A/B/C 만 허용 (Codex Round 5 mandatory)."""
        with pytest.raises(ValueError, match="layer must be A/B/C"):
            log_agent_audit(
                decision_id="dec-bad",
                actor_name="x",
                actor_version="0.1.0",
                layer="D",
                input_hash="h",
                output="{}",
                db_path=db_path,
            )

    def test_invalid_outcome_rejected(self, db_path):
        """outcome 은 pass/block/warn/error 만 허용."""
        with pytest.raises(ValueError, match="outcome must be"):
            log_agent_audit(
                decision_id="dec-bad",
                actor_name="x",
                actor_version="0.1.0",
                layer="A",
                input_hash="h",
                output="{}",
                outcome="ok",
                db_path=db_path,
            )

    def test_append_only_two_decisions_preserved(self, db_path):
        """두 번 log → 두 row 모두 보존 (append-only)."""
        for i in range(2):
            log_agent_audit(
                decision_id=f"dec-{i:03d}",
                actor_name="audit-test",
                actor_version="0.1.0",
                layer="B",
                input_hash=f"h-{i}",
                output="{}",
                db_path=db_path,
            )
        rows = query(
            "SELECT decision_id FROM agent_audit_ledger WHERE actor_name=?",
            ("audit-test",),
            db_path=db_path,
        )
        assert len(rows) == 2


class TestFeatureFlags:
    """Release-Rollback-Manager — flag enable/disable/rollback."""

    def test_default_returns_false_when_flag_missing(self, db_path):
        """미존재 flag 는 default 반환."""
        assert is_feature_enabled("nonexistent", db_path=db_path) is False
        assert is_feature_enabled("nonexistent", default=True, db_path=db_path) is True

    def test_enable_then_check(self, db_path):
        """flag enable 후 조회 → True."""
        set_feature_flag(
            "cycle_engine_v1",
            enabled=True,
            canary_scope="paper",
            description="HMM cycle engine v1 paper trade",
            db_path=db_path,
        )
        assert is_feature_enabled("cycle_engine_v1", db_path=db_path) is True

    def test_disable_sets_disabled_at(self, db_path):
        """flag disable → disabled_at 자동 채움 + is_enabled False."""
        set_feature_flag("test_flag", enabled=True, db_path=db_path)
        set_feature_flag(
            "test_flag",
            enabled=False,
            disabled_reason="emergency rollback",
            db_path=db_path,
        )
        assert is_feature_enabled("test_flag", db_path=db_path) is False
        rows = query(
            "SELECT disabled_at, disabled_reason FROM feature_flags WHERE flag_name=?",
            ("test_flag",),
            db_path=db_path,
        )
        assert rows[0]["disabled_at"] is not None
        assert rows[0]["disabled_reason"] == "emergency rollback"

    def test_re_enable_clears_disabled(self, db_path):
        """rollback 후 재 enable → disabled_at NULL 리셋."""
        set_feature_flag("flag2", enabled=True, db_path=db_path)
        set_feature_flag("flag2", enabled=False, disabled_reason="x", db_path=db_path)
        set_feature_flag("flag2", enabled=True, db_path=db_path)
        assert is_feature_enabled("flag2", db_path=db_path) is True
        rows = query(
            "SELECT disabled_at FROM feature_flags WHERE flag_name=?",
            ("flag2",),
            db_path=db_path,
        )
        assert rows[0]["disabled_at"] is None

    def test_invalid_canary_scope_rejected(self, db_path):
        """canary_scope 는 paper/partial/full 만 허용."""
        with pytest.raises(ValueError, match="canary_scope must be"):
            set_feature_flag("x", enabled=True, canary_scope="beta", db_path=db_path)


class TestRunLedger:
    """Agent run lifecycle — heartbeat 식 추적, finished_at NULL = SRE alert."""

    def test_start_and_finish_run(self, db_path):
        """run start → finish 정상 lifecycle."""
        start_agent_run("run-001", "regime-detector", machine="mac-mini", db_path=db_path)
        finish_agent_run("run-001", status="finished", duration_ms=350, db_path=db_path)
        rows = query(
            "SELECT status, duration_ms FROM agent_run_ledger WHERE run_id=?",
            ("run-001",),
            db_path=db_path,
        )
        assert rows[0]["status"] == "finished"
        assert rows[0]["duration_ms"] == 350

    def test_failed_run_records_error(self, db_path):
        """run failed → error_message 저장."""
        start_agent_run("run-002", "collector", db_path=db_path)
        finish_agent_run(
            "run-002",
            status="failed",
            error_message="KIS API 401",
            db_path=db_path,
        )
        rows = query(
            "SELECT status, error_message FROM agent_run_ledger WHERE run_id=?",
            ("run-002",),
            db_path=db_path,
        )
        assert rows[0]["status"] == "failed"
        assert "401" in rows[0]["error_message"]

    def test_orphan_run_finished_at_null(self, db_path):
        """started 만 호출, finish 안 한 run → finished_at NULL (SRE trigger 패턴)."""
        start_agent_run("run-orphan", "stuck-actor", db_path=db_path)
        rows = query(
            "SELECT status, finished_at FROM agent_run_ledger WHERE run_id=?",
            ("run-orphan",),
            db_path=db_path,
        )
        assert rows[0]["status"] == "started"
        assert rows[0]["finished_at"] is None

    def test_invalid_status_rejected(self, db_path):
        """status 는 finished/failed/timeout/cancelled 만 허용."""
        start_agent_run("run-bad", "x", db_path=db_path)
        with pytest.raises(ValueError, match="status must be"):
            finish_agent_run("run-bad", status="success", db_path=db_path)

    def test_parent_run_chain(self, db_path):
        """parent_run_id 로 cross-actor causation chain 추적."""
        start_agent_run("run-parent", "decision-compiler", db_path=db_path)
        start_agent_run(
            "run-child",
            "execution-firewall",
            parent_run_id="run-parent",
            db_path=db_path,
        )
        rows = query(
            "SELECT parent_run_id FROM agent_run_ledger WHERE run_id=?",
            ("run-child",),
            db_path=db_path,
        )
        assert rows[0]["parent_run_id"] == "run-parent"
