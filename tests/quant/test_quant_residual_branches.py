"""quant 의 나머지 분기 — 모르는 시그널 id · 청산 전 빠진 종가 · 저장된 볼린저 밴드 우선."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.backtest.optimizer import _backtest_signal_with_params
from nuri.quant.chart_analysis import analyze_chart


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "quant.db"
    init_db(path)
    return path


def test_an_unknown_signal_id_takes_no_trades():
    """진입 규칙이 없는 id 는 거래 0 — 다른 시그널(예: MACD)의 규칙으로 흘러가지 않는다."""
    closes = [100 + 10 * math.sin(i / 6) for i in range(200)]  # MACD 교차가 여러 번 나는 파형

    result = _backtest_signal_with_params(pd.DataFrame({"close": closes}), "not_a_signal", {})

    assert result.total_trades == 0


def test_a_missing_close_before_the_macd_exit_drops_that_trade():
    """진입(골든크로스) 뒤 반대 크로스 전에 종가가 비면 그 뒤 MACD 는 전부 NaN 이다 — 청산 시점을 알 수
    없는 거래는 세지 않는다. 빈 종가는 #1480 이전 원장에 남은 NULL close 행이 `query_df` 로 읽힌 모양이다.

    같은 파형의 무결측 시리즈는 한 번 진입해 반대 크로스에서 청산한다 — 거래가 빠진 이유가 결측뿐임을 보인다.
    """
    closes = np.array([100 + 10 * math.sin(2 * math.pi * i / 60) for i in range(100)])  # 진입 48 · 청산 79
    holed = closes.copy()
    holed[51] = np.nan

    clean = _backtest_signal_with_params(pd.DataFrame({"close": closes}), "macd_golden", {})
    missing = _backtest_signal_with_params(pd.DataFrame({"close": holed}), "macd_golden", {})

    assert clean.total_trades == 1
    assert missing.total_trades == 0


def test_stored_bollinger_bands_are_used_instead_of_recomputing(db_path):
    """signals 에 밴드가 있으면 그 값을 쓴다 — 인라인 재계산은 수집기가 안 돈 날의 폴백일 뿐이다."""
    dates = pd.bdate_range("2026-01-02", periods=40)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            day, close = d.strftime("%Y-%m-%d"), 100.0 + i
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES ('TST_C', ?, ?, ?, ?, ?, 1000)",
                (day, close, close, close, close),
            )
            conn.execute(
                "INSERT INTO signals (ticker, date, macd_hist, bb_upper, bb_middle, bb_lower, sma_20, sma_50, sma_200) "
                "VALUES ('TST_C', ?, 0.5, 200, 100, 0, 100, 100, 100)",
                (day,),
            )

    chart = analyze_chart("TST_C", db_path=db_path)

    assert chart.bb_position == pytest.approx(139.0 / 200 * 100)
