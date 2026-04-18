#!/usr/bin/env python3
"""E3-3 Stage 2 main hard gate — paired counterfactual sim.

STRATEGY §3.6 Stage 2 — main decision gate of regime-adaptive SIEGE framework.

Setup (codex Plan consult E3-3-roundplan-r1):
- Frozen entry signal: per-ticker SMA 50/200 golden cross (single family,
  no entry-effect confounding)
- Frozen universe: `config/universe.yaml us_core.tickers` (85 tickers)
- VIX: 5Y backfill prerequisite (E3-3a #400)
- Sizing rule: 3-bucket on per_position_max only
  - Aggressive (×1.2): bull_low_vol, recovery → 15% → 18%
  - Conservative (×0.8): bear_high_vol, bull_high_vol, stagflation, euphoria → 15% → 12%
  - Neutral (×1.0): everything else → 15% (no change)

Methodology — paired counterfactual (same entries, same prices, only sizing differs):
1. Generate entries: for each ticker, find SMA 50/200 golden cross dates
2. Filter to dates with VIX coverage (regime classifiable)
3. For each entry: compute regime, baseline_size, adaptive_size, forward 30/60/90d return
4. Paired delta = (adaptive_size - baseline_size) × forward_return / 100
5. Bootstrap CI (10000 iter, percentile method) on paired delta at each horizon
6. Wrong-directional rate = P(paired_delta < 0) — adaptive 가 baseline 대비 lose 한 비율
7. MAE = max drawdown within forward window
8. CVaR = mean of bottom 5% paired_delta

Stage 2 PASS criteria (codex Plan consult, adapted for single-position model):
- Primary: 60d horizon 95% bootstrap CI lower bound > 0.00%
- Risk gate (reframed): wrong-directional rate ≤ 55% 모든 horizon — adaptive 가
  baseline 대비 손해 본 비율이 coin-flip 근접 이하 (single-position model 에서는
  codex 의 "downside rate" gate 가 trivially identical 이라 wrong-directional rate
  로 reframe; 자세한 limitation 은 §"Known limitations" 참조)
- Sanity: median paired delta ≥ 0 at 60d, CVaR_5% not materially worse

Sector cap (E3-3 Q4 second axis) not tested here — single-position isolation
cannot measure sector cap effect (requires multi-position portfolio sim).
Deferred to E3-3c follow-up if Stage 2 PASS on per_position_max alone.

사용:
    .venv/bin/python scripts/e3_3b_stage2_counterfactual.py [--save] [--bootstrap-iter 10000]
"""
from __future__ import annotations

import argparse
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import query, query_df
from nuri.core.timezone import today_kst
from nuri.quant.regime.classifier import classify_regime

LOG = logging.getLogger("e3_3b_stage2")

# Sizing rule (codex Plan consult Q4) — per_position_max only
BASELINE_POSITION_PCT = 15.0  # config/rules.yaml core strategy
REGIME_MULTIPLIERS = {
    # Aggressive
    "bull_low_vol": 1.2,
    "recovery": 1.2,
    # Conservative
    "bear_high_vol": 0.8,
    "bull_high_vol": 0.8,
    "stagflation": 0.8,
    "euphoria": 0.8,
    # Neutral (default 1.0)
    # bull_low_vol covered above
    # bear_low_vol, sideways_*, sector_rotation → fall through to 1.0
}
HORIZONS = [30, 60, 90]
UNIVERSE_KEY = "us_core"


@dataclass
class Entry:
    """Single SMA cross entry with all measurements for paired counterfactual."""
    ticker: str
    date: str
    regime: str | None
    confidence: float | None
    baseline_size_pct: float
    adaptive_size_pct: float
    forward_returns: dict[int, float | None]  # horizon → return %
    forward_mae: dict[int, float | None]      # horizon → MAE %
    paired_deltas: dict[int, float | None] = field(default_factory=dict)


def _load_universe() -> list[str]:
    import yaml
    with open("config/universe.yaml") as f:
        u = yaml.safe_load(f) or {}
    section = u.get(UNIVERSE_KEY) or {}
    tickers = section.get("tickers") or []
    if not tickers:
        raise RuntimeError(f"{UNIVERSE_KEY}.tickers empty")
    return sorted(tickers)


def _detect_golden_crosses(ticker: str) -> list[str]:
    """ticker 의 SMA 50/200 golden cross dates (sma50 가 sma200 위로 cross)."""
    df = query_df("SELECT date, close FROM prices WHERE ticker=? ORDER BY date", (ticker,))
    if len(df) < 200:
        return []
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["cross"] = (df["sma50"] > df["sma200"]) & (df["sma50"].shift(1) <= df["sma200"].shift(1))
    return df[df["cross"]]["date"].tolist()


def _has_vix_at(date: str) -> bool:
    r = query("SELECT COUNT(*) c FROM macro WHERE indicator='vix' AND date=?", (date,))
    return r[0]["c"] > 0


def _adaptive_size(regime: str | None) -> float:
    """regime → adaptive position pct (baseline × multiplier)."""
    if regime is None:
        return BASELINE_POSITION_PCT  # no regime = no adjustment
    mult = REGIME_MULTIPLIERS.get(regime, 1.0)
    return BASELINE_POSITION_PCT * mult


def _forward_return_and_mae(ticker: str, entry_date: str, n_trading_days: int
                             ) -> tuple[float | None, float | None]:
    """entry_date 이후 N trading days 의 return % + MAE % (max drawdown).

    forward_return = (close[N] - close[0]) / close[0] * 100
    MAE = min(close[1..N]) / close[0] - 1) * 100 — 가장 unfavorable excursion.
    Both None if 데이터 부족.
    """
    rows = query(
        "SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date LIMIT ?",
        (ticker, entry_date, n_trading_days + 1),
    )
    if len(rows) < n_trading_days + 1:
        return None, None
    entry_close = rows[0]["close"]
    exit_close = rows[n_trading_days]["close"]
    fwd_return = (exit_close - entry_close) / entry_close * 100

    # MAE: lowest close in [1..N] window (excluding entry)
    intra_lows = [r["close"] for r in rows[1:n_trading_days + 1]]
    if not intra_lows:
        return fwd_return, None
    mae = (min(intra_lows) - entry_close) / entry_close * 100  # negative typically
    return fwd_return, mae


def collect_entries(tickers: list[str]) -> list[Entry]:
    """Generate all entries across universe with paired counterfactual measurements."""
    entries: list[Entry] = []
    skipped_no_vix = 0
    skipped_no_regime = 0

    for ticker in tickers:
        crosses = _detect_golden_crosses(ticker)
        for entry_date in crosses:
            if not _has_vix_at(entry_date):
                skipped_no_vix += 1
                continue
            state = classify_regime(date=entry_date)
            if state is None:
                skipped_no_regime += 1
                continue

            baseline_size = BASELINE_POSITION_PCT
            adaptive_size = _adaptive_size(state.regime)

            forward_returns: dict[int, float | None] = {}
            forward_mae: dict[int, float | None] = {}
            for h in HORIZONS:
                ret, mae = _forward_return_and_mae(ticker, entry_date, h)
                forward_returns[h] = ret
                forward_mae[h] = mae

            paired_deltas: dict[int, float | None] = {}
            size_diff_pct = adaptive_size - baseline_size  # signed
            for h, ret in forward_returns.items():
                if ret is None:
                    paired_deltas[h] = None
                else:
                    # paired delta = (adaptive_pos - baseline_pos) × forward_return / 100
                    # 단위: portfolio-level return % (size_diff in pp × return in %)
                    paired_deltas[h] = size_diff_pct * ret / 100

            entries.append(Entry(
                ticker=ticker, date=entry_date,
                regime=state.regime, confidence=state.confidence,
                baseline_size_pct=baseline_size, adaptive_size_pct=adaptive_size,
                forward_returns=forward_returns, forward_mae=forward_mae,
                paired_deltas=paired_deltas,
            ))

    LOG.info(f"  collected {len(entries)} entries  "
             f"(skipped: {skipped_no_vix} no-vix, {skipped_no_regime} no-regime)")
    return entries


def bootstrap_ci(values: list[float], n_iter: int = 10000,
                 conf_level: float = 0.95, seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap CI on mean. (lower, upper)."""
    arr = np.array([v for v in values if v is not None])
    if len(arr) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, len(arr), replace=True).mean() for _ in range(n_iter)])
    alpha = (1 - conf_level) / 2
    lo, hi = np.percentile(means, [alpha * 100, (1 - alpha) * 100])
    return float(lo), float(hi)


def aggregate_metrics(entries: list[Entry], n_iter: int = 10000) -> dict[int, dict]:
    """horizon → metric dict.

    Single-position model note: baseline_return 과 adaptive_return 은 same sign
    (forward_return × positive_size) 이라 P(return < 0) 가 trivially identical.
    따라서 codex 원안 "downside rate of adaptive vs baseline" 는 정보 0.
    Reframe: `wrong_directional_pct` = P(paired_delta < 0) — adaptive 가 baseline
    대비 손해 본 entry 비율 (single-position 에서 의미 있는 risk metric).
    """
    out: dict[int, dict] = {}
    for h in HORIZONS:
        deltas = [e.paired_deltas[h] for e in entries if e.paired_deltas[h] is not None]
        adaptive_maes = [
            e.forward_mae[h] * e.adaptive_size_pct / 100
            for e in entries if e.forward_mae[h] is not None
        ]
        baseline_maes = [
            e.forward_mae[h] * e.baseline_size_pct / 100
            for e in entries if e.forward_mae[h] is not None
        ]
        if not deltas:
            out[h] = {"n": 0}
            continue

        ci_lo, ci_hi = bootstrap_ci(deltas, n_iter=n_iter)
        # Wrong-directional rate: P(paired_delta < 0) — adaptive underperformed
        wrong_pct = sum(1 for d in deltas if d < 0) / len(deltas) * 100
        # Sign-test secondary (codex demoted but informative)
        positive_pct = sum(1 for d in deltas if d > 0) / len(deltas) * 100

        # CVaR: mean of bottom 5% of paired deltas
        sorted_deltas = sorted(deltas)
        cvar_n = max(1, int(len(sorted_deltas) * 0.05))
        cvar = statistics.mean(sorted_deltas[:cvar_n])

        # MAE delta: adaptive MAE − baseline MAE (negative = adaptive worse)
        mae_baseline_mean = statistics.mean(baseline_maes) if baseline_maes else None
        mae_adaptive_mean = statistics.mean(adaptive_maes) if adaptive_maes else None
        mae_delta = ((mae_adaptive_mean - mae_baseline_mean)
                     if (mae_adaptive_mean is not None and mae_baseline_mean is not None) else None)

        out[h] = {
            "n": len(deltas),
            "mean_delta": statistics.mean(deltas),
            "median_delta": statistics.median(deltas),
            "ci_95_lo": ci_lo,
            "ci_95_hi": ci_hi,
            "wrong_directional_pct": wrong_pct,
            "positive_pct": positive_pct,
            "mae_baseline_pct": mae_baseline_mean,
            "mae_adaptive_pct": mae_adaptive_mean,
            "mae_delta_pp": mae_delta,
            "cvar_5pct": cvar,
        }
    return out


def evaluate_stage2_gate(metrics: dict[int, dict]) -> tuple[str, list[str]]:
    """Codex acceptance criteria adapted for single-position model. 반환: (verdict, reasons)."""
    reasons: list[str] = []
    primary_h = 60
    m60 = metrics.get(primary_h, {})
    if not m60 or m60.get("n", 0) == 0:
        return "REJECTED", [f"no entries at {primary_h}d horizon"]

    # Primary gate: 60d 95% bootstrap CI lower bound > 0.00%
    if m60["ci_95_lo"] <= 0:
        reasons.append(f"60d CI lower bound = {m60['ci_95_lo']:+.4f}% ≤ 0 (primary gate FAIL)")

    # Risk gate (reframed): wrong_directional_pct ≤ 55% 모든 horizon
    for h in HORIZONS:
        m = metrics.get(h, {})
        if m.get("n", 0) == 0:
            continue
        if m["wrong_directional_pct"] > 55:
            reasons.append(f"{h}d wrong-directional rate {m['wrong_directional_pct']:.1f}% > 55% "
                           "(risk gate FAIL — adaptive 가 baseline 대비 자주 손해)")

    # Sanity: median ≥ 0 at 60d
    if m60["median_delta"] < 0:
        reasons.append(f"60d median delta = {m60['median_delta']:+.4f}% < 0 (sanity FAIL)")

    verdict = "PASS" if not reasons else "REJECTED"
    return verdict, reasons


def render_markdown(entries: list[Entry], metrics: dict[int, dict],
                    verdict: str, reasons: list[str]) -> str:
    n = len(entries)
    by_regime: dict[str, int] = {}
    for e in entries:
        by_regime[e.regime or "None"] = by_regime.get(e.regime or "None", 0) + 1

    out: list[str] = []
    out.append("# E3-3 Stage 2 — Paired Counterfactual (main hard gate)")
    out.append("")
    out.append(f"Run date: {today_kst()}")
    out.append(f"Verdict: **{verdict}**")
    if reasons:
        out.append("")
        out.append("**Failure reasons**:")
        for r in reasons:
            out.append(f"- {r}")
    out.append("")
    out.append("## Setup (codex Plan consult E3-3-roundplan-r1)")
    out.append("")
    out.append(f"- Universe: `{UNIVERSE_KEY}` ({len(_load_universe())} tickers)")
    out.append("- Entry signal: per-ticker SMA 50/200 golden cross")
    out.append("- VIX prerequisite: 5Y backfill (#400)")
    out.append(f"- Baseline `per_position_max`: {BASELINE_POSITION_PCT}%")
    out.append("- Adaptive multipliers: aggressive(1.2×) {bull_low_vol, recovery}, "
               "conservative(0.8×) {bear_high_vol, bull_high_vol, stagflation, euphoria}, "
               "neutral(1.0×) others")
    out.append(f"- N entries (regime-classifiable): **{n}**")
    out.append("")
    out.append("## Entry distribution by regime")
    out.append("")
    out.append("| regime | n | adaptive_size | category |")
    out.append("|---|---|---|---|")
    for regime, count in sorted(by_regime.items(), key=lambda x: -x[1]):
        size = _adaptive_size(regime if regime != "None" else None)
        cat = ("aggressive" if size > BASELINE_POSITION_PCT
               else "conservative" if size < BASELINE_POSITION_PCT
               else "neutral")
        out.append(f"| {regime} | {count} | {size:.1f}% | {cat} |")
    out.append("")
    out.append("## Paired counterfactual results")
    out.append("")
    out.append("| horizon | n | mean_Δ_% | median_Δ_% | 95%CI_lo | 95%CI_hi "
               "| wrong_dir_% | positive_% | MAE_base | MAE_adapt | MAE_Δpp | CVaR_5%_Δ |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        m = metrics.get(h, {})
        if m.get("n", 0) == 0:
            out.append(f"| {h}d | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        mae_b = f"{m['mae_baseline_pct']:+.3f}" if m['mae_baseline_pct'] is not None else "—"
        mae_a = f"{m['mae_adaptive_pct']:+.3f}" if m['mae_adaptive_pct'] is not None else "—"
        mae_d = f"{m['mae_delta_pp']:+.4f}" if m['mae_delta_pp'] is not None else "—"
        out.append(f"| {h}d | {m['n']} | {m['mean_delta']:+.4f} | {m['median_delta']:+.4f} | "
                   f"{m['ci_95_lo']:+.4f} | {m['ci_95_hi']:+.4f} | "
                   f"{m['wrong_directional_pct']:.1f} | {m['positive_pct']:.1f} | "
                   f"{mae_b} | {mae_a} | {mae_d} | {m['cvar_5pct']:+.4f} |")
    out.append("")
    out.append("## Stage 2 acceptance gates (codex, adapted for single-position)")
    out.append("")
    out.append("| gate | criterion | result |")
    out.append("|---|---|---|")
    m60 = metrics.get(60, {})
    out.append(f"| Primary | 60d CI lower bound > 0.00% | "
               f"{'✅' if m60.get('ci_95_lo', 0) > 0 else '❌'} {m60.get('ci_95_lo', 0):+.4f}% |")
    for h in HORIZONS:
        m = metrics.get(h, {})
        if m.get("n", 0) == 0:
            continue
        ok = m["wrong_directional_pct"] <= 55
        out.append(f"| Risk {h}d | wrong-directional ≤ 55% | "
                   f"{'✅' if ok else '❌'} {m['wrong_directional_pct']:.1f}% |")
    if m60.get("n", 0) > 0:
        ok = m60["median_delta"] >= 0
        out.append(f"| Sanity | 60d median ≥ 0 | "
                   f"{'✅' if ok else '❌'} {m60['median_delta']:+.4f}% |")
    out.append("")
    out.append("## Known limitations")
    out.append("")
    out.append("- **Survivorship bias** (codex Plan consult biggest risk): us_core is "
               "today's curated list — delisted tickers absent. Affects magnitude not "
               "direction. PASS = 'within current curated-survivor universe', not "
               "market-wide proof.")
    out.append("- **Single-position model + `wrong_directional_pct` semantics** (codex Round 1): "
               "원안 \"downside rate of adaptive vs baseline\" 는 single-position 에서 trivially "
               "identical (둘 다 forward_return × positive_size, same sign). Reframe `wrong_directional_pct` "
               "= P(paired_delta < 0) — answers \"did adaptive sizing **help** vs baseline?\", **NOT** "
               "\"did loss frequency worsen?\". Weaker risk measure than codex 원안 — must be read "
               "alongside MAE / CVaR (둘 다 reported above), not standalone. Caveat: neutral entries "
               "(paired_delta == 0) mechanically improve this metric, so 55% threshold is loose. "
               "Multi-position portfolio sim with true downside-rate gate 은 E3-3c 후속 (sector cap 도 함께).")
    out.append("- **Sector cap untested**: Q4 second axis (max_sector_exposure) NOT tested — "
               "single-position isolation 으로는 portfolio-level cap effect 측정 불가.")
    out.append("- **Single signal family**: SMA 50/200 cross only — momentum/RSI 등 "
               "다른 entry signal 일반화 여부 untested.")
    out.append("- **No exit logic**: fixed forward 30/60/90d horizon — stop-loss / "
               "take-profit 와 sizing rule interaction 미측정.")
    out.append("- **Modest magnitude**: paired delta 는 portfolio-level 단위로 통계적 "
               "significant 이지만 magnitude 작음 (60d ~+0.08% portfolio return). "
               "annualize 시 ~+0.5%/year 수준 — 룰 자체 적용은 합리적이나 마법은 아님.")
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true",
                        help="data/reports/{today}/e3_stage2_paired_counterfactual.md 에 저장")
    parser.add_argument("--bootstrap-iter", type=int, default=10000,
                        help="bootstrap iterations (default 10000)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    LOG.info("E3-3 Stage 2 paired counterfactual — start")
    tickers = _load_universe()
    LOG.info(f"  universe: {len(tickers)} tickers")

    entries = collect_entries(tickers)
    if not entries:
        LOG.error("No entries collected — abort")
        return

    metrics = aggregate_metrics(entries, n_iter=args.bootstrap_iter)
    verdict, reasons = evaluate_stage2_gate(metrics)
    md = render_markdown(entries, metrics, verdict, reasons)
    print(md)

    if args.save:
        out_dir = Path("data/reports") / today_kst()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "e3_stage2_paired_counterfactual.md"
        out_path.write_text(md)
        LOG.info(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
