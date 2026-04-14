"""Universe + Agent coverage API (#272 Phase 4).

Frontend의 Dashboard widget이 5/5 PASS 현황을 시각적으로 표시할 수 있도록
`nuri.core.coverage`의 순수 함수 결과를 JSON 으로 노출.

KR "n/a (US-only)" 구분은 `US_ONLY_TABLES` 멤버십으로 결정 (#288 참고).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["coverage"])


@router.get("/coverage")
def get_coverage() -> dict:
    """Universe + Agent 데이터 coverage 현황.

    Returns:
        {
            "pass": int, "fail": int, "exit_code": 0|1,
            "checks": [
                {
                    "name": "data.prices",
                    "actual": 0.99, "threshold": 0.95,
                    "status": "PASS"|"FAIL",
                    "detail": "537/543 US tickers (KR n/a — 소스 미지원)",
                    "us_only": true|false,
                },
                ...
            ],
        }
    """
    try:
        from nuri.core.coverage import (
            US_ONLY_TABLES,
            compute_all_data_coverage,
            summary,
        )

        checks = compute_all_data_coverage()
        payload = summary(checks)

        # Annotate each check with `us_only` flag so the frontend can render
        # the "n/a (US-only)" KR label without re-implementing the heuristic.
        for c in payload["checks"]:
            table_name = c["name"].replace("data.", "", 1)
            c["us_only"] = table_name in US_ONLY_TABLES

        return payload
    except Exception:
        # Avoid leaking stack traces in HTTP responses (CodeQL py/stack-trace-exposure).
        logger.exception("coverage computation failed")
        return {"error": "coverage computation failed"}
