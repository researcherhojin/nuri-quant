"""analysis 계층의 나머지 분기 — 가격 없는 보유의 손절 검사 · 전부 NaN 인 환율 폴백 · 문자열 계좌 항목."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from nuri.analysis.portfolio import StaleExchangeRateError, get_exchange_rate, portfolio_state
from nuri.analysis.risk import analyze_risk
from nuri.core.db import get_db, init_db
from nuri.core.rules import STOCK_STOP_LOSS
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "analysis.db"
    init_db(path)
    return path


def test_a_holding_without_any_price_is_skipped_by_the_stop_loss_scan(db_path):
    """가격이 한 번도 안 들어온 보유는 손절 판정 대상이 아니다 — 조회가 비었다고 스캔이 죽지 않는다."""
    breach_close = 100.0 * (1 + (STOCK_STOP_LOSS - 5) / 100)  # 손절선보다 5%p 아래
    dates = pd.bdate_range("2026-06-01", periods=30)
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES ('Brokerage Alpha', ?, 10, 100.0, 'USD')",
            [("TST_A",), ("TST_NOPRICE",)],
        )
        conn.executemany(
            "INSERT INTO prices (ticker, date, close) VALUES ('TST_A', ?, ?)",
            [(d.strftime("%Y-%m-%d"), 100.0 - i * (100.0 - breach_close) / 29) for i, d in enumerate(dates)],
        )

    metrics = analyze_risk(db_path=db_path)

    assert [a["ticker"] for a in metrics["stop_loss_alerts"]] == ["TST_A"]


def test_a_fallback_quote_with_only_nan_closes_is_no_rate(db_path, monkeypatch):
    """DB 에 환율이 없고 yfinance 도 NaN 만 주면 지어내지 않고 크게 실패한다."""
    import nuri.core.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        MagicMock(download=MagicMock(return_value=pd.DataFrame({"Close": [float("nan"), float("nan")]}))),
    )

    with pytest.raises(StaleExchangeRateError):
        get_exchange_rate(db_path=db_path)


def test_a_non_mapping_account_entry_contributes_no_cash(db_path, tmp_path):
    """옛 형식의 문자열 계좌 항목은 현금 계산에서 건너뛴다 — 다른 계좌의 현금은 그대로 센다."""
    with get_db(db_path) as conn:
        conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('usd_krw', ?, 1400.0)", (today_kst(),))
    config = tmp_path / "portfolio.yaml"
    config.write_text(
        "accounts:\n  alpha:\n    cash_usd: 1000\n    cash_krw: 1400000\n  legacy: just-a-label\n", encoding="utf-8"
    )

    state = portfolio_state(db_path=db_path, config_path=config)

    assert state["cash"] == 2000.0
