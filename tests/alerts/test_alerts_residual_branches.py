"""alerts 의 나머지 분기 — 전송된 일일 리포트 · 두 읽기 사이에 들어온 새 봉."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from nuri.alerts import daily_report, risk_signals
from nuri.core.db import init_db, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from nuri.trading.recommend import stop_loss


def test_a_delivered_report_is_not_also_printed(monkeypatch):
    """생성한 리포트를 Discord 로 정확히 한 번 보내고, 전송이 성공하면 stdout 폴백은 없다."""
    embed = {"title": "Daily", "fields": [{"name": "VIX", "value": "16"}]}
    sent, printed = [], []
    monkeypatch.setattr(daily_report, "generate_report", lambda: embed)
    monkeypatch.setattr(daily_report, "send_discord", lambda e: sent.append(e) or True)
    monkeypatch.setattr(daily_report, "print_report", lambda e: printed.append(e))

    assert daily_report.main([]) == 0
    assert len(sent) == 1 and sent[0] is embed
    assert printed == []


def _bar(ticker, date, close):
    row = {"ticker": ticker, "date": date, "open": close, "high": close, "low": close, "close": close}
    return pd.DataFrame([{**row, "volume": 1_000_000, "adj_close": close}])


def test_a_bar_that_recovers_between_the_scan_and_its_context_claims_no_breach_days(tmp_path, monkeypatch):
    """손절 이탈은 첫 읽기(최신 종가 90)로 판정하고, 이탈 경과는 두 번째 읽기로 센다. 그 사이 수집기가
    손절선 위의 새 봉(97)을 쓰면 경과는 0 이다 — 그때 '1일째' 같은 경과를 지어내지 않고 항목을 뺀다."""
    db_path = tmp_path / "risk.db"
    init_db(db_path)
    monkeypatch.setattr(stop_loss, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(stop_loss, "get_stop_loss_for_account", lambda a: -7)  # 손절가 93
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_A",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    upsert_prices(_bar("TST_A", (kst_now() - timedelta(days=1)).date().isoformat(), 90.0), db_path)
    real_context = risk_signals._price_context

    def context_after_a_new_bar(ticker, avg, threshold, db_path=None, lookback=260):
        upsert_prices(_bar(ticker, today_kst(), 97.0), db_path)  # 두 읽기 사이에 도착한 봉
        return real_context(ticker, avg, threshold, db_path=db_path, lookback=lookback)

    monkeypatch.setattr(risk_signals, "_price_context", context_after_a_new_bar)

    (breach,) = risk_signals.scan_stop_breaches(db_path=db_path)

    assert (breach["current"], breach["threshold"]) == (90.0, -7)
    assert "breach_days" not in breach and "first_breach_date" not in breach
    assert breach["drawdown_52w"] == 0.0  # 문맥은 두 번째 읽기 기준 — 최신 97 이 곧 고점
