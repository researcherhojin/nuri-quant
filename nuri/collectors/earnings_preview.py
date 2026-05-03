"""Earnings preview collector — fetch consensus EPS / revenue + options-implied move (Issue #509).

User-visible 결함: 사용자가 broker app 의 "위스퍼링 넘버 + 평균 변동성 + 내재 변동성"
같은 어닝 직전 데이터를 시스템 brief 에서도 보고 싶어함. 현재 system 에 earnings_date /
options chain / implied move 데이터 0 — `fundamentals` 테이블엔 PE 만 있고 forward EPS
estimate / earnings calendar / options IV 없음.

이 모듈이 그 gap 메움:
  - earnings date + EPS High/Low/Average (consensus) + revenue High/Low/Average
  - 가장 가까운 options expiration 의 ATM straddle → implied move %
  - 직전 4 분기 surprise % (already in `earnings_surprises` 테이블)

Phase 1 (이 PR):
  - yfinance.Ticker.calendar + option_chain 활용 (외부 API 추가 X)
  - CLI: `make earnings-preview ticker=MSFT` 또는 `--watchlist` 로 multiple
  - data 는 fetch on-demand (cache X — earnings 직전엔 stale 빠르게 발생)

Phase 2 (deferred):
  - whisper number (Estimize / StockTwits) — 별도 외부 API 필요
  - earnings_preview 테이블 cache + daily refresh
  - `premarket_brief` 통합 (이번 주 어닝 holdings 자동 surface)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import yfinance as yf

from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)


@dataclass
class EarningsPreview:
    ticker: str
    earnings_date: date | None
    eps_avg: float | None
    eps_high: float | None
    eps_low: float | None
    revenue_avg: float | None
    last_price: float | None
    next_expiration: str | None
    atm_strike: float | None
    straddle_mid: float | None
    implied_move_pct: float | None
    surprise_history: list[float]  # last 4Q surprise percentages


def _select_expiration(exps: tuple[str, ...], earnings_date: date | None, min_days: int = 2) -> str | None:
    """Pick first expiration ≥ min_days out (skip same-day/imminent expiries with 0 time value).

    어닝 직후 만료 옵션이 가장 깨끗한 implied move signal — 만료 임박은 시간가치 0,
    artificially low IV (e.g. AMZN 4-29 case).
    """
    if not exps:
        return None
    today = datetime.strptime(today_kst(), "%Y-%m-%d").date()
    cutoff = today + timedelta(days=min_days)
    parsed: list[tuple[date, str]] = []
    for e in exps:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            parsed.append((d, e))
        except ValueError:
            continue
    parsed.sort()
    # 1순위: earnings_date 직후 첫 만료. 2순위: cutoff 이후 첫 만료.
    if earnings_date:
        post_earnings = [(d, e) for d, e in parsed if d >= earnings_date]
        if post_earnings:
            return post_earnings[0][1]
    valid = [(d, e) for d, e in parsed if d >= cutoff]
    if valid:
        return valid[0][1]
    return parsed[-1][1] if parsed else None


def _atm_straddle(
    ticker_obj: yf.Ticker, last: float, earnings_date: date | None = None
) -> tuple[str | None, float | None, float | None, float | None]:
    """Return (expiration, ATM strike, straddle mid, implied move %)."""
    try:
        exps = ticker_obj.options
        exp = _select_expiration(exps, earnings_date)
        if not exp:
            return None, None, None, None
        chain = ticker_obj.option_chain(exp)
        calls, puts = chain.calls, chain.puts
        if calls.empty or puts.empty:
            return exp, None, None, None
        atm_call_idx = (calls["strike"] - last).abs().idxmin()
        atm_put_idx = (puts["strike"] - last).abs().idxmin()
        atm_call = calls.loc[atm_call_idx]
        atm_put = puts.loc[atm_put_idx]
        strike = float(atm_call["strike"])
        call_mid = (atm_call["bid"] + atm_call["ask"]) / 2
        put_mid = (atm_put["bid"] + atm_put["ask"]) / 2
        straddle = float(call_mid + put_mid)
        implied_move = straddle / last * 100 if last else 0.0
        return exp, strike, straddle, implied_move
    except Exception as e:
        logger.warning("ATM straddle fetch failed: %s", e)
        return None, None, None, None


def fetch_earnings_preview(ticker: str) -> EarningsPreview:
    """Fetch consensus EPS/revenue + options-implied move for a single ticker."""
    t = yf.Ticker(ticker.upper())

    # Earnings calendar
    cal = t.calendar or {}
    earnings_dates = cal.get("Earnings Date") or []
    earnings_date = earnings_dates[0] if earnings_dates else None
    eps_avg = cal.get("Earnings Average")
    eps_high = cal.get("Earnings High")
    eps_low = cal.get("Earnings Low")
    revenue_avg = cal.get("Revenue Average")

    # Last price
    try:
        last = float(t.fast_info.get("lastPrice", 0) or 0)
    except Exception:
        last = 0.0

    # ATM straddle (post-earnings expiration 우선)
    exp, strike, straddle, implied_move = _atm_straddle(t, last, earnings_date) if last else (None, None, None, None)

    # Surprise history from DB (already collected by other path)
    from nuri.core.db import query_df

    surprise_history: list[float] = []
    try:
        df = query_df(
            """SELECT surprise_pct FROM earnings_surprises WHERE ticker = ?
               ORDER BY quarter DESC LIMIT 4""",
            (ticker.upper(),),
        )
        surprise_history = [float(s) for s in df["surprise_pct"].tolist()] if not df.empty else []
    except Exception as e:
        logger.warning("surprise history fetch failed: %s", e)

    return EarningsPreview(
        ticker=ticker.upper(),
        earnings_date=earnings_date,
        eps_avg=eps_avg,
        eps_high=eps_high,
        eps_low=eps_low,
        revenue_avg=revenue_avg,
        last_price=last if last else None,
        next_expiration=exp,
        atm_strike=strike,
        straddle_mid=straddle,
        implied_move_pct=implied_move,
        surprise_history=surprise_history,
    )


def render_markdown(p: EarningsPreview) -> str:
    """Render preview as user-facing markdown."""
    lines = [f"## Earnings Preview — {p.ticker}", ""]

    if p.earnings_date:
        lines.append(f"**Earnings Date**: {p.earnings_date}")
    else:
        lines.append("**Earnings Date**: (no upcoming announcement found)")

    if p.eps_avg:
        rev_str = f" / Revenue avg ${p.revenue_avg / 1e9:.2f}B" if p.revenue_avg else ""
        eps_range = f"${p.eps_low:.2f}~${p.eps_high:.2f}" if (p.eps_low and p.eps_high) else "—"
        lines.append(f"**Consensus**: EPS avg ${p.eps_avg:.2f} (range {eps_range}){rev_str}")

    if p.last_price and p.implied_move_pct:
        lower = p.last_price * (1 - p.implied_move_pct / 100)
        upper = p.last_price * (1 + p.implied_move_pct / 100)
        lines.append(
            f"**Implied Move (ATM straddle, exp {p.next_expiration})**: "
            f"**±{p.implied_move_pct:.2f}%** (${lower:.2f} ~ ${upper:.2f}, "
            f"strike ${p.atm_strike:.2f}, straddle mid ${p.straddle_mid:.2f})"
        )
    elif p.last_price:
        lines.append(f"**Last price**: ${p.last_price:.2f} (options chain unavailable)")

    if p.surprise_history:
        history = " / ".join(f"{s * 100:+.1f}%" for s in p.surprise_history)
        avg = sum(p.surprise_history) / len(p.surprise_history) * 100
        lines.append(f"**Recent surprises (newest first)**: {history} (avg {avg:+.1f}%)")
    else:
        lines.append("**Recent surprises**: (no DB history)")

    lines.append("")
    lines.append(
        "> 위스퍼 넘버는 외부 API (Estimize/StockTwits) 필요 — Phase 2 deferred. "
        "현재는 consensus + options-implied move 만."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", help="single ticker (e.g. MSFT)")
    parser.add_argument(
        "--watchlist",
        help="comma-separated tickers (e.g. MSFT,META,AMZN,GOOGL)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.ticker and not args.watchlist:
        parser.error("provide --ticker or --watchlist")

    tickers = [args.ticker] if args.ticker else [t.strip() for t in args.watchlist.split(",")]

    for t in tickers:
        try:
            p = fetch_earnings_preview(t)
            print(render_markdown(p))
            print()
        except Exception as e:
            print(f"## {t}: ERROR {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
