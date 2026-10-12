"""Pipeline API — 파이프라인 상태·타임라인·신선도 조회 (읽기 전용).

스테이지는 스케줄러만 실행한다. 대시보드의 실행 엔드포인트(`POST /pipeline/{step}/run`)는
#1778 에서 뺐다 — 레거시 6-step 이름만 받아 라이브 스테이지 셋은 400 이었고, collect 는
아무것도 안 하고 성공 이벤트를 남겼다. 실제 잡을 붙이면 같은 날 재실행이 그날의
recommendations·decisions 행을 덮어쓴다.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from nuri.core.db import DatabaseError, query
from nuri.core.timezone import sqlite_utc_to_kst_iso

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pipeline"])

# 타임라인 `?step=` 필터의 어휘 — 레거시 6-step 이라 이벤트 어휘와 다르다 (#1785).
VALID_STEPS = ("collect", "validate", "classify", "diagnose", "recommend", "track")

# Frontend PipelineStep presentation (frontend/src/app/pipeline/page.tsx expects this shape).
# `nuri/core/events.PIPELINE_STEPS` 와 같은 5 stage 어휘 (#921).
_STEP_LABELS = {
    "collect": "Collect",
    "analyze": "Analyze",
    "consensus": "Consensus",
    "decide": "Decide",
    "track": "Track",
}
_STEP_DESCRIPTIONS = {
    "collect": "Collector jobs + external sources",
    "analyze": "Factor composite",
    "consensus": "10 agents weighted vote",
    "decide": "Decision record (in-memory hand-off)",
    "track": "7–90d outcomes + alpha",
}
# core event status -> frontend PipelineStep.status enum (idle|running|done|error).
# Robust to both vocabularies: canonical EVENT_TYPES (step_completed/...) and the
# legacy "step_success" left by the run endpoint removed in #1778 and by seeds
# (event-schema drift, normalized at the emit site separately).
_UI_STATUS = {
    "step_started": "running",
    "running": "running",
    "step_completed": "done",
    "completed": "done",
    "step_success": "done",
    "success": "done",
    "step_failed": "error",
    "failed": "error",
    "step_blocked": "error",
    "blocked": "error",
    "unknown": "idle",
    "idle": "idle",
}

_HEARTBEAT_PATH = None  # 테스트에서 monkeypatch 가능


def _get_heartbeat_path():
    if _HEARTBEAT_PATH:
        return _HEARTBEAT_PATH
    from pathlib import Path

    return Path(__file__).parent.parent.parent.parent / "data" / ".scheduler_heartbeat"


@router.get("/scheduler/health")
def get_scheduler_health():
    """스케줄러 heartbeat 상태. 마지막 heartbeat 시각 + 경과 시간."""
    heartbeat_path = _get_heartbeat_path()
    if not heartbeat_path.exists():
        return {"status": "unknown", "detail": "heartbeat 파일 없음 (스케줄러 미실행?)"}

    from datetime import datetime

    from nuri.core.timezone import kst_now

    try:
        last = datetime.fromisoformat(heartbeat_path.read_text().strip())
        age_seconds = (kst_now().replace(tzinfo=None) - last).total_seconds()
        status = "ok" if age_seconds < 600 else "stale"  # 10분 기준
        return {
            "status": status,
            "last_heartbeat": last.isoformat(),
            "age_seconds": round(age_seconds),
        }
    except Exception:
        # Avoid leaking stack traces in HTTP responses (CodeQL py/stack-trace-exposure).
        logger.exception("heartbeat parse failed")
        return {"status": "error", "detail": "heartbeat unavailable"}


@router.get("/pipeline/status")
def get_pipeline_status():
    """5-stage 파이프라인 최신 상태 + 신선도.

    `steps` 는 PIPELINE_STEPS 순서의 **배열** (프론트 PipelineStep[] 계약).
    과거엔 dict {step: {...}} 를 반환 → 프론트가 array(`for...of`/`.length`)로
    소비 못해 항상 하드코딩 DEFAULT_NODES 로 fallback → DAG 가 가짜 데이터였음.
    """
    from nuri.core.events import get_pipeline_status as _step_status_map
    from nuri.core.freshness import get_freshness_summary

    status_map = _step_status_map()  # {step: {step, status, timestamp, payload, record_count}}
    steps = []
    for name, st in status_map.items():
        raw = st.get("status", "unknown")
        payload = st.get("payload")
        steps.append(
            {
                "step": name,
                "label": _STEP_LABELS.get(name, name.title()),
                "description": _STEP_DESCRIPTIONS.get(name, ""),
                "record_count": st.get("record_count", 0) or 0,
                "last_updated": sqlite_utc_to_kst_iso(st.get("timestamp")),
                "status": _UI_STATUS.get(raw, "idle"),
                "started_at": sqlite_utc_to_kst_iso(st.get("timestamp")) if raw == "running" else None,
                "error": payload.get("error") if isinstance(payload, dict) else None,
            }
        )
    # decide 는 독립 cron 이 없으므로 lifecycle 과 실제 원장 산출물을 구분한다.
    for step in steps:
        if step["step"] == "decide":
            step["execution_mode"] = "inline_with_consensus"
            step["artifact"] = _decision_artifact()
    return {"steps": steps, "freshness": get_freshness_summary()}


def _decision_artifact():
    """기록 존재는 판정의 최신성/품질이나 실행 성공을 뜻하지 않는다."""
    try:
        rows = query(
            "SELECT date, COUNT(*) AS count, MAX(created_at) AS recorded_at FROM decisions "
            "GROUP BY date ORDER BY date DESC LIMIT 1"
        )
        return {
            "status": "available" if rows else "empty",
            "date": rows[0]["date"] if rows else None,
            "count": rows[0]["count"] if rows else 0,
            # 다른 스테이지와 같은 시각 축(KST ISO)으로 — date 는 판정일, recorded_at 은 그 판정일 행이
            # **처음** 기록된 시각이다. upsert 는 created_at 을 건드리지 않으므로 같은 날 재실행은
            # 반영되지 않는다 (updated_at 은 추적기가 KST 텍스트로 써서 축이 섞여 쓰지 않는다).
            "recorded_at": sqlite_utc_to_kst_iso(rows[0]["recorded_at"]) if rows else None,
        }
    except DatabaseError:
        logger.exception("decision artifact lookup failed")
        return {"status": "unavailable", "date": None, "count": None, "recorded_at": None}


@router.get("/pipeline/timeline")
def get_pipeline_timeline(
    limit: int = Query(default=50, ge=1, le=500),
    step: str | None = Query(default=None),
):
    """최근 N개 파이프라인 이벤트 타임라인."""
    from nuri.core.events import get_timeline

    if step and step not in VALID_STEPS:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step}. Valid: {', '.join(VALID_STEPS)}")
    events = get_timeline(limit=limit, step=step)
    for event in events:
        event["timestamp"] = sqlite_utc_to_kst_iso(event.get("timestamp"))
    return {"events": events}


@router.get("/freshness")
def get_freshness():
    """전체 데이터 신선도 조회."""
    from nuri.core.freshness import get_freshness_summary

    return get_freshness_summary()
