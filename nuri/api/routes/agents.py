"""멀티 에이전트 합의 API — 캐시 적용 + SSE 스트리밍."""

import asyncio
import json
import queue
import threading
import time
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["agents"])

# 큐 폴링 간격 / SSE 주석 keepalive 주기 (초). 근거는 stream.py 상단 주석 참조 —
# Next rewrite 프록시의 30초 무통신 abort 를 피하기 위한 값이다.
_POLL_INTERVAL = 0.05
KEEPALIVE_INTERVAL = 10

_cache = {"data": None, "ts": 0}
CACHE_TTL = 300  # 5분


@router.get("/consensus")
def get_consensus():
    """전 종목 멀티 에이전트 합의 (5분 캐시)."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    from nuri.trading.agents.consensus import analyze_portfolio

    results = analyze_portfolio()

    # VIX/regime 정보 (반포지션 배너용)
    regime_info = None
    try:
        from nuri.quant.regime.classifier import classify_regime

        regime = classify_regime()
        if regime:
            regime_info = {
                "regime": regime.regime,
                "trend": regime.trend,
                "vix": regime.details.get("vix") if regime.details else None,
                "fear_greed": regime.details.get("fear_greed") if regime.details else None,
            }
    except Exception:
        pass

    # A-2b: scoring_detail 은 _build_consensus (PR #364) 에서 채워짐.
    # `source="consensus"`/`schema_version=1`/`contributions`/`basis_action`/
    # `final_action_source` 필드 포함. frontend A-2c 가 이 dict 를 consume.
    data = {
        "regime": regime_info,
        "results": [
            {
                "ticker": r.ticker,
                "final_action": r.final_action,
                "final_confidence": r.final_confidence,
                "agreement_rate": r.agreement_rate,
                "verdicts": [asdict(v) for v in r.verdicts],
                "dissent": r.dissent,
                "reasoning": r.reasoning,
                "divergence_flag": r.divergence_flag,
                "divergence_reason": r.divergence_reason,
                "scoring_detail": r.scoring_detail,
            }
            for r in results
        ],
        "count": len(results),
    }
    _cache["data"] = data
    _cache["ts"] = now
    return data


@router.get("/consensus/{ticker}")
def get_consensus_ticker(ticker: str):
    """단일 종목 멀티 에이전트 합의."""
    from nuri.trading.agents.consensus import analyze_ticker

    r = analyze_ticker(ticker.upper())
    return {
        "ticker": r.ticker,
        "final_action": r.final_action,
        "final_confidence": r.final_confidence,
        "agreement_rate": r.agreement_rate,
        "verdicts": [asdict(v) for v in r.verdicts],
        "dissent": r.dissent,
        "reasoning": r.reasoning,
        "divergence_flag": r.divergence_flag,
        "divergence_reason": r.divergence_reason,
        "scoring_detail": r.scoring_detail,
    }


@router.get("/consensus/{ticker}/stream")
async def stream_consensus_ticker(ticker: str):
    """단일 종목 에이전트 reasoning trace — SSE 스트리밍."""

    async def _event_generator():
        q: queue.Queue = queue.Queue()

        def _run():
            from nuri.trading.agents.consensus import stream_analyze_ticker

            for event_type, data in stream_analyze_ticker(ticker.upper()):
                q.put((event_type, data))
            q.put(None)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            # 큐가 빌 동안은 바이트가 전혀 안 나간다. 에이전트 1개 LLM 호출이
            # 30초를 넘기면 Next rewrite 프록시가 소켓을 abort 하고
            # (proxy-request.js `proxyTimeout || 30000`), use-trace-stream 은
            # onerror 에서 es.close() 를 부르므로 복구되지 않는다.
            # stream.py 와 같은 이유로 주석 keepalive 를 흘린다.
            waited = 0.0
            while q.empty():
                await asyncio.sleep(_POLL_INTERVAL)
                waited += _POLL_INTERVAL
                if waited >= KEEPALIVE_INTERVAL:
                    waited = 0.0
                    yield ": keepalive\n\n"
            item = q.get()
            if item is None:
                break
            event_type, data = item
            payload = json.dumps(
                {"type": event_type, "data": asdict(data)},
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
