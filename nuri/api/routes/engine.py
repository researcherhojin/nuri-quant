"""SIEGE-inspired engine API: gate, conflicts, memory."""
from dataclasses import asdict

from fastapi import APIRouter

router = APIRouter(tags=["engine"])


@router.get("/gate")
def get_gate():
    """파이프라인 게이트 상태 (전 단계)."""
    from nuri.engine.gate import check_all_gates
    gates = check_all_gates()
    return {
        phase: asdict(result) for phase, result in gates.items()
    }


@router.get("/gate/{phase}")
def get_gate_phase(phase: str):
    """특정 단계 게이트 상태."""
    from nuri.engine.gate import check_gate
    result = check_gate(phase)
    return asdict(result)


@router.get("/conflicts")
def get_conflicts():
    """시그널 충돌 감지."""
    from nuri.engine.conflicts import detect_conflicts
    conflicts = detect_conflicts()
    return {
        "conflicts": [asdict(c) for c in conflicts],
        "count": len(conflicts),
        "high": len([c for c in conflicts if c.severity == "high"]),
    }


@router.get("/memory")
def get_memory():
    """전략 학습 메모리 — 성과 변화 감지."""
    from nuri.engine.memory import detect_drift
    drifts = detect_drift()
    return {
        "drifts": [asdict(d) for d in drifts],
        "critical": len([d for d in drifts if d.status == "critical"]),
        "degrading": len([d for d in drifts if d.status == "degrading"]),
    }


@router.post("/memory/snapshot")
def post_memory_snapshot():
    """전략 성과 스냅샷 저장."""
    from nuri.engine.memory import save_snapshot
    n = save_snapshot()
    return {"saved": n}
