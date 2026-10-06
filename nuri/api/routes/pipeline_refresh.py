"""대시보드에서 요청한 데이터 갱신. 판정/성과 원장은 변경하지 않는다."""

import logging
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Literal, get_args

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from nuri.api import limits
from nuri.api.auth import require_write_auth
from nuri.core.db import audit_log
from nuri.core.events import emit_event
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
JOB_IDS = frozenset(get_args(Job))  # 테스트가 JOBS 키와 같은지 잠근다 (드리프트 가드)
ORIGIN = "dashboard_refresh"
# 접수(queued) 뒤 이 시간 안에 백그라운드가 시작하지 않으면 버려진 것으로 본다 — Starlette 는 응답 send 가
# 예외로 끝나면 BackgroundTasks 를 돌리지 않아 접수 때 잡은 heavy slot 이 영영 안 풀린다 (Codex #1658 r2 P1).
QUEUE_GRACE_SECONDS = 60
_lock = threading.Lock()
_state: dict | None = None


class RefreshInput(BaseModel):
    jobs: list[Job] = Field(min_length=1, max_length=5)


@router.get("/pipeline/refresh")
def get_refresh():
    with _lock:
        _reclaim_abandoned_locked()
        state = deepcopy(_state)
    return {"jobs": [{"id": key, **value} for key, value in JOBS.items()], "run": _public(state)}


@router.post("/pipeline/refresh", status_code=202)
def start_refresh(body: RefreshInput, background: BackgroundTasks, user=Depends(require_write_auth)):
    global _state
    # 선택 순서에 무관하게 가격 → 지표 → 종합 분석 순서를 보장한다.
    requested = [key for key in JOBS if key in body.jobs]
    with _lock:
        _reclaim_abandoned_locked()
        if _state and _state["status"] in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="이미 데이터 갱신이 진행 중입니다.")
        # heavy slot 은 **접수 시점**에 비블로킹으로 잡는다 — 응답 뒤 백그라운드에서 잡으면 포화가 "실패한 실행"
        # 으로 둔갑하고 클라이언트는 503/Retry-After 계약을 잃는다 (Codex #1658 P2). 해제는 `_release_permit`.
        if not limits._heavy_slots.acquire(blocking=False):
            logger.warning("heavy slot 포화 — dashboard refresh 503 shed")
            raise HTTPException(
                status_code=503,
                detail="서버가 무거운 요청을 처리 중입니다. 잠시 후 다시 시도하세요.",
                headers={"Retry-After": "5"},
            )
        run = {
            "id": uuid.uuid4().hex,
            "status": "queued",
            "started_at": kst_now().isoformat(),
            "finished_at": None,
            "jobs": [{"id": key, "status": "queued"} for key in requested],
            "permit": True,  # 접수 때 잡은 heavy slot 을 아직 쥐고 있는가 (내부 필드)
        }
        # 접수 자체는 DB 에 행을 쓰지 않는다 — 감사 로그만. pipeline_events 는 백그라운드가 남긴다
        # (스테이지 lifecycle 은 run_step, 작업 단위 refresh_job_* 는 _mark).
        audit_log("REFRESH", "pipeline_refresh", run["id"], ",".join(requested), user_id=user.get("sub", "unknown"))
        _state = run
    background.add_task(_run_refresh, run["id"], requested)
    return _public(deepcopy(run))


def _public(run: dict | None) -> dict | None:
    """내부 permit 플래그는 응답에서 뺀다."""
    if run is None:
        return None
    return {key: value for key, value in run.items() if key != "permit"}


def _release_permit_locked(run: dict | None) -> None:
    """접수 때 잡은 heavy slot 을 한 번만 놓는다 (멱등). `_lock` 을 쥔 채 부른다."""
    if run and run.get("permit"):
        run["permit"] = False
        limits._heavy_slots.release()


def _reclaim_abandoned_locked() -> None:
    """백그라운드가 시작하지 못한 채 유예를 넘긴 queued 실행은 abandoned 로 닫고 slot 을 돌려준다."""
    if not _state or _state["status"] != "queued":
        return
    age = (kst_now() - datetime.fromisoformat(_state["started_at"])).total_seconds()
    if age <= QUEUE_GRACE_SECONDS:
        return
    logger.warning("dashboard refresh %s 가 %.0fs 동안 시작하지 않음 — abandoned 로 닫고 slot 반환", _state["id"], age)
    _state["status"] = "abandoned"
    _state["finished_at"] = kst_now().isoformat()
    for job in _state["jobs"]:
        if job["status"] == "queued":
            job["status"] = "skipped"
    _release_permit_locked(_state)


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


def _mark(event_type: str, key: str, run_id: str, **payload):
    """스테이지 lifecycle 행(run_step)과 별도로 **어느 작업이 어디서** 돌았는지 남긴다 — 대시보드의 macro 단독
    갱신이 스케줄러의 collect 성공과 같은 행으로 보이던 것 (Codex #1658 P2). 관측이 본 작업을 막으면 안 된다."""
    try:
        emit_event(event_type, JOBS[key]["stage"], {"origin": ORIGIN, "job": key, "run_id": run_id, **payload})
    except Exception:
        logger.warning("dashboard refresh 이벤트 기록 실패: %s %s", event_type, key, exc_info=True)


def _run_refresh(run_id: str, jobs: list[str]):
    """접수 시 잡은 heavy slot 을 쥔 채 실행하고, 끝나면 반드시 놓는다."""
    from nuri.core.pipeline import run_step

    with _lock:
        # 유예를 넘겨 abandoned 로 닫힌 뒤 늦게 도착한 실행은 돌리지 않는다 — slot 은 이미 반환됐다.
        if not _state or _state["id"] != run_id or _state["status"] != "queued":
            return
        # 이 실행의 run dict 를 **참조로** 붙든다. 완료/실패를 공개한 직후 새 접수가 `_state` 를 바꿔치면
        # `_state` 식별로는 옛 실행의 permit 을 영영 못 놓는다 (Codex #1658 r3 P1) — finally 는 이 참조로 놓는다.
        run = _state
        run["status"] = "running"
    try:
        for key in jobs:
            _job_update(run_id, key, "running")
            _mark("refresh_job_started", key, run_id)
            try:
                run_step(JOBS[key]["stage"], _execute, key=key, warn_only=True, reraise=True)
            except Exception as exc:
                _job_update(run_id, key, "failed")
                _mark("refresh_job_failed", key, run_id, error=str(exc)[:500])
                raise
            _job_update(run_id, key, "completed")
            _mark("refresh_job_completed", key, run_id)
        _update(run_id, status="completed", finished_at=kst_now().isoformat())
    except Exception:
        logger.exception("dashboard data refresh failed")
        for key in jobs:
            with _lock:
                queued = bool(_state and any(j["id"] == key and j["status"] == "queued" for j in _state["jobs"]))
            if queued:
                _job_update(run_id, key, "skipped")
        _update(run_id, status="failed", finished_at=kst_now().isoformat())
    finally:
        with _lock:
            _release_permit_locked(run)


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
