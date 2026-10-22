"""계좌별 손절 평가 — API와 브리프가 같은 입력 계약을 사용한다."""

import math

from nuri.core.freshness import check_timestamp_freshness
from nuri.core.rules import get_account_strategy_name, get_stop_loss_for_account
from nuri.core.timezone import today_kst


def assess_stop_loss(account: str, avg: float | None, current: float | None, price_date: str | None) -> dict:
    """기존 손절선은 그대로 적용하고, 평가 불가능한 입력은 별도로 반환한다."""
    result = {
        "status": "unknown",
        "price_date": price_date,
        "pnl_pct": None,
        "threshold": get_stop_loss_for_account(account),
        "reason": "판단 불가 — 가격 또는 매입가 없음",
    }
    if get_account_strategy_name(account) == "pension":
        return {**result, "status": "excluded", "reason": "연금 계좌 — 일일 손절 평가 제외"}
    if any(v is None or not math.isfinite(v) or v <= 0 for v in (avg, current)):
        return result
    freshness = check_timestamp_freshness("prices", price_date)
    if not price_date or freshness["status"] != "PASS":
        return {**result, "reason": f"판단 불가 — 가격 기준일 {price_date or '미상'} ({freshness['message']})"}
    if price_date[:10] > today_kst():
        return {**result, "reason": f"판단 불가 — 미래 가격 기준일 {price_date}"}
    assert avg is not None and current is not None
    pnl = (current - avg) / avg * 100
    threshold = result["threshold"]
    breached = current < avg * (1 + threshold / 100)
    return {
        **result,
        "status": "breached" if breached else "clear",
        "pnl_pct": pnl,
        "reason": (
            f"손실 {pnl:+.1f}% — 손절선 {threshold}% 돌파 ({threshold - pnl:.1f}%p 초과)"
            if breached
            else "손절선 이탈 없음"
        ),
    }
