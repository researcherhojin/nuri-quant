"""Toss 보유 종목 → portfolio DB/yaml reconcile (read-only fetch, 로컬 write).

사용:
  python scripts/ops/reconcile_toss.py            # dry-run — diff 만 출력 (기본)
  python scripts/ops/reconcile_toss.py --apply    # toss 계좌를 Toss API 기준으로 DB+yaml 동기

Toss Open API 는 Toss 계좌만 조회 — 다른 브로커 계좌는 각자 별도 reconcile 필요.
브로커 주문 endpoint 미사용 (STRATEGY §7.1) — 로컬 portfolio DB/yaml 만 갱신한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from nuri.collectors import toss
from nuri.core.db import query, replace_portfolio_account
from nuri.core.portfolio_sync import sync_portfolio_to_yaml

ACCOUNT = "toss"


def _to_ticker(symbol: str, market_country: str) -> str:
    """Toss 심볼 → portfolio.yaml 티커. KR 은 KRX 코드 + .KS 접미사, US 는 그대로."""
    if (market_country or "").upper() == "KR":
        return f"{symbol}.KS"
    return symbol


def fetch_toss_records(account: str = ACCOUNT, account_seq: Optional[str] = None) -> list[dict]:
    """Toss holdings → portfolio record 리스트 (replace_portfolio_account 입력 형태)."""
    records = []
    for h in toss.get_holdings(account_seq):
        symbol = str(h.get("symbol", "")).strip()
        qty = float(h.get("quantity") or 0)
        if not symbol or qty <= 0:
            continue
        records.append(
            {
                "account": account,
                "ticker": _to_ticker(symbol, h.get("marketCountry", "")),
                "quantity": qty,
                "avg_price": float(h.get("averagePurchasePrice") or 0),
                "currency": h.get("currency") or "KRW",
                "sector": None,
                "metadata": None,
            }
        )
    return records


def _current_holdings(account: str, db_path=None) -> dict[str, dict]:
    rows = query(
        "SELECT ticker, quantity, avg_price FROM portfolio WHERE account = ?",
        (account,),
        db_path=db_path,
    )
    return {r["ticker"]: {"quantity": r["quantity"], "avg_price": r["avg_price"]} for r in rows}


def compute_diff(current: dict, fetched: list[dict]) -> dict:
    """현재 DB vs Toss API → added / removed / changed(qty 또는 avg 변동)."""
    fetched_map = {r["ticker"]: r for r in fetched}
    added = [t for t in fetched_map if t not in current]
    removed = [t for t in current if t not in fetched_map]
    changed = []
    for t, r in fetched_map.items():
        cur = current.get(t)
        if cur and (
            abs(cur["quantity"] - r["quantity"]) > 1e-9 or abs((cur["avg_price"] or 0) - r["avg_price"]) > 1e-9
        ):
            changed.append(t)
    return {"added": added, "removed": removed, "changed": changed}


def reconcile(
    account: str = ACCOUNT,
    *,
    dry_run: bool = True,
    account_seq: Optional[str] = None,
    db_path=None,
    config_path: Optional[Path] = None,
) -> dict:
    """Toss holdings 를 fetch → 현재 DB 와 diff → dry_run=False 면 DB+yaml 반영."""
    fetched = fetch_toss_records(account, account_seq)
    current = _current_holdings(account, db_path=db_path)
    diff = compute_diff(current, fetched)
    n = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])

    print(
        f"=== Toss reconcile [{account}] {'DRY-RUN' if dry_run else 'APPLY'} — {len(fetched)} holdings, {n} changes ==="
    )
    for t in diff["added"]:
        print(f"  + {t}")
    for t in diff["removed"]:
        print(f"  - {t}")
    for t in diff["changed"]:
        print(f"  ~ {t} (qty/avg 변동)")
    if not n:
        print("  변경 없음 — 이미 동기 상태.")

    if dry_run:
        print("ℹ️ dry-run — 실제 변경 없음. --apply 로 반영.")
    else:
        deleted, inserted = replace_portfolio_account(account, fetched, db_path=db_path)
        sync_portfolio_to_yaml(config_path=config_path, db_path=db_path)
        print(f"✓ APPLIED — DB {deleted} 삭제 / {inserted} 삽입, portfolio.yaml 동기 완료.")

    return {"fetched": len(fetched), "diff": diff, "applied": not dry_run}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Toss 보유 → portfolio reconcile (기본 dry-run)")
    parser.add_argument("--apply", action="store_true", help="DB+portfolio.yaml 에 반영 (기본: dry-run)")
    parser.add_argument("--account", default=ACCOUNT, help="대상 account id (기본: toss)")
    args = parser.parse_args(argv)
    try:
        reconcile(account=args.account, dry_run=not args.apply)
    except toss.TossCredentialsError as e:
        print(f"✗ Toss 인증/계좌 오류: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
