"""DB → YAML 역동기화가 **두 번 읽는 사이**에 원장이 바뀔 때.

보유 스냅샷(`_build_holdings_from_db`)을 먼저 읽고, 계좌별 통화·잔여 행 수는 그 뒤에 따로 읽는다.
그 사이 import 나 API 수정이 계좌를 지우거나 되살릴 수 있다. 스냅샷을 그 시점의 낡은 값으로 고정하고,
두 번째 읽기는 실제 DB 를 그대로 탄다.
"""

from __future__ import annotations

import yaml

from nuri.core import portfolio_sync
from nuri.core.db import init_db, upsert_portfolio


def _write_yaml(path, accounts):
    path.write_text(yaml.safe_dump({"accounts": accounts}, allow_unicode=True), encoding="utf-8")


def _read_accounts(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["accounts"]


def test_an_account_deleted_after_the_snapshot_keeps_its_currency(tmp_path, monkeypatch):
    """스냅샷엔 있던 계좌가 통화 조회 전에 지워지면 통화를 지어내거나 죽지 않는다 — 기존 통화를 두고
    스냅샷 보유를 쓴다 (다음 동기화가 비운다)."""
    db_path = tmp_path / "p.db"
    init_db(db_path)
    config = tmp_path / "portfolio.yaml"
    _write_yaml(config, {"acct_gone": {"currency": "KRW", "holdings": [{"ticker": "TST_OLD", "qty": 1, "avg": 10.0}]}})
    snapshot = {"acct_gone": [{"ticker": "TST_A", "qty": 3, "avg": 50.0}]}
    monkeypatch.setattr(portfolio_sync, "_build_holdings_from_db", lambda db_path=None: snapshot)

    assert portfolio_sync.sync_portfolio_to_yaml(config_path=config, db_path=db_path) == 1

    assert _read_accounts(config)["acct_gone"] == {"currency": "KRW", "holdings": snapshot["acct_gone"]}


def test_an_account_restored_after_the_snapshot_keeps_its_holdings(tmp_path, monkeypatch):
    """스냅샷 뒤에 행이 다시 생긴 계좌의 YAML 보유는 지우지 않는다 — 지우는 것은 DB 에 정말 0 행일 때뿐이다
    (대조군 `acct_empty` 는 지워진다)."""
    db_path = tmp_path / "p.db"
    init_db(db_path)
    config = tmp_path / "portfolio.yaml"
    kept = [{"ticker": "TST_B", "qty": 2, "avg": 20.0}]
    _write_yaml(
        config,
        {
            "acct_back": {"currency": "USD", "holdings": kept},
            "acct_empty": {"currency": "USD", "holdings": [{"ticker": "TST_C", "qty": 1, "avg": 5.0}]},
        },
    )
    upsert_portfolio(
        [
            {
                "account": "acct_back",
                "ticker": "TST_B",
                "quantity": 2,
                "avg_price": 20.0,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    monkeypatch.setattr(portfolio_sync, "_build_holdings_from_db", lambda db_path=None: {})  # 행이 생기기 전 스냅샷

    assert portfolio_sync.sync_portfolio_to_yaml(config_path=config, db_path=db_path) == 0

    accounts = _read_accounts(config)
    assert accounts["acct_back"] == {"currency": "USD", "holdings": kept}
    assert accounts["acct_empty"] == {"currency": "USD"}
