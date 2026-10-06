"""대시보드에서 요청한 데이터 갱신. 판정/성과 원장은 변경하지 않는다."""

import logging
import threading
import uuid
from contextlib import contextmanager
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from nuri.api.auth import require_write_auth
from nuri.api.limits import heavy_slot
from nuri.core.db import audit_log
from nuri.core.timezone import kst_now

router = APIRouter(tags=["pipeline"])
logger = logging.getLogger(__name__)
Job = Literal["prices", "macro", "technical", "fundamentals", "factors"]
JOBS = {
    "prices": {
        "label": "미국·한국 주가 수집",
        "keys": ["prices"],
        "stage": "collect",
        "description": "보유·관심 종목의 가격을 외부 데이터 제공처에서 수집합니다.",
    },
    "macro": {
        "label": "경제 지표·환율 수집",
        "keys": ["macro_vix"],
        "stage": "collect",
        "description": "VIX와 경제 지표, 환율을 수집합니다.",
    },
    "technical": {
        "label": "기술 지표 재계산",
        "keys": ["signals", "signals_kr"],
        "stage": "collect",
        "description": "저장된 주가로 미국·한국 기술 지표를 계산합니다. 주가가 오래되었다면 먼저 수집하세요.",
    },
    "fundamentals": {
        "label": "기업 재무정보 수집",
        "keys": ["fundamentals", "fundamentals_kr"],
        "stage": "collect",
        "description": "보유·관심 기업의 재무정보를 수집합니다. 여러 분이 걸릴 수 있습니다.",
    },
    "factors": {
        "label": "종합 분석 재계산",
        "keys": ["factors"],
        "stage": "analyze",
        "description": "저장된 가격·재무정보로 종합 분석 점수를 다시 계산합니다.",
    },
}
_lock = threading.Lock()
_state: dict | None = None


class RefreshInput(BaseModel):
    jobs: list[Job] = Field(min_length=1, max_length=5)


@router.get("/pipeline/refresh")
def get_refresh():
    with _lock:
        state = deepcopy(_state)
    return {"jobs": [{"id": key, **value} for key, value in JOBS.items()], "run": state}


@router.post("/pipeline/refresh", status_code=202)
def start_refresh(body: RefreshInput, background: BackgroundTasks, user=Depends(require_write_auth)):
    global _state
    # 선택 순서에 무관하게 가격 → 지표 → 종합 분석 순서를 보장한다.
    requested = [key for key in JOBS if key in body.jobs]
    with _lock:
        if _state and _state["status"] in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="이미 데이터 갱신이 진행 중입니다.")
        run = {
            "id": uuid.uuid4().hex,
            "status": "queued",
            "started_at": kst_now().isoformat(),
            "finished_at": None,
            "jobs": [{"id": key, "status": "queued"} for key in requested],
        }
        audit_log("INSERT", "pipeline_events", run["id"], ",".join(requested), user_id=user.get("sub", "unknown"))
        _state = run
    background.add_task(_run_refresh, run["id"], requested)
    return deepcopy(run)


def _update(run_id: str, **values):
    with _lock:
        if _state and _state["id"] == run_id:
            _state.update(values)


def _job_update(run_id: str, key: str, status: str):
    with _lock:
        if _state and _state["id"] == run_id:
            for job in _state["jobs"]:
                if job["id"] == key:
                    job["status"] = status


def _run_refresh(run_id: str, jobs: list[str]):
    from nuri.core.pipeline import run_step

    _update(run_id, status="running")
    try:
        # 응답은 즉시 반환하지만 실제 작업의 전 구간은 heavy slot 을 차지한다.
        with contextmanager(heavy_slot)():
            for key in jobs:
                _job_update(run_id, key, "running")
                try:
                    run_step(JOBS[key]["stage"], _execute, key=key, warn_only=True, reraise=True)
                except Exception:
                    _job_update(run_id, key, "failed")
                    raise
                _job_update(run_id, key, "completed")
        _update(run_id, status="completed", finished_at=kst_now().isoformat())
    except Exception:
        logger.exception("dashboard data refresh failed")
        for key in jobs:
            with _lock:
                queued = bool(_state and any(j["id"] == key and j["status"] == "queued" for j in _state["jobs"]))
            if queued:
                _job_update(run_id, key, "skipped")
        _update(run_id, status="failed", finished_at=kst_now().isoformat())


def _execute(key: str):
    if key == "prices":
        from nuri.collectors.stock import StockCollector
        from nuri.collectors.stock_kr import StockKRCollector

        return (StockCollector().run(source="all") or 0) + (StockKRCollector().run(source="all") or 0)
    if key == "macro":
        from nuri.collectors.macro import MacroCollector

        return MacroCollector().run()
    if key == "technical":
        from nuri.collectors.technical import TechnicalCollector

        return TechnicalCollector().run(source="all")
    if key == "fundamentals":
        from nuri.collectors.fundamental import FundamentalCollector

        return FundamentalCollector().run(source="all")
    if key == "factors":
        from nuri.quant.factors.composite import compute_composite, save_composite

        return save_composite(compute_composite())
    raise ValueError("unsupported refresh job")
