"""strategy 계층의 나머지 분기 — 평균회귀 최대보유 청산 · 인증 실패 사유 · 레버리지 연구 출력."""

from __future__ import annotations

import logging
import warnings

import pandas as pd

from nuri.core.db import get_db
from nuri.trading.strategy import position
from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
from nuri.trading.strategy.position import PositionCertification


def test_a_dip_that_never_reaches_the_mid_band_exits_at_max_hold(db_path):
    """폭락 후 바닥에 머물면 BB 중간선에 닿지 않는다 — 보유는 `max_hold` 일에서 끝난다."""
    closes = [100 + (1 if i % 2 else -1) for i in range(55)] + [80.0] * 15
    dates = pd.bdate_range("2026-01-02", periods=len(closes))
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
            "VALUES ('Brokerage Alpha', 'TST_MR', 1, 100, 'USD')"
        )
        conn.executemany(
            "INSERT INTO prices (ticker, date, close) VALUES ('TST_MR', ?, ?)",
            [(d.strftime("%Y-%m-%d"), c) for d, c in zip(dates, closes)],
        )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = backtest_mean_reversion(max_hold=5, db_path=db_path)
    assert result["profit_factor"] is None

    assert (result["total_trades"], result["avg_hold_days"], result["avg_return"]) == (1, 5.0, 0.0)


def test_a_regime_only_certification_failure_names_only_that_reason(db_path, monkeypatch, caplog):
    """인증이 레짐 불일치 하나로 막혔으면 사유도 그것 하나다 — 통과한 축을 실패로 적지 않는다."""
    cert = PositionCertification(
        regime_aligned=False,
        agent_consensus=True,
        concentration_ok=True,
        daily_limit_ok=True,
        drift_safe=True,
        certified=False,
        details={},
    )
    monkeypatch.setattr(position, "certify_position", lambda *a, **k: cert)

    with caplog.at_level(logging.WARNING, logger=position.logger.name):
        opened = position.open_position("TST_A", "short", 100.0, regime="bull_low_vol", db_path=db_path)

    assert opened is False
    assert "[CERT BLOCKED] TST_A short: 레짐 불일치(bull_low_vol↔short)" in caplog.text
    assert "에이전트 미합의" not in caplog.text


def test_a_scenario_without_a_leveraged_leg_prints_only_the_underlying(capsys):
    from nuri.quant.backtest.leverage_study import print_study as print_leverage_study

    print_leverage_study(
        {
            "leveraged_ticker": "TST_L",
            "underlying_ticker": "TST_U",
            "period_start": "2026-01-02",
            "period_end": "2026-06-30",
            "scenarios": {
                "hold": {
                    "scenario": "buy & hold",
                    "underlying": {"total_return_pct": 5.0, "max_drawdown_pct": -3.0, "sharpe_ratio": 0.8},
                }
            },
        }
    )

    out = capsys.readouterr().out
    assert "[TST_U] 수익: +5.00%" in out
    assert "[TST_L]" not in out
