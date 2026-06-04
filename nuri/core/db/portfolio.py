"""Portfolio writes — upsert_portfolio + replace_portfolio_account.

Per-account replacement preserves transaction atomicity (DELETE + INSERT
inside one `with get_db()` context).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nuri.core.timezone import today_kst

from .connection import get_db


def upsert_portfolio(records: list[dict], db_path: Optional[Path] = None) -> int:
    """포트폴리오 보유 종목 upsert.

    first_buy_date 는 (account, ticker) 가 처음 등장할 때 today_kst() 로 기록되고,
    이후 재upsert(수량/평단 변경) 시에는 보존된다 (first-seen 시맨틱). 이 진입일이
    트레일링 스톱 HWM 의 앵커로 쓰인다 (price_targets.check_trailing_stop_signals).
    """
    if not records:
        return 0
    today = today_kst()
    # 호출자 dict 변형 방지(재사용 객체 stale anchor 방지) — 복사본으로 파라미터 구성.
    params = []
    for r in records:
        p = dict(r)
        p.setdefault("metadata", None)
        p.setdefault("first_buy_date", today)
        params.append(p)
    with get_db(db_path) as conn:
        # 충돌 시 first_buy_date 는 COALESCE: 기존 비-NULL 보존 + 기존 NULL(레거시 행) backfill.
        conn.executemany(
            """INSERT INTO portfolio
               (account, ticker, quantity, avg_price, currency, sector, metadata,
                updated_at, first_buy_date)
               VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                       :metadata, datetime('now'), :first_buy_date)
               ON CONFLICT(account, ticker) DO UPDATE SET
                   quantity=excluded.quantity,
                   avg_price=excluded.avg_price,
                   currency=excluded.currency,
                   sector=excluded.sector,
                   metadata=excluded.metadata,
                   updated_at=excluded.updated_at,
                   first_buy_date=COALESCE(portfolio.first_buy_date, excluded.first_buy_date)""",
            params,
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

    with get_db(db_path) as conn:
        # first_buy_date 보존(first-seen): DELETE+INSERT 라 진입일을 미리 조회해 둔다.
        existing = {
            row["ticker"]: row["first_buy_date"]
            for row in conn.execute(
                "SELECT ticker, first_buy_date FROM portfolio WHERE account = ?",
                (account,),
            ).fetchall()
        }
        cur = conn.execute("DELETE FROM portfolio WHERE account = ?", (account,))
        deleted = cur.rowcount
        if records:
            today = today_kst()
            # 기존 보유면 진입일 보존, 신규면 today (first-seen). 복사본만 변형 — 호출자 dict 불변.
            params = [
                {**r, "metadata": r.get("metadata"), "first_buy_date": existing.get(r["ticker"]) or today}
                for r in records
            ]
            conn.executemany(
                """INSERT INTO portfolio
                   (account, ticker, quantity, avg_price, currency, sector, metadata,
                    updated_at, first_buy_date)
                   VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                           :metadata, datetime('now'), :first_buy_date)""",
                params,
            )
        return (deleted, len(records))
