"""Audit logging — external LLM calls + general audit_log table.

Both are append-only. `audit_log` swallows write errors (audit failure must
never break the main code path). `log_external_llm_call` per STRATEGY §4.4.3
intentionally NEVER stores prompt/response content — token counts only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db


def log_external_llm_call(
    *,
    provider: str,
    model: str,
    endpoint: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    success: bool = True,
    error_type: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """STRATEGY.md §4.4.3 audit log — 외부 LLM 호출 1건 기록.

    **content는 절대 저장하지 않는다.** prompt나 response 텍스트는
    이 함수의 인자로 받지도, DB에 넣지도 않는다. token 카운트와
    metadata만 audit한다.

    Returns: 새로 insert된 row id
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO external_llm_calls
               (provider, model, endpoint, prompt_tokens, completion_tokens,
                latency_ms, success, error_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, endpoint, prompt_tokens, completion_tokens, latency_ms, 1 if success else 0, error_type),
        )
        return cursor.lastrowid or 0


def audit_log(
    action: str,
    table_name: str,
    ticker: str = "",
    details: str = "",
    user_id: str = "system",
    ip_address: str = "",
    db_path: Optional[Path] = None,
) -> None:
    """감사 로그 기록 (append-only)."""
    try:
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO audit_log (user_id, action, table_name, ticker, details, ip_address)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, action, table_name, ticker, details, ip_address),
            )
    except Exception:
        pass  # 감사 로깅 실패가 메인 로직을 방해하면 안 됨
