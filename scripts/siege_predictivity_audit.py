#!/usr/bin/env python3
"""E4-0b — SIEGE historical predictivity audit.

docs/plans/e4_0b.md Plan doc 구현. SIEGE 각 gate 의 실측 predictivity 측정:
각 gate 가 fire 할 때 실제로 portfolio forward return 이 낮은가?

Methodology (Plan doc §2 Q1-Q5):
- Q1 Monthly top-10 momentum snapshot (us_core 85 universe, 5Y = 60 snapshots)
- Q2 Universe: us_core (Stage 2 연속성)
- Q3 Forward NAV: fixed 30/60/90d horizon (Stage 2 패턴)
- Q4 Metric: conditional mean diff + 95% bootstrap CI (primary) + AUC (secondary)
- Q5 Output: ranking + advisory (hard threshold → E4-0c)

Architecture:
1. Generate monthly snapshot dates (month-end, 5Y back from today)
2. For each date:
   a. Pick top-10 momentum tickers from us_core (252d lookback, strict no-lookahead)
   b. Classify regime at that date
   c. Build CertSnapshot (synthetic portfolio: 10 tickers × 10% weight)
   d. Run certify(snapshot=..., caller="audit:historical", timestamp=...)
   e. Compute forward 30/60/90d NAV (portfolio-level, weight-averaged return + MAE)
3. After loop: analyze persisted audit rows + NAV outcomes → per-gate predictivity
4. Output markdown report

Usage:
    .venv/bin/python scripts/siege_predictivity_audit.py [--full | --universe us_core | --months 60]
                                                         [--bootstrap-iter 5000]
                                                         [--save | --dry-run]

기본값 dry-run — 실 certifications 에 persist 안 함. `--save` 로 audit rows 기록.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import query, query_df
from nuri.core.timezone import today_kst
from nuri.quant.regime.classifier import classify_regime
from nuri.trading.engine.certification import (
    CertCondition,
    CertSnapshot,
    _compute_portfolio_hash,
    certify,
)

LOG = logging.getLogger("e4_0b_audit")

HORIZONS = [30, 60, 90]
DEFAULT_UNIVERSE = "us_core"
DEFAULT_MONTHS = 60
DEFAULT_TOP_N = 10
MOMENTUM_LOOKBACK = 252  # 1Y trading days


@dataclass
class AuditSnapshot:
    """Single monthly snapshot — portfolio + forward NAV measurement."""

    snapshot_date: str  # "YYYY-MM-DD"
    tickers: list[str]  # top-N by momentum
    cert: dict | None  # Certificate dict (from certify() output)
    regime: str | None
    forward_nav: dict[int, float | None]  # horizon → portfolio-level forward return %
    forward_mae: dict[int, float | None]  # horizon → max adverse excursion %
    skipped_reason: str | None = None  # None if snapshot constructed, else reason


@dataclass
class GateMetric:
    """Per-gate predictivity metric — Q4 B primary."""

    gate_id: str
    severity: str  # "error" | "warning"
    fire_count: int  # snapshots where this gate failed
    not_fire_count: int  # snapshots where this gate passed
    # conditional means at each horizon (fwd return | gate fired vs not fired)
    mean_when_fired: dict[int, float | None] = field(default_factory=dict)
    mean_when_not_fired: dict[int, float | None] = field(default_factory=dict)
    # primary metric (Q4 B): mean_fired - mean_not_fired + 95% CI
    cond_mean_diff: dict[int, float | None] = field(default_factory=dict)
    ci_low: dict[int, float | None] = field(default_factory=dict)
    ci_high: dict[int, float | None] = field(default_factory=dict)
    # Sharpe-like (Q4 B bonus): (diff) / std(forward_returns)
    sharpe_like: dict[int, float | None] = field(default_factory=dict)


# ─── helpers: universe + snapshot dates ────────────────────────────────────


def _load_universe(key: str = DEFAULT_UNIVERSE) -> list[str]:
    """config/universe.yaml 의 tickers 로드. Stage 2 와 동일 루틴."""
    import yaml

    with open("config/universe.yaml") as f:
        u = yaml.safe_load(f) or {}
    section = u.get(key) or {}
    tickers = section.get("tickers") or []
    if not tickers:
        raise RuntimeError(f"universe.yaml {key}.tickers empty")
    return sorted(tickers)


def monthly_snapshot_dates(end_date: str, months: int = DEFAULT_MONTHS) -> list[str]:
    """end_date 부터 뒤로 N개월, 매월 말 (business day) 날짜 리스트 (오래된 → 최신).

    Determinism — 같은 (end_date, months) 입력 → 항상 같은 리스트.
    """
    end = pd.Timestamp(end_date)
    # 월말로 스냅 (pandas 'ME' frequency)
    dates = pd.date_range(end=end, periods=months, freq="ME")
    return [d.strftime("%Y-%m-%d") for d in dates]


def _trading_day_on_or_before(date: str, db_path=None) -> str | None:
    """prices 테이블에서 해당 date 이전(포함) 가장 최신 거래일."""
    rows = query(
        "SELECT date FROM prices WHERE ticker='SPY' AND date <= ? ORDER BY date DESC LIMIT 1",
        (date,),
        db_path=db_path,
    )
    return rows[0]["date"] if rows else None


# ─── momentum selection (strict no-lookahead) ───────────────────────────────


def top_n_momentum(
    universe: list[str], as_of_date: str, n: int = DEFAULT_TOP_N, db_path=None
) -> list[str]:
    """as_of_date 기준 252d return top N 반환. Strict no-lookahead.

    각 ticker 의 return = (close[as_of] - close[as_of - 252td]) / close[as_of - 252td]
    - 250d 이상 coverage 없으면 제외
    - as_of_date 이후 row 참조 금지
    """
    scores: list[tuple[str, float]] = []
    for ticker in universe:
        df = query_df(
            "SELECT date, close FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT ?",
            (ticker, as_of_date, MOMENTUM_LOOKBACK + 10),
            db_path=db_path,
        )
        if len(df) < MOMENTUM_LOOKBACK:
            continue
        # df 은 내림차순 → [0] 가 가장 최신 (as_of 이하), [lookback-1] 가 1년 전
        close_now = df.iloc[0]["close"]
        close_then = df.iloc[MOMENTUM_LOOKBACK - 1]["close"]
        if close_then <= 0:
            continue
        ret = (close_now - close_then) / close_then
        scores.append((ticker, ret))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scores[:n]]


# ─── synthetic portfolio_df (analyze_portfolio schema) ──────────────────────


def synthesize_portfolio_df(
    tickers: list[str], as_of_date: str, db_path=None, weight_pct: float = 10.0
) -> pd.DataFrame | None:
    """Historical portfolio DataFrame — analyze_portfolio() output schema.

    각 ticker 10% weight, USD 기준 (us_core 가정 — KR 미지원).
    가격 lookup: as_of_date 이전 최신 close. 데이터 부족 시 None.
    """
    rows = []
    for ticker in tickers:
        price_row = query(
            "SELECT close, date FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
            (ticker, as_of_date),
            db_path=db_path,
        )
        if not price_row:
            LOG.debug(f"  {ticker}: no price on/before {as_of_date}")
            return None
        close = price_row[0]["close"]
        # sector lookup — portfolio 테이블이 단일 sector source (fundamentals 는 sector 미포함).
        # historical audit 은 portfolio 에 해당 ticker 가 없을 수 있으므로 fallback "Unknown".
        sector_row = query(
            "SELECT DISTINCT sector FROM portfolio WHERE ticker=? AND sector IS NOT NULL LIMIT 1",
            (ticker,),
            db_path=db_path,
        )
        sector = sector_row[0]["sector"] if sector_row else "Unknown"
        # 단순 unit: quantity=1 each → position_usd = close. Weight 는 total 에서 derive.
        rows.append(
            {
                "account": "audit",
                "ticker": ticker,
                "sector": sector,
                "quantity": 1,
                "avg_price": close,
                "current_price": close,
                "currency": "USD",
                "current_value_usd": round(close, 2),
                "cost_basis_usd": round(close, 2),
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "price_date": price_row[0]["date"],
            }
        )
    if not rows:
        return None
    df = pd.DataFrame(rows)
    total = df["current_value_usd"].sum() or 1
    # Equal-weight override — 각 ticker 가 정확히 weight_pct 로 보이도록 value 재조정
    # (top-N momentum 에서 ticker 간 close 차이가 커서 natural weight 가 비대칭)
    target_value = total / len(tickers)
    df["current_value_usd"] = round(target_value, 2)
    df["cost_basis_usd"] = round(target_value, 2)
    df["weight_pct"] = round(df["current_value_usd"] / (target_value * len(tickers)) * 100, 2)
    df.attrs["warnings"] = []
    df.attrs["total_value_usd"] = round(total, 2)
    df.attrs["usd_krw"] = 1380.0  # historical USD/KRW not material for us-only
    return df


def synthesize_cert_snapshot(
    tickers: list[str], as_of_date: str, db_path=None
) -> CertSnapshot | None:
    """완전한 CertSnapshot — certify(snapshot=...) 에 주입 가능.

    regime 은 classify_regime(date=as_of_date). None 이면 snapshot 반환 None.
    """
    state = classify_regime(date=as_of_date)
    if state is None:
        LOG.debug(f"  {as_of_date}: regime classification 실패 (데이터 부족)")
        return None
    df = synthesize_portfolio_df(tickers, as_of_date, db_path=db_path)
    if df is None or df.empty:
        return None
    raw = [
        {
            "account": r["account"],
            "ticker": r["ticker"],
            "sector": r["sector"],
            "quantity": r["quantity"],
            "avg_price": r["avg_price"],
        }
        for r in df.to_dict(orient="records")
    ]
    return CertSnapshot(
        regime=state.regime,
        portfolio_raw=raw,
        portfolio_df=df,
        portfolio_hash=_compute_portfolio_hash(rows=raw),
        portfolio_error=None,
    )


# ─── forward NAV ────────────────────────────────────────────────────────────


def forward_portfolio_nav(
    tickers: list[str], entry_date: str, horizon: int, db_path=None
) -> tuple[float | None, float | None]:
    """Equal-weight portfolio-level forward return % + MAE %.

    각 ticker 의 forward N-day return 을 equal-weight average.
    partial data (일부 ticker 누락) 은 None 반환 (conservative).
    """
    per_ticker: list[float] = []
    per_ticker_mae: list[float] = []
    for ticker in tickers:
        rows = query(
            "SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date LIMIT ?",
            (ticker, entry_date, horizon + 1),
            db_path=db_path,
        )
        if len(rows) < horizon + 1:
            return None, None
        entry_close = rows[0]["close"]
        exit_close = rows[horizon]["close"]
        ret = (exit_close - entry_close) / entry_close * 100
        # MAE (max adverse excursion) — intra-window lowest close
        intra_lows = [r["close"] for r in rows[1 : horizon + 1]]
        mae = (min(intra_lows) - entry_close) / entry_close * 100 if intra_lows else 0.0
        per_ticker.append(ret)
        per_ticker_mae.append(mae)
    if not per_ticker:
        return None, None
    return statistics.mean(per_ticker), statistics.mean(per_ticker_mae)


# ─── audit loop ─────────────────────────────────────────────────────────────


def _fixed_timestamp(snapshot_date: str) -> str:
    """Idempotency key — snapshot_date 00:00 KST. 재실행 시 기존 row 감지 가능."""
    return f"{snapshot_date}T00:00:00+09:00"


def _already_audited(snapshot_date: str, db_path=None) -> bool:
    """이미 같은 snapshot_date × audit:historical row 있으면 True."""
    rows = query(
        "SELECT COUNT(*) c FROM certifications WHERE timestamp = ? AND caller = 'audit:historical'",
        (_fixed_timestamp(snapshot_date),),
        db_path=db_path,
    )
    return rows[0]["c"] > 0


def run_audit(
    universe_key: str,
    months: int,
    top_n: int,
    save: bool,
    db_path=None,
) -> list[AuditSnapshot]:
    """Main loop — 월별 snapshot 생성 + certify + forward NAV."""
    universe = _load_universe(universe_key)
    end_date = today_kst()
    dates = monthly_snapshot_dates(end_date, months)
    LOG.info(f"Universe: {universe_key} ({len(universe)} tickers), months: {months}, "
             f"save: {save}")
    LOG.info(f"Snapshot dates: {dates[0]} → {dates[-1]} ({len(dates)} total)")

    results: list[AuditSnapshot] = []
    for snapshot_date in dates:
        if save and _already_audited(snapshot_date, db_path=db_path):
            LOG.info(f"  {snapshot_date}: 이미 audit 완료 (skip, idempotent)")
            continue

        tickers = top_n_momentum(universe, snapshot_date, n=top_n, db_path=db_path)
        if len(tickers) < top_n:
            results.append(AuditSnapshot(
                snapshot_date=snapshot_date,
                tickers=tickers,
                cert=None, regime=None,
                forward_nav={h: None for h in HORIZONS},
                forward_mae={h: None for h in HORIZONS},
                skipped_reason=f"momentum top-N insufficient ({len(tickers)}/{top_n})",
            ))
            continue

        snapshot = synthesize_cert_snapshot(tickers, snapshot_date, db_path=db_path)
        if snapshot is None:
            results.append(AuditSnapshot(
                snapshot_date=snapshot_date,
                tickers=tickers,
                cert=None, regime=None,
                forward_nav={h: None for h in HORIZONS},
                forward_mae={h: None for h in HORIZONS},
                skipped_reason="snapshot build 실패 (regime 또는 price 데이터 부족)",
            ))
            continue

        try:
            cert = certify(
                db_path=db_path,
                persist=save,
                caller="audit:historical",
                snapshot=snapshot,
                timestamp=_fixed_timestamp(snapshot_date),
            )
        except Exception as e:
            LOG.warning(f"  {snapshot_date}: certify 실패 — {e}")
            results.append(AuditSnapshot(
                snapshot_date=snapshot_date,
                tickers=tickers,
                cert=None, regime=snapshot.regime,
                forward_nav={h: None for h in HORIZONS},
                forward_mae={h: None for h in HORIZONS},
                skipped_reason=f"certify raise: {type(e).__name__}",
            ))
            continue

        forward_nav: dict[int, float | None] = {}
        forward_mae: dict[int, float | None] = {}
        for h in HORIZONS:
            ret, mae = forward_portfolio_nav(tickers, snapshot_date, h, db_path=db_path)
            forward_nav[h] = ret
            forward_mae[h] = mae

        # Serialize cert for analysis (conditions 포함)
        cert_dict = {
            "timestamp": cert.timestamp,
            "certified": cert.certified,
            "score": cert.score,
            "total_conditions": cert.total_conditions,
            "passed": cert.passed,
            "failed": cert.failed,
            "warnings": cert.warnings,
            "conditions": [
                {"id": c.id, "passed": c.passed, "severity": c.severity}
                for c in cert.conditions
            ],
        }
        results.append(AuditSnapshot(
            snapshot_date=snapshot_date,
            tickers=tickers,
            cert=cert_dict,
            regime=snapshot.regime,
            forward_nav=forward_nav,
            forward_mae=forward_mae,
        ))

    LOG.info(f"  collected {len([r for r in results if r.cert])} snapshots "
             f"(skipped: {len([r for r in results if r.skipped_reason])})")
    return results


# ─── predictivity analysis ──────────────────────────────────────────────────


def _bootstrap_diff_ci(
    fired_returns: list[float],
    not_fired_returns: list[float],
    n_iter: int = 5000,
    conf_level: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap CI on (mean_fired - mean_not_fired). (lower, upper).

    percentile method. None if either sample < 2.
    """
    arr_f = np.array([v for v in fired_returns if v is not None])
    arr_n = np.array([v for v in not_fired_returns if v is not None])
    if len(arr_f) < 2 or len(arr_n) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        bf = rng.choice(arr_f, len(arr_f), replace=True).mean()
        bn = rng.choice(arr_n, len(arr_n), replace=True).mean()
        diffs[i] = bf - bn
    alpha = (1 - conf_level) / 2
    lo, hi = np.percentile(diffs, [alpha * 100, (1 - alpha) * 100])
    return float(lo), float(hi)


def analyze_predictivity(
    snapshots: list[AuditSnapshot], n_iter: int = 5000
) -> list[GateMetric]:
    """Per-gate predictivity — Q4 B primary (conditional mean diff + bootstrap CI).

    각 gate id 에 대해:
    - fired snapshots (passed=False) vs not_fired (passed=True)
    - 각 subset 의 forward_nav (30/60/90d) 분포
    - mean_fired - mean_not_fired + 95% CI (percentile bootstrap)
    """
    # Filter snapshots with cert + NAV
    valid = [s for s in snapshots if s.cert is not None]
    if not valid:
        return []

    # Collect all unique gate_id × severity combos
    gates: dict[tuple[str, str], GateMetric] = {}
    for s in valid:
        assert s.cert is not None  # Pylance narrowing: valid 에서 이미 필터됨
        for cond in s.cert["conditions"]:
            key = (cond["id"], cond["severity"])
            if key not in gates:
                gates[key] = GateMetric(gate_id=cond["id"], severity=cond["severity"],
                                        fire_count=0, not_fire_count=0)

    # Aggregate forward NAV per gate × horizon
    for (gate_id, severity), metric in gates.items():
        fired_per_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
        not_fired_per_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
        for s in valid:
            assert s.cert is not None  # same narrowing as above
            cond_found = None
            for c in s.cert["conditions"]:
                if c["id"] == gate_id and c["severity"] == severity:
                    cond_found = c
                    break
            if cond_found is None:
                continue  # 이 snapshot 에 해당 gate 없음 (variable total_conditions)
            for h in HORIZONS:
                ret = s.forward_nav.get(h)
                if ret is None:
                    continue
                if cond_found["passed"]:
                    not_fired_per_h[h].append(ret)
                else:
                    fired_per_h[h].append(ret)

        metric.fire_count = len(fired_per_h[HORIZONS[0]])
        metric.not_fire_count = len(not_fired_per_h[HORIZONS[0]])

        for h in HORIZONS:
            fired_arr = fired_per_h[h]
            not_fired_arr = not_fired_per_h[h]
            metric.mean_when_fired[h] = (
                round(statistics.mean(fired_arr), 3) if fired_arr else None
            )
            metric.mean_when_not_fired[h] = (
                round(statistics.mean(not_fired_arr), 3) if not_fired_arr else None
            )
            if fired_arr and not_fired_arr:
                diff = statistics.mean(fired_arr) - statistics.mean(not_fired_arr)
                metric.cond_mean_diff[h] = round(diff, 3)
                lo, hi = _bootstrap_diff_ci(fired_arr, not_fired_arr, n_iter=n_iter)
                metric.ci_low[h] = round(lo, 3)
                metric.ci_high[h] = round(hi, 3)
                # Sharpe-like: normalized by std of the full sample
                all_rets = fired_arr + not_fired_arr
                if len(all_rets) >= 2:
                    sd = statistics.stdev(all_rets)
                    metric.sharpe_like[h] = round(diff / sd, 3) if sd > 0 else None
            else:
                metric.cond_mean_diff[h] = None
                metric.ci_low[h] = None
                metric.ci_high[h] = None
                metric.sharpe_like[h] = None

    return list(gates.values())


# ─── report output ──────────────────────────────────────────────────────────


def _format_pct(v: float | None, digits: int = 2) -> str:
    return f"{v:+.{digits}f}%" if v is not None else "—"


def write_report(
    snapshots: list[AuditSnapshot],
    metrics: list[GateMetric],
    output_path: Path,
) -> None:
    """Markdown report — per-gate table + top/bottom predictivity rank."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    valid = [s for s in snapshots if s.cert is not None]
    skipped = [s for s in snapshots if s.skipped_reason]

    lines: list[str] = []
    lines.append("# E4-0b — SIEGE Historical Predictivity Audit")
    lines.append("")
    lines.append(f"Generated: {today_kst()} KST")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total snapshots attempted: **{len(snapshots)}**")
    lines.append(f"- Valid (cert + NAV): **{len(valid)}**")
    lines.append(f"- Skipped: **{len(skipped)}** ({_skip_breakdown(skipped)})")
    if valid:
        certified_n = sum(1 for s in valid if s.cert and s.cert["certified"])
        lines.append(f"- CERTIFIED rate: **{certified_n}/{len(valid)} = {certified_n/len(valid)*100:.1f}%**")
    lines.append("")

    # Per-gate table
    lines.append("## Per-gate predictivity (Q4 B — conditional mean difference)")
    lines.append("")
    lines.append("| Gate | Severity | Fire | Not-fire | Δ30d | CI30d | Δ60d | CI60d | Δ90d | CI90d |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    # Sort: most negative Δ30d first (strongest downside predictivity). None 은 마지막.
    def _sort_key(m: GateMetric) -> float:
        v = m.cond_mean_diff.get(30)
        return v if v is not None else float("inf")

    sorted_metrics = sorted(metrics, key=_sort_key)
    for m in sorted_metrics:
        ci30 = (
            f"[{_format_pct(m.ci_low.get(30))}, {_format_pct(m.ci_high.get(30))}]"
            if m.ci_low.get(30) is not None else "—"
        )
        ci60 = (
            f"[{_format_pct(m.ci_low.get(60))}, {_format_pct(m.ci_high.get(60))}]"
            if m.ci_low.get(60) is not None else "—"
        )
        ci90 = (
            f"[{_format_pct(m.ci_low.get(90))}, {_format_pct(m.ci_high.get(90))}]"
            if m.ci_low.get(90) is not None else "—"
        )
        lines.append(
            f"| `{m.gate_id}` | {m.severity} | {m.fire_count} | {m.not_fire_count} | "
            f"{_format_pct(m.cond_mean_diff.get(30))} | {ci30} | "
            f"{_format_pct(m.cond_mean_diff.get(60))} | {ci60} | "
            f"{_format_pct(m.cond_mean_diff.get(90))} | {ci90} |"
        )
    lines.append("")
    lines.append("**해석**: Δ = mean(fwd_return | gate fired) − mean(fwd_return | not fired).")
    lines.append("음수가 클수록 해당 gate fire 시 forward NAV 저조 → predictivity 높음.")
    lines.append("CI 가 0을 포함하면 통계적 significance 부족.")
    lines.append("")

    # Top/bottom rank
    if sorted_metrics:
        lines.append("## Top 3 downside predictivity (Δ30d most negative)")
        lines.append("")
        for m in sorted_metrics[:3]:
            lines.append(
                f"- `{m.gate_id}` ({m.severity}): Δ30d = {_format_pct(m.cond_mean_diff.get(30))}, "
                f"fire/not = {m.fire_count}/{m.not_fire_count}"
            )
        lines.append("")
        lines.append("## Bottom 3 predictivity (Δ30d most positive or null)")
        lines.append("")
        for m in sorted_metrics[-3:]:
            lines.append(
                f"- `{m.gate_id}` ({m.severity}): Δ30d = {_format_pct(m.cond_mean_diff.get(30))}, "
                f"fire/not = {m.fire_count}/{m.not_fire_count}"
            )
        lines.append("")

    # Methodology note
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Snapshot**: monthly end, {} snapshots over 5Y (us_core top-10 momentum)".format(len(snapshots)))
    lines.append("- **Portfolio**: equal-weight 10 positions (10% each)")
    lines.append("- **Forward NAV**: fixed horizon 30/60/90d, equal-weight average forward return")
    lines.append("- **Regime**: classify_regime(date=snapshot_date) — 과거 시점 snapshot")
    lines.append("- **Metric**: conditional mean diff + 95% percentile bootstrap CI (primary Q4 B)")
    lines.append("- **Caller tag**: `audit:historical` — production cert 와 분리 (V2.1 dashboard 에서 square shape)")
    lines.append("")
    lines.append("See docs/plans/e4_0b.md for full Plan doc + codex consult log.")

    output_path.write_text("\n".join(lines))
    LOG.info(f"Report written: {output_path}")


def _skip_breakdown(skipped: list[AuditSnapshot]) -> str:
    """skipped snapshots 원인 요약."""
    reasons: dict[str, int] = {}
    for s in skipped:
        key = (s.skipped_reason or "unknown").split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in reasons.items())


# ─── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE, help="universe.yaml key")
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS, help="number of monthly snapshots")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="momentum top-N positions per snapshot")
    parser.add_argument("--bootstrap-iter", type=int, default=5000, help="bootstrap iterations for CI")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--save", action="store_true", help="persist audit rows to certifications")
    grp.add_argument("--dry-run", action="store_true",
                     help="no DB write (default when --save not given)")
    args = parser.parse_args()

    # 기본은 dry-run. --save 가 명시되면 실제 persist.
    save = bool(args.save) and not bool(args.dry_run)

    LOG.info("═" * 60)
    LOG.info("  E4-0b SIEGE Historical Predictivity Audit")
    LOG.info("═" * 60)
    snapshots = run_audit(
        universe_key=args.universe, months=args.months,
        top_n=args.top_n, save=save,
    )

    metrics = analyze_predictivity(snapshots, n_iter=args.bootstrap_iter)

    output_dir = Path("data/reports") / today_kst()
    output_path = output_dir / "e4_0b_siege_predictivity.md"
    write_report(snapshots, metrics, output_path)

    # Console summary
    print()
    print("═" * 60)
    print(f"  Audit complete — {len([s for s in snapshots if s.cert])} valid snapshots")
    print(f"  Report: {output_path}")
    if save:
        print(f"  DB: {len([s for s in snapshots if s.cert])} audit:historical rows persisted")
    else:
        print("  DB: dry-run (no rows persisted — use --save to persist)")
    print("═" * 60)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
