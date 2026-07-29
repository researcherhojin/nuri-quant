"""파이프라인 스텝 의존성 + 실행 래퍼.

5-stage 파이프라인: Collect → Analyze → Consensus → Certify → Track
각 스텝은 의존성 충족 시에만 실행 가능.

⚠️ 예전 6-step 어휘(Collect/Validate/Classify/Diagnose/Recommend/Track)는 #921 에서
폐기됐다 — 그 이름들은 더 이상 어디에도 존재하지 않는다. `STEP_DEPENDENCIES` 가 canonical.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from nuri.core.events import emit_event, get_step_status

logger = logging.getLogger(__name__)

# 스테이지 의존성 — `nuri/core/events.PIPELINE_STEPS` 와 같은 어휘.
# 이 DAG 는 **차단하지 않는다**: 스케줄러는 warn_only=True 로 호출해, 의존성이
# 안 맞으면 경고 이벤트만 남기고 실행은 그대로 진행한다. 진단이 본 작업을 막으면
# DB 하나 삐끗했을 때 파이프라인 전체가 조용히 서기 때문이다 (#894 학습).
STEP_DEPENDENCIES: dict[str, list[str]] = {
    "collect": [],
    "analyze": ["collect"],
    "consensus": ["collect"],
    "certify": ["consensus"],
    "track": ["consensus"],
}


def _safe_emit(*args, **kwargs) -> int | None:
    """이벤트 기록 실패가 본 작업을 죽이지 않게 한다.

    CI 가 실제로 이걸 잡았다: `pipeline_events` 테이블이 없는 환경에서
    `emit_event` 가 OperationalError 를 던졌고, 그게 `run_step` 밖으로 나가
    **감싼 함수가 아예 실행되지 않았다**. warn_only 로 "차단하지 않는다" 를
    만들어 놓고, 텔레메트리 자체가 게이트가 된 셈이다.

    관측은 실패해도 조용히 실패해야 한다 ([[feedback_observability_must_not_gate]]).
    """
    try:
        return emit_event(*args, **kwargs)
    except Exception:  # noqa: BLE001 — 관측 실패는 본 작업과 무관
        logger.debug("pipeline 이벤트 기록 실패 (무시): %s", args[0] if args else "?", exc_info=True)
        return None


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


def run_step(
    step: str,
    func: Callable[..., Any],
    db_path: Optional[Path] = None,
    *,
    warn_only: bool = False,
    reraise: bool = False,
    **kwargs,
) -> dict:
    """스테이지 실행 + lifecycle 이벤트 기록 + 의존성 체크.

    Args:
        warn_only: True 면 의존성 미충족이어도 **실행한다**. 경고를 이벤트로
            남기고 결과에 `dependency_warning` 을 실어 보낸다. 스케줄러는 항상
            이 모드로 부른다 — 관측이 본 작업을 막으면 안 된다.
        reraise: True 면 step_failed 를 남긴 뒤 원래 예외를 그대로 다시 던진다.
            호출자가 이미 자기 로깅/복구를 갖고 있을 때 쓴다 — 여기서 삼키면
            그 로깅이 죽고, 실패가 성공처럼 기록된다.
    """
    # 1. 의존성 체크
    deps = check_dependencies(step, db_path)
    warning = None
    if not deps["ready"]:
        if not warn_only:
            _safe_emit("step_blocked", step, {"blocked_by": deps["missing"]}, db_path=db_path)
            return {"status": "blocked", "missing": deps["missing"]}
        warning = deps["missing"]
        _safe_emit("step_dependency_warning", step, {"missing": warning}, db_path=db_path)

    # 2. 시작 이벤트
    start_id = _safe_emit("step_started", step, db_path=db_path)
    start_time = time.time()

    # 3. 실행
    try:
        result = func(**kwargs)
        duration = int((time.time() - start_time) * 1000)
        record_count = result if isinstance(result, int) else None
        _safe_emit(
            "step_completed",
            step,
            payload={"summary": str(result)[:500] if result else None},
            duration_ms=duration,
            record_count=record_count,
            causation_id=start_id,
            db_path=db_path,
        )
        return {"status": "success", "duration_ms": duration, "result": result, "dependency_warning": warning}
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        _safe_emit(
            "step_failed",
            step,
            payload={"error": str(e)[:500]},
            duration_ms=duration,
            causation_id=start_id,
            db_path=db_path,
        )
        if reraise:
            raise
        return {"status": "failed", "error": str(e)}
