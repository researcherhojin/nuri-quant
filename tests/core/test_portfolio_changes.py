"""보유 수량 변경 원장 (#1720) — 트리거가 모든 쓰기 경로를 기록하는지 잠근다.

writer 가 셋(upsert · 계좌 교체 · API 직접 SQL)이고 앞으로도 늘 수 있어서 호출 지점이 아니라
테이블 트리거로 남긴다. 그래서 잠금도 경로별로 실제로 써 보고 원장 행을 읽는다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from nuri.core.db import get_db, init_db, query, replace_portfolio_account, upsert_portfolio
from nuri.core.timezone import kst_now

ACCOUNT = "Brokerage Alpha"


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "changes.db"
    init_db(p)
    return p


def _holding(ticker="AAA", quantity=10.0, account=ACCOUNT):
    return {
        "account": account,
        "ticker": ticker,
        "quantity": quantity,
        "avg_price": 100.0,
        "currency": "USD",
        "sector": None,
    }


def _net(db_path, ticker="AAA"):
    rows = query(
        "SELECT SUM(COALESCE(new_quantity, 0) - COALESCE(old_quantity, 0)) AS net, COUNT(*) AS n "
        "FROM portfolio_changes WHERE ticker = ?",
        (ticker,),
        db_path=db_path,
    )
    return rows[0]["net"], rows[0]["n"]


class TestEveryWritePathIsLogged:
    def test_new_holding(self, db_path):
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        assert _net(db_path) == (10, 1)

    def test_upsert_changing_quantity_logs_the_delta(self, db_path):
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        upsert_portfolio([_holding(quantity=15)], db_path=db_path)
        assert _net(db_path)[0] == 15

    def test_upsert_that_changes_only_the_price_logs_nothing(self, db_path):
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        upsert_portfolio([{**_holding(quantity=10), "avg_price": 120.0}], db_path=db_path)
        assert _net(db_path) == (10, 1)

    def test_account_replace_with_unchanged_holdings_nets_to_zero(self, db_path):
        """가져오기(replace)는 DELETE+INSERT — 변하지 않은 종목도 −q/+q 를 남긴다. 순변화는 0 이고,
        그 행들이 "이 시각에 가져오기가 있었다" 는 흔적이 된다."""
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        replace_portfolio_account(ACCOUNT, [_holding(quantity=10)], db_path=db_path)
        net, n = _net(db_path)
        assert net == 10 and n == 3

    def test_account_replace_that_sells_out_logs_the_sale(self, db_path):
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        replace_portfolio_account(ACCOUNT, [], db_path=db_path)
        assert _net(db_path)[0] == 0

    def test_raw_sql_update_and_delete_from_the_api_paths(self, db_path):
        """`nuri/api/routes/portfolio.py` 는 헬퍼를 거치지 않고 직접 UPDATE/DELETE 한다."""
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET quantity = 4 WHERE account = ? AND ticker = 'AAA'", (ACCOUNT,))
        assert _net(db_path)[0] == 4
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM portfolio WHERE account = ? AND ticker = 'AAA'", (ACCOUNT,))
        assert _net(db_path)[0] == 0

    def test_moving_a_holding_between_accounts_is_two_sided(self, db_path):
        upsert_portfolio([_holding(quantity=10)], db_path=db_path)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET account = 'Brokerage Beta' WHERE ticker = 'AAA'")
        by_account = query(
            "SELECT account, SUM(COALESCE(new_quantity,0) - COALESCE(old_quantity,0)) AS net "
            "FROM portfolio_changes GROUP BY account ORDER BY account",
            db_path=db_path,
        )
        assert by_account == [{"account": ACCOUNT, "net": 0}, {"account": "Brokerage Beta", "net": 10}]


class TestTimestamp:
    def test_changed_at_is_kst_wall_time(self, db_path):
        """`datetime('now')` 는 UTC — KST 결정 날짜와 비교하면 하루가 밀린다 (#1675)."""
        upsert_portfolio([_holding()], db_path=db_path)
        stamped = datetime.strptime(
            query("SELECT changed_at FROM portfolio_changes", db_path=db_path)[0]["changed_at"], "%Y-%m-%d %H:%M:%S"
        )
        now = kst_now().replace(tzinfo=None)
        assert abs((now - stamped).total_seconds()) < 120
