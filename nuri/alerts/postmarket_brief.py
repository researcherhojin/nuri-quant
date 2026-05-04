"""Post-market daily brief — KR (16:00 KST) / US (16:00 ET + 30min) 종장 후 자동 생성.

KR session (KST 16:00 cron): 한국장 holdings (`.KS`) PnL 합산 + KOSPI200 계열
sector mover. US session (KST 06:30 + 07:30 dual cron, NYSE close +30min 시점만
fire): non-`.KS` holdings PnL + 11 SPDR sector ETF mover.

Privacy: Discord publish payload 는 summary-only (regime / VIX delta / top sector
mover / total PnL %). ticker+PnL 조합 누설 방지 위해 `_privacy_gate_payload` 수동
호출 — violation 발견 시 publish abort + WARNING log.

Pension 계좌 제외: `account.strategy == "pension"` holdings 는 daily action 대상
아니므로 brief 출력에서 제외 (`_filter_actionable_accounts`).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from nuri.alerts._brief_common import (
    _filter_actionable_accounts,
    format_holdings_table,
    load_macro_snapshot,
)
from nuri.core.db import query, upsert_postmortem
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

# 11 SPDR sector ETFs (US session)
US_SECTOR_ETFS = (
    "XLK",  # Technology
    "XLF",  # Financials
    "XLE",  # Energy
    "XLV",  # Health Care
    "XLP",  # Consumer Staples
    "XLY",  # Consumer Discretionary
    "XLB",  # Materials
    "XLI",  # Industrials
    "XLU",  # Utilities
    "XLRE",  # Real Estate
    "XLC",  # Communication Services
)

# KR session sector universe — KOSPI200 ETF 우선, sector-level ETF 부재 시 fallback.
KR_SECTOR_ETFS = (
    "069500.KS",  # KODEX 200 (KOSPI200 추종 — 시장 전체 proxy)
)


def _resolve_strategy_name(account: str) -> str:
    """portfolio.yaml `accounts.<account>.strategy` 직접 조회 — 없으면 'core'.

    `get_account_strategy()` 는 dict (stop_loss/max_position/...) 만 반환하므로
    pension 식별이 modeling-noise (stop_loss=-30 매칭) 가 됨. 여기선 strategy
    이름이 명시적으로 필요하므로 yaml 을 직접 읽어 names 만 반환.
    """
    import yaml

    portfolio_path = Path(__file__).resolve().parents[2] / "config" / "portfolio.yaml"
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            portfolio = yaml.safe_load(f) or {}
        return portfolio.get("accounts", {}).get(account, {}).get("strategy", "core")
    except Exception:
        return "core"


def _load_holdings_with_strategy(db_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """portfolio + 계좌 strategy 매핑.

    Returns:
        {account: {"strategy": "core"|...|"pension", "rows": [{ticker, qty, ...}, ...]}}
    """
    portfolio_rows = query(
        """
        SELECT p.account, p.ticker, p.quantity, p.avg_price,
               pr.close, pr_prev.close as prev_close
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (
                SELECT ticker, date FROM (
                    SELECT ticker, date, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                    FROM prices
                ) WHERE rn = 2
            )
        ) pr_prev ON p.ticker = pr_prev.ticker
        """,
        db_path=db_path,
    )

    by_account: dict[str, dict[str, Any]] = {}
    for r in portfolio_rows:
        account = r["account"]
        if account not in by_account:
            strategy_name = _resolve_strategy_name(account)
            by_account[account] = {"strategy": strategy_name, "rows": []}
        by_account[account]["rows"].append(
            {
                "ticker": r["ticker"],
                "qty": r["quantity"] or 0,
                "avg_price": r["avg_price"],
                "close": r["close"],
                "prev_close": r["prev_close"],
            }
        )
    return by_account


def _filter_session_holdings(
    holdings: dict[str, dict[str, Any]], session: Literal["kr", "us"]
) -> dict[str, dict[str, Any]]:
    """session 별 ticker 필터 — KR=`.KS` only, US=non-`.KS`."""
    out: dict[str, dict[str, Any]] = {}
    for acct, data in holdings.items():
        kept = [
            r
            for r in data["rows"]
            if (str(r["ticker"]).endswith(".KS") if session == "kr" else not str(r["ticker"]).endswith(".KS"))
        ]
        if kept:
            out[acct] = {"strategy": data["strategy"], "rows": kept}
    return out


def _compute_holdings_pnl(holdings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """일일 PnL — (close - prev_close) × qty per ticker, account 별 합산.

    Returns:
        {
          "total_abs": <sum>,         # 통화 무관 raw 합 (단순 시각화 용)
          "total_pct_weighted": <%>,  # close*qty 가중 평균 변화율
          "rows": [{ticker, account, qty, close, prev_close, pnl_abs, pnl_pct}]
        }
    """
    rows_out: list[dict[str, Any]] = []
    total_abs = 0.0
    total_value = 0.0
    total_pnl = 0.0

    for acct, data in holdings.items():
        for r in data["rows"]:
            qty = float(r.get("qty") or 0)
            close = r.get("close")
            prev = r.get("prev_close")
            if close is None or prev is None or qty == 0:
                rows_out.append(
                    {
                        "ticker": r["ticker"],
                        "account": acct,
                        "qty": qty,
                        "close": close,
                        "prev_close": prev,
                        "pnl_abs": None,
                        "pnl_pct": None,
                    }
                )
                continue
            pnl_abs = (close - prev) * qty
            pnl_pct = (close - prev) / prev * 100 if prev else 0.0
            value = close * qty
            total_abs += pnl_abs
            total_value += value
            total_pnl += pnl_abs
            rows_out.append(
                {
                    "ticker": r["ticker"],
                    "account": acct,
                    "qty": qty,
                    "close": close,
                    "prev_close": prev,
                    "pnl_abs": pnl_abs,
                    "pnl_pct": pnl_pct,
                }
            )

    weighted_pct = (total_pnl / total_value * 100) if total_value > 0 else 0.0
    return {"total_abs": total_abs, "total_pct_weighted": weighted_pct, "rows": rows_out}


def _load_sector_movers(session: Literal["kr", "us"], db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Session 별 sector ETF 일일 변화율 — close vs prev_close.

    US: 11 SPDR (schema lock) — 가용 prices 없으면 None 으로 surface.
    KR: KOSPI200 ETF (069500.KS) — sector-level ETF 부재 시 fallback (시장 proxy 만).
    """
    tickers = US_SECTOR_ETFS if session == "us" else KR_SECTOR_ETFS
    out: list[dict[str, Any]] = []
    for t in tickers:
        try:
            rows = query(
                "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 2",
                (t,),
                db_path=db_path,
            )
        except Exception:
            logger.warning("sector mover %s 조회 실패", t, exc_info=True)
            rows = []
        if rows and rows[0]["close"] is not None:
            latest = float(rows[0]["close"])
            prev = float(rows[1]["close"]) if len(rows) > 1 and rows[1]["close"] is not None else None
            pct = ((latest - prev) / prev * 100) if prev else None
            out.append({"ticker": t, "close": latest, "delta_pct": pct})
        else:
            out.append({"ticker": t, "close": None, "delta_pct": None})
    return out


def _format_markdown(
    session: Literal["kr", "us"],
    date: str,
    macro: dict[str, Any],
    holdings: dict[str, dict[str, Any]],
    pnl: dict[str, Any],
    sectors: list[dict[str, Any]],
) -> str:
    """Local persist artifact — Claude 가 다음 session 에서 읽을 수 있게 markdown."""
    title = "Post-market Brief — {} ({})".format(date, "KR session" if session == "kr" else "US session")
    lines = [f"# {title}", "", f"Generated: {kst_now().isoformat()}", ""]

    # Macro snapshot
    lines.append("## Macro Snapshot")
    for key, label in (
        ("vix", "VIX"),
        ("fear_greed", "F&G"),
        ("usd_krw", "USD/KRW"),
        ("spy", "SPY"),
        ("kospi200", "KOSPI200"),
    ):
        m = macro.get(key)
        if not m:
            continue
        v = m.get("value")
        d = m.get("delta") if "delta" in m else m.get("delta_pct")
        if d is None:
            lines.append(f"- {label}: {v:.2f} ({m.get('date')})")
        else:
            unit = "%" if "delta_pct" in m else ""
            lines.append(f"- {label}: {v:.2f} (Δ{d:+.2f}{unit})")
    lines.append("")

    # Sectors
    label = "11 SPDR Sectors" if session == "us" else "KR Market"
    lines.append(f"## Sector Movers ({label})")
    valid = [s for s in sectors if s.get("delta_pct") is not None]
    if not valid:
        lines.append("_데이터 없음_")
    else:
        for s in sorted(valid, key=lambda x: -x["delta_pct"]):
            lines.append(f"- {s['ticker']}: {s['delta_pct']:+.2f}% (close {s['close']:.2f})")
    lines.append("")

    # Holdings (pension 제외)
    actionable = _filter_actionable_accounts(holdings)
    flat_rows: list[dict[str, Any]] = []
    for acct, data in actionable.items():
        for r in data["rows"]:
            # pnl 계산이 끝난 rows 와 cross-ref — 같은 (ticker, account) 매칭
            for pnl_row in pnl["rows"]:
                if pnl_row["ticker"] == r["ticker"] and pnl_row["account"] == acct:
                    flat_rows.append(pnl_row)
                    break

    lines.append("## Holdings (pension 제외)")
    if not flat_rows:
        lines.append("_데이터 없음_")
    else:
        lines.append(format_holdings_table(flat_rows))
        # pension 제외한 actionable 만의 합산을 별도 표시
        a_pnl = sum((r.get("pnl_abs") or 0) for r in flat_rows)
        a_val = sum(((r.get("close") or 0) * (r.get("qty") or 0)) for r in flat_rows)
        a_pct = (a_pnl / a_val * 100) if a_val > 0 else 0.0
        lines.append("")
        lines.append(f"**Actionable PnL**: {a_pnl:+,.0f} ({a_pct:+.2f}%)")
    lines.append("")

    return "\n".join(lines)


def _persist_markdown(markdown: str, session: Literal["kr", "us"], date: str) -> Path:
    """`data/reports/postmarket/{date}-{session}.md` UPSERT (idempotent re-write)."""
    base = Path(__file__).resolve().parents[2] / "data" / "reports" / "postmarket"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{date}-{session}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def _build_summary_payload(
    session: Literal["kr", "us"],
    macro: dict[str, Any],
    pnl: dict[str, Any],
    sectors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Discord summary payload — ticker+PnL combo 누설 방지 위해 aggregate only.

    Privacy: 개별 ticker × signed-% 조합 미포함. sector mover 는 ETF ticker 만,
    holdings PnL 은 합산 % 만.
    """
    vix_delta = None
    if macro.get("vix") and macro["vix"].get("delta") is not None:
        vix_delta = macro["vix"]["delta"]

    valid = [s for s in sectors if s.get("delta_pct") is not None]
    top_sector = max(valid, key=lambda x: x["delta_pct"]) if valid else None

    summary = {
        "kind": "INFO",
        "session": session,
        "date": today_kst(),
        "regime_note": f"{session.upper()} close",
        "vix_delta": vix_delta,
        "total_pnl_pct": round(pnl.get("total_pct_weighted", 0.0), 2),
        "top_sector": (
            {"ticker": top_sector["ticker"], "delta_pct": round(top_sector["delta_pct"], 2)} if top_sector else None
        ),
    }
    return summary


def _publish_discord(payload: dict[str, Any]) -> Optional[int]:
    """`stage_brief` 호출 전 `_privacy_gate_payload` 수동 호출 — violation 발견 시 abort.

    Returns: outbox id (성공) / None (privacy abort or stage failure).
    """
    from nuri.agents.discord.outbox import _privacy_gate_payload, stage_brief

    try:
        findings = _privacy_gate_payload(payload)
    except Exception as exc:
        logger.warning("privacy gate raised (%s); blocking postmarket publish", exc)
        return None
    if findings:
        logger.warning(
            "privacy gate blocked postmarket_brief publish — %d violation(s): %s",
            len(findings),
            [f"{f.category}:{f.pattern}" for f in findings[:3]],
        )
        return None

    return stage_brief(payload, dedupe_key=f"postmarket-{payload['session']}-{payload['date']}")


def _load_5d_macro_delta(indicator: str, *, db_path: Optional[Path] = None) -> Optional[float]:
    """`macro` 테이블에서 latest - 5거래일전 delta. 데이터 부족 시 None.

    Phase 2 (#596): similarity feature vector 의 `*_5d_delta` 채움 용도.
    """
    rows = query(
        "SELECT value FROM macro WHERE indicator = ? ORDER BY date DESC LIMIT 6",
        (indicator,),
        db_path=db_path,
    )
    if len(rows) < 6:
        return None
    try:
        latest = float(rows[0]["value"])
        five_back = float(rows[5]["value"])
    except (
        TypeError,
        ValueError,
    ):  # pragma: no cover — defensive numeric coercion (DB returns valid numerics in tests)
        return None
    return latest - five_back


def _load_5d_price_delta_pct(ticker: str, *, db_path: Optional[Path] = None) -> Optional[float]:
    """`prices` close — latest 대비 5거래일전 close 의 % 변화. 데이터 부족 시 None."""
    rows = query(
        "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 6",
        (ticker,),
        db_path=db_path,
    )
    if len(rows) < 6 or rows[0]["close"] is None or rows[5]["close"] is None:
        return None
    latest = float(rows[0]["close"])
    five_back = float(rows[5]["close"])
    if five_back == 0:  # pragma: no cover — divide-by-zero guard
        return None
    return (latest - five_back) / five_back * 100


def _persist_postmortem(
    session: Literal["kr", "us"],
    date: str,
    macro: dict[str, Any],
    pnl: dict[str, Any],
    sectors: list[dict[str, Any]],
    *,
    db_path: Optional[Path] = None,
) -> None:
    """`market_postmortem` row UPSERT — Phase 2 pattern memory (#596).

    Indexed feature columns drive `find_similar_days` cosine similarity;
    JSON blobs preserve full markdown context for downstream LLM retro.
    """
    from nuri.quant.regime.classifier import classify_regime

    try:
        regime_state = classify_regime(date=date, db_path=db_path)
        regime = regime_state.regime if regime_state is not None else None
    except Exception:  # pragma: no cover — regime DB missing in fresh test env
        logger.warning("classify_regime 실패 — regime field 비움", exc_info=True)
        regime = None

    valid_sectors = [s for s in sectors if s.get("delta_pct") is not None]
    top_sector = max(valid_sectors, key=lambda x: abs(x["delta_pct"])) if valid_sectors else None

    vix_val = (macro.get("vix") or {}).get("value")
    fg_val = (macro.get("fear_greed") or {}).get("value")

    upsert_postmortem(
        date=date,
        session=session,
        regime=regime,
        vix=vix_val,
        fear_greed=fg_val,
        vix_5d_delta=_load_5d_macro_delta("vix", db_path=db_path),
        fg_5d_delta=_load_5d_macro_delta("fear_greed", db_path=db_path),
        spy_5d_delta=_load_5d_price_delta_pct("SPY", db_path=db_path),
        top_sector_delta_pct=top_sector["delta_pct"] if top_sector else None,
        holdings_total_pnl_pct=round(pnl.get("total_pct_weighted", 0.0), 4),
        macro_summary=macro,
        holdings_pnl={
            "total_abs": pnl.get("total_abs"),
            "total_pct_weighted": pnl.get("total_pct_weighted"),
            "rows": pnl.get("rows", []),
        },
        sector_movers=sectors,
        catalysts={},  # Phase 3: news + earnings join
        retro_lessons=[],  # Phase 3: LLM synthesis
        db_path=db_path,
    )


def write_brief(
    session: Literal["kr", "us"],
    date: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> Path:
    """KR/US 종장 후 brief markdown 생성 + Discord publish + DB pattern row.

    Returns: data/reports/postmarket/{date}-{session}.md path.
    """
    d = date or today_kst()

    macro = load_macro_snapshot(db_path=db_path)
    holdings_all = _load_holdings_with_strategy(db_path=db_path)
    holdings = _filter_session_holdings(holdings_all, session)
    pnl = _compute_holdings_pnl(_filter_actionable_accounts(holdings))
    sectors = _load_sector_movers(session, db_path=db_path)

    md = _format_markdown(session, d, macro, holdings, pnl, sectors)
    path = _persist_markdown(md, session, d)
    logger.info("Post-market brief persisted: %s", path)

    # Phase 2 (#596): pattern memory row — similarity-search ready
    try:
        _persist_postmortem(session, d, macro, pnl, sectors, db_path=db_path)
    except Exception:
        logger.warning("market_postmortem upsert 실패 (브리프 자체는 생성됨)", exc_info=True)

    # Discord publish — privacy gate 후 stage_brief
    summary = _build_summary_payload(session, macro, pnl, sectors)
    outbox_id = _publish_discord(summary)
    if outbox_id is None:
        logger.info("Post-market brief Discord publish 미발행 (gate 차단 또는 outbox 미작동)")

    return path


# ─── US session DST-aware dispatch ───────────────────────────────────────────
# Cron 06:30 KST + 07:30 KST 두 시각 양쪽 등록 — 함수 내부에서 NYSE close
# (16:00 ET) + 30min 시각인지 확인 후 분기. EST/EDT 자동 처리. 2회 fire risk
# 는 idempotent persist (덮어쓰기) 로 mitigate.


def _is_now_within_us_postclose_window(*, _now_kst=None) -> bool:
    """현재 시각이 NYSE close + 30min 의 ±15분 내인지 (DST 자동 처리).

    NYSE close: 16:00 America/New_York. close + 30min = 16:30 ET.
    EST (Nov 첫 일요일 ~ Mar 둘째 일요일): KST 06:30
    EDT (Mar 둘째 일요일 ~ Nov 첫 일요일): KST 05:30 — but cron 06:30 / 07:30
    KST 양쪽 등록이라 EDT 기간엔 06:30 (=NYSE 17:30 ET, late-fire) skip.

    실제 trigger 는 dual-cron 중 NYSE 16:30 ET 와 매칭되는 한쪽만 진행.
    """
    now_kst = _now_kst or kst_now()
    nyse_now = now_kst.astimezone(ZoneInfo("America/New_York"))
    # 16:30 ET ± 15분
    minutes_from_close = (nyse_now.hour - 16) * 60 + nyse_now.minute - 30
    return -15 <= minutes_from_close <= 15


def run_postmarket_us_dst_aware() -> Optional[Path]:
    """Scheduler 진입점 — dual-cron (06:30 / 07:30 KST) 중 NYSE 16:30 ET 와 일치하는 시점만 실행."""
    if not _is_now_within_us_postclose_window():
        logger.info("postmarket_us skip — not within NYSE 16:30 ET window")
        return None
    return write_brief("us")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Post-market daily brief (KR / US)")
    parser.add_argument("--session", choices=("kr", "us"), required=True, help="Session (KR / US)")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today KST)")
    args = parser.parse_args(argv)

    path = write_brief(args.session, date=args.date)
    print(str(path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
