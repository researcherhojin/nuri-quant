"""portfolio.yaml → DB 동기화 스크립트.

config/portfolio.yaml에서 보유 종목을 읽어 portfolio 테이블에 동기화한다.
yaml에 `holdings` 키가 정의된 계좌는 DB가 yaml 상태와 정확히 일치하도록
교체된다 (stale 행 자동 삭제). `holdings` 키가 없는 계좌(예: irp, test, sample)는
건드리지 않는다.

ticker/qty/avg/sector 외 추가 필드는 metadata JSON으로 보존.

#515 (Session 8 발견): sync 후 신규 매수 ticker 가 있으면 자동으로 consensus
재실행. brief 가 stale recommendation (예: 4-10 SELL conf 100) 으로 신규
보유 종목을 잘못 표시하는 noise 차단.
"""

import argparse
import json
import logging
from pathlib import Path

import yaml

from nuri.core.db import init_db, query, replace_portfolio_account

_KNOWN_FIELDS = {"ticker", "qty", "avg", "sector"}

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "portfolio.yaml"

logger = logging.getLogger(__name__)


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
            records.append(
                {
                    "account": account_id,
                    "ticker": str(h["ticker"]),
                    "quantity": float(h["qty"]),
                    "avg_price": float(h["avg"]),
                    "currency": currency,
                    "sector": h.get("sector", ""),
                    "metadata": json.dumps(extra, ensure_ascii=False) if extra else None,
                }
            )

        result[account_id] = records

    return result


def load_holdings(config_path: Path | None = None) -> list[dict]:
    """portfolio.yaml에서 보유 종목 레코드를 평탄화해서 반환 (legacy API).

    하위 호환성을 위해 유지. 신규 코드는 load_holdings_by_account()를 사용할 것.
    """
    by_account = load_holdings_by_account(config_path)
    return [r for records in by_account.values() for r in records]


def _diff_new_tickers(by_account: dict[str, list[dict]], db_path: Path | None = None) -> set[str]:
    """sync 호출 직전의 portfolio 테이블 ticker set vs yaml 신규 ticker set diff.

    Returns: yaml 에 있고 DB 에 없는 ticker (신규 매수). 빈 set 이면 변동 없음.
    """
    yaml_tickers = {r["ticker"] for records in by_account.values() for r in records}
    rows = query("SELECT DISTINCT ticker FROM portfolio WHERE quantity > 0", db_path=db_path)
    db_tickers = {str(r["ticker"]) for r in rows}
    return yaml_tickers - db_tickers


def _trigger_consensus(new_tickers: set[str], db_path: Path | None = None) -> int:
    """신규 ticker 에 대해 analyze_ticker → save_to_recommendations.

    #515: 신규 매수 시 stale recommendation (예: 4-10 SELL conf 100) 이 brief 에
    surface 되어 사용자 confusion 유발하는 문제 차단. analyze_ticker 1회 호출이
    consensus result 1건 + save_to_recommendations 가 today date row 갱신.

    Returns: 성공 ticker 수.
    """
    from nuri.trading.agents.consensus import analyze_ticker, save_to_recommendations

    saved = 0
    for ticker in sorted(new_tickers):
        try:
            result = analyze_ticker(ticker, db_path=db_path)
        except Exception as e:
            logger.warning("analyze_ticker(%s) 실패: %s", ticker, e)
            continue
        try:
            save_to_recommendations([result], db_path=db_path)
            saved += 1
        except Exception as e:
            logger.warning("save_to_recommendations(%s) 실패: %s", ticker, e)
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="portfolio.yaml → DB sync")
    parser.add_argument(
        "--no-consensus",
        action="store_true",
        help="신규 ticker 발견 시 자동 consensus 호출 건너뜀 (#515 옵트아웃)",
    )
    args = parser.parse_args(argv)

    print("=== Nuri-Quant Portfolio Sync ===")

    # DB가 없으면 먼저 생성
    init_db()

    by_account = load_holdings_by_account()

    # #515: sync 직전 diff 추출 — sync 후엔 yaml=DB 라 diff 0 됨
    new_tickers = _diff_new_tickers(by_account)

    total_deleted = 0
    total_inserted = 0
    for account, records in by_account.items():
        deleted, inserted = replace_portfolio_account(account, records)
        total_deleted += deleted
        total_inserted += inserted
        marker = (
            ""
            if deleted == inserted
            else f"  (-{deleted - inserted} stale)"
            if deleted > inserted
            else f"  (+{inserted - deleted} new)"
        )
        print(f"  - {account}: {inserted}종목{marker}")

    print(f"=== Sync complete: -{total_deleted} +{total_inserted} ===")

    if new_tickers and not args.no_consensus:
        print(f"\n=== #515 Auto-consensus for {len(new_tickers)} new ticker(s): {sorted(new_tickers)} ===")
        saved = _trigger_consensus(new_tickers)
        print(f"  → {saved}/{len(new_tickers)} recommendations 갱신 (today date)")
    elif new_tickers:
        print(f"\n--no-consensus 지정 — 신규 {len(new_tickers)}종 consensus 건너뜀: {sorted(new_tickers)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
