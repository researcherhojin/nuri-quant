"""Catalyst detection — Phase 2 A-4.

Non-emergency SELL 추천은 이유(catalyst)가 있어야 한다. stop-loss breach 는 기계적
규칙 (§2.2) 으로 예외 처리하지만, 그 외 SELL 은 (a) 해당 티커의 최근 뉴스 또는
(b) 최근 macro_events 중 유의미한 것 이 하나라도 있어야 'actionable' 로 surface.

없으면 tier=advisory 로 downgrade — STRATEGY §2.1 Evidence-first 의 "증거 없으면
추천 금지" 원칙. §2.6 Escalation Ladder 의 **Soft penalty** 단계 (차단 아닌 downgrade).

사용:
    from nuri.core.catalyst import has_recent_catalyst
    ok, reason = has_recent_catalyst("TSLA")
    if not ok:
        # downgrade SELL to advisory
"""
from __future__ import annotations

from nuri.core.db import query
from nuri.core.timezone import today_kst

# 윈도우: 티커 뉴스는 2주 (주식 관련 뉴스 사이클), macro 는 1주 (빠르게 stale)
NEWS_WINDOW_DAYS = 14
MACRO_WINDOW_DAYS = 7

# macro_events 유의미 판정 임계. event_score.py 의 CONFIDENCE_FLOOR 와 align.
MACRO_MIN_CONFIDENCE = 0.5
MACRO_MIN_ABS_SENTIMENT = 0.3


def has_recent_catalyst(
    ticker: str,
    ref_date: str | None = None,
    db_path=None,
) -> tuple[bool, str]:
    """티커에 최근 catalyst 가 있는지 판정.

    판정 기준 (둘 중 하나라도 만족 → catalyst 있음):
      1. `news` 테이블에 해당 ticker 로 최근 14일 내 뉴스가 있음
      2. `macro_events` 테이블에 최근 7일 내 유의미한 이벤트가 있음
         (confidence ≥ 0.5 AND |sentiment| ≥ 0.3)

    stop-loss breach 는 이 함수를 거치지 않음 — caller 가 skip 해야 함.

    Returns:
        (has_catalyst, reason): reason 은 logging/UI 용 짧은 설명.
    """
    ref = ref_date or today_kst()

    news_rows = query(
        """
        SELECT COUNT(*) AS n
        FROM news
        WHERE ticker = ?
          AND date >= date(?, '-' || ? || ' days')
        """,
        (ticker, ref, str(NEWS_WINDOW_DAYS)),
        db_path=db_path,
    )
    news_count = news_rows[0]["n"] if news_rows else 0

    if news_count > 0:
        return True, f"news ({news_count} item(s) in {NEWS_WINDOW_DAYS}d)"

    macro_rows = query(
        """
        SELECT COUNT(*) AS n
        FROM macro_events
        WHERE published_at >= date(?, '-' || ? || ' days')
          AND confidence >= ?
          AND ABS(COALESCE(sentiment, 0)) >= ?
        """,
        (ref, str(MACRO_WINDOW_DAYS), MACRO_MIN_CONFIDENCE, MACRO_MIN_ABS_SENTIMENT),
        db_path=db_path,
    )
    macro_count = macro_rows[0]["n"] if macro_rows else 0

    if macro_count > 0:
        return True, f"macro ({macro_count} significant event(s) in {MACRO_WINDOW_DAYS}d)"

    return False, "no ticker news + no significant macro event"
