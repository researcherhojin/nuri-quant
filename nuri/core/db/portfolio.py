"""Portfolio writes — upsert_portfolio + replace_portfolio_account.

Per-account replacement preserves transaction atomicity (DELETE + INSERT
inside one `with get_db()` context).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db


def upsert_portfolio(records: list[dict], db_path: Optional[Path] = None) -> int:
    """포트폴리오 보유 종목 upsert."""
    if not records:
        return 0
    # metadata 필드 없는 레코드에 기본값 추가
    for r in records:
        r.setdefault("metadata", None)
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO portfolio
               (account, ticker, quantity, avg_price, currency, sector, metadata, updated_at)
               VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                       :metadata, datetime('now'))""",
            records,
        )
        return len(records)


def replace_portfolio_account(
    account: str,
    records: list[dict],
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """특정 계좌의 보유 종목을 records로 완전 교체 (sync 시맨틱).

    yaml → DB 동기화 시 stale 행을 제거하기 위한 함수.
    DELETE + INSERT를 단일 트랜잭션으로 수행 → 다른 계좌는 건드리지 않음.
    records가 빈 리스트면 해당 계좌의 모든 행을 삭제 (전량 청산 표현).

    Args:
        account: 대상 계좌 ID
        records: 새 보유 종목 레코드. 모든 record["account"]가 account와 일치해야 함.

    Returns:
        (deleted_count, inserted_count)

    Raises:
        ValueError: records 중 account가 일치하지 않는 항목이 있을 때
    """
    for r in records:
        if r.get("account") != account:
            raise ValueError(f"record account mismatch: expected {account!r}, got {r.get('account')!r}")
        r.setdefault("metadata", None)

    with get_db(db_path) as conn:
        cur = conn.execute("DELETE FROM portfolio WHERE account = ?", (account,))
        deleted = cur.rowcount
        if records:
            conn.executemany(
                """INSERT INTO portfolio
                   (account, ticker, quantity, avg_price, currency, sector, metadata, updated_at)
                   VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                           :metadata, datetime('now'))""",
                records,
            )
        return (deleted, len(records))
