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
    # warn_only 모드에서 의존성 미충족을 알리되 실행은 막지 않을 때 (#921).
    "step_dependency_warning",
    # nuri/api/routes/pipeline.py 의 수동 실행 엔드포인트가 쓰는 레거시 철자.
    # step_completed 와 같은 뜻 — 등재해 스키마를 정직하게 둔다 (#921).
    "step_success",
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
    # Signal-evaluation heartbeat (#825) — signals 테이블은 발화(계산) 행만 저장하므로
    # 무기록이 '조건 미충족(정상)'인지 '평가 미실행(고장)'인지 구분 불가 (#734 계열).
    # technical collector 가 평가 실행마다 1행 기록 (record_count=fired_count, 0 포함).
    # emitter: nuri/collectors/technical.py save() /
    # consumer: SREIncidentAgent._detect_signal_evaluation_stale.
    "signal_evaluation_run",
}

# 파이프라인 스테이지 — README 의 5 stage 와 같은 어휘.
# 예전 6-step(collect/validate/classify/diagnose/recommend/track)은 2026-04-09 수동
# 실행 때 두 행씩 남기고 이후 아무도 쓰지 않았다. 이름이 실제 시스템과 달라서
# 스케줄러가 step 이벤트를 남길 수도, 대시보드가 진짜 상태를 보여줄 수도 없었다 (#921).
PIPELINE_STEPS = ("collect", "analyze", "consensus", "certify", "track")

# `step` 컬럼은 lifecycle 이벤트(step_*)와 임의 도메인 이벤트가 공유한다 —
# 예: holdings_monitor 가 step="track" 으로 holdings_monitor_run 을 남긴다.
# 스테이지 "상태"는 lifecycle 이벤트로만 판정해야 한다. 그렇지 않으면
# get_step_status("track") 이 "holdings_monitor_run" 을 status 로 돌려주고,
# 의존성 체크와 대시보드가 그걸 completed 가 아닌 값으로 읽는다.
# `step_success` 는 `nuri/api/routes/pipeline.py` 의 수동 실행 엔드포인트가 남기는
# 레거시 이름이다(같은 뜻, 다른 철자). 빼면 대시보드에서 수동 실행한 스테이지가
# idle 로 보인다 — 프로덕션에 실제로 6행 있다.
_LIFECYCLE_EVENT_TYPES = (
    "step_started",
    "step_completed",
    "step_success",
    "step_failed",
    "step_blocked",
)


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
        # payload 는 항상 **유효 JSON** 이어야 한다 (#935). 이 테이블을 읽는 쿼리 12곳이
        # `json_extract()` 를 쓰는데, 그 쿼리들은 행을 거르는 게 아니라 테이블을 스캔하므로
        # malformed 행 하나가 무관한 조회까지 전부 `OperationalError` 로 죽인다.
        # 이전 구현은 비-dict 를 `str()` 로 썼다 — 시그니처가 `str` 을 허용하니
        # `emit_event(..., payload="skipped")` 한 번이면 테이블이 영구 오염됐다.
        # `default=str`: 직렬화 불가 객체 때문에 writer 가 죽어 **본 작업을 막으면 안 된다**.
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)

    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO pipeline_events (event_type, step, payload, duration_ms, record_count, causation_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_type, step, payload_str, duration_ms, record_count, causation_id),
        )
        return cursor.lastrowid


def get_step_status(step: str, db_path: Optional[Path] = None) -> dict:
    """스테이지의 최신 **lifecycle** 상태 → {status, timestamp, payload, record_count}.

    도메인 이벤트(holdings_monitor_run 등)는 같은 `step` 값을 쓰더라도 상태로
    치지 않는다 — 그것들이 섞이면 `status` 가 completed/running/failed 가 아닌
    임의 문자열이 되고, 의존성 체크가 영영 ready 를 못 본다 (#921).
    """
    placeholders = ",".join("?" for _ in _LIFECYCLE_EVENT_TYPES)
    try:
        rows = query(
            f"""SELECT event_type, timestamp, payload, record_count
               FROM pipeline_events
               WHERE step = ? AND event_type IN ({placeholders})
               ORDER BY timestamp DESC, id DESC
               LIMIT 1""",
            (step, *_LIFECYCLE_EVENT_TYPES),
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
        "step_success": "completed",  # API 수동 실행의 레거시 철자
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
    """전체 5-stage 파이프라인 상태 조회 (#921 — 예전 6-step 어휘 폐기)."""
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
