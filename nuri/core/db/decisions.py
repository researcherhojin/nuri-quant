"""Decision Intelligence (#178) writes — decisions / decision_evidence / certifications.

Read paths (`get_decisions`, `get_decision_with_evidence`) stay at facade root.

Note: this module's `upsert_decision` writes to the legacy `decisions` table
(#178 research-grade record). Phase 2 actor #8 production state machine writes
to `agent_decisions` via `execution_ops.log_decision` — distinct table, distinct
function, by design (see ARCHITECTURE.md "Three decision-related tables").
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db


def upsert_decision(data: dict, db_path: Optional[Path] = None) -> int:
    """의사결정 기록 멱등 삽입/갱신. UNIQUE(date, ticker) 기준.

    같은 날 같은 종목에 대해 재실행하면 최신 데이터로 UPDATE.
    Returns: decision id (신규 삽입 시 lastrowid, 기존 갱신 시 기존 id).
    """
    with get_db(db_path) as conn:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        # updated_at을 갱신하기 위해 ON CONFLICT 사용
        update_cols = [k for k in data.keys() if k not in ("date", "ticker")]
        on_conflict = ", ".join(f"{k} = :{k}" for k in update_cols)
        sql = f"""INSERT INTO decisions ({cols}) VALUES ({placeholders})
                  ON CONFLICT(date, ticker) DO UPDATE SET {on_conflict},
                  updated_at = datetime('now')"""
        cursor = conn.execute(sql, data)
        if cursor.lastrowid:
            return cursor.lastrowid
        # ON CONFLICT UPDATE → lastrowid가 0일 수 있음, 기존 id 조회
        row = conn.execute("SELECT id FROM decisions WHERE date = :date AND ticker = :ticker", data).fetchone()
        return row[0] if row else 0


def upsert_decision_evidence(decision_id: int, records: list[dict], db_path: Optional[Path] = None) -> int:
    """의사결정 증거 기록 멱등 삽입. UNIQUE(decision_id, source_type, source_key) 기준."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        for rec in records:
            rec["decision_id"] = decision_id
            conn.execute(
                """INSERT INTO decision_evidence
                   (decision_id, source_type, source_key, action, confidence, detail)
                   VALUES (:decision_id, :source_type, :source_key, :action, :confidence, :detail)
                   ON CONFLICT(decision_id, source_type, source_key)
                   DO UPDATE SET action = :action, confidence = :confidence, detail = :detail""",
                rec,
            )
        return len(records)


def insert_certification(data: dict, db_path: Optional[Path] = None) -> int:
    """SIEGE Certificate 실행 기록 삽입 (E4-0a instrumentation).

    각 certify() 호출 = 새 row. UNIQUE 제약 없음 — 동일 portfolio_hash 라도 시점이
    다르면 별개로 기록되어야 엔진 predictivity 측정이 가능 (§3.7 E4 hypothesis).

    Required keys: timestamp, certified, score, total_conditions, passed, failed,
    warnings, conditions_json. Optional: regime, portfolio_hash, caller.

    Returns: inserted row id (lastrowid).
    """
    required = {
        "timestamp",
        "certified",
        "score",
        "total_conditions",
        "passed",
        "failed",
        "warnings",
        "conditions_json",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"insert_certification: missing required keys {missing}")

    with get_db(db_path) as conn:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        sql = f"INSERT INTO certifications ({cols}) VALUES ({placeholders})"
        cursor = conn.execute(sql, data)
        return cursor.lastrowid or 0
