"""thesis 실험 원장 기록 (#1962) — 실행 한 번에 한 행, 추가 전용, 운영 기기에서만.

봉인 · 검증은 `ledger_seal.THESIS_RUNS` 체인이 한다(날짜가 닫히면 봉인, 머리는 월간 #brief).
쓰기는 `NURI_ROLE=production` 에서만 한다 — 그 값은 mini 의 scheduler plist 에만 있다
(`alpha_report.is_production()` 과 같은 게이트). dev 복제본이나 MBP 의 대화형 실행은 원장에 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import timezone
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

PRODUCTION_ROLE = "production"


class NotProductionError(RuntimeError):
    """운영 기기가 아닌 곳에서 원장에 쓰려 했다."""


def _json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def require_production() -> None:
    """채점 배치는 시작 전에 이걸 부른다 — 끝까지 돌린 뒤 기록 단계에서 거부당하지 않게 (#1981)."""
    _require_production()


def _require_production() -> None:
    if os.getenv("NURI_ROLE", "").strip().lower() != PRODUCTION_ROLE:
        raise NotProductionError("thesis ledger tables are written only where NURI_ROLE=production (the scored host)")


def record_run(
    run: dict[str, Any],
    *,
    experiment: str,
    batch_id: str,
    cohort_date: str,
    cutoff: str,
    late: bool,
    runtime: dict[str, Any],
    canary_sha256: Optional[str],
    db_path: Optional[Path] = None,
) -> int:
    """`thesis_contract.run_baseline` (또는 다단계 팔)의 실행 기록 한 건을 남긴다. 새 행 id.

    `cutoff` 는 묶음 기준 시점(ISO) — 진입(그 뒤 첫 NYSE 개장)이 여기서 정해진다 (#1966). `late` 는 이 기록이
    그 개장 뒤에 일어났는가 — 호출자가 실제 기록 시각으로 계산한다.
    """
    _require_production()
    if not experiment.strip():
        raise ValueError("a scored run needs a non-blank experiment tag")
    from .provenance import code_rev

    with get_db(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO thesis_runs (experiment, batch_id, cohort_date, arm, arm_hash, ticker, cutoff, late, scored,
                   run_hash, packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, canary_sha256, budget_tokens,
                   rating, size, outcome, code_rev)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment,
                batch_id,
                cohort_date,
                run["arm"],
                run["arm_hash"],
                run["ticker"],
                cutoff,
                int(bool(late)),
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
                run.get("size"),
                run["outcome"],
                code_rev(),
            ),
        )
        return int(cur.lastrowid or 0)


def record_return(row: dict[str, Any], *, db_path: Optional[Path] = None) -> None:
    """(종목, cutoff) 의 정산 한 건 — 이미 있으면 그대로 둔다(정산은 한 번)."""
    _require_production()
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO thesis_returns (ticker, cutoff, status, entry_session, exit_session, exit_close_at,
                   raw_return, benchmark, benchmark_return, alpha, series, fetched_at)
               VALUES (:ticker, :cutoff, :status, :entry_session, :exit_session, :exit_close_at, :raw_return,
                   :benchmark, :benchmark_return, :alpha, :series, :fetched_at)""",
            {**row, "series": _json(row["series"])},
        )


def record_reflection(row: dict[str, Any], *, db_path: Optional[Path] = None) -> None:
    """실행 하나의 reflection — 이미 있으면 그대로 둔다."""
    _require_production()
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO thesis_reflections (run_id, decision_text, decision_sha256, reflection,
                   call_content_hash, created_at)
               VALUES (:run_id, :decision_text, :decision_sha256, :reflection, :call_content_hash, :created_at)""",
            row,
        )


def _utc_now() -> str:
    from nuri.core.timezone import kst_now

    return kst_now().astimezone(timezone.utc).isoformat()


def start_batch(experiment: str, canary_sha256: str, *, db_path: Optional[Path] = None) -> str:
    """채점 배치 시작 — 시작 canary 를 남기고 `open`. 새 batch_id."""
    _require_production()
    if not experiment.strip():
        raise ValueError("a scored batch needs a non-blank experiment tag")
    batch_id = uuid.uuid4().hex
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO thesis_batches (batch_id, experiment, started_at, canary_start, status) "
            "VALUES (?, ?, ?, ?, 'open')",
            (batch_id, experiment, _utc_now(), canary_sha256),
        )
    return batch_id


def end_batch(batch_id: str, canary_sha256: Optional[str], *, db_path: Optional[Path] = None) -> str:
    """배치 끝 — 끝 canary 가 시작과 같으면 `ok`, 다르거나 못 쟀으면 `canary_changed`. 상태를 돌려준다."""
    _require_production()
    with get_db(db_path) as conn:
        row = conn.execute("SELECT canary_start, status FROM thesis_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None or row[1] != "open":
            raise ValueError(f"batch {batch_id} is not open")
        status = "ok" if canary_sha256 is not None and canary_sha256 == row[0] else "canary_changed"
        conn.execute(
            "UPDATE thesis_batches SET ended_at = ?, canary_end = ?, status = ? WHERE batch_id = ?",
            (_utc_now(), canary_sha256, status, batch_id),
        )
    return status
