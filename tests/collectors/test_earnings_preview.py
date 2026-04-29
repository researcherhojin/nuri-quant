"""Lock-tests for #509 earnings preview collector.

가드: AMZN ±2.20% bug regression (만료 임박 옵션 0 time value) 차단.
_select_expiration() 의 post-earnings 우선 + min_days cutoff + fallback 분기 lock.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.earnings_preview import (
    EarningsPreview,
    _atm_straddle,
    _select_expiration,
    fetch_earnings_preview,
    render_markdown,
)
from nuri.core.db import get_db, init_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# --- _select_expiration: AMZN bug regression guard ----------------------


def test_select_expiration_empty_returns_none():
    assert _select_expiration((), None) is None


def test_select_expiration_skips_imminent():
    """today=4-30, exps=[4-30,5-01,5-02,5-09]: skip 4-30 (≤2d), pick 5-02."""
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        exp = _select_expiration(
            ("2026-04-30", "2026-05-01", "2026-05-02", "2026-05-09"),
            earnings_date=None,
            min_days=2,
        )
        assert exp == "2026-05-02"


def test_select_expiration_post_earnings_priority():
    """earnings_date=4-30 → post-earnings list first valid: 5-01.

    AMZN bug fix lock: yfinance returns 4-29 (same-day) options, must skip
    in favor of post-earnings 5-01 expiration to avoid 0-IV reading.
    """
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        exp = _select_expiration(
            ("2026-04-29", "2026-05-01", "2026-05-08"),
            earnings_date=date(2026, 4, 30),
            min_days=2,
        )
        assert exp == "2026-05-01"


def test_select_expiration_invalid_format_skipped():
    """Malformed date strings skipped, valid ones picked."""
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        exp = _select_expiration(
            ("not-a-date", "2026-05-15"),
            earnings_date=None,
            min_days=2,
        )
        assert exp == "2026-05-15"


def test_select_expiration_fallback_to_last_when_all_too_imminent():
    """All exps before cutoff + no earnings_date → return last (best available)."""
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        exp = _select_expiration(
            ("2026-04-29", "2026-04-30"),
            earnings_date=None,
            min_days=5,
        )
        assert exp == "2026-04-30"


# --- _atm_straddle: math + edge cases ---------------------------------


def test_atm_straddle_no_options_returns_nones():
    t = MagicMock()
    t.options = ()
    assert _atm_straddle(t, 100.0) == (None, None, None, None)


def test_atm_straddle_empty_chain():
    t = MagicMock()
    t.options = ("2026-05-15",)
    chain = MagicMock()
    chain.calls = pd.DataFrame()
    chain.puts = pd.DataFrame()
    t.option_chain.return_value = chain
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        result = _atm_straddle(t, 100.0)
    assert result == ("2026-05-15", None, None, None)


def test_atm_straddle_computes_implied_move():
    """ATM straddle with strike=100, call mid=3, put mid=2 → straddle=5, IV=5%."""
    t = MagicMock()
    t.options = ("2026-05-15",)
    chain = MagicMock()
    chain.calls = pd.DataFrame({"strike": [95, 100, 105], "bid": [6, 2.8, 0.5], "ask": [6.5, 3.2, 0.7]})
    chain.puts = pd.DataFrame({"strike": [95, 100, 105], "bid": [0.4, 1.8, 5.5], "ask": [0.6, 2.2, 6.0]})
    t.option_chain.return_value = chain
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        exp, strike, straddle, iv = _atm_straddle(t, 100.0)
    assert exp == "2026-05-15"
    assert strike == 100.0
    assert straddle == pytest.approx(5.0, abs=0.01)
    assert iv == pytest.approx(5.0, abs=0.01)


def test_atm_straddle_exception_returns_nones():
    t = MagicMock()
    t.options = ("2026-05-15",)
    t.option_chain.side_effect = Exception("network error")
    with patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"):
        assert _atm_straddle(t, 100.0) == (None, None, None, None)


# --- fetch_earnings_preview: integration ------------------------------


def test_fetch_earnings_preview_full_path(db):
    """yfinance mocked; surprise_history fetched from DB."""
    with get_db(db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS earnings_surprises (ticker TEXT, quarter TEXT, surprise_pct REAL)")
        for q, s in [("Q1", 0.05), ("Q4", 0.12), ("Q3", 0.08), ("Q2", -0.02)]:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, surprise_pct) VALUES (?, ?, ?)",
                ("MSFT", q, s),
            )

    mock_ticker = MagicMock()
    mock_ticker.calendar = {
        "Earnings Date": [date(2026, 4, 30)],
        "Earnings Average": 4.07,
        "Earnings High": 4.23,
        "Earnings Low": 3.94,
        "Revenue Average": 81.43e9,
    }
    mock_ticker.fast_info = {"lastPrice": 422.46}
    mock_ticker.options = ("2026-05-01",)
    chain = MagicMock()
    chain.calls = pd.DataFrame({"strike": [422.5], "bid": [14.0], "ask": [16.0]})
    chain.puts = pd.DataFrame({"strike": [422.5], "bid": [13.0], "ask": [15.0]})
    mock_ticker.option_chain.return_value = chain

    with (
        patch("nuri.collectors.earnings_preview.yf.Ticker", return_value=mock_ticker),
        patch("nuri.collectors.earnings_preview.today_kst", return_value="2026-04-30"),
    ):
        result = fetch_earnings_preview("msft")

    assert isinstance(result, EarningsPreview)
    assert result.ticker == "MSFT"
    assert result.earnings_date == date(2026, 4, 30)
    assert result.eps_avg == 4.07
    assert result.last_price == pytest.approx(422.46)
    assert result.implied_move_pct is not None and result.implied_move_pct > 0
    assert len(result.surprise_history) == 4


def test_fetch_no_calendar_data():
    """Missing earnings calendar → graceful degrade."""
    mock_ticker = MagicMock()
    mock_ticker.calendar = None
    mock_ticker.fast_info = {"lastPrice": 0.0}
    mock_ticker.options = ()

    with patch("nuri.collectors.earnings_preview.yf.Ticker", return_value=mock_ticker):
        result = fetch_earnings_preview("UNKNOWN")

    assert result.earnings_date is None
    assert result.eps_avg is None
    assert result.last_price is None
    assert result.implied_move_pct is None


def test_fetch_fast_info_exception():
    """fast_info access failure → last=0.0, no straddle attempted."""
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [date(2026, 4, 30)], "Earnings Average": 4.0}
    mock_ticker.fast_info.get.side_effect = Exception("boom")
    mock_ticker.options = ()

    with patch("nuri.collectors.earnings_preview.yf.Ticker", return_value=mock_ticker):
        result = fetch_earnings_preview("MSFT")
    assert result.last_price is None
    assert result.implied_move_pct is None


# --- render_markdown ---------------------------------------------------


def test_render_no_earnings():
    p = EarningsPreview(
        ticker="X",
        earnings_date=None,
        eps_avg=None,
        eps_high=None,
        eps_low=None,
        revenue_avg=None,
        last_price=None,
        next_expiration=None,
        atm_strike=None,
        straddle_mid=None,
        implied_move_pct=None,
        surprise_history=[],
    )
    md = render_markdown(p)
    assert "X" in md
    assert "no upcoming announcement" in md


def test_render_full_preview():
    p = EarningsPreview(
        ticker="MSFT",
        earnings_date=date(2026, 4, 30),
        eps_avg=4.07,
        eps_high=4.23,
        eps_low=3.94,
        revenue_avg=81.43e9,
        last_price=422.46,
        next_expiration="2026-05-01",
        atm_strike=422.5,
        straddle_mid=29.62,
        implied_move_pct=7.01,
        surprise_history=[0.057, 0.127, 0.081, 0.074],
    )
    md = render_markdown(p)
    assert "MSFT" in md
    assert "2026-04-30" in md
    assert "$4.07" in md
    assert "±7.01%" in md
    assert "2026-05-01" in md
    assert "+8.5%" in md  # surprise avg


def test_render_consensus_no_options():
    """EPS available but no implied move — show last_price line."""
    p = EarningsPreview(
        ticker="QCOM",
        earnings_date=date(2026, 4, 30),
        eps_avg=2.56,
        eps_high=2.66,
        eps_low=2.50,
        revenue_avg=10.58e9,
        last_price=154.85,
        next_expiration=None,
        atm_strike=None,
        straddle_mid=None,
        implied_move_pct=None,
        surprise_history=[],
    )
    md = render_markdown(p)
    assert "$154.85" in md
    assert "options chain unavailable" in md
    assert "no DB history" in md
