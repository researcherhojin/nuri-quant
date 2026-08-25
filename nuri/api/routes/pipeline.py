"""Pipeline API — 파이프라인 상태 조회 + 스텝 실행."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from nuri.api.limits import heavy_slot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pipeline"])
_limiter = Limiter(key_func=get_remote_address)

VALID_STEPS = ("collect", "validate", "classify", "diagnose", "recommend", "track")

# Frontend PipelineStep presentation (frontend/src/app/pipeline/page.tsx expects this shape).
# `nuri/core/events.PIPELINE_STEPS` 와 같은 5 stage 어휘 (#921).
_STEP_LABELS = {
    "collect": "Collect",
    "analyze": "Analyze",
    "consensus": "Consensus",
    "certify": "Certify",
    "track": "Track",
}
_STEP_DESCRIPTIONS = {
    "collect": "27 collectors + external sites",
    "analyze": "Signals, regimes, factor composite",
    "consensus": "10 agents weighted vote",
    "certify": "3-D gates + decision record",
    "track": "30/60/90d outcomes",
}
# core event status -> frontend PipelineStep.status enum (idle|running|done|error).
# Robust to both vocabularies: canonical EVENT_TYPES (step_completed/...) and the
# legacy "step_success" emitted by run_pipeline_step + seeds (event-schema drift,
# normalized at the emit site separately).
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
                "last_updated": st.get("timestamp"),
                "status": _UI_STATUS.get(raw, "idle"),
                "started_at": st.get("timestamp") if raw == "running" else None,
                "error": payload.get("error") if isinstance(payload, dict) else None,
            }
        )
    return {"steps": steps, "freshness": get_freshness_summary()}


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
    return {"events": events}


@router.post("/pipeline/{step}/run", dependencies=[Depends(heavy_slot)])
@_limiter.limit("2/minute")
def run_pipeline_step(step: str, request: Request):
    """특정 파이프라인 스텝 실행 (동기)."""
    if step not in VALID_STEPS:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step}. Valid: {', '.join(VALID_STEPS)}")

    from nuri.core.events import emit_event

    start = time.time()
    emit_event("step_started", step=step)

    try:
        detail = _execute_step(step)
        duration_ms = int((time.time() - start) * 1000)
        emit_event("step_success", step=step, duration_ms=duration_ms, payload={"detail": detail})
        return {"status": "success", "duration_ms": duration_ms, "detail": detail}
    except Exception:
        # Log full exception (incl. stack) server-side, return generic detail to client
        # to avoid leaking internals (CodeQL py/stack-trace-exposure). The pipeline event
        # journal still records the failure for operator audit.
        duration_ms = int((time.time() - start) * 1000)
        logger.exception("pipeline step %s failed", step)
        emit_event("step_failed", step=step, duration_ms=duration_ms, payload={"error": "step execution failed"})
        return {"status": "failed", "duration_ms": duration_ms, "detail": f"step '{step}' execution failed"}


@router.get("/freshness")
def get_freshness():
    """전체 데이터 신선도 조회."""
    from nuri.core.freshness import get_freshness_summary

    return get_freshness_summary()


def _execute_step(step: str) -> str:
    """스텝별 실행 함수 매핑."""
    if step == "collect":
        return "not_implemented: collect requires individual collector runs"
    elif step == "validate":
        from nuri.quant.validation.signal_backtest import backtest_signals

        result = backtest_signals()
        return f"signal_backtest: {len(result) if result else 0} signals"
    elif step == "classify":
        from nuri.quant.regime.classifier import classify_regime

        r = classify_regime()
        if r:
            return f"regime={r.regime}, trend={r.trend}, confidence={r.confidence:.0%}"
        return "regime=unknown (데이터 부족)"
    elif step == "diagnose":
        from nuri.trading.agents.consensus import analyze_portfolio

        results = analyze_portfolio()
        return f"consensus: {len(results)} tickers analyzed"
    elif step == "recommend":
        from nuri.trading.recommend.candidates import screen_candidates

        candidates = screen_candidates()
        return f"candidates: {len(candidates)} found"
    elif step == "track":
        from nuri.trading.recommend.tracker import track_outcomes

        tracked = track_outcomes()
        return f"tracked: {tracked} recommendations updated"
    return "unknown step"
