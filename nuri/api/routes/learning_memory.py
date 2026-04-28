"""Learning Memory readiness API — per-agent source breakdown.

#468 codex Plan consult Round 1 #6/#7 — first-class subsystem endpoint.
- Per-agent source label (canonical_30d / provisional_21d / default / structurally_unsaturating)
- Sample counts (BUY+SELL verdicts) per horizon
- Summary counts for operator readiness check

Read-only. No mutation. 5-min in-memory cache (consensus 패턴 일관).
"""
import time

from fastapi import APIRouter

router = APIRouter(prefix="/learning-memory", tags=["learning-memory"])

_cache = {"data": None, "ts": 0.0}
CACHE_TTL = 300


@router.get("/readiness")
def get_readiness():
    """Per-agent Learning Memory readiness state.

    Response shape:
        {
            "agents": [
                {
                    "name": "technical",
                    "default_weight": 0.152,
                    "final_weight": 0.165,
                    "source": "canonical_30d" | "provisional_21d" | "default" | "structurally_unsaturating",
                    "canonical_30d": {"sample_count": int, "eligible": bool, "weight": float},
                    "provisional_21d": {"sample_count": int, "eligible": bool, "weight": float},
                },
                ...
            ],
            "summary": {
                "canonical_30d": int,
                "provisional_21d": int,
                "default": int,
                "structurally_unsaturating": int,
            },
        }
    """
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    from nuri.trading.agents.consensus import agent_readiness

    data = agent_readiness()
    _cache["data"] = data
    _cache["ts"] = now
    return data
