"""Crontab weekday parsing helpers for nuri.scheduler (#929)."""

from __future__ import annotations

# crontab 요일 숫자(0=일) → 이름. crontab 은 0 과 7 을 모두 일요일로 본다.
_CRONTAB_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")
_NAME_TO_CRONTAB_DOW = {n: i for i, n in enumerate(_CRONTAB_DOW_NAMES[:7])}


def _crontab_dow(field: str) -> str:
    """crontab 요일 필드 → APScheduler `day_of_week` 문자열.

    치환이 아니라 **열거**한다. `mon-fri` 로 문자열만 바꾸면 `*/2` 같은 step 형식이
    조용히 다른 요일 집합이 된다 — crontab `*/2` 는 0 부터라 일·화·목·토, APScheduler
    `*/2` 는 월부터라 월·수·금·일이다.
    """
    if field.strip() == "*":
        return "*"
    days = sorted(_parse_crontab_dow(field))  # crontab 번호 (0=일)
    # APScheduler 는 이름을 Mon=0…Sun=6 로 읽으므로 월요일부터 정렬해 내보낸다.
    ordered = sorted(days, key=lambda d: (d - 1) % 7)
    return ",".join(_CRONTAB_DOW_NAMES[d] for d in ordered)


def _parse_crontab_dow(field: str) -> set[int]:
    """crontab 요일 필드 → {0..6} (0=일). 7 은 0 으로 정규화."""
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, step_raw = part.partition("/")
            step = int(step_raw)
            if step < 1:
                raise ValueError(f"crontab 요일 step 이 1 미만: {field!r}")
        if part == "*":
            lo, hi = 0, 6
        elif "-" in part:
            lo_raw, _, hi_raw = part.partition("-")
            lo, hi = _dow_num(lo_raw), _dow_num(hi_raw)
        else:
            lo = hi = _dow_num(part)
        # crontab 은 lo > hi 인 wrap 범위(fri-mon 등)를 표준으로 지원하지 않는다.
        if lo > hi:
            raise ValueError(f"crontab 요일 범위가 역순: {field!r}")
        out.update(range(lo, hi + 1, step))
    return out


def _dow_num(token: str) -> int:
    """요일 토큰 → crontab 번호(0=일). 숫자와 이름 모두 허용."""
    token = token.strip().lower()
    if token.isdigit():
        n = int(token)
        if not 0 <= n <= 7:
            raise ValueError(f"crontab 요일 범위 밖: {token!r}")
        return n % 7
    if token not in _NAME_TO_CRONTAB_DOW:
        raise ValueError(f"알 수 없는 요일 토큰: {token!r}")
    return _NAME_TO_CRONTAB_DOW[token]
