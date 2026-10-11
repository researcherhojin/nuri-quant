"""holdings_monitor 의 dry-run 과 전송 집계 분기.

- dry-run 은 **판정은 그대로 내되 이벤트 원장에 아무것도 쓰지 않는다** — 부모 run 이벤트도,
  자식 알림 이벤트도, 마감 집계 이벤트도. 하나라도 새면 검증용 실행이 원장을 오염시킨다.
- `send_alerts` 는 webhook 이 실제로 나간 건만 센다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.core.db import get_db, init_db, query
from nuri.trading.recommend import holdings_monitor as hm
from nuri.trading.recommend.holdings_monitor import TRIGGER_TECHNICAL_SELL, run_monitor, send_alerts

SELL_DIAG = {
    "technical_action": "SELL",
    "technical_confidence": 85.0,
    "technical_reasoning": "MACD<Signal",
    "divergence_flag": False,
    "divergence_reason": "",
    "consensus_action": "HOLD",
}


@pytest.fixture
def two_holdings(tmp_path):
    path = tmp_path / "hm.db"
    init_db(path)
    with get_db(path) as conn:
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
            [("Brokerage Alpha", "AAA", 10, 100.0, "USD"), ("Brokerage Alpha", "BBB", 5, 50.0, "USD")],
        )
        conn.executemany(
            "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            [("AAA", "2026-04-29", 95.0), ("BBB", "2026-04-29", 45.0)],
        )
    return path


def test_a_dry_run_reports_alerts_without_writing_any_event(two_holdings):
    with patch.object(hm, "_evaluate_triggers", return_value=(TRIGGER_TECHNICAL_SELL, dict(SELL_DIAG))):
        summary = run_monitor(db_path=two_holdings, dry_run=True)

    assert summary.n_alerted == 2
    assert sorted(a["ticker"] for a in summary.alerts) == ["AAA", "BBB"]
    assert query("SELECT COUNT(*) AS n FROM pipeline_events", db_path=two_holdings)[0]["n"] == 0


def test_send_alerts_counts_only_webhooks_that_went_out(two_holdings):
    with patch.object(hm, "_evaluate_triggers", return_value=(TRIGGER_TECHNICAL_SELL, dict(SELL_DIAG))):
        summary = run_monitor(db_path=two_holdings, dry_run=True)
    outcomes = iter([True, False])

    with patch("nuri.alerts.discord_bot.send_webhook_text", side_effect=lambda msg: next(outcomes)) as webhook:
        sent = send_alerts(summary)

    assert webhook.call_count == 2
    assert sent == 1
