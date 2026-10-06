"""미국 주식시장 휴장 달력 — 수집기(세션 날짜)와 신선도(휴장일 면제)가 같은 달력을 쓴다.

#1636 에서 `nuri/collectors/kis_realtime.py` 에 만든 것을 core 로 옮겼다 (#1677). 신선도 판정이
주말·휴장일을 "낡음" 으로 세지 않으려면 같은 달력이 필요한데, core 가 collectors 를 import 하면
안 되고 두 벌을 두면 갈라진다.
"""

from datetime import date

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USFederalHolidayCalendar,
    sunday_to_monday,
)


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """NYSE 휴장일 ≈ 연방 공휴일 − (Columbus Day, Veterans Day: 장은 연다) + Good Friday.

    New Year's 는 연방 규칙(nearest_workday)과 달리 토요일이면 금요일에 쉬지 않는다 — 일요일만
    월요일로 넘긴다. 특별 휴장(국장 등)은 모델에 없다 *(facts, no fix)*. `nuri/core/freshness.py`
    의 `_us_federal_holidays` 는 발행 달력용 연방 공휴일이라 이 달력과 다른 것이 맞다.
    """

    rules = (
        [Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday)]
        + [
            r
            for r in USFederalHolidayCalendar.rules
            if r.name not in ("New Year's Day", "Columbus Day", "Veterans Day")
        ]
        + [GoodFriday]
    )


def nyse_holidays(start: date, end: date) -> set[date]:
    """[start, end] 안의 NYSE 휴장일 (주말 제외)."""
    # stubs 가 holidays() 원소를 NaT 가능으로 잡는다 — isinstance 로 date 만 남겨 타입을 확정한다
    days = [pd.Timestamp(ts).to_pydatetime().date() for ts in NYSEHolidayCalendar().holidays(start=start, end=end)]
    return {d for d in days if isinstance(d, date)}


def us_market_closed_days(start: date, end: date) -> list[date]:
    """(start, end) **열린 구간**의 미국 장 휴장일 — 주말 + NYSE 휴장일.

    `end` 는 뉴욕 기준 오늘이다: 그 날이 뉴욕에서 다 지나야 "장이 없었던 날" 이 된다
    (`freshness._us_federal_holidays` 와 같은 규약, #1469 Codex).
    """
    days = pd.date_range(start, end, inclusive="neither")
    closed = nyse_holidays(start, end)
    out = [ts.date() for ts in days]
    return [d for d in out if d.weekday() >= 5 or d in closed]


def weekend_days(start: date, end: date) -> list[date]:
    """(start, end) 열린 구간의 토·일 — 휴장 달력이 없는 시장(한국)용. 공휴일은 정직하게 센다."""
    return [ts.date() for ts in pd.date_range(start, end, inclusive="neither") if ts.weekday() >= 5]
