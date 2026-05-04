"""Agent runtime infra (#529) — audit / feature flags / run lifecycle / DR / collectors / Discord.

Cross-cutting writes used by all 15 actors. Stays as a single module since
these helpers reference each other (e.g. start_agent_run + finish_agent_run
share the agent_run_ledger row lifecycle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db

# DR enums (codex Round 5 single-writer — primary/replica)
_DR_VALID_ROLES: tuple[str, ...] = ("primary", "replica")
_DR_VALID_STATUSES: tuple[str, ...] = ("healthy", "stale", "unreachable", "out_of_sync")
_COLLECTOR_VALID_STATUSES: tuple[str, ...] = (
    "started",
    "finished",
    "failed",
    "timeout",
    "rate_limited",
)


def log_agent_audit(
    decision_id: str,
    actor_name: str,
    actor_version: str,
    layer: str,
    input_hash: str,
    output: str,
    input_summary: Optional[str] = None,
    sample_n: Optional[int] = None,
    duration_ms: Optional[int] = None,
    outcome: Optional[str] = None,
    llm_narrative: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Append-only agent decision audit (#529).

    layer: 'A' enforcement / 'B' computation / 'C' interpretation.
    outcome: 'pass' / 'block' / 'warn' / 'error'. Layer A 결정 시 필수.
    """
    if layer not in ("A", "B", "C"):
        raise ValueError(f"layer must be A/B/C, got {layer!r}")
    if outcome is not None and outcome not in ("pass", "block", "warn", "error"):
        raise ValueError(f"outcome must be pass/block/warn/error, got {outcome!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO agent_audit_ledger
               (decision_id, actor_name, actor_version, layer, input_hash, input_summary,
                output, sample_n, duration_ms, outcome, llm_narrative, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                actor_name,
                actor_version,
                layer,
                input_hash,
                input_summary,
                output,
                sample_n,
                duration_ms,
                outcome,
                llm_narrative,
                run_id,
            ),
        )
        return cursor.lastrowid or 0


def set_feature_flag(
    flag_name: str,
    enabled: bool,
    canary_scope: Optional[str] = None,
    owner: str = "system",
    description: Optional[str] = None,
    disabled_reason: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Feature flag set/update (#529).

    canary_scope: 'paper' / 'partial' / 'full'.
    enabled=False 로 호출 시 disabled_at + disabled_reason 자동 채움.
    """
    if canary_scope is not None and canary_scope not in ("paper", "partial", "full"):
        raise ValueError(f"canary_scope must be paper/partial/full, got {canary_scope!r}")
    with get_db(db_path) as conn:
        if enabled:
            conn.execute(
                """INSERT INTO feature_flags
                   (flag_name, enabled, canary_scope, owner, description, updated_at,
                    disabled_at, disabled_reason)
                   VALUES (?, 1, ?, ?, ?, datetime('now'), NULL, NULL)
                   ON CONFLICT(flag_name) DO UPDATE SET
                     enabled = 1,
                     canary_scope = COALESCE(?, canary_scope),
                     owner = ?,
                     description = COALESCE(?, description),
                     updated_at = datetime('now'),
                     disabled_at = NULL,
                     disabled_reason = NULL""",
                (
                    flag_name,
                    canary_scope,
                    owner,
                    description,
                    canary_scope,
                    owner,
                    description,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO feature_flags
                   (flag_name, enabled, owner, description, updated_at,
                    disabled_at, disabled_reason)
                   VALUES (?, 0, ?, ?, datetime('now'), datetime('now'), ?)
                   ON CONFLICT(flag_name) DO UPDATE SET
                     enabled = 0,
                     updated_at = datetime('now'),
                     disabled_at = datetime('now'),
                     disabled_reason = ?""",
                (flag_name, owner, description, disabled_reason, disabled_reason),
            )


def start_agent_run(
    run_id: str,
    actor_name: str,
    parent_run_id: Optional[str] = None,
    machine: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Agent run lifecycle 시작 (#529 SRE-Incident + Drift-Sentinel)."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_run_ledger (run_id, actor_name, parent_run_id, status, machine)
               VALUES (?, ?, ?, 'started', ?)""",
            (run_id, actor_name, parent_run_id, machine),
        )


def finish_agent_run(
    run_id: str,
    status: str = "finished",
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Agent run lifecycle 완료 (#529).

    status: 'finished' / 'failed' / 'timeout' / 'cancelled'.
    finished_at NULL 로 남으면 SRE-Incident-Agent alert trigger.
    """
    if status not in ("finished", "failed", "timeout", "cancelled"):
        raise ValueError(f"status must be finished/failed/timeout/cancelled, got {status!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """UPDATE agent_run_ledger
               SET status = ?, finished_at = datetime('now'),
                   duration_ms = ?, error_message = ?
               WHERE run_id = ?""",
            (status, duration_ms, error_message, run_id),
        )


def upsert_dr_replica(
    replica_id: str,
    role: str,
    hostname: str,
    last_sync_at: Optional[str],
    last_sync_schema_version: Optional[int],
    sync_lag_seconds: Optional[int],
    status: str,
    notes: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """DR replica state upsert (#529 State-Replicator-DR).

    role: 'primary' / 'replica' — single-writer 모델 (Codex Round 5 mandatory #1).
    status: 'healthy' / 'stale' / 'unreachable' / 'out_of_sync'.
    enum 위반 시 ValueError — Layer A actor 호출 전 validation 강제.
    """
    if role not in _DR_VALID_ROLES:
        raise ValueError(f"role must be primary/replica, got {role!r}")
    if status not in _DR_VALID_STATUSES:
        raise ValueError(f"status must be healthy/stale/unreachable/out_of_sync, got {status!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO dr_replicas
               (replica_id, role, hostname, last_sync_at, last_sync_schema_version,
                sync_lag_seconds, status, notes, run_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(replica_id) DO UPDATE SET
                 role = excluded.role,
                 hostname = excluded.hostname,
                 last_sync_at = excluded.last_sync_at,
                 last_sync_schema_version = excluded.last_sync_schema_version,
                 sync_lag_seconds = excluded.sync_lag_seconds,
                 status = excluded.status,
                 notes = COALESCE(excluded.notes, notes),
                 run_id = COALESCE(excluded.run_id, run_id),
                 updated_at = datetime('now')""",
            (
                replica_id,
                role,
                hostname,
                last_sync_at,
                last_sync_schema_version,
                sync_lag_seconds,
                status,
                notes,
                run_id,
            ),
        )


def log_collector_run(
    collector_name: str,
    status: str,
    rows_collected: int = 0,
    rows_expected: Optional[int] = None,
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    retry_count: int = 0,
    rate_limit_hits: int = 0,
    actor_run_id: Optional[str] = None,
    finished_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Single INSERT — 매 collector run 의 결과 영구 기록. lastrowid 반환.

    enum 검증: status ∈ ('started','finished','failed','timeout','rate_limited').
    Layer B Collector-Orchestrator 가 21+ collector 의 health 추적용으로 호출.

    actor_run_id: agent_run_ledger.run_id 와 join 가능 (오케스트레이션 chain 추적).
    finished_at None 이면 in-progress 상태 (started 직후 호출 시).
    """
    if status not in _COLLECTOR_VALID_STATUSES:
        raise ValueError(f"status must be one of {_COLLECTOR_VALID_STATUSES}, got {status!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO collector_runs
               (collector_name, status, rows_collected, rows_expected,
                duration_ms, error_message, retry_count, rate_limit_hits,
                actor_run_id, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                collector_name,
                status,
                rows_collected,
                rows_expected,
                duration_ms,
                error_message,
                retry_count,
                rate_limit_hits,
                actor_run_id,
                finished_at,
            ),
        )
        return int(cursor.lastrowid or 0)


def log_agent_message(
    channel: str,
    content_preview: str,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    http_status: Optional[int] = None,
    retry_count: int = 0,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Discord publish audit (#529 Phase 2 — DiscordBridge).

    channel: 'brief' / 'ops' / 'incidents' / 'rollout' / 'agent_control' / 'agent_dev_log'.
    content_preview: 첫 200자 (긴 embed 도 grep 가능하도록).
    http_status: 204 정상 발송, 4xx/5xx 실패. NULL = 네트워크 실패 전 단계.
    """
    valid = ("brief", "ops", "incidents", "rollout", "agent_control", "agent_dev_log")
    if channel not in valid:  # pragma: no cover — input validation guard
        raise ValueError(f"channel must be one of {valid}, got {channel!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO agent_messages
               (channel, actor_name, run_id, decision_id, content_preview,
                http_status, retry_count, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                channel,
                actor_name,
                run_id,
                decision_id,
                content_preview[:200],
                http_status,
                retry_count,
                error_message,
            ),
        )
        return cursor.lastrowid or 0
