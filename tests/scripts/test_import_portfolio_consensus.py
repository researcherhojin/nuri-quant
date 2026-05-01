"""#515 — scripts/import_portfolio.py 신규 ticker 자동 consensus 트리거 검증.

문제: portfolio.yaml 에 신규 매수 ticker 추가 후 import 만 하면
brief 가 stale recommendation (예: 4-10 SELL conf 100) 으로 신규 보유 종목을
잘못 표시. import 직후 consensus 자동 호출이 today date row 갱신해 차단.

이 lock-test 가 fail 하면 사용자가 `make consensus` 별도 실행 잊어버린 채
brief 보고 잘못된 매도 권고로 confusion 가능.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db, query, upsert_portfolio
from scripts.ops.import_portfolio import _diff_new_tickers, _trigger_consensus


@pytest.fixture
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ─── _diff_new_tickers ──────────────────────────────────────────────────


def test_diff_finds_new_ticker_added_to_yaml(db):
    """yaml 에 추가된 ticker 가 DB 에 없으면 diff 에 포함."""
    upsert_portfolio(
        [{"account": "main", "ticker": "AAPL", "quantity": 10, "avg_price": 100, "currency": "USD", "sector": "Tech"}],
        db,
    )
    by_account = {
        "main": [
            {
                "ticker": "AAPL",
                "quantity": 10.0,
                "avg_price": 100.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
            {
                "ticker": "MSFT",
                "quantity": 3.0,
                "avg_price": 424.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
        ]
    }
    diff = _diff_new_tickers(by_account, db_path=db)
    assert diff == {"MSFT"}


def test_diff_returns_empty_when_no_changes(db):
    """yaml 과 DB 가 일치하면 diff 빈 set."""
    upsert_portfolio(
        [{"account": "main", "ticker": "AAPL", "quantity": 10, "avg_price": 100, "currency": "USD", "sector": "Tech"}],
        db,
    )
    by_account = {
        "main": [
            {
                "ticker": "AAPL",
                "quantity": 10.0,
                "avg_price": 100.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
        ]
    }
    diff = _diff_new_tickers(by_account, db_path=db)
    assert diff == set()


def test_diff_skips_zero_qty_db_rows(db):
    """DB 의 0주 row 는 'held' 아님 — 같은 ticker 가 yaml 에 있으면 신규로 분류."""
    # qty=0 row (stale) 직접 INSERT
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES ('main', 'TSM', 0, 200.0, 'USD', 'Tech')"
        )
    by_account = {
        "main": [
            {
                "ticker": "TSM",
                "quantity": 5.0,
                "avg_price": 200.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
        ]
    }
    diff = _diff_new_tickers(by_account, db_path=db)
    assert diff == {"TSM"}


def test_diff_multi_account(db):
    """여러 계좌의 신규 ticker 모두 합쳐 반환."""
    upsert_portfolio(
        [{"account": "main", "ticker": "AAPL", "quantity": 10, "avg_price": 100, "currency": "USD", "sector": "Tech"}],
        db,
    )
    by_account = {
        "main": [
            {
                "ticker": "AAPL",
                "quantity": 10.0,
                "avg_price": 100.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
            {
                "ticker": "GOOGL",
                "quantity": 3.0,
                "avg_price": 350.0,
                "account": "main",
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        "sub": [
            {
                "ticker": "NVDA",
                "quantity": 5.0,
                "avg_price": 180.0,
                "account": "sub",
                "currency": "USD",
                "sector": "Tech",
            },
        ],
    }
    diff = _diff_new_tickers(by_account, db_path=db)
    assert diff == {"GOOGL", "NVDA"}


# ─── _trigger_consensus ──────────────────────────────────────────────────


def test_trigger_consensus_calls_analyze_per_ticker(db):
    """신규 ticker 마다 analyze_ticker + save_to_recommendations 호출."""
    fake_result = type("R", (), {"ticker": "MSFT", "action": "HOLD", "confidence": 60})()

    with (
        patch("nuri.trading.agents.consensus.analyze_ticker", return_value=fake_result) as mock_analyze,
        patch("nuri.trading.agents.consensus.save_to_recommendations", return_value=1) as mock_save,
    ):
        saved = _trigger_consensus({"MSFT", "GOOGL"}, db_path=db)

    assert saved == 2
    assert mock_analyze.call_count == 2
    assert mock_save.call_count == 2


def test_trigger_consensus_continues_on_analyze_error(db):
    """한 ticker analyze 실패해도 나머지 진행."""
    fake_result = type("R", (), {"ticker": "MSFT", "action": "HOLD", "confidence": 60})()

    def analyze_side_effect(ticker, db_path=None):
        if ticker == "BAD":
            raise RuntimeError("network error")
        return fake_result

    with (
        patch("nuri.trading.agents.consensus.analyze_ticker", side_effect=analyze_side_effect),
        patch("nuri.trading.agents.consensus.save_to_recommendations", return_value=1) as mock_save,
    ):
        saved = _trigger_consensus({"MSFT", "BAD"}, db_path=db)

    # MSFT 만 성공
    assert saved == 1
    assert mock_save.call_count == 1


def test_trigger_consensus_empty_set_no_calls(db):
    """빈 set 이면 호출 0 — graceful no-op."""
    with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_analyze:
        saved = _trigger_consensus(set(), db_path=db)
    assert saved == 0
    assert mock_analyze.call_count == 0


# ─── E2E (main 함수 + --no-consensus 플래그) ────────────────────────────


def test_main_no_consensus_flag_skips_trigger(db, tmp_path, monkeypatch):
    """--no-consensus 지정 시 신규 ticker 있어도 consensus 호출 X."""
    import scripts.ops.import_portfolio as ip

    yaml_path = tmp_path / "portfolio.yaml"
    yaml_path.write_text(
        """
accounts:
  main:
    currency: USD
    holdings:
      - { ticker: NEWCO, qty: 1, avg: 100 }
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ip, "CONFIG_PATH", yaml_path)

    with patch("scripts.ops.import_portfolio._trigger_consensus") as mock_trigger:
        rc = ip.main(["--no-consensus"])

    assert rc == 0
    mock_trigger.assert_not_called()
    # 그래도 sync 는 일어났어야 함
    rows = query("SELECT ticker FROM portfolio WHERE ticker = 'NEWCO'", db_path=db)
    assert len(rows) == 1


def test_main_default_calls_trigger_for_new_tickers(db, tmp_path, monkeypatch):
    """default (--no-consensus 없음) 신규 ticker 발견 시 _trigger_consensus 호출."""
    import scripts.ops.import_portfolio as ip

    yaml_path = tmp_path / "portfolio.yaml"
    yaml_path.write_text(
        """
accounts:
  main:
    currency: USD
    holdings:
      - { ticker: NEWCO, qty: 1, avg: 100 }
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ip, "CONFIG_PATH", yaml_path)

    with patch("scripts.ops.import_portfolio._trigger_consensus", return_value=1) as mock_trigger:
        rc = ip.main([])

    assert rc == 0
    mock_trigger.assert_called_once()
    # 호출 인자 — 신규 ticker set 포함
    args, _ = mock_trigger.call_args
    assert "NEWCO" in args[0]


def test_main_no_new_tickers_skips_trigger(db, tmp_path, monkeypatch):
    """yaml 과 DB 일치 시 _trigger_consensus 호출 X (불필요한 LLM 호출 회피)."""
    import scripts.ops.import_portfolio as ip

    upsert_portfolio(
        [{"account": "main", "ticker": "AAPL", "quantity": 1, "avg_price": 100, "currency": "USD", "sector": "Tech"}],
        db,
    )
    yaml_path = tmp_path / "portfolio.yaml"
    yaml_path.write_text(
        """
accounts:
  main:
    currency: USD
    holdings:
      - { ticker: AAPL, qty: 1, avg: 100 }
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ip, "CONFIG_PATH", yaml_path)

    with patch("scripts.ops.import_portfolio._trigger_consensus") as mock_trigger:
        rc = ip.main([])

    assert rc == 0
    mock_trigger.assert_not_called()
