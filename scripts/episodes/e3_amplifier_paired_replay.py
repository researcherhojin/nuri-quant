#!/usr/bin/env python3
"""E3 Phase 2 Stage 2 — paired counterfactual replay engine.

STRATEGY §3.6 Stage 2 main gate. Spec:
  docs/plans/E3_phase2_paired_counterfactual.md

Methodology (frozen, post Round 5 GATE PASS 2026-04-29):
  - Universe: us_core 85 (frozen — 81/85 with ≥1000 price rows since 2020-01-01).
  - Date range: 2020-01-01 → today (COVID included; codex Q8).
  - Entry signal: close > rolling_20d_high.shift(1), strict `>`, no volume filter (codex Q1).
  - Eligibility gate (single definition, both arms): breakout_entry AND
    recovery_confirmed AND vix_favorable AND regime_favorable.
    macro_benign arm dropped — macro_events has no 5Y backfill (Phase 3+ live).
  - Sizing: baseline=1.0, treatment=1.5 (codex Q4 — quarter-Kelly is later work).
  - Forward returns: 30/60/90 trading days, adj_close (codex Q5).
  - Bootstrap CI: 1000 iter, block_size=20 trading days, seed=42 (codex Q6).
    10/40 sensitivity informational only (cannot move PASS/FAIL).

Acceptance (binary, frozen — Round 5 GATE PASS):
  Precondition: Stage 0 audit must be CLEAN.
                If not, this script exits 2 without producing verdict.json.
  Given Stage 0 clean:
    PASS  iff  CI_lower_30d > 0
    FAIL  otherwise (CI_lower ≤ 0, including CI crossing 0)

Power-limit caveat (binding, surface honestly): N=203 entries cluster on
~9 unique trading days; effective independent block count ≈ 9. CI likely
wide. Verdict reports magnitudes regardless; the binary rule decides.

Usage:
  .venv/bin/python scripts/e3_amplifier_paired_replay.py [--dry-run] [--horizons 30,60,90]

Output:
  data/reports/<YYYY-MM-DD>/e3_phase2_verdict.json   (gitignored)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nuri.core.db import query_df  # noqa: E402
from nuri.core.timezone import kst_now, today_kst  # noqa: E402
from nuri.quant.regime.classifier import classify_regime  # noqa: E402
from nuri.quant.regime.recovery_detector import evaluate_recovery  # noqa: E402

LOG = logging.getLogger("e3_phase2.replay")

# ─── Frozen parameters (do not edit without spec re-amend + new GATE) ──────

UNIVERSE_KEY = "us_core"
DATE_START = "2020-01-01"
ENTRY_LOOKBACK_DAYS = 20
HORIZONS = (30, 60, 90)  # trading days
AMP_MULT = 1.5
BASELINE_MULT = 1.0
BOOTSTRAP_ITERS = 1000
BLOCK_SIZE_PRIMARY = 20  # trading days
BLOCK_SIZES_SENSITIVITY = (10, 40)
SEED = 42
MIN_PRICE_ROWS = 1000  # 5Y × 252 lenient floor
REGIME_FAVORABLE_LABELS = {"bull_low_vol", "recovery"}
REGIME_MIN_CONFIDENCE = 0.60
SPEC_VERSION = "phase2-p1-amended-2026-04-29-r2"


@dataclass
class HorizonMetrics:
    horizon: int
    n_entries: int
    mean_paired_delta: float
    median_paired_delta: float
    ci_lower_95: float
    ci_upper_95: float


@dataclass
class SensitivityBlock:
    block_size: int
    metrics_by_horizon: dict[int, dict]


@dataclass
class Verdict:
    spec_version: str
    run_at_kst: str
    git_commit: str
    decision: str  # "PASS" | "FAIL"
    decision_reason: str
    stage0_audit: dict
    universe: dict
    date_range: dict
    entry_rule: str
    treatment_rule: str
    amp_mult: float
    sample_counts: dict
    bootstrap: dict
    metrics_by_horizon: dict[int, dict]
    sensitivity: dict
    caveats: list[str] = field(default_factory=list)


# ─── Stage 0 precondition gate ─────────────────────────────────────────────


def run_stage0_precondition() -> tuple[bool, dict]:
    """Run Stage 0 audit. Return (clean, audit_dict).

    Per spec: if Stage 0 fails, no verdict.json is produced — caller exits
    with code 2 and a contamination report (already emitted by audit script).
    """
    from scripts.episodes.e3_amplifier_stage0_audit import _result_to_json, run_audit

    LOG.info("running Stage 0 audit precondition…")
    result = run_audit()
    payload = _result_to_json(result)
    if not result.clean:
        LOG.error(
            "Stage 0 audit FAILED — %d violations. Verdict NOT produced (precondition).",
            len(result.violations),
        )
    return result.clean, payload


# ─── Universe + price load ─────────────────────────────────────────────────


def _load_universe() -> list[str]:
    uy = yaml.safe_load((PROJECT_ROOT / "config" / "universe.yaml").read_text())
    return sorted((uy.get(UNIVERSE_KEY) or {}).get("tickers") or [])


def _load_covered_tickers(target: list[str]) -> tuple[list[str], list[str]]:
    """Return (covered, missing) using ≥ MIN_PRICE_ROWS rows since DATE_START."""
    placeholders = ",".join(f"'{t}'" for t in target)
    sql = (
        f"SELECT ticker, COUNT(*) AS n FROM prices "
        f"WHERE ticker IN ({placeholders}) AND date >= '{DATE_START}' "
        f"GROUP BY ticker HAVING n >= {MIN_PRICE_ROWS}"
    )
    df = query_df(sql)
    covered = sorted(df["ticker"].tolist()) if not df.empty else []
    missing = sorted(set(target) - set(covered))
    return covered, missing


def _load_prices(ticker: str) -> pd.DataFrame:
    df = query_df(
        "SELECT date, close FROM prices WHERE ticker=? AND date >= ? ORDER BY date",
        params=(ticker, DATE_START),
    )
    if df.empty:
        return df
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


def _spy_trading_days() -> list[str]:
    df = query_df(
        "SELECT date FROM prices WHERE ticker='SPY' AND date >= ? ORDER BY date",
        params=(DATE_START,),
    )
    return df["date"].tolist()


# ─── Day-level eligibility cache ───────────────────────────────────────────


def _vix_favorable_dates() -> set[str]:
    df = query_df(
        "SELECT date, value FROM macro WHERE indicator='vix' AND date >= ? ORDER BY date",
        params=(DATE_START,),
    )
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["v3"] = df["value"].shift(3)
    df["fav"] = (df["value"] < 22) & (df["value"] < df["v3"])
    return set(df.loc[df["fav"], "date"].tolist())


def _eligible_days(spy_days: list[str], vix_fav: set[str]) -> tuple[set[str], dict]:
    """For each VIX-favorable day, evaluate recovery_detector + classify_regime.

    Returns (eligible_dates, day_stats). eligible = recovery_confirmed AND
    vix_favorable AND regime_favorable. Computing only on VIX-favorable days
    is a sound optimization (mandatory AND short-circuits on vix_favorable=False).
    """
    fav_subset = [d for d in spy_days if d in vix_fav]
    LOG.info("evaluating recovery + regime on %d VIX-favorable trading days…", len(fav_subset))

    eligible: set[str] = set()
    n_recovery_only = 0
    n_regime_only = 0
    n_both = 0

    t0 = time.time()
    for i, d in enumerate(fav_subset):
        if i and i % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / i * (len(fav_subset) - i)
            LOG.info("  [%d/%d] %.1fs elapsed, ETA ~%.0fs", i, len(fav_subset), elapsed, eta)
        try:
            rec = evaluate_recovery(as_of_date=d)
            recovery_ok = bool(rec.recovery_confirmed)
        except Exception as e:  # noqa: BLE001
            LOG.warning("evaluate_recovery(%s) failed: %s", d, e)
            recovery_ok = False

        try:
            rs = classify_regime(date=d)
            regime_ok = (
                rs is not None
                and getattr(rs, "regime", None) in REGIME_FAVORABLE_LABELS
                and float(getattr(rs, "confidence", 0.0)) >= REGIME_MIN_CONFIDENCE
            )
        except Exception as e:  # noqa: BLE001
            LOG.warning("classify_regime(%s) failed: %s", d, e)
            regime_ok = False

        if recovery_ok:
            n_recovery_only += 1
        if regime_ok:
            n_regime_only += 1
        if recovery_ok and regime_ok:
            n_both += 1
            eligible.add(d)

    stats = {
        "n_vix_favorable_days": len(fav_subset),
        "n_recovery_confirmed_days": n_recovery_only,
        "n_regime_favorable_days": n_regime_only,
        "n_eligible_days": n_both,
    }
    return eligible, stats


# ─── Entries + forward returns ─────────────────────────────────────────────


def _ticker_breakout_entries(ticker: str) -> list[tuple[str, int]]:
    """Return [(entry_date, entry_idx)] for 20d breakouts since DATE_START."""
    df = _load_prices(ticker)
    if len(df) < 25:
        return []
    df["roll_high_prev"] = df["close"].rolling(ENTRY_LOOKBACK_DAYS).max().shift(1)
    df["breakout"] = df["close"] > df["roll_high_prev"]
    breakouts = df.index[df["breakout"]].tolist()
    return [(df.loc[i, "date"], int(i)) for i in breakouts]


def _forward_returns(ticker: str, eligible_entries: list[tuple[str, int]]) -> list[dict]:
    """Compute per-entry forward returns at each horizon. Returns list of
    {entry_date, h_30: ret, h_60: ret, h_90: ret}; entries lacking enough
    forward bars are skipped (ragged-edge of dataset).
    """
    df = _load_prices(ticker)
    if df.empty:
        return []
    out: list[dict] = []
    n = len(df)
    for entry_date, idx in eligible_entries:
        entry_close = df.loc[idx, "close"]
        if entry_close <= 0:
            continue
        rec = {"ticker": ticker, "entry_date": entry_date, "entry_idx": idx}
        valid = True
        for h in HORIZONS:
            j = idx + h
            if j >= n:
                valid = False
                break
            rec[f"h_{h}"] = float(df.loc[j, "close"] / entry_close - 1.0)
        if valid:
            out.append(rec)
    return out


# ─── Block bootstrap ────────────────────────────────────────────────────────


def _block_bootstrap_ci(
    deltas: np.ndarray, block_size: int, iters: int, seed: int
) -> tuple[float, float, float, float]:
    """Stationary block bootstrap of paired deltas. Returns (mean, median, ci_lo, ci_hi).

    Block bootstrap respects local autocorrelation: deltas are sampled in
    contiguous blocks of `block_size`, with replacement, until we cover N.
    """
    rng = np.random.default_rng(seed)
    n = len(deltas)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")

    means = np.empty(iters, dtype=np.float64)
    n_blocks = (n + block_size - 1) // block_size
    for it in range(iters):
        starts = rng.integers(0, max(1, n - block_size + 1), size=n_blocks)
        chunks = [deltas[s : s + block_size] for s in starts]
        sample = np.concatenate(chunks)[:n]
        means[it] = float(sample.mean())
    ci_lo = float(np.percentile(means, 2.5))
    ci_hi = float(np.percentile(means, 97.5))
    mean = float(deltas.mean())
    median = float(np.median(deltas))
    return mean, median, ci_lo, ci_hi


# ─── Main orchestrator ────────────────────────────────────────────────────


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_replay(dry_run: bool = False) -> Verdict:
    t_start = time.time()

    # Stage 0 precondition
    clean, stage0_audit = run_stage0_precondition()
    if not clean:
        # Per spec: no verdict.json produced. Caller (main) exits 2.
        raise RuntimeError("Stage 0 audit failed — Phase 2 blocked at precondition.")

    # Universe load
    target = _load_universe()
    covered, missing = _load_covered_tickers(target)
    LOG.info("universe %s: %d/%d covered (≥%d rows)", UNIVERSE_KEY, len(covered), len(target), MIN_PRICE_ROWS)

    # Trading-day frame + eligibility precompute
    spy_days = _spy_trading_days()
    vix_fav = _vix_favorable_dates()
    eligible_dates, day_stats = _eligible_days(spy_days, vix_fav)
    LOG.info("eligible trading days (rec ∩ vix ∩ regime): %d", len(eligible_dates))

    # Entries — collect all 20d breakouts on eligible days, then forward returns
    LOG.info("scanning 20d breakouts × %d tickers…", len(covered))
    n_breakout_total = 0
    all_records: list[dict] = []
    for tk in covered:
        breakouts = _ticker_breakout_entries(tk)
        n_breakout_total += len(breakouts)
        eligible_breakouts = [(d, i) for d, i in breakouts if d in eligible_dates]
        all_records.extend(_forward_returns(tk, eligible_breakouts))

    n_eligible = len(all_records)
    n_unique_eligible_days = len({r["entry_date"] for r in all_records})
    LOG.info(
        "entries: %d total breakouts, %d eligible (post-forward-window), %d unique days",
        n_breakout_total,
        n_eligible,
        n_unique_eligible_days,
    )

    if n_eligible == 0:
        LOG.error("no eligible entries — cannot compute paired delta")
        # Still produce a FAIL verdict.
        return _build_verdict(
            decision="FAIL",
            decision_reason="no eligible entries — power exhausted",
            stage0_audit=stage0_audit,
            covered=covered,
            target=target,
            missing=missing,
            n_breakout_total=n_breakout_total,
            n_eligible=0,
            n_unique_eligible_days=0,
            day_stats=day_stats,
            metrics={h: {"n_entries": 0} for h in HORIZONS},
            sensitivity={},
            extra_caveats=[],
        )

    # Paired deltas (per horizon) + bootstrap
    metrics_by_horizon: dict[int, dict] = {}
    deltas_by_horizon: dict[int, np.ndarray] = {}
    for h in HORIZONS:
        deltas = np.array([r[f"h_{h}"] * (AMP_MULT - BASELINE_MULT) for r in all_records], dtype=np.float64)
        deltas_by_horizon[h] = deltas
        mean, median, ci_lo, ci_hi = _block_bootstrap_ci(deltas, BLOCK_SIZE_PRIMARY, BOOTSTRAP_ITERS, SEED)
        metrics_by_horizon[h] = {
            "n_entries": int(len(deltas)),
            "mean_paired_delta": mean,
            "median_paired_delta": median,
            "ci_lower_95": ci_lo,
            "ci_upper_95": ci_hi,
        }
        LOG.info(
            "horizon %dd | N=%d | mean=%.4f | CI95=[%.4f, %.4f]",
            h,
            len(deltas),
            mean,
            ci_lo,
            ci_hi,
        )

    # Sensitivity blocks (informational)
    sensitivity = {}
    for bs in BLOCK_SIZES_SENSITIVITY:
        block_metrics = {}
        for h in HORIZONS:
            mean, median, ci_lo, ci_hi = _block_bootstrap_ci(deltas_by_horizon[h], bs, BOOTSTRAP_ITERS, SEED)
            block_metrics[h] = {
                "mean_paired_delta": mean,
                "ci_lower_95": ci_lo,
                "ci_upper_95": ci_hi,
            }
        sensitivity[f"block_size_{bs}"] = block_metrics

    # Decision (binary): primary = 30d
    primary = metrics_by_horizon[30]
    if primary["ci_lower_95"] > 0:
        decision = "PASS"
        decision_reason = (
            f"30d CI_lower={primary['ci_lower_95']:.4f} > 0 "
            f"(mean={primary['mean_paired_delta']:.4f}, N={primary['n_entries']})"
        )
    else:
        decision = "FAIL"
        decision_reason = (
            f"30d CI_lower={primary['ci_lower_95']:.4f} ≤ 0 "
            f"(mean={primary['mean_paired_delta']:.4f}, N={primary['n_entries']}); "
            f"binary acceptance rule routes to FAIL regardless of effect magnitude"
        )

    elapsed = time.time() - t_start
    LOG.info("decision: %s (%s) — total %.1fs", decision, decision_reason, elapsed)

    return _build_verdict(
        decision=decision,
        decision_reason=decision_reason,
        stage0_audit=stage0_audit,
        covered=covered,
        target=target,
        missing=missing,
        n_breakout_total=n_breakout_total,
        n_eligible=n_eligible,
        n_unique_eligible_days=n_unique_eligible_days,
        day_stats=day_stats,
        metrics=metrics_by_horizon,
        sensitivity=sensitivity,
        extra_caveats=[],
    )


def _build_verdict(
    *,
    decision: str,
    decision_reason: str,
    stage0_audit: dict,
    covered: list[str],
    target: list[str],
    missing: list[str],
    n_breakout_total: int,
    n_eligible: int,
    n_unique_eligible_days: int,
    day_stats: dict,
    metrics: dict,
    sensitivity: dict,
    extra_caveats: list[str],
) -> Verdict:
    caveats = [
        f"{UNIVERSE_KEY} embeds today's survivorship — delisted tickers absent",
        "macro_benign arm of canonical gate dropped (no 5Y backfill); re-enters at Phase 3+ live",
        f"{n_eligible} eligible entries cluster on {n_unique_eligible_days} unique trading days — "
        "effective independent N limited; block bootstrap CI likely wide",
    ]
    caveats.extend(extra_caveats)

    return Verdict(
        spec_version=SPEC_VERSION,
        run_at_kst=kst_now().isoformat(),
        git_commit=_git_commit(),
        decision=decision,
        decision_reason=decision_reason,
        stage0_audit=stage0_audit,
        universe={
            "name": UNIVERSE_KEY,
            "n_tickers_target": len(target),
            "n_tickers_covered": len(covered),
            "missing": missing,
        },
        date_range={"start": DATE_START, "end": today_kst()},
        entry_rule="close > rolling_20d_high.shift(1), strict >, no volume filter",
        treatment_rule=(
            "recovery_confirmed AND vix_favorable(VIX<22 AND 3d_slope<0) "
            "AND regime_favorable(regime in {bull_low_vol, recovery} AND conf>=0.60); "
            "macro_benign dropped (no 5Y data)"
        ),
        amp_mult=AMP_MULT,
        sample_counts={
            "n_breakout_total": n_breakout_total,
            "n_eligible": n_eligible,
            "n_unique_eligible_days": n_unique_eligible_days,
            **day_stats,
        },
        bootstrap={
            "iterations": BOOTSTRAP_ITERS,
            "block_size_primary": BLOCK_SIZE_PRIMARY,
            "seed": SEED,
            "effective_n_caveat": (
                "eligible entries cluster on n_unique_eligible_days; effective independent block count limited"
            ),
        },
        metrics_by_horizon=metrics,
        sensitivity=sensitivity,
        caveats=caveats,
    )


def _verdict_to_dict(v: Verdict) -> dict:
    return asdict(v)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="E3 Phase 2 paired counterfactual replay")
    parser.add_argument("--dry-run", action="store_true", help="run replay but do not write verdict.json")
    parser.add_argument("--out-dir", type=Path, default=None, help="override output directory")
    args = parser.parse_args(argv)

    try:
        verdict = run_replay(dry_run=args.dry_run)
    except RuntimeError as e:
        LOG.error("replay halted at precondition: %s", e)
        return 2

    payload = _verdict_to_dict(verdict)

    out_dir = args.out_dir or (PROJECT_ROOT / "data" / "reports" / today_kst())
    out_path = out_dir / "e3_phase2_verdict.json"

    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    if args.dry_run:
        LOG.info("--dry-run: skipped writing %s", out_path)
        return 0 if verdict.decision == "PASS" else 1

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    LOG.info("verdict → %s", out_path)
    return 0 if verdict.decision == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
