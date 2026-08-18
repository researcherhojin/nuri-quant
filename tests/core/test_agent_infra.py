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
    """16 신규 migration (#25 audit / #26 flags / #27 runs / #28 messages / #29 walkforward_runs / #30 regime_posteriors / #31 hypotheses / #32 causal_audits / #33 agent_decisions / #34 decision_outcomes / #35 execution_blocks / #36 incidents / #37 dr_replicas / #38 collector_runs / #39 drift_alerts / #40 foundation_benchmarks) 적용 확인."""

    def test_schema_version_at_54(self, db_path):
        """Phase 1+2 + discord_outbox + agent_control/agent_dev_log channel CHECK 확장 (#582) +
        held_add_shadow (#518) + market_postmortem (#596 Phase 2) +
        incidents signal_evaluation_stale enum 확장 (#825) +
        incidents alpha_report_stale enum 확장 (#894) +
        execution_blocks sleeve_cap enum 확장 (#834) +
        decision_outcomes.benchmark_ticker (#833) +
        incidents enum 확장 — health_check.sh 흡수 3종 (#939) +
        recommendations.source — emit 경로 구분 (#1078) +
        theses / thesis_evidence — 상승·하락 논지 원장 (#1083) +
        thesis_criteria / thesis_criteria_checks — 사전등록 반증 기준 (#1092) +
        candidate_runs / candidate_ledger — 미실행 거래 원장 (#1094) +
        superinvestors.investor_class — 확신/딜러 13F 분리 (#1098) → 54."""
        assert get_schema_version(db_path) == 54

    def test_block_type_allowlist_matches_sql_check(self, db_path):
        """`_BLOCK_TYPES`(파이썬 검증) 와 execution_blocks CHECK(스키마) 는 같아야 한다.

        #834 에서 실제로 갈렸다 — CHECK 에 'sleeve_cap' 을 넣고 `_BLOCK_TYPES` 를
        빼먹으면 `log_execution_block` 이 ValueError 로 죽는다. 반대 방향(파이썬만
        확장)은 IntegrityError 로 죽는다. 둘 다 firewall 이 통째로 멈추는 고장이라
        한쪽만 고치는 조합을 여기서 잠근다.

        Gotcha-Test Pair: 어느 한쪽에만 block_type 을 추가하면 FAIL.
        """
        import re

        from nuri.core.db.execution_ops import _BLOCK_TYPES

        sql = query(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='execution_blocks'",
            db_path=db_path,
        )[0]["sql"]
        check_body = re.search(r"block_type TEXT NOT NULL CHECK\(block_type IN \((.*?)\)\)", sql, re.S)
        assert check_body, "execution_blocks CHECK 파싱 실패 — 스키마 형태가 바뀜"
        in_sql = set(re.findall(r"'([a-z_]+)'", check_body.group(1)))
        assert in_sql == set(_BLOCK_TYPES), f"SQL CHECK {sorted(in_sql)} != _BLOCK_TYPES {sorted(_BLOCK_TYPES)}"

    def test_incident_type_allowlist_matches_sql_check(self, db_path):
        """`_INCIDENT_TYPES`(파이썬 검증) 와 incidents CHECK(스키마) 는 같아야 한다.

        block_type 과 완전히 같은 실패 모드인데 여기엔 잠금이 없었다 — #939 에서
        detector 3종을 추가하며 양쪽을 손으로 맞췄고, 한쪽만 고치면 `log_incident`
        가 ValueError(파이썬만 좁음) 또는 IntegrityError(스키마만 좁음)로 죽는다.
        둘 다 **감시자가 통째로 멈추는** 고장이라 조합을 여기서 잠근다.

        Gotcha-Test Pair: 어느 한쪽에만 incident_type 을 추가하면 FAIL.
        """
        import re

        from nuri.core.db.execution_ops import _INCIDENT_TYPES

        sql = query(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='incidents'",
            db_path=db_path,
        )[0]["sql"]
        check_body = re.search(r"incident_type TEXT NOT NULL CHECK\(incident_type IN \((.*?)\)\)", sql, re.S)
        assert check_body, "incidents CHECK 파싱 실패 — 스키마 형태가 바뀜"
        in_sql = set(re.findall(r"'([a-z_]+)'", check_body.group(1)))
        assert in_sql == set(_INCIDENT_TYPES), (
            f"SQL CHECK {sorted(in_sql)} != _INCIDENT_TYPES {sorted(_INCIDENT_TYPES)}"
        )

    def test_every_sre_detector_type_is_allowed(self, db_path):
        """detector 가 낼 수 있는 타입은 전부 DB 가 받아줘야 한다 (#939).

        `_DETECTOR_INCIDENT_TYPES` 는 자동 해소 가드용이지만, 그 값이 곧 detector 가
        `log_incident` 에 넘기는 타입이다. allowlist 에 없으면 스캔 중 그 detector 가
        예외로 죽고 scan 루프가 db_lock 으로 바꿔 담는다 — 원인이 가려진다.
        """
        from nuri.agents.actors.sre_incident_agent import _DETECTOR_INCIDENT_TYPES
        from nuri.core.db.execution_ops import _INCIDENT_TYPES

        emitted = {t for types in _DETECTOR_INCIDENT_TYPES.values() for t in types}
        assert emitted <= set(_INCIDENT_TYPES), f"allowlist 누락: {sorted(emitted - set(_INCIDENT_TYPES))}"

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
