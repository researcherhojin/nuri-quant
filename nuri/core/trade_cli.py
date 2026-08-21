"""실거래 기록 CLI (#1163) — `make trade-log` / `make trade-list`.

**왜 CLI 인가**: `trades` 테이블은 도입 이래 prod 0행 — 사용자 매매는 증권사 앱에서
수동 실행되고 시스템 유입 경로가 없었다. 이 기록이 없으면 회전율 측정(W4), 논지→거래
→성과 귀속, 처분효과 사후분석이 전부 불가능하다. 매매 직후 1줄 입력이 마찰의 전부가
되도록 최소로 유지한다.

**원장**: 판정에 쓰이는 기록의 원장은 prod(Mac mini) DB 다 (§3.11). dev 에서 입력했으면
`scripts/sync_dev.sh push` 로 밀거나 mini 에서 직접 입력할 것.

사용:
    python -m nuri.core.trade_cli add --ticker AAPL --side BUY --qty 10 --price 231.50 --account main
    python -m nuri.core.trade_cli list [--month 2026-08]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nuri.core.db import query, upsert_trade
from nuri.core.timezone import today_kst

#: 계좌 이름은 자유 문자열이 아니다 — 오타 계좌가 생기면 회전율 귀속이 조용히 갈라진다.
#: config/rules.yaml account_strategies 와 같은 어휘를 쓰되, 여기서는 최소 검증만 한다.
VALID_SIDES = ("BUY", "SELL")


def add_trade(
    ticker: str,
    side: str,
    qty: float,
    price: float,
    account: str,
    date: str | None = None,
    note: str | None = None,
    db_path: Path | None = None,
) -> int:
    """거래 1건 기록. BUY 는 entry_price, SELL 은 exit_price/exit_date 로 매핑."""
    side = side.upper()
    if side not in VALID_SIDES:
        raise ValueError(f"side 는 BUY/SELL 만: {side!r}")
    if qty <= 0 or price <= 0:
        raise ValueError("qty/price 는 양수여야 한다")
    d = date or today_kst()
    data: dict = {
        "ticker": ticker.upper(),
        "action": side,
        "executed_at": d,
        "shares": qty,
        "account": account,
        "notes": note,
    }
    if side == "BUY":
        data["entry_price"] = price
    else:
        data["exit_price"] = price
        data["exit_date"] = d
    return upsert_trade(data, db_path=db_path)


def list_trades(month: str | None = None, db_path: Path | None = None) -> list[dict]:
    """월별(YYYY-MM) 또는 전체 최근 30건."""
    if month:
        return query(
            "SELECT * FROM trades WHERE executed_at LIKE ? ORDER BY executed_at DESC",
            (f"{month}%",),
            db_path=db_path,
        )
    return query("SELECT * FROM trades ORDER BY executed_at DESC LIMIT 30", db_path=db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="실거래 기록 (#1163)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="거래 1건 기록")
    p_add.add_argument("--ticker", required=True)
    p_add.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"])
    p_add.add_argument("--qty", type=float, required=True)
    p_add.add_argument("--price", type=float, required=True)
    p_add.add_argument("--account", required=True)
    p_add.add_argument("--date", default=None, help="YYYY-MM-DD (기본 오늘 KST)")
    p_add.add_argument("--note", default=None)

    p_list = sub.add_parser("list", help="기록 조회")
    p_list.add_argument("--month", default=None, help="YYYY-MM")

    args = parser.parse_args(argv)
    if args.cmd == "add":
        try:
            tid = add_trade(
                args.ticker,
                args.side,
                args.qty,
                args.price,
                args.account,
                date=args.date,
                note=args.note,
            )
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        print(f"✓ {args.ticker.upper()} {args.side.upper()} {args.qty} @ {args.price} ({args.account}) — id={tid}")
        return 0
    rows = list_trades(month=args.month)
    if not rows:
        print("기록 없음")
        return 0
    for r in rows:
        price = r.get("entry_price") or r.get("exit_price")
        print(
            f"{r['executed_at']} {r['action']:4s} {r['ticker']:10s} {r['shares']} @ {price} ({r.get('account') or '-'})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
