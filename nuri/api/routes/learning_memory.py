"""Learning Memory readiness API — per-agent source breakdown.

#468 codex Plan consult Round 1 #6/#7 — first-class subsystem endpoint.
- Per-agent source label (canonical_30d / provisional_21d / default / structurally_unsaturating)
- Sample counts (BUY+SELL verdicts) per horizon
- Summary counts for operator readiness check

Read-only. No mutation. 5-min in-memory cache (consensus 패턴 일관).
"""

import threading
import time

from fastapi import APIRouter

router = APIRouter(prefix="/learning-memory", tags=["learning-memory"])

_cache = {"data": None, "ts": 0.0}
CACHE_TTL = 300
# single-flight — TTL 만료 시 동시 요청이 전부 재계산하는 걸 막는다 (#1119)
_lock = threading.Lock()


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

    with _lock:
        # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다
        now = time.time()
        if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
            return _cache["data"]
        data = agent_readiness()
        _cache["data"] = data
        _cache["ts"] = now
        return data
