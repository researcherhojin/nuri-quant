"""Trade execution log writes — upsert_trade.

Reads (`get_trades`) stay at facade root since they're patch-sensitive read
helpers (codex 'do not split' list).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db


def upsert_trade(data: dict, db_path: Optional[Path] = None) -> int:
    """매매 실행 기록 삽입 또는 업데이트.

    data 필수 키: ticker, action, executed_at
    선택 키: recommendation_id, entry_price, exit_price, exit_date, exit_reason, shares, notes
    기존 id가 있으면 업데이트, 없으면 삽입.
    """
    with get_db(db_path) as conn:
        if "id" in data and data["id"] is not None:
            # 기존 레코드 업데이트
            trade_id = data.pop("id")
            if not data:  # pragma: no cover — id-only payload guard
                return 0
            set_clause = ", ".join(f"{k} = :{k}" for k in data)
            data["_id"] = trade_id
            conn.execute(f"UPDATE trades SET {set_clause} WHERE id = :_id", data)
            return trade_id
        else:
            # 신규 삽입
            data.pop("id", None)
            cols = ", ".join(data.keys())
            placeholders = ", ".join(f":{k}" for k in data.keys())
            cursor = conn.execute(f"INSERT INTO trades ({cols}) VALUES ({placeholders})", data)
            # cursor.lastrowid is Optional[int] per DB-API spec; coerce to int
            # because the function signature is `-> int` and SQLite always
            # populates lastrowid after an INSERT.
            return cursor.lastrowid or 0
