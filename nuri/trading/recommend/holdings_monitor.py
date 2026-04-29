"""Holdings monitor — close the post-entry technical-divergence gap exposed by JKHY-class failures.

Entry-time defense (PR #303 divergence penalty + risk_agent veto, STRATEGY §5.10)
catches "fundamentals BUY but technicals SELL" BEFORE a buy. This module catches
the analogous AFTER-buy failure: a name that was valid at entry but later turns
into a falling knife technically.

Design (Codex Plan consult 2026-04-29 — frozen, ≤3 commit Build):
  - Source of truth: `portfolio` DB table (NOT config/portfolio.yaml at runtime)
  - Reuse `analyze_ticker` (consensus → TechnicalAgent + divergence_flag) — no new TA logic
  - Two triggers (independent):
      (a) TechnicalAgent action == SELL AND confidence ≥ 80 — "falling knife"
      (b) Divergence: consensus.divergence_flag True AND tech.confidence ≥ 70
  - Dedup: 7 calendar days per (ticker, trigger_type) — query pipeline_events directly
  - Asset-class scope: equity_us + equity_kr (crypto excluded — different vol profile)
  - Data gap: skip + warn + count in run-summary; NO user-facing "data gap" alert
  - Alerts only — REVIEW CTA, never SELL (auto-trade deferred per STRATEGY §7.1)
  - NO outcome_30d/60d/90d attachment (would contaminate Learning Memory)

Run:
  - APScheduler 07:10 KST daily (after consensus 07:05) — see nuri/scheduler.py
  - CLI: `make holdings-monitor` or `python -m nuri.trading.recommend.holdings_monitor`
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from nuri.core.db import query, query_df
from nuri.core.events import emit_event
from nuri.core.rules import RULES
from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)


TRIGGER_TECHNICAL_SELL = "technical_sell"
TRIGGER_DIVERGENCE = "divergence"

EVENT_TYPE_RUN = "holdings_monitor_run"
EVENT_TYPE_TECHNICAL_SELL = "holdings_monitor_technical_sell"
EVENT_TYPE_DIVERGENCE = "holdings_monitor_divergence"


@dataclass
class AlertPayload:
    """Single alert event payload — kept flat for easy SQL/JSON inspection."""

    ticker: str
    account: str
    trigger_type: str  # TRIGGER_TECHNICAL_SELL | TRIGGER_DIVERGENCE
    technical_action: str  # BUY | SELL | HOLD
    technical_confidence: float
    divergence_flag: bool
    divergence_reason: str
    current_price: float | None
    avg_price: float | None
    pnl_pct: float | None
    recommended_action: str  # always "REVIEW" — auto-trade deferred
    dedupe_key: str  # f"{ticker}:{trigger_type}"
    price_date: str | None
    technical_reasoning: str  # short excerpt (≤120 chars)
    # #517 Phase 2b — Cooldown SELL-type split. trigger_type → action_type 매핑:
    #   technical_sell → "hard_sell" (SELL conf ≥ 80, thesis 회복 21d cooldown)
    #   divergence    → "divergence_alert" (정보성, 3d cooldown)
    # buy_candidate_emitter._get_cooldown_tickers_by_type 가 SQL filter.
    action_type: str = ""  # "hard_sell" | "divergence_alert" (set in _emit_alert)


@dataclass
class RunSummary:
    """Per-run accounting — emitted as the parent `holdings_monitor_run` event."""

    run_at_kst: str
    n_holdings: int
    n_alerted: int
    n_skipped_dedup: int
    n_skipped_data_gap: int
    n_skipped_scope: int
    failed_tickers: list[str] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)


# ─── Holdings load (DB → in-memory rows) ────────────────────────────────


def _classify_asset_class(ticker: str, currency: str | None) -> str:
    """Coarse asset-class bucket — used to scope the monitor to equities only.

    Crypto excluded explicitly (futures PR per Codex Plan). Anything not US/KR
    equity is treated as out-of-scope for v1.
    """
    if currency and currency.upper() == "KRW":
        return "equity_kr"
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "equity_kr"
    if ticker in {"BTC-USD", "ETH-USD"} or ticker.endswith("-USD"):
        return "crypto"
    return "equity_us"


def _load_holdings(db_path=None) -> list[dict]:
    """Read current holdings from `portfolio` DB table. Excludes zero-quantity rows."""
    df = query_df(
        "SELECT account, ticker, quantity, avg_price, currency, sector "
        "FROM portfolio WHERE quantity IS NOT NULL AND quantity > 0",
        db_path=db_path,
    )
    if df.empty:
        return []
    rows = df.to_dict(orient="records")
    for r in rows:
        r["asset_class"] = _classify_asset_class(r["ticker"], r.get("currency"))
    return rows


def _latest_close(ticker: str, db_path=None) -> tuple[float | None, str | None]:
    df = query_df(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        params=(ticker,),
        db_path=db_path,
    )
    if df.empty:
        return None, None
    return float(df.iloc[0]["close"]), str(df.iloc[0]["date"])


# ─── Dedup (pipeline_events as state journal) ────────────────────────────


def _is_deduped(dedupe_key: str, dedup_days: int, db_path=None) -> bool:
    """True if a matching alert event was emitted within `dedup_days` calendar days.

    pipeline_events itself is the state journal — no separate dedup table.
    Match strategy: latest event for either trigger event_type whose payload
    contains the dedupe_key. SQLite JSON1 `json_extract` is broadly available
    (built-in since 3.38, present in all platforms shipped here).
    """
    rows = query(
        """
        SELECT timestamp FROM pipeline_events
        WHERE event_type IN (?, ?)
          AND json_extract(payload, '$.dedupe_key') = ?
          AND timestamp >= datetime('now', ? || ' days')
        ORDER BY timestamp DESC LIMIT 1
        """,
        (
            EVENT_TYPE_TECHNICAL_SELL,
            EVENT_TYPE_DIVERGENCE,
            dedupe_key,
            f"-{dedup_days}",
        ),
        db_path=db_path,
    )
    return bool(rows)


# ─── Trigger evaluation ─────────────────────────────────────────────────


def _evaluate_triggers(
    *,
    ticker: str,
    db_path,
    technical_sell_threshold: float,
    divergence_threshold: float,
) -> tuple[str | None, dict]:
    """Run consensus once, return (trigger_type | None, diagnostics).

    Importing analyze_ticker locally to avoid a circular import at module load
    time (consensus.py → agents/* → domain code).
    """
    from nuri.trading.agents.consensus import analyze_ticker

    result = analyze_ticker(ticker, db_path=db_path)
    tech_v = next((v for v in result.verdicts if v.agent_name == "technical"), None)

    diagnostics = {
        "technical_action": tech_v.action if tech_v else "HOLD",
        "technical_confidence": float(tech_v.confidence) if tech_v else 0.0,
        "technical_reasoning": (tech_v.reasoning[:120] if tech_v and tech_v.reasoning else ""),
        "divergence_flag": bool(result.divergence_flag),
        "divergence_reason": result.divergence_reason,
        "consensus_action": result.final_action,
    }

    # Trigger A: direct technical SELL with high conviction.
    if tech_v and tech_v.action == "SELL" and tech_v.confidence >= technical_sell_threshold:
        return TRIGGER_TECHNICAL_SELL, diagnostics

    # Trigger B: divergence flag (consensus disagrees with technical) AND
    # technical conviction strong enough to surface as "review me".
    if result.divergence_flag and tech_v and tech_v.action == "SELL" and tech_v.confidence >= divergence_threshold:
        return TRIGGER_DIVERGENCE, diagnostics

    return None, diagnostics


# ─── Main run ───────────────────────────────────────────────────────────


def run_monitor(db_path=None, dry_run: bool = False) -> RunSummary:
    """Single daily run — iterate holdings, evaluate triggers, emit alerts."""
    cfg = RULES.get("holdings_monitor", {}) if RULES else {}
    if not cfg.get("enabled", False):
        logger.info("holdings_monitor disabled via config — skipping")
        return RunSummary(
            run_at_kst=kst_now().isoformat(),
            n_holdings=0,
            n_alerted=0,
            n_skipped_dedup=0,
            n_skipped_data_gap=0,
            n_skipped_scope=0,
        )

    tech_sell_th = float(cfg.get("technical_sell_min_confidence", 80))
    div_th = float(cfg.get("divergence_min_tech_confidence", 70))
    dedup_days = int(cfg.get("dedup_calendar_days", 7))
    scope = set(cfg.get("asset_class_scope", ["equity_us", "equity_kr"]))

    holdings = _load_holdings(db_path=db_path)
    summary = RunSummary(
        run_at_kst=kst_now().isoformat(),
        n_holdings=len(holdings),
        n_alerted=0,
        n_skipped_dedup=0,
        n_skipped_data_gap=0,
        n_skipped_scope=0,
    )

    # Parent run event first — children carry causation_id pointing here.
    parent_id = None
    if not dry_run:
        parent_id = emit_event(
            event_type=EVENT_TYPE_RUN,
            step="recommend",
            payload={
                "n_holdings": len(holdings),
                "config": {
                    "technical_sell_min_confidence": tech_sell_th,
                    "divergence_min_tech_confidence": div_th,
                    "dedup_calendar_days": dedup_days,
                    "asset_class_scope": sorted(scope),
                },
            },
            db_path=db_path,
        )

    for h in holdings:
        ticker = h["ticker"]
        if h.get("asset_class") not in scope:
            summary.n_skipped_scope += 1
            continue

        try:
            trigger_type, diag = _evaluate_triggers(
                ticker=ticker,
                db_path=db_path,
                technical_sell_threshold=tech_sell_th,
                divergence_threshold=div_th,
            )
        except Exception as e:  # noqa: BLE001 — data gap / agent failure is non-fatal
            logger.warning("holdings_monitor: %s evaluation failed: %s", ticker, e)
            summary.n_skipped_data_gap += 1
            summary.failed_tickers.append(ticker)
            continue

        if trigger_type is None:
            continue

        dedupe_key = f"{ticker}:{trigger_type}"
        if _is_deduped(dedupe_key, dedup_days, db_path=db_path):
            summary.n_skipped_dedup += 1
            continue

        cur, price_date = _latest_close(ticker, db_path=db_path)
        avg = h.get("avg_price")
        pnl_pct = (cur / float(avg) - 1.0) * 100 if (cur and avg) else None

        # #517 Phase 2b — trigger_type → action_type 매핑 (cooldown SELL-type split)
        action_type = "hard_sell" if trigger_type == TRIGGER_TECHNICAL_SELL else "divergence_alert"

        payload = AlertPayload(
            ticker=ticker,
            account=h["account"],
            trigger_type=trigger_type,
            technical_action=diag["technical_action"],
            technical_confidence=diag["technical_confidence"],
            divergence_flag=diag["divergence_flag"],
            divergence_reason=diag["divergence_reason"],
            current_price=cur,
            avg_price=float(avg) if avg is not None else None,
            pnl_pct=pnl_pct,
            recommended_action="REVIEW",
            dedupe_key=dedupe_key,
            price_date=price_date,
            technical_reasoning=diag["technical_reasoning"],
            action_type=action_type,
        )

        event_type = EVENT_TYPE_TECHNICAL_SELL if trigger_type == TRIGGER_TECHNICAL_SELL else EVENT_TYPE_DIVERGENCE

        if not dry_run:
            emit_event(
                event_type=event_type,
                step="recommend",
                payload=asdict(payload),
                causation_id=parent_id,
                db_path=db_path,
            )

        summary.n_alerted += 1
        summary.alerts.append(asdict(payload))

    if not dry_run and parent_id is not None:
        # Update parent with final tally — emit a tiny follow-up event so the
        # journal stays append-only (no UPDATE on existing rows).
        emit_event(
            event_type=EVENT_TYPE_RUN,
            step="recommend",
            payload={
                "phase": "complete",
                "n_holdings": summary.n_holdings,
                "n_alerted": summary.n_alerted,
                "n_skipped_dedup": summary.n_skipped_dedup,
                "n_skipped_data_gap": summary.n_skipped_data_gap,
                "n_skipped_scope": summary.n_skipped_scope,
                "failed_tickers": summary.failed_tickers,
            },
            causation_id=parent_id,
            db_path=db_path,
        )

    logger.info(
        "holdings_monitor done: %d holdings, %d alerted, %d dedup, %d data-gap, %d scope-skip",
        summary.n_holdings,
        summary.n_alerted,
        summary.n_skipped_dedup,
        summary.n_skipped_data_gap,
        summary.n_skipped_scope,
    )
    return summary


# ─── Discord/Telegram surface (optional, non-fatal on failure) ──────────


def _format_alert_message(p: AlertPayload) -> str:
    pnl = f"{p.pnl_pct:+.1f}%" if p.pnl_pct is not None else "n/a"
    cur = f"{p.current_price:.2f}" if p.current_price is not None else "n/a"
    avg = f"{p.avg_price:.2f}" if p.avg_price is not None else "n/a"
    return (
        f"🔔 [{p.trigger_type}] {p.ticker} ({p.account}) — REVIEW\n"
        f"tech={p.technical_action} conf={p.technical_confidence:.0f} | "
        f"price={cur} (avg {avg}, {pnl}) | as_of {p.price_date}\n"
        f"reason: {p.technical_reasoning}"
    )


def send_alerts(summary: RunSummary) -> int:
    """Best-effort Discord webhook surface. Returns count actually sent."""
    sent = 0
    if not summary.alerts:
        return 0
    try:
        from nuri.alerts.discord_bot import send_webhook_text
    except Exception as e:  # noqa: BLE001
        logger.debug("Discord webhook unavailable, skipping surface: %s", e)
        return 0

    for alert_dict in summary.alerts:
        payload = AlertPayload(**alert_dict)
        msg = _format_alert_message(payload)
        try:
            if send_webhook_text(msg):
                sent += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Discord send failed for %s: %s", payload.ticker, e)
    return sent


# ─── CLI ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Holdings technical-divergence monitor")
    parser.add_argument("--dry-run", action="store_true", help="evaluate but do not emit events / alerts")
    parser.add_argument("--no-alert", action="store_true", help="emit events but skip Discord surface")
    args = parser.parse_args(argv)

    summary = run_monitor(dry_run=args.dry_run)
    print(json.dumps(asdict(summary), indent=2, ensure_ascii=False, default=str))

    if not args.dry_run and not args.no_alert and summary.alerts:
        sent = send_alerts(summary)
        logger.info("Discord surface: %d/%d sent", sent, summary.n_alerted)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
