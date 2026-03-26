"""멀티 에이전트 합의 API — 캐시 적용."""
import time
from dataclasses import asdict
from fastapi import APIRouter

router = APIRouter(tags=["agents"])

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
    data = {
        "results": [
            {
                "ticker": r.ticker,
                "final_action": r.final_action,
                "final_confidence": r.final_confidence,
                "agreement_rate": r.agreement_rate,
                "verdicts": [asdict(v) for v in r.verdicts],
                "dissent": r.dissent,
                "reasoning": r.reasoning,
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
    }
