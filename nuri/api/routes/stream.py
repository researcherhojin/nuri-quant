"""SSE 스트림 — 대시보드 실시간 업데이트. 60초 메모리 캐시."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])

# 업데이트 간격 (초)
INTERVAL = 30

# Next 의 /api/* rewrite 프록시는 30초 동안 바이트가 없으면 소켓을 abort 한다
# (next/dist/server/lib/router-utils/proxy-request.js — `proxyTimeout || 30000`,
# next.config 에 experimental.proxyTimeout 미설정이라 기본값 적용). INTERVAL 이
# 정확히 30 이라 데이터 간격이 임계값과 같아 매 주기 끊긴다.
# 그보다 짧은 주기로 SSE 주석을 흘려 소켓을 살려둔다 — EventSource 는 ':' 로
# 시작하는 줄을 무시하므로 클라이언트 변경이 필요 없다.
# 참고: 응답의 `X-Accel-Buffering: no` 는 nginx 지시어라 Node 프록시엔 무효.
KEEPALIVE_INTERVAL = 10

# 메모리 캐시 (DB 직접 조회 대신 60초 갱신)
_CACHE_TTL = 60
_cache: dict = {}
_cache_time: float = 0


def _get_snapshot() -> dict:
    """현재 상태 스냅샷 (60초 캐시)."""
    global _cache, _cache_time
    now = time.time()
    if now - _cache_time < _CACHE_TTL and _cache:
        return {**_cache, "timestamp": now, "cached": True}

    # 값 타입을 명시한다 — 첫 항목이 float 라 추론이 `dict[str, float]` 로 굳고,
    # 그 뒤 regime(str) · vix(None 가능) 대입이 전부 타입 오류가 된다. 런타임은 멀쩡했지만
    # 그 오류 3건이 노이즈 바닥에 섞여 **이 파일의 진짜 오류를 가린다**.
    result: dict[str, Any] = {"timestamp": now}

    try:
        from nuri.quant.regime.classifier import classify_regime

        r = classify_regime()
        if r:
            result["regime"] = r.regime
            result["confidence"] = round(r.confidence * 100)
            result["vix"] = r.details.get("vix")
            result["fear_greed"] = r.details.get("fear_greed")
    except Exception:
        pass

    try:
        from nuri.quant.regime.macro_score import compute_macro_score

        m = compute_macro_score()
        result["macro_score"] = round(m.total_score)
    except Exception:
        pass

    try:
        from nuri.core.db import query

        positions = query("SELECT COUNT(*) as c FROM positions WHERE status='open'")
        result["open_positions"] = positions[0]["c"] if positions else 0
    except Exception:
        pass

    _cache = result
    _cache_time = now
    return result


async def _event_generator():
    """SSE 이벤트 생성기."""
    while True:
        try:
            snapshot = _get_snapshot()
            data = json.dumps(snapshot, ensure_ascii=False)
            yield f"data: {data}\n\n"
        except Exception:
            # Log full exception server-side, send a generic SSE error event to
            # the client (CodeQL py/stack-trace-exposure).
            logger.exception("SSE snapshot error")
            yield f"data: {json.dumps({'error': 'snapshot unavailable'})}\n\n"

        # INTERVAL 을 KEEPALIVE_INTERVAL 조각으로 쪼개 대기하며 주석을 흘린다.
        remaining = INTERVAL
        while remaining > 0:
            nap = min(KEEPALIVE_INTERVAL, remaining)
            await asyncio.sleep(nap)
            remaining -= nap
            if remaining > 0:
                yield ": keepalive\n\n"


@router.get("/stream")
async def stream():
    """SSE 엔드포인트 — 30초마다 상태 스냅샷 전송."""
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
