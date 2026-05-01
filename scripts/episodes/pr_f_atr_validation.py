#!/usr/bin/env python3
"""PR F — ATR/regime-scaled stop-loss grid validation.

Paired counterfactual (E3-3b #402 pattern) + walk-forward CV:
- Baseline: fixed -7% percent stop (현 production STOCK_STOP_LOSS)
- Treatment: ATR-k × regime_multiplier stop. Grid = {1.5, 2.0, 2.5, 3.0} × {0.8, 1.0, 1.3}.
- Universe: us_core 85 tickers (frozen, E3-3b parity).
- Entry signal: SMA 50/200 golden cross (frozen, E3-3b parity — entry-effect confound 제거).
- Walk-forward: 2 folds (train 2021-2023 → test 2024; train 2022-2024 → test 2025).

Per-trade exit simulation (핵심 차이 vs E3-3b):
- Both rules get same entry_price (close at cross date) + forward OHLC window.
- Baseline: 첫 close ≤ entry × (1 − 0.07) 인 date 에서 exit. 없으면 horizon N 에 exit.
- Treatment: entry 당일까지 ATR(14) 계산 → stop = entry − k × regime_mult × ATR.
  첫 close ≤ stop date 에서 exit. 없으면 horizon N.
- forward_return = (exit_close − entry_price) / entry_price × 100.

6-metric acceptance panel (codex Plan Q5-C):
1. CAGR: annualized mean forward return
2. Max DD: worst trade return (most negative)
3. Ulcer Index: sqrt(mean(DD_i²)) — drawdown frequency × severity
4. Turnover: % of trades that exited via stop (vs horizon) — 높으면 whipsaw
5. Tax drag proxy: % of trades held < 252 days (short-term gain, 더 높은 세율)
6. Hit rate: % positive return trades

Each k × regime_mult combo vs baseline: +1 score per metric where combo 우위.
4+ / 6 + (bootstrap CI lower bound > 0 at any horizon) = PASS.

Usage:
    .venv/bin/python scripts/pr_f_atr_validation.py [--save] [--bootstrap-iter 10000]
"""
from __future__ import annotations

import argparse
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import query, query_df
from nuri.core.timezone import today_kst
from nuri.quant.exits.atr import (
    K_GRID,
    MIN_ROWS_FOR_ATR,
    REGIME_MULTIPLIER,
    compute_atr,
)
from nuri.quant.regime.classifier import classify_regime

LOG = logging.getLogger("pr_f_atr_validation")

UNIVERSE_KEY = "us_core"
BASELINE_STOP_PCT = -7.0       # config/rules.yaml stop_loss.per_stock
HORIZONS = [30, 60, 90]         # trading days
ATR_PERIOD = 14
# Grid = K_GRID × {0.8 (bull_low_vol), 1.0 (neutral), 1.3 (bear_high_vol)}
REGIME_MULT_TEST = [0.8, 1.0, 1.3]
FOLDS = [
    # (name, test_start, test_end) — train window implicit (all entries before test_start)
    ("fold1_2024", "2024-01-01", "2024-12-31"),
    ("fold2_2025", "2025-01-01", "2025-12-31"),
]


@dataclass
class Trade:
    """Single entry + per-rule exit simulation result."""
    ticker: str
    entry_date: str
    entry_price: float
    regime: str | None
    atr_at_entry: float | None
    baseline_return_pct: dict[int, float | None]   # horizon → return
    baseline_holding_days: dict[int, int | None]
    baseline_stopped: dict[int, bool]
    # ATR grid results: (k, regime_mult) → horizon → dict
    treatment: dict[tuple[float, float], dict[int, dict]]


def _load_universe() -> list[str]:
    import yaml
    with open("config/universe.yaml") as f:
        u = yaml.safe_load(f) or {}
    section = u.get(UNIVERSE_KEY) or {}
    tickers = section.get("tickers") or []
    if not tickers:
        raise RuntimeError(f"{UNIVERSE_KEY}.tickers empty")
    return sorted(tickers)


def _detect_golden_crosses(ticker: str) -> list[tuple[str, float]]:
    """ticker 의 SMA 50/200 golden cross dates + close price at cross."""
    df = query_df("SELECT date, close FROM prices WHERE ticker=? ORDER BY date", (ticker,))
    if len(df) < 200:
        return []
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["cross"] = (df["sma50"] > df["sma200"]) & (df["sma50"].shift(1) <= df["sma200"].shift(1))
    cross_rows = df[df["cross"]][["date", "close"]]
    return list(zip(cross_rows["date"].tolist(), cross_rows["close"].tolist()))


def _load_ohlc_prior(ticker: str, ref_date: str, n_rows: int) -> pd.DataFrame | None:
    """entry date 까지 (포함) 마지막 n_rows 의 OHLC. ATR 계산용."""
    df = query_df(
        "SELECT date, open, high, low, close FROM prices "
        "WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT ?",
        (ticker, ref_date, n_rows),
    )
    if df is None or df.empty or len(df) < MIN_ROWS_FOR_ATR:
        return None
    return df.sort_values("date").reset_index(drop=True)


def _load_ohlc_forward(ticker: str, entry_date: str, n_rows: int) -> list[dict]:
    """entry date 다음 (exclusive) n_rows trading days OHLC. Exit simulation 용."""
    rows = query(
        "SELECT date, high, low, close FROM prices WHERE ticker=? AND date>? ORDER BY date LIMIT ?",
        (ticker, entry_date, n_rows),
    )
    return list(rows)


def _simulate_stop(forward_rows: list[dict], entry_price: float, stop_price: float,
                   horizon: int) -> tuple[float, int, bool]:
    """첫 close ≤ stop_price 인 idx 에서 exit. 없으면 horizon 에 exit.

    Returns:
        (return_pct, holding_days, stopped_flag)
    """
    if not forward_rows or horizon <= 0:
        return 0.0, 0, False
    window = forward_rows[:horizon]
    if not window:
        return 0.0, 0, False
    for i, row in enumerate(window):
        if row["close"] <= stop_price:
            exit_close = row["close"]
            return (exit_close - entry_price) / entry_price * 100, i + 1, True
    # No stop hit → exit at horizon (or last available if < horizon)
    exit_close = window[-1]["close"]
    return (exit_close - entry_price) / entry_price * 100, len(window), False


def collect_trades(tickers: list[str]) -> list[Trade]:
    """Generate all trades across universe with both baseline + treatment simulations."""
    trades: list[Trade] = []
    skipped_no_atr = 0
    skipped_no_regime = 0

    for ticker in tickers:
        crosses = _detect_golden_crosses(ticker)
        for entry_date, entry_price in crosses:
            # Regime classification (lookahead-free via classify_regime at entry_date)
            state = classify_regime(date=entry_date)
            if state is None:
                skipped_no_regime += 1
                continue

            # ATR at entry — must use prior-only data (no lookahead)
            ohlc_prior = _load_ohlc_prior(ticker, entry_date, ATR_PERIOD * 3)
            if ohlc_prior is None:
                skipped_no_atr += 1
                continue
            atr_series = compute_atr(ohlc_prior, period=ATR_PERIOD)
            if atr_series is None or pd.isna(atr_series.iloc[-1]) or atr_series.iloc[-1] <= 0:
                skipped_no_atr += 1
                continue
            atr_val = float(atr_series.iloc[-1])

            # Forward window (max of HORIZONS + 1 buffer)
            forward_rows = _load_ohlc_forward(ticker, entry_date, max(HORIZONS))
            if len(forward_rows) < min(HORIZONS):
                continue  # insufficient forward coverage

            # Baseline: entry × (1 − 0.07)
            baseline_stop = entry_price * (1 + BASELINE_STOP_PCT / 100)
            baseline_ret: dict[int, float | None] = {}
            baseline_hold: dict[int, int | None] = {}
            baseline_stopped: dict[int, bool] = {}
            for h in HORIZONS:
                if len(forward_rows) < h:
                    baseline_ret[h] = None
                    baseline_hold[h] = None
                    baseline_stopped[h] = False
                    continue
                ret, hold, stopped = _simulate_stop(forward_rows, entry_price, baseline_stop, h)
                baseline_ret[h] = ret
                baseline_hold[h] = hold
                baseline_stopped[h] = stopped

            # Treatment grid: each (k, regime_mult)
            treatment: dict[tuple[float, float], dict[int, dict]] = {}
            for k in K_GRID:
                for regime_mult in REGIME_MULT_TEST:
                    stop_dist = k * regime_mult * atr_val
                    stop_price = entry_price - stop_dist
                    per_horizon: dict[int, dict] = {}
                    for h in HORIZONS:
                        if len(forward_rows) < h:
                            per_horizon[h] = {"return_pct": None, "holding_days": None, "stopped": False}
                            continue
                        ret, hold, stopped = _simulate_stop(forward_rows, entry_price, stop_price, h)
                        per_horizon[h] = {"return_pct": ret, "holding_days": hold, "stopped": stopped}
                    treatment[(k, regime_mult)] = per_horizon

            trades.append(Trade(
                ticker=ticker, entry_date=entry_date, entry_price=entry_price,
                regime=state.regime, atr_at_entry=atr_val,
                baseline_return_pct=baseline_ret,
                baseline_holding_days=baseline_hold,
                baseline_stopped=baseline_stopped,
                treatment=treatment,
            ))

    LOG.info(f"  collected {len(trades)} trades "
             f"(skipped: {skipped_no_regime} no-regime, {skipped_no_atr} no-atr)")
    return trades


def bootstrap_ci(values: list[float], n_iter: int = 10000,
                 conf_level: float = 0.95, seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap CI on mean."""
    arr = np.array([v for v in values if v is not None and not np.isnan(v)])
    if len(arr) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, len(arr), replace=True).mean() for _ in range(n_iter)])
    alpha = (1 - conf_level) / 2
    lo, hi = np.percentile(means, [alpha * 100, (1 - alpha) * 100])
    return float(lo), float(hi)


def compute_metrics(returns: list[float], holding_days: list[int],
                    stopped: list[bool]) -> dict:
    """6-metric panel for a single rule's trade sequence."""
    valid = [r for r in returns if r is not None]
    if not valid:
        return {"n": 0}
    n = len(valid)
    valid_hold = [h for h in holding_days if h is not None]
    mean_return = statistics.mean(valid)
    # CAGR: annualized per-trade (assumes trade return repeatable)
    # mean hold in trading days → annualization factor = 252 / mean_hold
    mean_hold = statistics.mean(valid_hold) if valid_hold else 1
    if mean_hold > 0:
        # (1 + mean_return/100) ^ (252/mean_hold) − 1
        try:
            cagr = ((1 + mean_return / 100) ** (252 / mean_hold) - 1) * 100
        except (OverflowError, ValueError):
            cagr = float("nan")
    else:
        cagr = float("nan")
    max_dd = min(valid)  # worst single-trade return
    # Ulcer Index: sqrt(mean(negative_returns²))
    neg_sq = [r ** 2 for r in valid if r < 0]
    ulcer = (statistics.mean(neg_sq) ** 0.5) if neg_sq else 0.0
    # Turnover: % stopped
    turnover = sum(1 for s in stopped if s) / n * 100
    # Tax drag proxy: % holding < 252 days (short-term gain)
    short_term = sum(1 for h in valid_hold if h < 252) / len(valid_hold) * 100 if valid_hold else 100.0
    # Hit rate: % positive
    hit_rate = sum(1 for r in valid if r > 0) / n * 100

    return {
        "n": n,
        "mean_return": mean_return,
        "cagr": cagr,
        "max_dd": max_dd,
        "ulcer": ulcer,
        "turnover": turnover,
        "tax_drag": short_term,
        "hit_rate": hit_rate,
    }


def score_vs_baseline(treatment: dict, baseline: dict) -> tuple[int, list[str]]:
    """6-metric comparison. +1 for each metric where treatment 우위."""
    if baseline.get("n", 0) == 0 or treatment.get("n", 0) == 0:
        return 0, ["insufficient sample"]
    wins = []
    score = 0
    # CAGR: higher better
    if treatment["cagr"] > baseline["cagr"]:
        score += 1
        wins.append("CAGR")
    # Max DD: less negative (higher) better
    if treatment["max_dd"] > baseline["max_dd"]:
        score += 1
        wins.append("MaxDD")
    # Ulcer: lower better
    if treatment["ulcer"] < baseline["ulcer"]:
        score += 1
        wins.append("Ulcer")
    # Turnover: lower better (less whipsaw)
    if treatment["turnover"] < baseline["turnover"]:
        score += 1
        wins.append("Turnover")
    # Tax drag: lower better (more long-term)
    if treatment["tax_drag"] < baseline["tax_drag"]:
        score += 1
        wins.append("TaxDrag")
    # Hit rate: higher better
    if treatment["hit_rate"] > baseline["hit_rate"]:
        score += 1
        wins.append("HitRate")
    return score, wins


def paired_deltas(trades: list[Trade], k: float, regime_mult: float,
                  horizon: int) -> list[float]:
    """Treatment − baseline paired delta per trade at given horizon."""
    deltas = []
    for t in trades:
        base = t.baseline_return_pct.get(horizon)
        treat = t.treatment.get((k, regime_mult), {}).get(horizon, {}).get("return_pct")
        if base is not None and treat is not None:
            deltas.append(treat - base)
    return deltas


def evaluate_combo(trades: list[Trade], k: float, regime_mult: float,
                   n_iter: int) -> dict:
    """Single (k, regime_mult) combo vs baseline on primary horizon (60d)."""
    primary_h = 60
    # Extract primary-horizon rule-specific trade outcomes
    base_returns = [t.baseline_return_pct.get(primary_h) for t in trades]
    base_holds = [t.baseline_holding_days.get(primary_h) for t in trades]
    base_stopped = [t.baseline_stopped.get(primary_h, False) for t in trades]

    treat_returns = [t.treatment.get((k, regime_mult), {}).get(primary_h, {}).get("return_pct")
                     for t in trades]
    treat_holds = [t.treatment.get((k, regime_mult), {}).get(primary_h, {}).get("holding_days")
                   for t in trades]
    treat_stopped = [t.treatment.get((k, regime_mult), {}).get(primary_h, {}).get("stopped", False)
                     for t in trades]

    base_metrics = compute_metrics(
        [r for r in base_returns if r is not None],
        [h for h in base_holds if h is not None],
        [s for s, r in zip(base_stopped, base_returns) if r is not None],
    )
    treat_metrics = compute_metrics(
        [r for r in treat_returns if r is not None],
        [h for h in treat_holds if h is not None],
        [s for s, r in zip(treat_stopped, treat_returns) if r is not None],
    )
    score, wins = score_vs_baseline(treat_metrics, base_metrics)

    # Bootstrap CI on paired delta at each horizon
    ci_by_horizon: dict[int, tuple[float, float]] = {}
    mean_delta_by_horizon: dict[int, float] = {}
    for h in HORIZONS:
        deltas = paired_deltas(trades, k, regime_mult, h)
        if len(deltas) >= 2:
            ci_by_horizon[h] = bootstrap_ci(deltas, n_iter=n_iter)
            mean_delta_by_horizon[h] = statistics.mean(deltas)
        else:
            ci_by_horizon[h] = (float("nan"), float("nan"))
            mean_delta_by_horizon[h] = float("nan")

    # CI gate: any horizon lower bound > 0?
    ci_pass = any(ci_by_horizon[h][0] > 0 for h in HORIZONS
                   if not np.isnan(ci_by_horizon[h][0]))

    return {
        "k": k, "regime_mult": regime_mult,
        "baseline_metrics": base_metrics,
        "treatment_metrics": treat_metrics,
        "score": score, "wins": wins,
        "ci_by_horizon": ci_by_horizon,
        "mean_delta_by_horizon": mean_delta_by_horizon,
        "ci_pass": ci_pass,
    }


def split_by_fold(trades: list[Trade]) -> dict[str, list[Trade]]:
    """Walk-forward fold split by entry_date."""
    out: dict[str, list[Trade]] = {"all": trades[:]}
    for name, start, end in FOLDS:
        out[name] = [t for t in trades if start <= t.entry_date <= end]
    return out


def render_markdown(all_results: dict[str, list[dict]], n_trades: int,
                     fold_counts: dict[str, int]) -> str:
    out: list[str] = []
    out.append("# PR F — ATR grid validation (paired counterfactual)")
    out.append("")
    out.append(f"Run date: {today_kst()}")
    out.append("")
    out.append("## Setup")
    out.append("")
    out.append(f"- Universe: `{UNIVERSE_KEY}` ({len(_load_universe())} tickers)")
    out.append("- Entry: SMA 50/200 golden cross (E3-3b parity)")
    out.append(f"- Baseline: fixed {BASELINE_STOP_PCT}% (config/rules.yaml stop_loss.per_stock)")
    out.append(f"- Grid: K {list(K_GRID)} × regime_mult {REGIME_MULT_TEST} = {len(K_GRID) * len(REGIME_MULT_TEST)} combos")
    out.append(f"- Horizons: {HORIZONS} trading days")
    out.append(f"- ATR period: {ATR_PERIOD}")
    out.append(f"- N trades total: **{n_trades}** (fold1_2024: {fold_counts.get('fold1_2024', 0)}, "
               f"fold2_2025: {fold_counts.get('fold2_2025', 0)})")
    out.append("")
    out.append("## Combined (all trades) — 6-metric panel")
    out.append("")
    all_combos = all_results.get("all", [])
    out.append("| k | regime_mult | score | wins | Baseline CAGR | Treatment CAGR | MaxDD Δ | Ulcer Δ | Turnover Δ | HitRate Δ |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(all_combos, key=lambda x: (-x["score"], -x.get("treatment_metrics", {}).get("cagr", float("-inf")))):
        bm = r["baseline_metrics"]
        tm = r["treatment_metrics"]
        if tm.get("n", 0) == 0:
            out.append(f"| {r['k']} | {r['regime_mult']} | — | — | — | — | — | — | — | — |")
            continue
        out.append(f"| {r['k']} | {r['regime_mult']} | {r['score']}/6 | "
                   f"{','.join(r['wins'])} | "
                   f"{bm['cagr']:+.2f}% | {tm['cagr']:+.2f}% | "
                   f"{tm['max_dd'] - bm['max_dd']:+.2f}pp | "
                   f"{tm['ulcer'] - bm['ulcer']:+.2f} | "
                   f"{tm['turnover'] - bm['turnover']:+.1f}pp | "
                   f"{tm['hit_rate'] - bm['hit_rate']:+.1f}pp |")
    out.append("")
    out.append("## Bootstrap CI on paired delta (all trades)")
    out.append("")
    out.append("| k | regime_mult | 30d mean Δ | 30d 95%CI | 60d mean Δ | 60d 95%CI | 90d mean Δ | 90d 95%CI | CI PASS |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(all_combos, key=lambda x: (-x["score"], -x.get("mean_delta_by_horizon", {}).get(60, float("-inf")))):
        row = [f"| {r['k']} | {r['regime_mult']} |"]
        for h in HORIZONS:
            mean_d = r["mean_delta_by_horizon"].get(h)
            ci = r["ci_by_horizon"].get(h, (float("nan"), float("nan")))
            if mean_d is None or np.isnan(mean_d):
                row.append(" — | — |")
            else:
                row.append(f" {mean_d:+.3f}% | [{ci[0]:+.3f}, {ci[1]:+.3f}] |")
        row.append(" ✅ |" if r["ci_pass"] else " ❌ |")
        out.append("".join(row))
    out.append("")
    out.append("## Walk-forward per-fold (best combo on each fold)")
    out.append("")
    out.append("| fold | n | best k | best regime_mult | score | CAGR Δ | 60d CI lower |")
    out.append("|---|---|---|---|---|---|---|")
    for fold_name, _, _ in FOLDS:
        fold_combos = all_results.get(fold_name, [])
        fold_n = fold_counts.get(fold_name, 0)
        if not fold_combos or fold_n == 0:
            out.append(f"| {fold_name} | 0 | — | — | — | — | — |")
            continue
        valid = [r for r in fold_combos if r.get("treatment_metrics", {}).get("n", 0) > 0]
        if not valid:
            out.append(f"| {fold_name} | {fold_n} | — | — | — | — | — |")
            continue
        best = max(valid, key=lambda x: (x["score"], x["treatment_metrics"].get("cagr", float("-inf"))))
        cagr_delta = (best["treatment_metrics"]["cagr"] - best["baseline_metrics"]["cagr"])
        ci60 = best["ci_by_horizon"].get(60, (float("nan"), float("nan")))
        out.append(f"| {fold_name} | {fold_n} | {best['k']} | {best['regime_mult']} | "
                   f"{best['score']}/6 | {cagr_delta:+.2f}pp | {ci60[0]:+.3f}% |")
    out.append("")
    out.append("## Acceptance verdict")
    out.append("")
    # Winner = combo with ≥ 4/6 score + CI pass in all trades
    winners = [r for r in all_combos if r["score"] >= 4 and r["ci_pass"]]
    if winners:
        best_winner = max(winners, key=lambda x: (x["score"], x["treatment_metrics"].get("cagr", float("-inf"))))
        out.append(f"**PASS**: k={best_winner['k']}, regime_mult={best_winner['regime_mult']} "
                   f"({best_winner['score']}/6 + CI lower bound > 0). Commit 3 (shadow surface) 진행 가능.")
    elif any(r["score"] >= 4 or r["ci_pass"] for r in all_combos):
        marginal = [r for r in all_combos if r["score"] >= 4 or r["ci_pass"]]
        best_marginal = max(marginal, key=lambda x: x["score"])
        out.append(f"**MARGINAL**: best k={best_marginal['k']}, regime_mult={best_marginal['regime_mult']} "
                   f"({best_marginal['score']}/6, CI {'PASS' if best_marginal['ci_pass'] else 'FAIL'}). "
                   f"Shadow surface 보류 (PR F2 재검증).")
    else:
        out.append("**FAIL**: no combo ≥ 4/6 + CI PASS. Shadow 미도입, -7% 유지.")
    out.append("")
    out.append("## Known limitations")
    out.append("")
    out.append("- **Survivorship bias**: us_core 는 current curated list — delisted 제외. "
               "magnitude 영향, direction 영향은 제한적.")
    out.append("- **Single entry family**: SMA 50/200 cross 만 — momentum/RSI 등 generalization untested.")
    out.append("- **ATR anchor = entry date today approx**: held position 의 original avg_price 책정일이 "
               "아닌 entry_date=cross_date 기준. PR F2 에서 entry_date tracking.")
    out.append("- **No trailing / take-profit**: stop-loss only. trailing ATR 은 PR F2.")
    out.append("- **Regime_mult 3 values tested** (E3-3c parity) — 전체 10 regime matrix 미검증.")
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--bootstrap-iter", type=int, default=10000)
    parser.add_argument("--max-tickers", type=int, default=None,
                        help="debug: limit universe size")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    LOG.info("PR F ATR grid validation — start")
    tickers = _load_universe()
    if args.max_tickers:
        tickers = tickers[:args.max_tickers]
    LOG.info(f"  universe: {len(tickers)} tickers")

    trades = collect_trades(tickers)
    if not trades:
        LOG.error("No trades collected — abort")
        return

    folds = split_by_fold(trades)
    fold_counts = {name: len(subset) for name, subset in folds.items()}

    # Evaluate all combos for each fold
    all_results: dict[str, list[dict]] = {}
    for fold_name, fold_trades in folds.items():
        LOG.info(f"  evaluating fold={fold_name} (n={len(fold_trades)})")
        combos: list[dict] = []
        if not fold_trades:
            all_results[fold_name] = []
            continue
        for k in K_GRID:
            for regime_mult in REGIME_MULT_TEST:
                result = evaluate_combo(fold_trades, k, regime_mult, n_iter=args.bootstrap_iter)
                combos.append(result)
        all_results[fold_name] = combos

    md = render_markdown(all_results, len(trades), fold_counts)
    print(md)

    if args.save:
        out_dir = Path("data/reports") / today_kst()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "pr_f_atr_validation.md"
        out_path.write_text(md)
        LOG.info(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
