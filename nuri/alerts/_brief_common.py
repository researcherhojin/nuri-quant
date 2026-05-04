"""Shared helpers for premarket / postmarket brief generation (#596 Phase 1).

`premarket_brief.py` 의 일부 로직을 추출 — duplicate 제거는 별도 PR (Phase 2).
이 모듈은 외부 의존이 거의 없는 pure-data layer 로 유지.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from nuri.core.db import query

logger = logging.getLogger(__name__)


def load_macro_snapshot(db_path: Optional[Path] = None) -> dict[str, Any]:
    """VIX / Fear&Greed / SPY / KOSPI / USD-KRW 의 최신값 + 전 거래일 delta.

    각 indicator 는 macro 테이블 또는 prices 테이블에서 직접 조회. 없으면 None.
    """
    out: dict[str, Any] = {
        "vix": None,
        "fear_greed": None,
        "usd_krw": None,
        "spy": None,
        "kospi200": None,
    }

    # VIX / F&G / USD-KRW: macro 테이블 (latest + prev)
    for indicator, key in (("vix", "vix"), ("fear_greed", "fear_greed"), ("usd_krw", "usd_krw")):
        try:
            rows = query(
                "SELECT date, value FROM macro WHERE indicator = ? ORDER BY date DESC LIMIT 2",
                (indicator,),
                db_path=db_path,
            )
            if rows:
                latest = float(rows[0]["value"])
                prev = float(rows[1]["value"]) if len(rows) > 1 else None
                delta = (latest - prev) if prev is not None else None
                out[key] = {"value": latest, "date": rows[0]["date"], "delta": delta}
        except Exception:
            logger.warning("macro indicator %s 조회 실패", indicator, exc_info=True)

    # SPY / KOSPI200: prices 테이블 close 사용
    for ticker, key in (("SPY", "spy"), ("069500.KS", "kospi200")):
        try:
            rows = query(
                "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 2",
                (ticker,),
                db_path=db_path,
            )
            if rows and rows[0]["close"] is not None:
                latest = float(rows[0]["close"])
                prev = float(rows[1]["close"]) if len(rows) > 1 and rows[1]["close"] is not None else None
                pct = ((latest - prev) / prev * 100) if prev else None
                out[key] = {"value": latest, "date": rows[0]["date"], "delta_pct": pct}
        except Exception:
            logger.warning("price %s 조회 실패", ticker, exc_info=True)

    return out


def format_holdings_table(rows: list[dict[str, Any]]) -> str:
    """Markdown 표 — 보유 종목 한 줄씩.

    rows 는 dict(ticker, qty, close, prev_close, pnl_abs, pnl_pct, account) 형태.
    빈 list 면 "보유 없음" 텍스트.
    """
    if not rows:
        return "_보유 없음_"
    header = "| Ticker | Account | Qty | Close | Δ% | PnL |"
    sep = "|--------|---------|-----|-------|-----|-----|"
    lines = [header, sep]
    for r in rows:
        ticker = r.get("ticker", "?")
        account = r.get("account", "?")
        qty = r.get("qty", 0)
        close = r.get("close")
        pnl_pct = r.get("pnl_pct")
        pnl_abs = r.get("pnl_abs")
        close_s = f"{close:.2f}" if close is not None else "-"
        pct_s = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "-"
        abs_s = f"{pnl_abs:+,.0f}" if pnl_abs is not None else "-"
        lines.append(f"| {ticker} | {account} | {qty} | {close_s} | {pct_s} | {abs_s} |")
    return "\n".join(lines)


def _filter_actionable_accounts(holdings: dict[str, Any]) -> dict[str, Any]:
    """`account.strategy == "pension"` 인 계좌의 holdings 를 제외.

    holdings shape:
        {account_name: {"strategy": "core"|...|"pension", "rows": [...]}}
    pension 은 장기 연금성 buy-and-hold — daily action 대상이 아니므로
    postmarket brief 출력에서 제외.
    """
    return {
        acct: data
        for acct, data in holdings.items()
        if (data.get("strategy") or "core") != "pension"
    }
