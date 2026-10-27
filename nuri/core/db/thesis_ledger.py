"""thesis 실험 원장 기록 (#1962) — 실행 한 번에 한 행, 추가 전용, 운영 기기에서만.

봉인 · 검증은 `ledger_seal.THESIS_RUNS` 체인이 한다(날짜가 닫히면 봉인, 머리는 월간 #brief).
쓰기는 `NURI_ROLE=production` 에서만 한다 — 그 값은 mini 의 scheduler plist 에만 있다
(`alpha_report.is_production()` 과 같은 게이트). dev 복제본이나 MBP 의 대화형 실행은 원장에 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

PRODUCTION_ROLE = "production"


class NotProductionError(RuntimeError):
    """운영 기기가 아닌 곳에서 원장에 쓰려 했다."""


def _json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_run(
    run: dict[str, Any],
    *,
    cohort_date: str,
    runtime: dict[str, Any],
    canary_sha256: Optional[str],
    db_path: Optional[Path] = None,
) -> int:
    """`thesis_contract.run_baseline` (또는 다단계 팔)의 실행 기록 한 건을 남긴다. 새 행 id."""
    if os.getenv("NURI_ROLE", "").strip().lower() != PRODUCTION_ROLE:
        raise NotProductionError("thesis_runs is written only where NURI_ROLE=production (the scored host)")
    from .provenance import code_rev

    with get_db(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO thesis_runs (cohort_date, arm, arm_hash, ticker, scored, run_hash, packet_hashes, view_hash,
                   prompt_hashes, call_hashes, runtime, canary_sha256, budget_tokens, rating, outcome, code_rev)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cohort_date,
                run["arm"],
                run["arm_hash"],
                run["ticker"],
                int(bool(run["scored"])),
                run["run_hash"],
                _json(run["packet_hashes"]),
                run["view_hash"],
                _json([c["prompt_sha256"] for c in run["calls"]]),
                _json([c["content_hash"] for c in run["calls"]]),
                _json(runtime),
                canary_sha256,
                run["budget_tokens"],
                run["rating"],
                run["outcome"],
                code_rev(),
            ),
        )
        return int(cur.lastrowid or 0)
