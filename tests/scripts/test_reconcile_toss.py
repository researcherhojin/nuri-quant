"""Toss holdings reconcile lock-tests — 심볼매핑 + diff + dry-run/apply 게이트.

Toss API(get_holdings) 는 mock. DB 는 tmp 격리. 실 broker/holdings 데이터 미사용
(synthetic KRX 코드만). 브로커 주문 write 없음(§7.1) — DB/yaml 로컬 write 만 검증.
"""

from unittest.mock import patch

import pytest

from nuri.core.db import init_db, query, replace_portfolio_account
from scripts.ops import reconcile_toss as R


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(db_path=p)
    return p


def _seed(db, account="toss"):
    replace_portfolio_account(
        account,
        [
            {
                "account": account,
                "ticker": "005930.KS",
                "quantity": 10.0,
                "avg_price": 70000.0,
                "currency": "KRW",
                "sector": None,
                "metadata": None,
            }
        ],
        db_path=db,
    )


# synthetic Toss holdings 응답 (실데이터 아님)
_HOLDINGS = [
    {"symbol": "005930", "quantity": 15, "averagePurchasePrice": 72000, "marketCountry": "KR", "currency": "KRW"},
    {"symbol": "000000", "quantity": 5, "averagePurchasePrice": 1000, "marketCountry": "KR", "currency": "KRW"},
    {
        "symbol": "ZZZZ",
        "quantity": 0,
        "averagePurchasePrice": 10,
        "marketCountry": "US",
        "currency": "USD",
    },  # 0주 → skip
]


class TestSymbolMapping:
    def test_kr_gets_ks_suffix(self):
        assert R._to_ticker("005930", "KR") == "005930.KS"

    def test_us_unchanged(self):
        assert R._to_ticker("TSLA", "US") == "TSLA"


class TestFetch:
    def test_maps_and_filters_zero_qty(self):
        with patch("nuri.collectors.toss.get_holdings", return_value=_HOLDINGS):
            recs = R.fetch_toss_records()
        tickers = {r["ticker"] for r in recs}
        assert tickers == {"005930.KS", "000000.KS"}  # ZZZZ(0주) 제외
        rec = next(r for r in recs if r["ticker"] == "005930.KS")
        assert rec["quantity"] == 15.0 and rec["avg_price"] == 72000.0 and rec["account"] == "toss"


class TestDiff:
    def test_added_removed_changed(self):
        current = {
            "005930.KS": {"quantity": 10.0, "avg_price": 70000.0},
            "111111.KS": {"quantity": 1.0, "avg_price": 100.0},
        }
        fetched = [
            {"ticker": "005930.KS", "quantity": 15.0, "avg_price": 72000.0},  # changed
            {"ticker": "222222.KS", "quantity": 2.0, "avg_price": 200.0},
        ]  # added
        d = R.compute_diff(current, fetched)
        assert d["added"] == ["222222.KS"]
        assert d["removed"] == ["111111.KS"]
        assert d["changed"] == ["005930.KS"]

    def test_no_change(self):
        current = {"005930.KS": {"quantity": 10.0, "avg_price": 70000.0}}
        fetched = [{"ticker": "005930.KS", "quantity": 10.0, "avg_price": 70000.0}]
        d = R.compute_diff(current, fetched)
        assert not (d["added"] or d["removed"] or d["changed"])


class TestReconcile:
    def test_dry_run_does_not_write_db(self, db, capsys):
        _seed(db)  # 현재 005930.KS 10주
        with patch("nuri.collectors.toss.get_holdings", return_value=_HOLDINGS):
            res = R.reconcile(dry_run=True, db_path=db)
        # DB 미변경 — 여전히 10주
        rows = query("SELECT quantity FROM portfolio WHERE account='toss' AND ticker='005930.KS'", db_path=db)
        assert rows[0]["quantity"] == 10.0
        assert res["applied"] is False
        out = capsys.readouterr().out
        assert "DRY-RUN" in out and "dry-run" in out

    def test_apply_writes_db(self, db):
        _seed(db)
        with (
            patch("nuri.collectors.toss.get_holdings", return_value=_HOLDINGS),
            patch("scripts.ops.reconcile_toss.sync_portfolio_to_yaml") as sync,
        ):
            res = R.reconcile(dry_run=False, db_path=db)
        # 005930.KS 10→15, 000000.KS 신규, 111111 없음
        rows = {
            r["ticker"]: r["quantity"]
            for r in query("SELECT ticker, quantity FROM portfolio WHERE account='toss'", db_path=db)
        }
        assert rows == {"005930.KS": 15.0, "000000.KS": 5.0}
        assert res["applied"] is True
        sync.assert_called_once()  # yaml 동기 호출됨

    def test_main_creds_error_returns_2(self, capsys):
        err = R.toss.TossCredentialsError("no account")
        with patch("nuri.collectors.toss.get_holdings", side_effect=err):
            rc = R.main(["--apply"])
        assert rc == 2
        assert "오류" in capsys.readouterr().out

    def test_main_dry_run_default(self):
        # 기본(인자 없음) → reconcile(dry_run=True) 디스패치 (실 DB 미접근)
        with patch("scripts.ops.reconcile_toss.reconcile") as rec:
            rc = R.main([])
        assert rc == 0
        assert rec.call_args.kwargs["dry_run"] is True
