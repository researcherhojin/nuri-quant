"""Thesis Q&A engine — on-demand ticker analysis (Issue #508).

Sister module to `nuri/trading/recommend/buy_candidate_emitter.py` (proactive
top-N cash deploy emit, #507). #508 is reactive: user asks a question on a
specific ticker, system fuses DB context + LLM synthesis + portfolio
implications into a structured thesis.

Why this exists (2026-04-30 user escalation):
사용자가 "INTC가 hyperscaler 수혜자인가?" 같은 질문을 던져도 시스템이 답을
못 함 — `consensus.py` 는 BUY/SELL/HOLD verdict 만, narrative thesis 없음.
이 모듈이 그 gap 을 메움.

Phase 1 (이 PR):
  - DB context (factors / signals / prices / fundamentals / portfolio overlap)
  - LLM synthesis via `scripts/llm_consult.py` (codex + Qwen3.5)
  - structured markdown output → `data/thesis_query/{date}_{ticker}_{slug}.md`
  - CLI: `make thesis ticker=INTC question="..."`

Phase 2 (deferred):
  - WebSearch / WebFetch integration (analyst sites, dataroma, TipRanks)
  - Watchlist 등록 ticker 매일 thesis refresh in `premarket_brief`
  - cache + diff (yesterday's thesis vs today's)

Hard constraint: STRATEGY §7.1 — recommendation only, never execute.
Output 은 사용자 manual judgment 보조 자료.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

from nuri.core.db import query_df
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

OUT_DIR = Path("data/thesis_query")
LLM_CONSULT_SCRIPT = Path("scripts/dev/llm_consult.py")

DEFAULT_QUESTION = "investment thesis (long/short/avoid) + portfolio implications"


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert free-text question to filename-safe kebab slug."""
    s = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", text.lower()).strip("-")
    return s[:max_len] or "thesis"


def _fetch_db_context(ticker: str) -> dict[str, str]:
    """Collect DB snapshot for ticker. Returns markdown sections per data domain."""
    sections: dict[str, str] = {}

    # 1. Latest price + 30d momentum
    try:
        df = query_df(
            """SELECT date, close, volume FROM prices
               WHERE ticker = ? AND date >= date('now', '-45 days')
               ORDER BY date""",
            (ticker,),
        )
        if not df.empty and len(df) >= 6:
            closes = df["close"].tolist()
            last = closes[-1]
            ret_5d = (last / closes[-6] - 1.0) * 100.0
            recent = closes[-30:] if len(closes) >= 30 else closes
            high_30d = max(recent)
            low_30d = min(recent)
            sections["price"] = (
                f"close ${last:.2f} | 5d {ret_5d:+.2f}% | "
                f"30d range ${low_30d:.2f} ~ ${high_30d:.2f} | "
                f"current vs 30d high {(last / high_30d - 1) * 100:+.2f}%"
            )
        else:
            sections["price"] = "(no price data — < 6 rows in 45d window)"
    except Exception as e:
        sections["price"] = f"(error: {e})"

    # 2. Latest factor scores
    try:
        df = query_df(
            """SELECT date, momentum_score, value_score, quality_score,
                      sentiment_score, composite_score
               FROM factors WHERE ticker = ?
               ORDER BY date DESC LIMIT 1""",
            (ticker,),
        )
        if not df.empty:
            r = df.iloc[0]
            sections["factor"] = (
                f"composite {r['composite_score']:.3f} | "
                f"momentum {r['momentum_score']:.3f} | value {r['value_score']:.3f} | "
                f"quality {r['quality_score']:.3f} | sentiment {r['sentiment_score']:.3f} "
                f"(date {r['date']})"
            )
        else:
            sections["factor"] = "(no factor data)"
    except Exception as e:
        sections["factor"] = f"(error: {e})"

    # 3. Technical signals (RSI, MACD, SMA)
    try:
        df = query_df(
            """SELECT date, rsi_14, macd, macd_signal, sma_20, sma_50, sma_200
               FROM signals WHERE ticker = ?
               ORDER BY date DESC LIMIT 1""",
            (ticker,),
        )
        if not df.empty:
            r = df.iloc[0]
            sections["technical"] = (
                f"RSI(14) {r['rsi_14']:.1f} | MACD {r['macd']:.2f} (signal {r['macd_signal']:.2f}) | "
                f"SMA20 ${r['sma_20']:.2f} | SMA50 ${r['sma_50']:.2f} | SMA200 ${r['sma_200']:.2f}"
            )
        else:
            sections["technical"] = "(no signal data)"
    except Exception as e:
        sections["technical"] = f"(error: {e})"

    # 4. Fundamentals
    try:
        df = query_df(
            """SELECT pe_ratio, forward_pe, profit_margin, revenue_growth,
                      market_cap, debt_to_equity
               FROM fundamentals WHERE ticker = ?
               ORDER BY date DESC LIMIT 1""",
            (ticker,),
        )
        if not df.empty:
            r = df.iloc[0]

            def _fmt(v: float | None, fmt: str = ".1f", suffix: str = "") -> str:
                if v is None:
                    return "—"
                return format(v, fmt) + suffix

            mcap = r["market_cap"]
            if mcap is None:
                mcap_str = "—"
            elif mcap < 1e12:
                mcap_str = f"${mcap / 1e9:.1f}B"
            else:
                mcap_str = f"${mcap / 1e12:.2f}T"
            sections["fundamentals"] = (
                f"PE {_fmt(r['pe_ratio'])} | FwdPE {_fmt(r['forward_pe'])} | "
                f"profit margin {_fmt(r['profit_margin'] * 100 if r['profit_margin'] is not None else None)}% | "
                f"revenue growth {_fmt(r['revenue_growth'] * 100 if r['revenue_growth'] is not None else None)}% | "
                f"market cap {mcap_str} | D/E {_fmt(r['debt_to_equity'], '.2f')}"
            )
        else:
            sections["fundamentals"] = "(no fundamentals data)"
    except Exception as e:
        sections["fundamentals"] = f"(error: {e})"

    # 5. Portfolio overlap (held/cap/sector)
    try:
        df = query_df(
            """SELECT account, quantity, avg_price, sector FROM portfolio
               WHERE ticker = ?""",
            (ticker,),
        )
        if not df.empty:
            lines = [
                f"  - {r['account']}: {r['quantity']} @ ${r['avg_price']:.2f} ({r['sector']})" for _, r in df.iterrows()
            ]
            sections["portfolio"] = "**HELD** by user across:\n" + "\n".join(lines)
        else:
            sections["portfolio"] = "**NOT HELD** — fresh entry candidate"
    except Exception as e:
        sections["portfolio"] = f"(error: {e})"

    # 6. Recent recommendations
    try:
        df = query_df(
            """SELECT date, action, confidence, regime FROM recommendations
               WHERE ticker = ? ORDER BY date DESC LIMIT 3""",
            (ticker,),
        )
        if not df.empty:
            lines = [
                f"  - {r['date']}: {r['action']} (conf {r['confidence']}, regime {r['regime']})"
                for _, r in df.iterrows()
            ]
            sections["recent_calls"] = "Last 3 system recommendations:\n" + "\n".join(lines)
        else:
            sections["recent_calls"] = "(no recent system recommendations)"
    except Exception as e:
        sections["recent_calls"] = f"(error: {e})"

    # 7. Price levels — canonical, config-driven. LLM 이 직접 유도하면 안 된다
    #    (invariants.md "No ad-hoc buy/sell calls" + recommend/CLAUDE.md
    #    "price_targets.py is the canonical source — do not re-derive in callers").
    #    deferred import: nuri/llm 은 stage 가 아니라 cross-stage 규칙 대상은 아니나,
    #    price_targets 는 config/DB 를 끌어오므로 import 비용을 호출 시점으로 미룬다.
    try:
        from nuri.trading.recommend.price_targets import calculate_targets

        t = calculate_targets(ticker)
        if t.get("error"):
            sections["price_levels"] = f"(unavailable — {t['error']})"
        elif t.get("is_leader"):
            # 리더(성장주)는 고정 익절 폐기 → target_1/2 = None, 50일선 트레일이 유일한 exit
            sections["price_levels"] = "\n".join(
                [
                    f"  - stock_type: {t['stock_type']} (**leader** — 고정 익절 없음)",
                    f"  - entry: ${t['entry_price']:.2f} (current ${t['current_price']:.2f})",
                    f"  - stop_loss: ${t['stop_loss']:.2f} ({t['stop_loss_pct']}%)",
                    f"  - exit: {t['leader_ma_period']}일선 트레일 ${t['leader_ma']:.2f} 이탈",
                    f"  - trailing_stop: {t['trailing_stop_pct']}%",
                ]
            )
        else:
            sections["price_levels"] = "\n".join(
                [
                    f"  - stock_type: {t['stock_type']}",
                    f"  - entry: ${t['entry_price']:.2f} (current ${t['current_price']:.2f})",
                    f"  - stop_loss: ${t['stop_loss']:.2f} ({t['stop_loss_pct']}%)",
                    f"  - target_1: ${t['target_1']:.2f} (+{t['target_1_pct']}%, sell {t['target_1_sell_pct']}%)",
                    f"  - target_2: ${t['target_2']:.2f} (+{t['target_2_pct']}%, sell {t['target_2_sell_pct']}%)",
                    f"  - trailing_stop: {t['trailing_stop_pct']}%",
                ]
            )
    except Exception as e:
        sections["price_levels"] = f"(error: {e})"

    return sections


def _build_prompt(ticker: str, question: str, ctx: dict[str, str]) -> str:
    """Compose structured prompt for codex+Qwen consult."""
    parts = [
        f"# Thesis Q&A — {ticker}",
        "",
        f"**Question**: {question}",
        "",
        "## DB context (Nuri-Quant snapshot, latest available)",
        "",
        f"- **Price**: {ctx.get('price', '—')}",
        f"- **Factor scores (0-1)**: {ctx.get('factor', '—')}",
        f"- **Technicals**: {ctx.get('technical', '—')}",
        f"- **Fundamentals**: {ctx.get('fundamentals', '—')}",
        f"- **Portfolio**: {ctx.get('portfolio', '—')}",
        "",
        "## Recent system signals",
        "",
        ctx.get("recent_calls", "(no calls)"),
        "",
        "## Price levels (system-computed — DO NOT derive your own)",
        "",
        ctx.get("price_levels", "(unavailable)"),
        "",
        "## Constraints",
        "",
        "- STRATEGY §7.1: recommendation only, no auto-trade.",
        "- Price levels above are computed by `price_targets.calculate_targets` from "
        "`config/rules.yaml`. They are the only valid levels. Do NOT compute, round, "
        "adjust, or invent entry / stop / TP values of your own.",
        "- 3:1 reward-to-risk, growth ladder: stop -7% / TP1 +20% / TP2 +40%.",
        "- VIX gate: > 30 block buys, 25-30 half size.",
        "- Position cap: max 15% per ticker (core), 25% (active).",
        "- Korean retail investor — risk-averse after 4월 손실 cascade.",
        "",
        "## Required output",
        "",
        "1. **Verdict** (one of: STRONG BUY / BUY / HOLD / AVOID / SELL — single line)",
        "2. **Thesis** (3-5 sentences — what is the company's actual position in the value chain?)",
        "3. **Beneficiary analysis** (if relevant — who benefits from what trend? rank 5+)",
        "4. **Risk** (top 2 specific risks with quantified probability if possible)",
        "5. **Price levels** (if BUY/STRONG BUY — restate the system-computed levels "
        "from the 'Price levels' section verbatim. If that section says unavailable, "
        "say so and omit — never substitute your own numbers)",
        "6. **Portfolio implications** (given user's actual holdings + cash situation)",
        "7. **Confidence** (0-100, honest calibration)",
        "",
        "Be ruthlessly honest. Cite specific numbers from the DB context above. "
        "If user thesis is wrong, say so directly with data. No corporate-speak.",
    ]
    return "\n".join(parts)


def thesis_query(
    ticker: str,
    question: str = DEFAULT_QUESTION,
    out_dir: Path | None = None,
    codex_only: bool = False,
    qwen_only: bool = False,
) -> Path:
    """Main entry: gather context → consult LLMs → save markdown.

    Returns path to saved markdown.
    """
    ticker = ticker.upper()
    out = out_dir or OUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    ctx = _fetch_db_context(ticker)
    prompt = _build_prompt(ticker, question, ctx)

    slug = _slugify(question)
    out_path = out / f"{today_kst()}_{ticker.lower()}_{slug}.md"

    # Pipe to scripts/llm_consult.py via stdin (it accepts --slug + stdin)
    cmd = [
        sys.executable,
        str(LLM_CONSULT_SCRIPT),
        "--slug",
        f"thesis-{ticker.lower()}-{slug}",
        "--out-dir",
        str(out),
    ]
    if codex_only:
        cmd.append("--codex-only")
    if qwen_only:
        cmd.append("--qwen-only")

    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, check=False)
    if proc.returncode != 0:
        logger.error("llm_consult failed: %s", proc.stderr[-500:])
    else:
        logger.info(proc.stdout.strip())

    # llm_consult writes its own filename — find it and rename to our convention
    consult_files = sorted(out.glob(f"{today_kst()}_thesis-{ticker.lower()}-{slug}*.md"))
    if consult_files:
        latest = consult_files[-1]
        if latest != out_path:
            latest.rename(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True, help="ticker (e.g. INTC)")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="thesis question (free text)")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--codex-only", action="store_true")
    parser.add_argument("--qwen-only", action="store_true")
    parser.add_argument("--print", action="store_true", help="print markdown after generation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    out_path = thesis_query(
        ticker=args.ticker,
        question=args.question,
        out_dir=args.out_dir,
        codex_only=args.codex_only,
        qwen_only=args.qwen_only,
    )
    print(f"saved: {out_path}")

    if args.print and out_path.exists():
        print()
        print(out_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
