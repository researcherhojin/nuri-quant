"""SSE 스트림 — 대시보드 실시간 업데이트. 60초 메모리 캐시."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])

# 업데이트 간격 (초)
INTERVAL = 30

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

    result = {"timestamp": now}

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
        except Exception as e:
            logger.debug(f"SSE snapshot error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        await asyncio.sleep(INTERVAL)


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
