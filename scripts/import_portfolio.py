"""portfolio.yaml → DB 동기화 스크립트.

config/portfolio.yaml에서 보유 종목을 읽어 portfolio 테이블에 upsert한다.
연금저축(auto_invest)과 IRP(보유종목 없음)는 건너뛴다.
"""
from pathlib import Path

import yaml

from nuri.core.db import init_db, upsert_portfolio

CONFIG_PATH = Path(__file__).parent.parent / "config" / "portfolio.yaml"


def load_holdings(config_path: Path = CONFIG_PATH) -> list[dict]:
    """portfolio.yaml에서 보유 종목 레코드 추출."""
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    records = []
    accounts = data.get("accounts", {})

    for account_id, account_info in accounts.items():
        currency = account_info.get("currency", "USD")
        holdings = account_info.get("holdings", [])

        for h in holdings:
            # ticker + qty + avg가 있는 항목만 import
            if "ticker" not in h or "qty" not in h or "avg" not in h:
                continue

            records.append({
                "account": account_id,
                "ticker": str(h["ticker"]),
                "quantity": float(h["qty"]),
                "avg_price": float(h["avg"]),
                "currency": currency,
                "sector": h.get("sector", ""),
            })

    return records


def main():
    print("=== Nuri-Quant Portfolio Import ===")

    # DB가 없으면 먼저 생성
    init_db()

    records = load_holdings()
    count = upsert_portfolio(records)

    # 계좌별 통계
    by_account = {}
    for r in records:
        by_account.setdefault(r["account"], 0)
        by_account[r["account"]] += 1

    print(f"Imported {count} holdings:")
    for acct, cnt in by_account.items():
        print(f"  - {acct}: {cnt}종목")
    print("=== Import complete ===")


if __name__ == "__main__":
    main()
