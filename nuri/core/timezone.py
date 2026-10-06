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


def sqlite_utc_to_kst_iso(value: str | None) -> str | None:
    """SQLite `datetime('now')` 기본값(오프셋 없는 UTC 텍스트) → KST ISO(`+09:00`).

    `pipeline_events.timestamp`·`decisions.created_at` 같은 열은 UTC 인데 오프셋이 없어,
    API 가 그대로 내보내면 화면이 9시간 어긋난 시각을 KST 처럼 보인다 (#1675). API 경계에서만 쓴다.

    오프셋이 이미 있으면 그 시각을 KST 로 옮기기만 한다(다시 9시간 밀지 않는다). 시각으로 읽을 수 없는
    값은 그대로 돌려준다 — 표시용 변환 하나 때문에 엔드포인트 전체가 500 이 되면 안 된다.
    """
    if not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" ", "T", 1))
    except ValueError:
        return value
    return to_kst(parsed).replace(microsecond=0).isoformat()
