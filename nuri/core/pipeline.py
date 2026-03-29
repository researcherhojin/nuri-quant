"""파이프라인 스텝 의존성 + 실행 래퍼.

6-step 파이프라인: Collect → Validate → Classify → Diagnose → Recommend → Track
각 스텝은 의존성 충족 시에만 실행 가능.
"""
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from nuri.core.events import emit_event, get_step_status

STEP_DEPENDENCIES: dict[str, list[str]] = {
    "collect": [],
    "validate": ["collect"],
    "classify": ["collect"],
    "diagnose": ["collect", "validate", "classify"],
    "recommend": ["diagnose"],
    "track": ["recommend"],
}


def check_dependencies(step: str, db_path: Optional[Path] = None) -> dict:
    """스텝 의존성 확인 → {ready: bool, missing: [...], details: {...}}."""
    deps = STEP_DEPENDENCIES.get(step, [])
    if not deps:
        return {"ready": True, "missing": [], "details": {}}

    missing = []
    details = {}
    for dep in deps:
        status = get_step_status(dep, db_path)
        details[dep] = status
        if status["status"] != "completed":
            missing.append(dep)

    return {"ready": len(missing) == 0, "missing": missing, "details": details}


def run_step(step: str, func: Callable[..., Any], db_path: Optional[Path] = None, **kwargs) -> dict:
    """파이프라인 스텝 실행 + 이벤트 기록 + 의존성 체크."""
    # 1. 의존성 체크
    deps = check_dependencies(step, db_path)
    if not deps["ready"]:
        emit_event("step_blocked", step, {"blocked_by": deps["missing"]}, db_path=db_path)
        return {"status": "blocked", "missing": deps["missing"]}

    # 2. 시작 이벤트
    start_id = emit_event("step_started", step, db_path=db_path)
    start_time = time.time()

    # 3. 실행
    try:
        result = func(**kwargs)
        duration = int((time.time() - start_time) * 1000)
        record_count = result if isinstance(result, int) else None
        emit_event(
            "step_completed",
            step,
            payload={"summary": str(result)[:500] if result else None},
            duration_ms=duration,
            record_count=record_count,
            causation_id=start_id,
            db_path=db_path,
        )
        return {"status": "success", "duration_ms": duration, "result": result}
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        emit_event(
            "step_failed",
            step,
            payload={"error": str(e)[:500]},
            duration_ms=duration,
            causation_id=start_id,
            db_path=db_path,
        )
        return {"status": "failed", "error": str(e)}
