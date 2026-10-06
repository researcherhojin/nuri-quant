"""#1636 — KIS 미국 현재가 행의 date 는 KST 달력이 아니라 뉴욕 거래일이다."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from nuri.collectors import kis_realtime as mod

KST = ZoneInfo("Asia/Seoul")


def _kst(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


class TestUsSessionDate:
    @pytest.mark.parametrize(
        ("now", "expected", "why"),
        [
            (_kst(2026, 10, 6, 9, 0), "2026-10-05", "KST 화 09:00 = 뉴욕 월 20:00, 월요일 세션 종가"),
            (_kst(2026, 10, 6, 22, 0), "2026-10-05", "KST 화 22:00 = 뉴욕 화 09:00, 개장 전이라 월요일"),
            (_kst(2026, 10, 6, 23, 30), "2026-10-06", "KST 화 23:30 = 뉴욕 화 10:30, 장중"),
            (_kst(2026, 10, 7, 5, 30), "2026-10-06", "KST 수 05:30 = 뉴욕 화 16:30, 마감 직후"),
            (_kst(2026, 10, 11, 9, 0), "2026-10-09", "KST 일 09:00 = 뉴욕 토 20:00 → 금요일"),
            (_kst(2026, 10, 12, 22, 0), "2026-10-09", "KST 월 22:00 = 뉴욕 월 09:00 개장 전 → 금요일"),
            (_kst(2026, 10, 13, 0, 0), "2026-10-12", "Columbus Day 는 NYSE 가 열린다"),
            (_kst(2026, 4, 4, 0, 0), "2026-04-02", "Good Friday(04-03) 휴장 → 목요일"),
            (_kst(2026, 12, 26, 0, 0), "2026-12-24", "Christmas(12-25, 금) 휴장 → 목요일"),
            (_kst(2026, 1, 20, 1, 0), "2026-01-16", "MLK Day(01-19, 월) 휴장 → 직전 금요일"),
            (
                _kst(2027, 12, 31, 23, 30),
                "2027-12-31",
                "New Year's 가 토요일(2028-01-01)이면 NYSE 는 금요일에 쉬지 않는다",
            ),
            (
                _kst(2028, 1, 4, 1, 0),
                "2028-01-03",
                "KST 화 01:00 = 뉴욕 월(01-03) 11:00 장중 — 토요일 New Year's 의 월요일 대체 휴무는 없다",
            ),
        ],
    )
    def test_maps_kst_instant_to_new_york_trading_day(self, now, expected, why):
        assert mod.us_session_date(now) == expected, why

    def test_default_uses_kst_now(self, monkeypatch):
        monkeypatch.setattr(mod, "kst_now", lambda: _kst(2026, 10, 6, 9, 0))
        assert mod.us_session_date() == "2026-10-05"


class TestInquirePriceUsStampsSessionDate:
    def test_row_date_is_the_us_session_not_kst_today(self, monkeypatch):
        """KST 화요일 아침의 미국 시세는 월요일 세션 — 일일 수집기와 같은 (ticker, date) 에 들어간다."""
        monkeypatch.setattr(mod, "kst_now", lambda: _kst(2026, 10, 6, 9, 0))
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-10-06")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"rt_cd": "0", "output": {"last": "100.5"}}
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: ok)
        creds = mod.KISCredentials("k", "s", "", "", "prod")

        row = mod.inquire_price_us(creds, "T", "SPY")

        assert row is not None
        assert row["date"] == "2026-10-05"


class TestSaveNeverReplacesACompleteBar:
    """#1636 P1 — 날짜를 바로잡으면 KIS 미국 현재가(O/H/L 없음)가 yfinance 일봉과 같은 키에 떨어진다."""

    def _bar(self, ticker, date, o, h, lo, c):
        import pandas as pd

        return pd.DataFrame(
            [{"ticker": ticker, "date": date, "open": o, "high": h, "low": lo, "close": c, "volume": 1, "adj_close": c}]
        )

    def test_quote_without_ohl_does_not_overwrite_existing_bar(self):
        from nuri.core.db import query, upsert_prices

        upsert_prices(self._bar("SPY", "2026-10-05", 770.0, 776.0, 768.5, 774.88))
        collector = mod.KISRealtimeCollector.__new__(mod.KISRealtimeCollector)
        collector.logger = mod.logger

        written = collector.save(self._bar("SPY", "2026-10-05", 0.0, 0.0, 0.0, 775.1))

        assert written == 0
        row = query("SELECT open, high, low, close FROM prices WHERE ticker='SPY' AND date='2026-10-05'")[0]
        assert (row["open"], row["high"], row["low"], row["close"]) == (770.0, 776.0, 768.5, 774.88)

    def test_quote_without_ohl_is_written_when_no_bar_exists(self):
        from nuri.core.db import query

        collector = mod.KISRealtimeCollector.__new__(mod.KISRealtimeCollector)
        collector.logger = mod.logger

        assert collector.save(self._bar("SPY", "2026-10-06", 0.0, 0.0, 0.0, 775.1)) == 1
        assert query("SELECT close FROM prices WHERE ticker='SPY' AND date='2026-10-06'")[0]["close"] == 775.1

    def test_complete_bar_still_replaces(self):
        """한국 현재가와 yfinance fallback 행은 O/H/L 을 갖고 오므로 같은 날 갱신이 계속 된다."""
        from nuri.core.db import query, upsert_prices

        upsert_prices(self._bar("005930.KS", "2026-10-06", 70000, 70500, 69800, 70100))
        collector = mod.KISRealtimeCollector.__new__(mod.KISRealtimeCollector)
        collector.logger = mod.logger

        assert collector.save(self._bar("005930.KS", "2026-10-06", 70000, 71000, 69800, 70900)) == 1
        assert query("SELECT close FROM prices WHERE ticker='005930.KS'")[0]["close"] == 70900


class TestYfinanceFallbackDate:
    def test_us_fallback_row_carries_the_bar_date_not_kst_today(self, monkeypatch):
        import pandas as pd

        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-10-02 00:00", tz="America/New_York"),
                pd.Timestamp("2026-10-05 00:00", tz="America/New_York"),
            ]
        )
        hist = pd.DataFrame(
            {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0], "Close": [1.0, 2.5], "Volume": [1, 2]},
            index=idx,
        )
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value.history.return_value = hist
        monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-10-06")

        rows = mod.KISRealtimeCollector._yfinance_fallback(["SPY"])

        assert rows[0]["date"] == "2026-10-05"
        assert rows[0]["close"] == 2.5
