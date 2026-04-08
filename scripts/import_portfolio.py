"""portfolio.yaml → DB 동기화 스크립트.

config/portfolio.yaml에서 보유 종목을 읽어 portfolio 테이블에 동기화한다.
yaml에 `holdings` 키가 정의된 계좌는 DB가 yaml 상태와 정확히 일치하도록
교체된다 (stale 행 자동 삭제). `holdings` 키가 없는 계좌(예: irp, test, sample)는
건드리지 않는다.

ticker/qty/avg/sector 외 추가 필드는 metadata JSON으로 보존.
"""
import json
from pathlib import Path

import yaml

from nuri.core.db import init_db, replace_portfolio_account

_KNOWN_FIELDS = {"ticker", "qty", "avg", "sector"}

CONFIG_PATH = Path(__file__).parent.parent / "config" / "portfolio.yaml"


def load_holdings_by_account(
    config_path: Path | None = None,
) -> dict[str, list[dict]]:
    """portfolio.yaml에서 계좌별 보유 종목 레코드 추출.

    holdings 키가 정의된 계좌만 반환 (빈 리스트 포함 — 전량 청산 표현).
    config_path가 None이면 모듈 레벨 CONFIG_PATH를 호출 시점에 읽음
    (monkeypatch 호환성).
    """
    if config_path is None:
        config_path = CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    result: dict[str, list[dict]] = {}
    accounts = data.get("accounts", {}) or {}

    for account_id, account_info in accounts.items():
        # holdings 키가 없는 계좌는 sync 대상이 아님 (DB 보존)
        if "holdings" not in account_info:
            continue

        currency = account_info.get("currency", "USD")
        holdings = account_info.get("holdings") or []
        records: list[dict] = []

        for h in holdings:
            # ticker + qty + avg가 있는 항목만 import
            if "ticker" not in h or "qty" not in h or "avg" not in h:
                continue

            # ticker/qty/avg/sector 외 추가 필드 → metadata JSON
            extra = {k: v for k, v in h.items() if k not in _KNOWN_FIELDS}
            records.append({
                "account": account_id,
                "ticker": str(h["ticker"]),
                "quantity": float(h["qty"]),
                "avg_price": float(h["avg"]),
                "currency": currency,
                "sector": h.get("sector", ""),
                "metadata": json.dumps(extra, ensure_ascii=False) if extra else None,
            })

        result[account_id] = records

    return result


def load_holdings(config_path: Path | None = None) -> list[dict]:
    """portfolio.yaml에서 보유 종목 레코드를 평탄화해서 반환 (legacy API).

    하위 호환성을 위해 유지. 신규 코드는 load_holdings_by_account()를 사용할 것.
    """
    by_account = load_holdings_by_account(config_path)
    return [r for records in by_account.values() for r in records]


def main():
    print("=== Nuri-Quant Portfolio Sync ===")

    # DB가 없으면 먼저 생성
    init_db()

    by_account = load_holdings_by_account()

    total_deleted = 0
    total_inserted = 0
    for account, records in by_account.items():
        deleted, inserted = replace_portfolio_account(account, records)
        total_deleted += deleted
        total_inserted += inserted
        marker = "" if deleted == inserted else f"  (-{deleted - inserted} stale)" if deleted > inserted else f"  (+{inserted - deleted} new)"
        print(f"  - {account}: {inserted}종목{marker}")

    print(f"=== Sync complete: -{total_deleted} +{total_inserted} ===")


if __name__ == "__main__":
    main()
