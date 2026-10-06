"""Intraday live price oracle — Phase 2 A-5.

Stored prices in the `prices` table are T-1 (end of previous trading day). During
market hours the live price can diverge from stored by several percent, which
silently corrupts pnl calculation, stop-loss checks, and target hits.

This module surfaces the gap without yet acting on it — divergence is reported
as a flag alongside the existing stored-price-based reasoning. A future A-5b
(or similar) PR can swap the threshold comparisons over to live once we trust
the oracle under the full surface area.

Only yfinance is used as the live source. Rate-limited and best-effort — if
the fetch fails the caller sees `None` and treats the stored price as
authoritative (degrade gracefully).

Usage:
    from nuri.core.live_price import fetch_live_price, check_divergence

    live = fetch_live_price("TSLA")
    diverged, pct, live_val = check_divergence("TSLA", stored_price=407.5)
    if diverged:
        log.warning("TSLA diverged %+.2f%% — stored=%.2f live=%.2f",
                    pct, stored_price, live_val)
"""

from __future__ import annotations

import logging
from datetime import time as dtime

from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)

# 기본 divergence threshold (%) — NEXT_SESSION.md A-5 spec 과 일치. 3% 이상
# divergence 를 유의미한 stale 로 정의.
DEFAULT_DIVERGENCE_THRESHOLD_PCT = 3.0

# 시장 시간 (KST 기준). US: 22:30-05:00 (summer: 21:30-04:00; 간단 근사로 21:00-06:00 cover).
# KR: 09:00-15:30. 시장 외 시간 fetch 는 stale 가능성 높아 skip.
_US_OPEN_KST = dtime(21, 0)
_US_CLOSE_KST = dtime(6, 0)  # next day (wrap-around)
_KR_OPEN_KST = dtime(9, 0)
_KR_CLOSE_KST = dtime(15, 30)


def is_market_open_us(now=None) -> bool:
    """US 정규장이 KST 기준 열려 있는지 판정.

    US 장 시간은 KST 저녁 21:00 부터 다음날 새벽 06:00 까지 이어짐 (wrap-around).
    - `t >= 21:00`: 오늘 평일 밤 → 오늘이 Mon-Fri 여야 open
    - `t < 06:00`: 전날 밤 US 장의 연장 → 전날이 Mon-Fri 여야 open
      (codex Round 1 P2 수정: 이전엔 오늘 기준으로만 평일 check → 일→월 새벽 오판)
    """
    from datetime import timedelta

    now = now or kst_now()
    t = now.time()
    if t >= _US_OPEN_KST:
        return now.weekday() < 5
    if t < _US_CLOSE_KST:
        prev_day = (now - timedelta(days=1)).weekday()
        return prev_day < 5
    return False


def is_market_open_kr(now=None) -> bool:
    """KR 정규장이 KST 기준 열려 있는지 판정."""
    now = now or kst_now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return _KR_OPEN_KST <= t <= _KR_CLOSE_KST


def _ticker_market(ticker: str) -> str:
    """티커 → 'kr' or 'us' (거래 시장 분류)."""
    return "kr" if ticker.upper().endswith((".KS", ".KQ")) else "us"


def is_market_open_for(ticker: str, now=None) -> bool:
    """Ticker 시장이 지금 열려 있나?"""
    market = _ticker_market(ticker)
    return is_market_open_kr(now) if market == "kr" else is_market_open_us(now)


def fetch_live_price(ticker: str) -> float | None:
    """yfinance fast_info 로 live price 조회. 실패/시장외 시 None.

    시장 closed 면 stored price 와 같은 값일 가능성이 높아서 fetch 하지 않음
    (rate limit 소모 방지). 시장 open 이어도 fetch 실패하면 None (caller 는
    stored price fallback 사용 책임).
    """
    if not is_market_open_for(ticker):
        return None

    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        price = info.last_price
        if price is None or price <= 0:
            return None
        return float(price)
    except Exception as e:  # yfinance 이 다양한 내부 에러를 던짐
        logger.debug("live price fetch 실패 ticker=%s err=%s", ticker, e)
        return None


def fetch_quote(ticker: str) -> dict | None:
    """yfinance fast_info 로 현재 호가 한 건을 사실 그대로 — 시장 시간으로 걸러내지 않는다 (#1626).

    `fetch_live_price()` 는 divergence 검사용이라 장외에는 아예 조회하지 않지만, "지금 얼마인가" 를
    묻는 소비자(MCP `live_quote`)에게는 장외의 마지막 체결가도 사실이다. 대신 `market_open` 을
    같이 실어 소비자가 그 값을 실시간으로 오해하지 않게 한다. 미상장 티커·네트워크 실패는 None.
    """
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        price = info.last_price  # 미상장 티커는 여기서 KeyError
        if price is None or price <= 0:
            return None
        # `previous_close` 는 장외 시간 봉까지 섞은 값이라 공식 일간 변동과 어긋난다 (Codex 리뷰) —
        # 정규장 종가 기준을 쓴다.
        prev = info.regular_market_previous_close
        change_pct = round((float(price) - prev) / prev * 100, 2) if prev else None
        return {
            "ticker": ticker,
            "price": float(price),
            "previous_close": float(prev) if prev else None,
            "change_pct": change_pct,
            "currency": info.currency,
            "exchange": info.exchange,
            "market_open": is_market_open_for(ticker),
            "fetched_at": kst_now().isoformat(timespec="seconds"),
            "source": "yfinance",
        }
    except Exception as e:  # yfinance 이 다양한 내부 에러를 던짐
        logger.debug("quote fetch 실패 ticker=%s err=%s", ticker, e)
        return None


def check_divergence(
    ticker: str,
    stored_price: float,
    threshold_pct: float = DEFAULT_DIVERGENCE_THRESHOLD_PCT,
) -> tuple[bool, float, float | None]:
    """Stored price 와 live price 비교.

    Args:
        ticker: 티커
        stored_price: DB 에 저장된 (T-1) price
        threshold_pct: divergence threshold (기본 3%)

    Returns:
        (is_divergent, divergence_pct, live_price):
          - `is_divergent`: True if |divergence| >= threshold
          - `divergence_pct`: (live - stored) / stored * 100 — 양수 = live 가 높음
          - `live_price`: yfinance fetch 결과 (None 이면 check 불가)

        live_price 가 None 이면 is_divergent=False, div_pct=0.0 반환 (graceful
        degrade — 호출자는 live 확인 불가를 별도로 로깅할 수 있음).
    """
    if not stored_price or stored_price <= 0:
        return (False, 0.0, None)

    live = fetch_live_price(ticker)
    if live is None:
        return (False, 0.0, None)

    divergence_pct = (live - stored_price) / stored_price * 100
    # codex Round 1 LOW: spec 이 "3% 이상" 이므로 `>=` 로 정확히 boundary 포함.
    return (abs(divergence_pct) >= threshold_pct, divergence_pct, live)
