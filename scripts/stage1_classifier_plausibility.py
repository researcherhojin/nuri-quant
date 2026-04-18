#!/usr/bin/env python3
"""E3-2 Stage 1 — Classifier plausibility (diagnostic).

STRATEGY §3.6 Stage 1 — diagnostic, NOT a hard ship gate.

목적: regime label 별로 forward 21-trading-day SPY return (~ 1 month market
horizon) 분포를 측정해 directional sanity 확인. "bull_low_vol" 이 분포
right-skewed 인지 / "bear_high_vol" 이 left-skewed 인지. Sizing rule 은
loss attenuation 으로 가치 추가 가능하므로 이 stage 가 fail 해도
Stage 2 PASS 시 ship 가능.

사용:
    .venv/bin/python scripts/stage1_classifier_plausibility.py [--sample-count 12]

출력: stdout markdown table + (선택) data/reports/{today}/e3_stage1_*.md

데이터 제약 (2026-04-19 측정):
- SPY prices: 5Y OK
- VIX: 1Y only (258 rows from 2025-04-08) — binding constraint
- fear_greed: 10 rows only — confidence check 영향
- CPI/GDP: 0 rows — stagflation detection 항상 False

따라서 N=12 monthly samples (1Y window) 가 현 data depth 한계.
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from nuri.core.db import query
from nuri.core.timezone import today_kst
from nuri.quant.regime.classifier import classify_regime

FORWARD_TRADING_DAYS = 21  # ~30 calendar days market-horizon (codex Round 1 P1)


@dataclass
class SampleResult:
    """단일 historical date 의 regime label + forward 21-trading-day SPY return."""
    date: str
    regime: str | None
    confidence: float | None
    exit_date: str | None  # 실제 +21 거래일 종가 측정 date (transparency)
    forward_return_pct: float | None  # None = data not available


def _get_spy_close(date: str) -> float | None:
    rows = query("SELECT close FROM prices WHERE ticker = 'SPY' AND date = ?", (date,))
    return rows[0]["close"] if rows else None


def _get_spy_forward_close(entry_date: str, n_trading_days: int) -> tuple[str, float] | None:
    """entry_date 이후 N 거래일 째의 SPY close (date, close) 반환. 부족 시 None."""
    rows = query(
        "SELECT date, close FROM prices WHERE ticker = 'SPY' AND date > ? ORDER BY date LIMIT ?",
        (entry_date, n_trading_days),
    )
    if len(rows) < n_trading_days:
        return None
    last = rows[-1]
    return last["date"], last["close"]


def _generate_sample_dates(n: int) -> list[str]:
    """월별 sample dates — VIX window 내 + forward 21 거래일 확보 가능 시점.

    cutoff = SPY 의 가장 최근 date - 21 거래일. VIX 가능 date 중 cutoff 이전만.
    """
    rows = query("SELECT date FROM macro WHERE indicator = 'vix' ORDER BY date")
    if not rows:
        raise RuntimeError("VIX 데이터 없음 — Stage 1 실행 불가")

    vix_dates = [r["date"] for r in rows]
    # SPY prices 최신 21 거래일 안쪽 sample 제외 (forward 측정 불가)
    spy_rows = query("SELECT date FROM prices WHERE ticker = 'SPY' ORDER BY date DESC LIMIT ?",
                     (FORWARD_TRADING_DAYS + 1,))
    if len(spy_rows) <= FORWARD_TRADING_DAYS:
        raise RuntimeError("SPY prices 부족 — forward 21 거래일 확보 불가")
    cutoff = spy_rows[-1]["date"]  # = (latest SPY date) - 21 거래일
    candidate = [d for d in vix_dates if d <= cutoff]

    if not candidate:
        raise RuntimeError(f"forward 21 거래일 확보 가능한 VIX date 없음 (cutoff={cutoff})")

    # 월별 last available date (최신 → 과거 순으로 N 개)
    seen_months: set[str] = set()
    monthly: list[str] = []
    for d in reversed(candidate):
        m = d[:7]
        if m not in seen_months:
            seen_months.add(m)
            monthly.append(d)
            if len(monthly) >= n:
                break
    monthly.reverse()
    return monthly


def collect_samples(sample_dates: list[str]) -> list[SampleResult]:
    results: list[SampleResult] = []
    for d in sample_dates:
        state = classify_regime(date=d)
        if state is None:
            results.append(SampleResult(date=d, regime=None, confidence=None,
                                         exit_date=None, forward_return_pct=None))
            continue
        spot = _get_spy_close(d)
        forward = _get_spy_forward_close(d, FORWARD_TRADING_DAYS)
        exit_date, ret_pct = None, None
        if forward is not None and spot is not None:
            exit_date, forward_close = forward
            ret_pct = (forward_close - spot) / spot * 100
        results.append(SampleResult(
            date=d, regime=state.regime, confidence=state.confidence,
            exit_date=exit_date, forward_return_pct=ret_pct,
        ))
    return results


def aggregate(results: list[SampleResult]) -> dict[str, dict]:
    """regime → {n, mean, median, min, max, positive_rate}."""
    by_regime: dict[str, list[float]] = defaultdict(list)
    for r in results:
        if r.regime and r.forward_return_pct is not None:
            by_regime[r.regime].append(r.forward_return_pct)

    agg: dict[str, dict] = {}
    for regime, returns in by_regime.items():
        if not returns:
            continue
        agg[regime] = {
            "n": len(returns),
            "mean": statistics.mean(returns),
            "median": statistics.median(returns),
            "min": min(returns),
            "max": max(returns),
            "positive_rate": sum(1 for r in returns if r > 0) / len(returns) * 100,
        }
    return agg


def render_markdown(results: list[SampleResult], agg: dict[str, dict]) -> str:
    n_sampled = len(results)
    n_with_return = sum(1 for r in results if r.forward_return_pct is not None)
    out: list[str] = []
    out.append("# E3-2 Stage 1 — Classifier Plausibility (diagnostic)")
    out.append("")
    out.append(f"Run date: {today_kst()}")
    out.append("")
    out.append("**Sample design (codex Round 1 P1)**: recency-biased — 최근 1Y monthly endpoint, ")
    out.append("VIX window (1Y) + SPY forward 21 거래일 확보 가능 시점 한정. broad historical 아님.")
    out.append(f"Sampled N={n_sampled}, usable N_ret={n_with_return} (forward 21 trading days 측정 가능).")
    out.append("")
    out.append("## Sample raw data")
    out.append("")
    out.append("| date | regime | confidence | exit_date (+21 trading days) | forward_return_% |")
    out.append("|---|---|---|---|---|")
    for r in results:
        ret_str = f"{r.forward_return_pct:+.2f}" if r.forward_return_pct is not None else "N/A"
        exit_str = r.exit_date or "N/A"
        out.append(f"| {r.date} | {r.regime or 'N/A'} | "
                   f"{r.confidence if r.confidence is not None else 'N/A'} | {exit_str} | {ret_str} |")
    out.append("")
    out.append("## Regime → forward 21-trading-day SPY return distribution")
    out.append("")
    out.append("| regime | n | mean_% | median_% | min_% | max_% | positive_rate_% |")
    out.append("|---|---|---|---|---|---|---|")
    for regime in sorted(agg.keys()):
        s = agg[regime]
        out.append(f"| {regime} | {s['n']} | {s['mean']:+.2f} | {s['median']:+.2f} | "
                   f"{s['min']:+.2f} | {s['max']:+.2f} | {s['positive_rate']:.1f} |")
    out.append("")
    out.append("## Directional sanity check")
    out.append("")
    out.append("- bull_* regime → mean/median forward return 양수 기대")
    out.append("- bear_* regime → mean/median forward return 음수 기대")
    out.append("- 각 regime n 작음 (data depth 제약) — directional 만, statistical significance 아님")
    out.append("- Stage 1 은 diagnostic, hard ship gate 아님 (STRATEGY §3.6)")
    out.append("- fail 시 review 에 cite, Stage 2 (paired counterfactual) 가 main gate")
    out.append("")
    out.append("## Data depth limitations (2026-04-19 measurement)")
    out.append("")
    out.append("- SPY prices: 5Y OK (2021-04-08 ~ 2026-04-14, 1260 rows)")
    out.append("- VIX: **1Y only** (2025-04-08 ~ 2026-04-17, 258 rows) — binding constraint")
    out.append("- fear_greed: 10 rows only — classifier confidence check 영향")
    out.append("- CPI/GDP: 0 rows — _detect_stagflation 항상 False")
    out.append("")
    out.append(f"이로 인해 sampled N={n_sampled} monthly (VIX 1Y window 한계) — usable N_ret={n_with_return}. ")
    out.append("VIX backfill 후 N=24~36 (E3-0 spec 원본) 재실행 가능.")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-count", type=int, default=12,
                        help="monthly sample 개수 (default 12 = 1Y VIX window 한계)")
    parser.add_argument("--save", action="store_true",
                        help="data/reports/{today}/e3_stage1_classifier_plausibility.md 에 저장")
    args = parser.parse_args()

    sample_dates = _generate_sample_dates(args.sample_count)
    print(f"Sampling {len(sample_dates)} dates: {sample_dates[0]} ~ {sample_dates[-1]}")

    results = collect_samples(sample_dates)
    agg = aggregate(results)
    md = render_markdown(results, agg)
    print(md)

    if args.save:
        from pathlib import Path
        out_dir = Path("data/reports") / today_kst()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "e3_stage1_classifier_plausibility.md"
        out_path.write_text(md)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
