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
