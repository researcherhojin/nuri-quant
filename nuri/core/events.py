"""파이프라인 이벤트 저널 — SIEGE Event Journal 패턴.

모든 파이프라인 상태 전환을 append-only 기록.
대시보드와 Pipeline UI는 이 이벤트의 projection으로 동작.
"""

import json
from pathlib import Path
from typing import Optional

from nuri.core.db import get_db, query

# 허용 이벤트 타입
EVENT_TYPES = {
    "step_started",
    "step_completed",
    "step_failed",
    "step_blocked",
    "gate_evaluated",
    "regime_changed",
    "certification_result",
    "conflict_detected",
    "drift_detected",
    # Mechanical penalty 발동 감사 로그 (STRATEGY §2.6 Escalation Ladder — soft penalty rung).
    # 지금은 divergence_technical (P1 A3) 만 사용. 추후 다른 mechanical gate 추가 시 공유.
    "consensus_penalty_applied",
    # KIS analyst opinion collector (#418) run summary + truncation risk surface.
    # `_run` carries covered / empty / failed / rows counts per Sunday cron;
    # `_truncation_risk` fires when the per-ticker tr_cont pagination depth
    # approaches the official-sample max_depth=10 cap (silent truncation
    # would be the wrong failure mode — codex Round 2).
    "kis_analyst_opinion_run",
    "kis_analyst_opinion_truncation_risk",
    # Holdings monitor — close post-entry technical-divergence gap exposed
    # by JKHY-class entry failures. `_run` is the parent batch event each
    # daily run emits (covered / alerted / skipped counts); `_technical_sell`
    # and `_divergence` are per-holding alerts. Caller is `nuri.trading.
    # recommend.holdings_monitor` (cron 07:10 KST, after consensus 07:05).
    "holdings_monitor_run",
    "holdings_monitor_technical_sell",
    "holdings_monitor_divergence",
}

# 6-step 파이프라인
PIPELINE_STEPS = {"collect", "validate", "classify", "diagnose", "recommend", "track"}


def emit_event(
    event_type: str,
    step: str | None = None,
    payload: dict | str | None = None,
    duration_ms: int | None = None,
    record_count: int | None = None,
    causation_id: int | None = None,
    db_path: Optional[Path] = None,
) -> int | None:
    """이벤트를 pipeline_events 테이블에 기록하고 event ID 반환.

    sqlite3 cursor.lastrowid 는 int | None — 통상 INSERT 후 int 이지만 type 정확.
    """
    payload_str = None
    if payload is not None:
        payload_str = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else str(payload)

    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO pipeline_events (event_type, step, payload, duration_ms, record_count, causation_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_type, step, payload_str, duration_ms, record_count, causation_id),
        )
        return cursor.lastrowid


def get_step_status(step: str, db_path: Optional[Path] = None) -> dict:
    """특정 스텝의 최신 이벤트 조회 → {status, timestamp, payload}."""
    try:
        rows = query(
            """SELECT event_type, timestamp, payload, record_count
               FROM pipeline_events
               WHERE step = ?
               ORDER BY timestamp DESC, id DESC
               LIMIT 1""",
            (step,),
            db_path,
        )
    except Exception as e:  # noqa: BLE001
        # pipeline_events 테이블 미존재(마이그레이션 미적용) 또는 DB 접근 실패
        import logging

        logging.getLogger(__name__).debug("pipeline_events 조회 실패: %s", e)
        return {"step": step, "status": "unknown", "timestamp": None, "payload": None, "record_count": 0}
    if not rows:
        return {"step": step, "status": "unknown", "timestamp": None, "payload": None, "record_count": 0}

    row = rows[0]
    # event_type → status 매핑
    status_map = {
        "step_started": "running",
        "step_completed": "completed",
        "step_failed": "failed",
        "step_blocked": "blocked",
    }
    status = status_map.get(row["event_type"], row["event_type"])
    payload = json.loads(row["payload"]) if row["payload"] else None
    return {
        "step": step,
        "status": status,
        "timestamp": row["timestamp"],
        "payload": payload,
        "record_count": row["record_count"] if row["record_count"] is not None else 0,
    }


def get_pipeline_status(db_path: Optional[Path] = None) -> dict:
    """전체 6-step 파이프라인 상태 조회."""
    result = {}
    for step in PIPELINE_STEPS:
        result[step] = get_step_status(step, db_path)
    return result


def get_timeline(
    limit: int = 50,
    step: str | None = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """최근 이벤트 타임라인 (timestamp desc)."""
    if step:
        rows = query(
            """SELECT id, timestamp, event_type, step, payload, duration_ms, record_count, causation_id
               FROM pipeline_events
               WHERE step = ?
               ORDER BY timestamp DESC, id DESC
               LIMIT ?""",
            (step, limit),
            db_path,
        )
    else:
        rows = query(
            """SELECT id, timestamp, event_type, step, payload, duration_ms, record_count, causation_id
               FROM pipeline_events
               ORDER BY timestamp DESC, id DESC
               LIMIT ?""",
            (limit,),
            db_path,
        )
    result = []
    for row in rows:
        entry = dict(row)
        if entry["payload"]:
            try:
                entry["payload"] = json.loads(entry["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(entry)
    return result


def get_step_history(step: str, limit: int = 10, db_path: Optional[Path] = None) -> list[dict]:
    """특정 스텝의 실행 이력 (완료/실패 이벤트만)."""
    rows = query(
        """SELECT id, timestamp, event_type, payload, duration_ms, record_count, causation_id
           FROM pipeline_events
           WHERE step = ? AND event_type IN ('step_completed', 'step_failed')
           ORDER BY timestamp DESC, id DESC
           LIMIT ?""",
        (step, limit),
        db_path,
    )
    result = []
    for row in rows:
        entry = dict(row)
        if entry["payload"]:
            try:
                entry["payload"] = json.loads(entry["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(entry)
    return result
