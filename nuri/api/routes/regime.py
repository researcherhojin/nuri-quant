"""레짐 + 매크로 + LLM 리포트 API."""
import asyncio
from dataclasses import asdict

from fastapi import APIRouter

router = APIRouter(tags=["regime"])


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


@router.get("/report")
async def get_report():
    """LLM 리포트 (Gate → Context → Generate → Validate). 비동기 실행으로 이벤트 루프 블로킹 방지."""
    from nuri.llm.report import generate_llm_report
    return await asyncio.to_thread(generate_llm_report)


@router.get("/report/context")
def get_report_context():
    """LLM 리포트 컨텍스트 (프롬프트 입력 데이터)."""
    from nuri.llm.report import format_prompt, gather_context
    ctx = gather_context()
    return {
        "prompt": format_prompt(ctx),
        "gate_score": ctx.gate_score,
        "known_tickers": list(ctx.known_tickers),
    }


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
