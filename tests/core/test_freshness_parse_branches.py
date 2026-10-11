"""신선도 시각 파서의 strptime 폴백 — `fromisoformat` 이 거부하는 0 미패딩 날짜."""

from __future__ import annotations

from datetime import datetime

from nuri.core.freshness import _parse_timestamp
from nuri.core.timezone import KST


def test_an_unpadded_date_falls_back_to_strptime_and_is_read_as_kst():
    """`2026-1-5` 는 `fromisoformat` 이 거부하지만 `%Y-%m-%d` 는 받는다 — 시각대가 없으면 KST 다."""
    parsed = _parse_timestamp("2026-1-5")

    assert parsed == datetime(2026, 1, 5, tzinfo=KST)
    assert parsed.tzinfo is KST


def test_an_unpadded_hour_falls_back_too():
    assert _parse_timestamp("2026-10-07 9:05:00") == datetime(2026, 10, 7, 9, 5, tzinfo=KST)
