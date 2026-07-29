"""Phase 2 execution + incidents + drift writes (#529).

Production state machine for agent_decisions (Phase 2 actor #8 DecisionCompiler
— distinct from #178 upsert_decision in `decisions.py`!), forward-outcome
tracking, hard-veto execution blocks, SRE incident ledger, drift alerts.

All these writes are audit-trail; no in-place mutations except status field
transitions on agent_decisions/incidents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .connection import get_db

_DECISION_ACTIONS = ("BUY", "SELL", "HOLD")
_DECISION_STATUSES = ("pending", "emitted", "blocked", "superseded")
_REQUIRED_INPUT_KEYS = ("regime_run_id", "hypothesis_id", "causal_audit_id")
_OUTCOME_VALIDATIONS = ("pass", "reject", "insufficient_data")
_OUTCOME_WINDOWS = (7, 14, 30)
_BLOCK_TYPES = (
    "vix_too_high",
    "banned_leverage_etf",
    "position_cap",
    "sector_concentration",
    "cash_reserve",
    "leverage_cap",
    "max_daily_loss",
    "sleeve_cap",  # §3.11 실험 슬리브 상한 (#834) — migration 47 의 CHECK 와 짝
)
_BLOCK_SEVERITIES = ("hard", "soft")
_INCIDENT_TYPES = (
    "orphan_run",
    "disk_full",
    "db_lock",
    "scheduler_heartbeat",
    "actor_failure_streak",
    "data_freshness_critical",
    "signal_evaluation_stale",
    "alpha_report_stale",
    # health_check.sh 에서 이식 (#939) — 그쪽은 알림 경로가 없어 로그로만 남았다.
    "schema_version_drift",
    "required_table_missing",
    "writer_role",
)
_INCIDENT_SEVERITIES = ("critical", "warning", "info")
_INCIDENT_STATUSES = ("open", "acknowledged", "resolved")
_DRIFT_TEST_TYPES = ("psi", "ks")
_DRIFT_SEVERITIES = ("stable", "minor", "major", "critical")


def log_decision(
    decision_id: str,
    ticker: str,
    as_of_date: str,
    action: str,
    conviction: float,
    inputs: dict,
    rationale: dict,
    status: str,
    block_reason: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Decision-Compiler 출력 영구 기록 (#529 Phase 2 capstone).

    audit traceable form 강제: inputs 에 source actor run_id 누락 시 panic.
    Layer B contract: ZERO LLM, deterministic. 모든 emit / block 결정 기록.

    inputs 필수 키:
        regime_run_id — RegimePosterior 의 run_id
        hypothesis_id — HypothesisRegistry 의 hypothesis_id (check_emit 통과한 것)
        causal_audit_id — CausalFactorAuditor 의 (factor_id, as_of_date) 식별자
        walkforward_run_id (optional) — WalkForwardValidator 결과
    """
    if action not in _DECISION_ACTIONS:
        raise ValueError(f"action must be {_DECISION_ACTIONS}, got {action!r}")
    if status not in _DECISION_STATUSES:
        raise ValueError(f"status must be {_DECISION_STATUSES}, got {status!r}")
    if not (0.0 <= conviction <= 1.0):
        raise ValueError(f"conviction must be in [0,1], got {conviction}")
    missing = [k for k in _REQUIRED_INPUT_KEYS if k not in inputs]
    if missing:
        raise ValueError(f"inputs missing required audit keys: {missing} (audit traceability enforcement)")
    if status == "blocked" and not block_reason:
        raise ValueError("blocked decision must include block_reason")

    with get_db(db_path) as conn:
        # 동일 ticker 의 이전 emitted/pending decision 은 superseded 처리 (idempotent)
        if status in ("emitted", "blocked"):
            conn.execute(
                """UPDATE agent_decisions SET status='superseded'
                   WHERE ticker=? AND as_of_date=? AND decision_id != ?
                   AND status IN ('pending','emitted')""",
                (ticker, as_of_date, decision_id),
            )
        conn.execute(
            """INSERT INTO agent_decisions
               (decision_id, ticker, as_of_date, action, conviction,
                inputs_json, rationale_json, status, block_reason, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(decision_id) DO UPDATE SET
                 action = excluded.action,
                 conviction = excluded.conviction,
                 inputs_json = excluded.inputs_json,
                 rationale_json = excluded.rationale_json,
                 status = excluded.status,
                 block_reason = excluded.block_reason""",
            (
                decision_id,
                ticker,
                as_of_date,
                action,
                conviction,
                json.dumps(inputs, sort_keys=True, default=str),
                json.dumps(rationale, sort_keys=True, default=str),
                status,
                block_reason,
                run_id,
            ),
        )


def log_decision_outcome(
    decision_id: str,
    observation_window: int,
    tracked_as_of_date: str,
    hypothesis_validation: str,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    realized_return: Optional[float] = None,
    benchmark_return: Optional[float] = None,
    benchmark_ticker: Optional[str] = None,
    alpha: Optional[float] = None,
    hit_threshold: bool = False,
    notes: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Decision outcome audit (#529 Phase 2 closed-loop — Forward-Outcome-Tracker).

    (decision_id, observation_window) PK 로 동일 decision 의 7d/14d/30d 별도 row.
    동일 (decision_id, window) 재계산 시 idempotent upsert.

    hypothesis_validation: pass/reject/insufficient_data — Hypothesis-Registry 의 validate/reject
    호출 trigger. insufficient_data 는 false validation 차단 (가격 데이터 부족).
    """
    if observation_window not in _OUTCOME_WINDOWS:
        raise ValueError(f"observation_window must be {_OUTCOME_WINDOWS}, got {observation_window}")
    if hypothesis_validation not in _OUTCOME_VALIDATIONS:
        raise ValueError(f"hypothesis_validation must be {_OUTCOME_VALIDATIONS}, got {hypothesis_validation!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO decision_outcomes
               (decision_id, observation_window, tracked_as_of_date,
                entry_price, exit_price, realized_return, benchmark_return, benchmark_ticker, alpha,
                hit_threshold, hypothesis_validation, notes, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(decision_id, observation_window) DO UPDATE SET
                 tracked_as_of_date = excluded.tracked_as_of_date,
                 entry_price = excluded.entry_price,
                 exit_price = excluded.exit_price,
                 realized_return = excluded.realized_return,
                 benchmark_return = excluded.benchmark_return,
                 benchmark_ticker = excluded.benchmark_ticker,
                 alpha = excluded.alpha,
                 hit_threshold = excluded.hit_threshold,
                 hypothesis_validation = excluded.hypothesis_validation,
                 notes = excluded.notes,
                 run_id = excluded.run_id""",
            (
                decision_id,
                observation_window,
                tracked_as_of_date,
                entry_price,
                exit_price,
                realized_return,
                benchmark_return,
                benchmark_ticker,
                alpha,
                int(hit_threshold),
                hypothesis_validation,
                notes,
                run_id,
            ),
        )


def log_execution_block(
    decision_id: str,
    block_type: str,
    severity: str,
    block_reason: str,
    evidence: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Execution-Firewall block 결정 영구 기록 (#529 Phase 2 actor #9).

    block_type / severity enum 검증. evidence_json 에 위반 detail (현재 값 vs 임계값) 기록.
    Layer A enforcement: hard severity 위반 = emit 차단, soft = warn only.

    Returns: 신규 block_id (lastrowid).
    """
    if block_type not in _BLOCK_TYPES:
        raise ValueError(f"block_type must be {_BLOCK_TYPES}, got {block_type!r}")
    if severity not in _BLOCK_SEVERITIES:
        raise ValueError(f"severity must be {_BLOCK_SEVERITIES}, got {severity!r}")
    if not block_reason or not block_reason.strip():
        raise ValueError("block_reason required (Layer A enforcement audit)")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO execution_blocks
               (decision_id, block_type, severity, block_reason, evidence_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                block_type,
                severity,
                block_reason,
                json.dumps(evidence, sort_keys=True, default=str),
                run_id,
            ),
        )
        return cursor.lastrowid or 0


def log_incident(
    incident_type: str,
    severity: str,
    target: str,
    evidence: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """SRE-Incident 영구 기록 (#529 Phase 2 actor #14, Layer A).

    Idempotent semantics:
        동일 (incident_type, target, status='open') incident 가 존재하면
        last_detected_at + evidence_json 만 update (신규 row X — 동일 incident_id 반환).
        존재하지 않으면 신규 INSERT (status='open', first_detected_at=now).

    Returns: incident_id (기존 or 신규).

    enum 검증: incident_type, severity 모두 _INCIDENT_TYPES / _INCIDENT_SEVERITIES 에서.
    """
    if incident_type not in _INCIDENT_TYPES:
        raise ValueError(f"incident_type must be {_INCIDENT_TYPES}, got {incident_type!r}")
    if severity not in _INCIDENT_SEVERITIES:
        raise ValueError(f"severity must be {_INCIDENT_SEVERITIES}, got {severity!r}")
    if not target or not str(target).strip():
        raise ValueError("target required (actor_name / table / ticker / 'system')")

    evidence_json = json.dumps(evidence, sort_keys=True, default=str)
    with get_db(db_path) as conn:
        # open 인 동일 (type, target) 가 있으면 update + 기존 incident_id 반환.
        existing = conn.execute(
            """SELECT incident_id FROM incidents
               WHERE incident_type = ? AND target = ? AND status = 'open'""",
            (incident_type, target),
        ).fetchone()
        if existing is not None:
            existing_id = existing[0]
            conn.execute(
                """UPDATE incidents
                   SET last_detected_at = datetime('now'),
                       evidence_json = ?,
                       severity = ?,
                       run_id = COALESCE(?, run_id)
                   WHERE incident_id = ?""",
                (evidence_json, severity, run_id, existing_id),
            )
            return int(existing_id)
        # 신규 incident.
        cursor = conn.execute(
            """INSERT INTO incidents
               (incident_type, severity, target, status, evidence_json, run_id)
               VALUES (?, ?, ?, 'open', ?, ?)""",
            (incident_type, severity, target, evidence_json, run_id),
        )
        return cursor.lastrowid or 0


def acknowledge_incident(
    incident_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Incident 를 사용자가 봤음 표시 (audit-only — Discord re-publish 차단용).

    Returns: True if updated, False if no open incident with that id.
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE incidents
               SET status = 'acknowledged'
               WHERE incident_id = ? AND status = 'open'""",
            (incident_id,),
        )
        return (cursor.rowcount or 0) > 0


def resolve_incident(
    incident_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Incident 종료 — status='resolved' + resolved_at=now.

    Returns: True if updated, False if no open/acknowledged incident with that id.
    Resolve 후 동일 (type, target) 재발 시 신규 row 가능 (status 가 UNIQUE 의 일부).
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE incidents
               SET status = 'resolved',
                   resolved_at = datetime('now')
               WHERE incident_id = ? AND status IN ('open','acknowledged')""",
            (incident_id,),
        )
        return (cursor.rowcount or 0) > 0


def log_drift_alert(
    feature_name: str,
    test_type: str,
    test_statistic: float,
    threshold: float,
    severity: str,
    baseline_window: str,
    current_window: str,
    n_baseline: int,
    n_current: int,
    distribution_summary: dict,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Drift-Sentinel 분포 drift 결과 영구 기록 (#529 Phase 2 actor #12, Layer B).

    PSI / KS 2-sample test 결과 archive. 매 detection 이 신규 row (idempotent X) —
    historical drift trend 분석용.

    enum 검증:
        test_type ∈ ('psi','ks')
        severity ∈ ('stable','minor','major','critical')
    값 검증:
        test_statistic / threshold ≥ 0.0 (PSI / KS D-stat 양수)
        n_baseline / n_current ≥ 0

    Returns: alert_id (lastrowid).

    Layer B contract: ZERO LLM, deterministic. SREIncidentAgent 가 critical drift
    surfaced 시 incident 로 escalate 가능 (별도 trigger).
    """
    if test_type not in _DRIFT_TEST_TYPES:
        raise ValueError(f"test_type must be {_DRIFT_TEST_TYPES}, got {test_type!r}")
    if severity not in _DRIFT_SEVERITIES:
        raise ValueError(f"severity must be {_DRIFT_SEVERITIES}, got {severity!r}")
    if test_statistic < 0.0:
        raise ValueError(f"test_statistic must be >= 0.0, got {test_statistic}")
    if threshold < 0.0:
        raise ValueError(f"threshold must be >= 0.0, got {threshold}")
    if n_baseline < 0 or n_current < 0:
        raise ValueError(f"n_baseline / n_current must be >= 0, got {n_baseline} / {n_current}")
    if not feature_name or not str(feature_name).strip():
        raise ValueError("feature_name required")

    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO drift_alerts
               (feature_name, test_type, test_statistic, threshold, severity,
                baseline_window, current_window, n_baseline, n_current,
                distribution_summary_json, actor_name, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feature_name,
                test_type,
                float(test_statistic),
                float(threshold),
                severity,
                baseline_window,
                current_window,
                int(n_baseline),
                int(n_current),
                json.dumps(distribution_summary, sort_keys=True, default=str),
                actor_name,
                run_id,
            ),
        )
        return cursor.lastrowid or 0
