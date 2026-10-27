"""Discord 로 나갈 수 있는 thesis 이벤트의 허용 목록 (#1965). 모델 글·오류 원문은 포함하지 않는다."""

import re
from typing import Any

PREFIX = "NURI_THESIS_EVENT "
STAGE_LABELS = {
    "analyst:market": "시장·기술 분석",
    "analyst:fundamentals": "기업 기초체력 분석",
    "analyst:news": "뉴스 분석",
    "analyst:sentiment": "수급·시장심리 분석",
    "researcher:bull": "강세 논거 검증",
    "researcher:bear": "약세 논거 검증",
    "manager": "종합 판정",
}
STAGES = tuple(STAGE_LABELS)
STATUSES = {"started", "ok", "absent", "failed"}
RATINGS = {"Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"}
ERRORS = {"run_failed", "timeout", "stream_failed"}


def public_event(value: Any) -> dict[str, str] | None:
    """생산자와 소비자 양쪽에서 적용한다. 알 수 없는 값은 원문 없이 버린다."""
    if not isinstance(value, dict):
        return None
    event = value.get("event")
    if event == "stage":
        stage, status = value.get("stage"), value.get("status")
        if isinstance(stage, str) and stage in STAGES and isinstance(status, str) and status in STATUSES:
            return {"event": "stage", "stage": stage, "status": status}
    elif event == "result":
        rating, outcome, run_hash = value.get("rating"), value.get("outcome"), value.get("run_hash")
        if (
            isinstance(rating, str)
            and rating in RATINGS
            and isinstance(outcome, str)
            and outcome in {"verdict", "review", "failed"}
            and isinstance(run_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", run_hash)
            and ((outcome == "verdict" and rating != "REVIEW") or (outcome != "verdict" and rating == "REVIEW"))
        ):
            return {"event": "result", "rating": rating, "outcome": outcome, "run_hash": run_hash}
    elif event == "error":
        code = value.get("code")
        if isinstance(code, str) and code in ERRORS:
            return {"event": "error", "code": code}
    return None
