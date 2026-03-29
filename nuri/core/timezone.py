"""타임존 유틸리티 -- UTC 기반 내부 시간, KST 표시용 변환."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ET = timezone(timedelta(hours=-5))  # EST (DST 미적용 -- 단순화)
UTC = timezone.utc


def utc_now() -> datetime:
    """현재 UTC 시간."""
    return datetime.now(UTC)


def kst_now() -> datetime:
    """현재 KST 시간."""
    return datetime.now(KST)


def today_utc() -> str:
    """오늘 날짜 (UTC) YYYY-MM-DD."""
    return utc_now().strftime("%Y-%m-%d")


def today_kst() -> str:
    """오늘 날짜 (KST) YYYY-MM-DD."""
    return kst_now().strftime("%Y-%m-%d")


def to_kst(dt: datetime) -> datetime:
    """UTC datetime -> KST 변환."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST)
