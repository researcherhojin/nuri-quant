"""레짐 + 매크로 + LLM 리포트 API."""

import logging
import threading
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from nuri.api.limits import heavy_slot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["regime"])

# `/report/context` 는 캐시가 없어 **매 요청** 전액을 물었다 — 실측 28.4초, warm 도
# 28.9초 (#1119). 분해하면 `gather_context()` 안의 `consensus.analyze_portfolio`
# 하나가 약 20초로, 바로 옆 `/api/consensus` 가 5분 캐시로 이미 갖고 있는 계산이다.
# 나머지는 screen_candidates 3.58s + detect_conflicts 3.52s + 그 외 0.76s.
#
# 여기서는 다른 라우트와 같은 TTL + single-flight 만 붙인다. 구조적 해법
# (gather_context 가 `recommendations` 에 저장된 합의를 읽게 하는 것 —
# `ticker.py::_read_consensus_from_db` 에 선례가 있다) 은 LLM 리포트가 보는
# 내용을 바꾸므로 별건이다.
_context_cache: dict = {"data": None, "ts": 0.0}
CONTEXT_CACHE_TTL = 300  # 5분
_context_lock = threading.Lock()


@router.get("/regime")
def get_regime():
    """현재 시장 레짐."""
    from nuri.quant.regime.classifier import classify_regime

    state = classify_regime()
    if state is None:
        return {"error": "SPY 데이터 부족"}
    return asdict(state)


@router.get("/macro")
def get_macro():
    """매크로 스코어."""
    from nuri.quant.regime.macro_score import compute_macro_score

    score = compute_macro_score()
    return asdict(score)


@router.get("/report", dependencies=[Depends(heavy_slot)])
def get_report():
    """LLM 리포트 (Gate → Context → Generate → Validate)."""
    from nuri.llm.report import generate_llm_report

    try:
        return generate_llm_report()
    except Exception:
        # Avoid leaking stack traces in HTTP responses (CodeQL py/stack-trace-exposure).
        logger.exception("LLM report generation failed")
        raise HTTPException(status_code=500, detail="LLM report generation failed")


@router.get("/report/context", dependencies=[Depends(heavy_slot)])
def get_report_context():
    """LLM 리포트 컨텍스트 (프롬프트 입력 데이터). 5분 캐시 + single-flight."""
    from nuri.llm.report import format_prompt, gather_context

    now = time.time()
    if _context_cache["data"] and (now - _context_cache["ts"]) < CONTEXT_CACHE_TTL:
        return _context_cache["data"]

    with _context_lock:
        # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다
        now = time.time()
        if _context_cache["data"] and (now - _context_cache["ts"]) < CONTEXT_CACHE_TTL:
            return _context_cache["data"]
        ctx = gather_context()
        result = {
            "prompt": format_prompt(ctx),
            "gate_score": ctx.gate_score,
            "known_tickers": list(ctx.known_tickers),
        }
        _context_cache["data"] = result
        _context_cache["ts"] = now
        return result


@router.get("/strategy")
def get_strategy():
    """레짐별 전략 추천."""
    from nuri.quant.regime.strategy_map import map_regime_to_strategy

    rec = map_regime_to_strategy()
    if rec is None:
        return {"error": "데이터 부족"}
    return {
        "regime": rec.regime,
        "macro_interpretation": rec.macro_interpretation,
        "position_sizing": rec.position_sizing,
        "recommended_signals": rec.recommended_signals,
        "avoid_signals": rec.avoid_signals,
        "sector_preference": rec.sector_preference,
        "signal_regime_stats": rec.signal_regime_stats,
        "notes": rec.notes,
    }
