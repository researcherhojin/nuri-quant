#!/usr/bin/env python3
"""E4-0b v2 — SIEGE **snapshot-native portfolio-rule gate** predictivity audit.

**Scope (codex Plan consult, 2026-04-22)**: "SIEGE 전체 predictivity 측정" 이 아닌
**§3.7 hypothesis 중 REBALANCE/downside-structure subset 수치화**.

v1 (#417) failure mode — 48 rows Δ 전부 null:
1. Portfolio construction invariance — 모든 snapshot 이 us_core top-10 momentum × equal-weight 10% +
   `pnl_pct=0` → position_limit/leverage/stop/conflict 0 fire
2. Historical-date audit bias — `_age_hours()` 가 `kst_now()` 기준 → freshness/external/drift 47/0 fire
3. Sector concentration invariance — top-10 momentum 이 항상 tech 밀집

v2 methodology:
- **Variant ladder (Q1-A2)**: 월별 5 template × 60 months = 300 snapshots.
  Templates: momentum_top10 / equal_weight_sample / sector_tilted_tech /
  leverage_included / concentrated_top5.
  Construction-by-design 으로 각 gate 에 fire/not-fire 양쪽 sample 확보.
- **Gate eligibility matrix (codex Biggest Risk fix)**: 3 category tag —
  - `auditable_now` (snapshot-native): `position_limit`, `sector_limit`, `leverage_ban`.
  - `audit_incoherent` (current DB state 의존): `data_fresh_*`, `external_data_*`,
    `drift_safe`, `volatility_gate_*`, `macro_event_alignment`, `conflict_free`.
  - `requires_replayed_state`: `stop_loss` (synthetic pnl=0), `rules_loaded` (메타).
  측정은 `auditable_now` 3 gate 에만. report 에 matrix 명시 → §3.8 "11 gate 전부 실측"
  오해 차단.
- **Hybrid metrics (Q2-B3)**: Binary Δ primary (fired − not_fired mean fwd return + 95% CI) +
  continuous severity slope secondary. Severity = gate 별 수치 magnitude (e.g., sector 초과 pp).
- **Acceptance (codex correction from Q5)**: `Δ = fired − not_fired` 이므로 downside
  predictivity = CI 전체가 0 아래. `CI_upper < 0` (NOT `CI_lower < 0`).
  - Primary keep: 30d `CI_high < 0` AND 60d point estimate < 0
  - Strong keep: 30d + 60d 모두 `CI_high < 0`
  - Continuous severity slope 는 보조 증거 (direction consistent 시 confidence 상승).

Usage:
    .venv/bin/python scripts/siege_predictivity_audit.py [--universe us_core | --months 60]
                                                         [--bootstrap-iter 5000]
                                                         [--save | --dry-run]

기본값 dry-run — 실 certifications 에 persist 안 함. `--save` 로 audit rows 기록.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


def _deterministic_seed(*parts: str) -> int:
    """SHA-256 기반 deterministic seed (numpy Generator 용, 0 ~ 2^32-1 range).

    Python built-in `hash()` 는 PYTHONHASHSEED 따라 process-randomized — 동일
    `(date, variant)` 가 run 마다 다른 결과 생성. Audit reproducibility 위배
    (codex Round 1 finding). `hashlib.sha256` 은 identical input → identical
    output 보장.
    """
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    # 앞 4 bytes → unsigned int32 (numpy Generator seed range)
    return int.from_bytes(digest[:4], byteorder="big")

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

# Gate eligibility matrix (codex Plan consult Biggest Risk fix)
# audit report 에 명시해 §3.8 "11 gate 전부 실측" 오해 차단.
# - auditable_now: snapshot-native, portfolio-rule gates — 이번 audit 측정 대상
# - audit_incoherent: current-DB 의존 — snapshot 시점 coherence 없음, 측정 skip
# - requires_replayed_state: historical pnl/metadata — 데이터 부재로 측정 불가
GATE_ELIGIBILITY: dict[str, str] = {
    "position_limit": "auditable_now",
    "sector_limit": "auditable_now",
    "leverage_ban": "auditable_now",
    # Current DB state-dependent → audit_incoherent
    "data_fresh_us_equity": "audit_incoherent",
    "data_fresh_kr_equity": "audit_incoherent",
    "data_fresh_commodity": "audit_incoherent",
    "data_fresh_bond": "audit_incoherent",
    "data_fresh_kr_index": "audit_incoherent",
    "external_data_us_equity": "audit_incoherent",
    "external_data_kr_equity": "audit_incoherent",
    "external_data_commodity": "audit_incoherent",
    "external_data_bond": "audit_incoherent",
    "external_data_kr_index": "audit_incoherent",
    "volatility_gate_us_equity": "audit_incoherent",
    "volatility_gate_kr_equity": "audit_incoherent",
    "volatility_gate_commodity": "audit_incoherent",
    "volatility_gate_bond": "audit_incoherent",
    "volatility_gate_kr_index": "audit_incoherent",
    "drift_safe": "audit_incoherent",
    "conflict_free": "audit_incoherent",
    # Requires historical portfolio state / metadata / replay wiring
    # codex Round 1 reclassification: macro_event_alignment 는 compute_event_score(date=...)
    # 가 이미 date-parametric → replayable-but-unwired. 현재 audit 인프라가 snapshot_date
    # 를 event_score 에 전달하지 않아 audit_incoherent 로 작동하지만, 본질은 replayable.
    "macro_event_alignment": "requires_replayed_state",
    "stop_loss": "requires_replayed_state",
    "rules_loaded": "requires_replayed_state",
}

# Variants — Q1-A2 template ladder. 각 month 에 이 5 template 모두 실행.
# Template 은 universe + construction rule 조합. 월별 ticker sampling 은 determinism
# 유지 위해 snapshot_date + template_name seed (codex suggestion: hand-craft bias 회피).
VARIANT_TEMPLATES: list[str] = [
    "momentum_top10",       # 기존 behavior — top-10 momentum × equal 10%
    "equal_weight_sample",  # random 10 tickers × equal 10% (baseline variance)
    "sector_concentrated",  # largest-sector 10 tickers (sector_limit 100% fire 유발)
    "concentrated_top5",    # top-5 momentum × equal 20% (position_limit fire 유발)
]
# NOTE (codex Plan consult caveat): `leverage_included` variant 는 production DB
# 에 TQQQ/UPRO prices 0 rows 로 skip. leveraged ETF price backfill (별도 PR)
# 후 재활성화 — 현재 `leverage_ban` gate 는 non-fire sample 만 (0/N) 제공.
# sector_tilted_tech (top-3 sector 3-4 pick) 는 us_core 의 sector coverage 희박
# (26/30 Unknown) 로 실패. sector_concentrated (single largest sector 10) 가
# 같은 목적 (sector_limit fire 유발) 을 robust 하게 달성.


@dataclass
class AuditSnapshot:
    """Single (date × variant) snapshot — portfolio + forward NAV measurement."""

    snapshot_date: str  # "YYYY-MM-DD"
    tickers: list[str]
    cert: dict | None  # Certificate dict (from certify() output)
    regime: str | None
    forward_nav: dict[int, float | None]  # horizon → portfolio-level forward return %
    forward_mae: dict[int, float | None]  # horizon → max adverse excursion %
    # v2 additions (default for back-compat with existing tests)
    variant: str = "momentum_top10"
    weights_pct: list[float] = field(default_factory=list)
    # Gate severity — continuous magnitude (Q2-B3 secondary metric)
    # e.g., "sector_limit": max_sector_pct - 35%; "position_limit": max_pos_pct - 15%
    gate_severity: dict[str, float | None] = field(default_factory=dict)
    skipped_reason: str | None = None  # None if snapshot constructed, else reason


@dataclass
class GateMetric:
    """Per-gate predictivity metric — binary Δ primary + continuous slope secondary."""

    gate_id: str
    severity: str  # "error" | "warning"
    eligibility: str = "auditable_now"  # auditable_now / audit_incoherent / requires_replayed_state
    fire_count: int = 0
    not_fire_count: int = 0
    # conditional means at each horizon (fwd return | gate fired vs not fired)
    mean_when_fired: dict[int, float | None] = field(default_factory=dict)
    mean_when_not_fired: dict[int, float | None] = field(default_factory=dict)
    # Primary: mean_fired - mean_not_fired + 95% CI (binary)
    cond_mean_diff: dict[int, float | None] = field(default_factory=dict)
    ci_low: dict[int, float | None] = field(default_factory=dict)
    ci_high: dict[int, float | None] = field(default_factory=dict)
    # Secondary (Q2-B3 continuous severity): slope of fwd_return on severity magnitude
    severity_slope: dict[int, float | None] = field(default_factory=dict)
    severity_slope_ci_low: dict[int, float | None] = field(default_factory=dict)
    severity_slope_ci_high: dict[int, float | None] = field(default_factory=dict)
    # Acceptance flag — codex criteria (CI_upper < 0 at 30d AND point estimate < 0 at 60d)
    primary_keep: bool = False
    strong_keep: bool = False  # 30d + 60d 모두 CI_upper < 0


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


# ─── variant construction (Q1-A2 template ladder) ──────────────────────────


# Leverage ETFs — config/rules.yaml leverage.banned_etfs 와 parity. `leverage_ban`
# gate fire 유도용. Audit 목적으로만 synthetic portfolio 에 포함.
_LEVERAGE_ETFS_FOR_AUDIT = ["TQQQ", "UPRO"]


def _ticker_sector(ticker: str, db_path=None) -> str:
    """Ticker 의 최근 known sector. `portfolio` 테이블만 sector column 보유."""
    row = query(
        "SELECT DISTINCT sector FROM portfolio WHERE ticker=? AND sector IS NOT NULL LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    return row[0]["sector"] if row else "Unknown"


def build_variant(
    variant: str, universe: list[str], as_of_date: str, db_path=None,
    momentum_n: int = DEFAULT_TOP_N,
) -> tuple[list[str], list[float]] | None:
    """Variant template → (tickers, weights_pct). None if 구성 실패.

    Codex suggestion: deterministic seeding per (date × variant) — hand-craft
    bias 회피하면서 reproducible. Template 별 constraint 안에서 universe sample.

    `momentum_n` 은 test 용 override (default 10 — production). Small universe
    test 에선 `momentum_n=2` 같은 축소값 사용 가능.
    """
    # codex Round 1 fix: Python hash() → hashlib.sha256 based (PYTHONHASHSEED independent)
    rng = np.random.default_rng(_deterministic_seed(as_of_date, variant))

    if variant == "momentum_top10":
        tickers = top_n_momentum(universe, as_of_date, n=momentum_n, db_path=db_path)
        if len(tickers) < momentum_n:
            return None
        w = 100.0 / momentum_n
        return tickers, [w] * momentum_n

    if variant == "equal_weight_sample":
        # 252d coverage 있는 ticker 중 random 10
        eligible = [t for t in universe
                    if len(query_df(
                        "SELECT date FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT ?",
                        (t, as_of_date, MOMENTUM_LOOKBACK), db_path=db_path,
                    )) >= MOMENTUM_LOOKBACK]
        if len(eligible) < 10:
            return None
        picks = rng.choice(eligible, size=10, replace=False).tolist()
        return sorted(picks), [10.0] * 10

    if variant == "sector_concentrated":
        # Largest **real** sector 에서 10 tickers → sector_limit 35% cap 확실히 fire.
        # codex Round 1 fix: "Unknown" sector (portfolio.yaml tag 부재) 는 pool 에서
        # 제외 — 그렇지 않으면 "largest tag bucket" 이 실제로 "sector concentration"
        # 이 아닌 "tag-missing bucket" 이 될 수 있음 (construct validity 손상).
        top_mom = top_n_momentum(universe, as_of_date, n=50, db_path=db_path)
        if len(top_mom) < 10:
            return None
        by_sector: dict[str, list[str]] = {}
        for t in top_mom:
            s = _ticker_sector(t, db_path=db_path)
            if s == "Unknown":
                continue  # tag 없는 ticker 는 sector concentration 구성에서 제외
            by_sector.setdefault(s, []).append(t)
        if not by_sector:
            return None  # 모든 top momentum 이 Unknown — variant 구성 불가
        largest = max(by_sector, key=lambda s: len(by_sector[s]))
        tickers = by_sector[largest][:10]
        if len(tickers) < 10:
            return None  # real sector 에서 10 tickers 못 채움
        return tickers, [10.0] * 10

    if variant == "concentrated_top5":
        # top-5 momentum × 20% → position_limit (15% cap) fire 유도
        tickers = top_n_momentum(universe, as_of_date, n=5, db_path=db_path)
        if len(tickers) < 5:
            return None
        return tickers, [20.0] * 5

    raise ValueError(f"unknown variant: {variant}")


def synthesize_portfolio_df_v2(
    tickers: list[str], weights_pct: list[float], as_of_date: str, db_path=None,
) -> pd.DataFrame | None:
    """v2 variant 용 synthesize — weight 리스트 지원.

    v1 의 `synthesize_portfolio_df` 는 equal-weight 가정. v2 에선 concentrated_top5 가
    20% × 5 같은 non-equal weight 필요.
    """
    if len(tickers) != len(weights_pct):
        raise ValueError(f"len mismatch: {len(tickers)} vs {len(weights_pct)}")
    rows = []
    for ticker, weight_pct in zip(tickers, weights_pct):
        price_row = query(
            "SELECT close, date FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
            (ticker, as_of_date), db_path=db_path,
        )
        if not price_row:
            return None
        close = price_row[0]["close"]
        sector = _ticker_sector(ticker, db_path=db_path)
        # synthetic NAV: weight 100$ portfolio → ticker 에 weight_pct 달러만큼 배정
        ticker_value = weight_pct  # 총 100$ 기준
        quantity = ticker_value / close if close > 0 else 0
        rows.append({
            "account": "audit",
            "ticker": ticker,
            "sector": sector,
            "quantity": quantity,
            "avg_price": close,
            "current_price": close,
            "currency": "USD",
            "current_value_usd": round(ticker_value, 2),
            "cost_basis_usd": round(ticker_value, 2),
            "pnl_usd": 0.0,
            "pnl_pct": 0.0,
            "price_date": price_row[0]["date"],
            "weight_pct": round(weight_pct, 2),
        })
    df = pd.DataFrame(rows)
    total = df["current_value_usd"].sum() or 1
    df.attrs["warnings"] = []
    df.attrs["total_value_usd"] = round(total, 2)
    df.attrs["usd_krw"] = 1380.0
    return df


def extract_gate_severity(df: pd.DataFrame) -> dict[str, float | None]:
    """3 auditable_now gate 에 대해 continuous severity (Q2-B3 secondary).

    - position_limit: max(weight_pct) - 15 (core per_position_max). + 는 over.
    - sector_limit: max(sector_sum_pct) - 35. + 는 over.
    - leverage_ban: sum(weight_pct | ticker in leverage_etfs). 0 이면 safe.
    """
    from nuri.core.rules import LEVERAGE_ETFS

    sev: dict[str, float | None] = {}
    if df is None or df.empty:
        return {k: None for k in ("position_limit", "sector_limit", "leverage_ban")}
    # per_position_max 기본은 core 전략의 15% (config/rules.yaml account_strategies.core)
    max_weight = df["weight_pct"].max()
    sev["position_limit"] = float(max_weight) - 15.0
    sector_sum = df.groupby("sector")["weight_pct"].sum()
    sev["sector_limit"] = float(sector_sum.max()) - 35.0
    leverage_weight = df[df["ticker"].isin(LEVERAGE_ETFS)]["weight_pct"].sum()
    sev["leverage_ban"] = float(leverage_weight)
    return sev


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


def forward_portfolio_nav_weighted(
    tickers: list[str], weights_pct: list[float], entry_date: str,
    horizon: int, db_path=None,
) -> tuple[float | None, float | None]:
    """Weighted portfolio-level forward return % + MAE %.

    각 ticker 의 forward N-day return 을 weight 로 가중 평균. weights_pct 합이
    100 미만이면 cash 잔여 (return 0 기여).
    """
    if len(tickers) != len(weights_pct):
        return None, None
    weighted_ret: float = 0.0
    weighted_mae: float = 0.0
    total_weight: float = 0.0
    for ticker, w in zip(tickers, weights_pct):
        rows = query(
            "SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date LIMIT ?",
            (ticker, entry_date, horizon + 1), db_path=db_path,
        )
        if len(rows) < horizon + 1:
            return None, None
        entry_close = rows[0]["close"]
        exit_close = rows[horizon]["close"]
        ret = (exit_close - entry_close) / entry_close * 100
        intra_lows = [r["close"] for r in rows[1:horizon + 1]]
        mae = (min(intra_lows) - entry_close) / entry_close * 100 if intra_lows else 0.0
        weighted_ret += w * ret
        weighted_mae += w * mae
        total_weight += w
    if total_weight == 0:
        return None, None
    # Normalize by 100 (weights are pct, so portfolio-level return)
    return weighted_ret / 100, weighted_mae / 100


def forward_portfolio_nav(
    tickers: list[str], entry_date: str, horizon: int, db_path=None
) -> tuple[float | None, float | None]:
    """Equal-weight portfolio-level forward return % + MAE % (v1 signature retain).

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


def _fixed_timestamp(snapshot_date: str, variant: str = "momentum_top10") -> str:
    """Idempotency key — variant 별로 분리된 second offset.

    v1 에선 `YYYY-MM-DDT00:00:00+09:00` 단일. v2 는 5 variant × month 라 각
    variant 가 own timestamp 필요 (같은 date 에 5 row). Variant 를 minute offset
    으로 encoding — deterministic.
    """
    minute_offset = VARIANT_TEMPLATES.index(variant) if variant in VARIANT_TEMPLATES else 0
    return f"{snapshot_date}T00:{minute_offset:02d}:00+09:00"


def _already_audited(snapshot_date: str, variant: str = "momentum_top10", db_path=None) -> bool:
    """이미 같은 (snapshot_date × variant) audit:historical row 있으면 True."""
    rows = query(
        "SELECT COUNT(*) c FROM certifications WHERE timestamp = ? AND caller = 'audit:historical'",
        (_fixed_timestamp(snapshot_date, variant),),
        db_path=db_path,
    )
    return rows[0]["c"] > 0


def _build_snapshot_for_variant(
    variant: str, universe: list[str], snapshot_date: str, db_path=None,
    momentum_n: int = DEFAULT_TOP_N,
) -> tuple[CertSnapshot, pd.DataFrame, list[str], list[float]] | tuple[None, None, None, None]:
    """Variant 1 개 snapshot 조립 — (CertSnapshot, df, tickers, weights) or (None, ...)."""
    built = build_variant(variant, universe, snapshot_date, db_path=db_path, momentum_n=momentum_n)
    if built is None:
        return None, None, None, None
    tickers, weights = built

    state = classify_regime(date=snapshot_date)
    if state is None:
        return None, None, None, None

    df = synthesize_portfolio_df_v2(tickers, weights, snapshot_date, db_path=db_path)
    if df is None or df.empty:
        return None, None, None, None

    raw = [
        {"account": r["account"], "ticker": r["ticker"], "sector": r["sector"],
         "quantity": r["quantity"], "avg_price": r["avg_price"]}
        for r in df.to_dict(orient="records")
    ]
    snap = CertSnapshot(
        regime=state.regime,
        portfolio_raw=raw,
        portfolio_df=df,
        portfolio_hash=_compute_portfolio_hash(rows=raw),
        portfolio_error=None,
    )
    return snap, df, tickers, weights


def run_audit(
    universe_key: str,
    months: int,
    top_n: int,  # kept for backward-compat (used only in momentum_top10 default)
    save: bool,
    db_path=None,
    variants: list[str] | None = None,
) -> list[AuditSnapshot]:
    """Main loop — 월 × variant cross product snapshot + certify + forward NAV.

    v2 (codex Plan consult 2026-04-22): variant ladder 추가 — 월 1 → 월 5 variants.
    Audit 측정은 `auditable_now` 3 gate 에만 (gate eligibility matrix).
    """
    universe = _load_universe(universe_key)
    end_date = today_kst()
    dates = monthly_snapshot_dates(end_date, months)
    vs = variants or VARIANT_TEMPLATES
    LOG.info(f"Universe: {universe_key} ({len(universe)} tickers), months: {months}, "
             f"variants: {len(vs)}, save: {save}")
    LOG.info(f"Snapshot dates: {dates[0]} → {dates[-1]} ({len(dates)} total × "
             f"{len(vs)} variants = {len(dates) * len(vs)} snapshots)")

    results: list[AuditSnapshot] = []
    for snapshot_date in dates:
        for variant in vs:
            if save and _already_audited(snapshot_date, variant, db_path=db_path):
                LOG.info(f"  {snapshot_date} [{variant}]: 이미 audit 완료 (skip, idempotent)")
                continue

            snap, df, tickers, weights = _build_snapshot_for_variant(
                variant, universe, snapshot_date, db_path=db_path,
                momentum_n=top_n,
            )
            if snap is None:
                results.append(AuditSnapshot(
                    snapshot_date=snapshot_date, variant=variant,
                    tickers=[], weights_pct=[],
                    cert=None, regime=None,
                    forward_nav={h: None for h in HORIZONS},
                    forward_mae={h: None for h in HORIZONS},
                    skipped_reason=f"{variant} build failed (momentum/regime/price insufficient)",
                ))
                continue

            try:
                cert = certify(
                    db_path=db_path, persist=save,
                    caller="audit:historical", snapshot=snap,
                    timestamp=_fixed_timestamp(snapshot_date, variant),
                )
            except Exception as e:
                LOG.warning(f"  {snapshot_date} [{variant}]: certify 실패 — {e}")
                results.append(AuditSnapshot(
                    snapshot_date=snapshot_date, variant=variant,
                    tickers=tickers or [], weights_pct=weights or [],
                    cert=None, regime=snap.regime,
                    forward_nav={h: None for h in HORIZONS},
                    forward_mae={h: None for h in HORIZONS},
                    skipped_reason=f"certify raise: {type(e).__name__}",
                ))
                continue

            # snap not None → _build_snapshot_for_variant success branch,
            # 즉 tickers/weights/df 도 not None (Pylance narrowing assist)
            assert tickers is not None and weights is not None and df is not None

            forward_nav: dict[int, float | None] = {}
            forward_mae: dict[int, float | None] = {}
            for h in HORIZONS:
                # Weighted forward return — weight_pct 사용 (non-equal variants 지원)
                ret, mae = forward_portfolio_nav_weighted(
                    tickers, weights, snapshot_date, h, db_path=db_path,
                )
                forward_nav[h] = ret
                forward_mae[h] = mae

            cert_dict = {
                "timestamp": cert.timestamp,
                "certified": cert.certified,
                "score": cert.score,
                "total_conditions": cert.total_conditions,
                "passed": cert.passed, "failed": cert.failed,
                "warnings": cert.warnings,
                "conditions": [
                    {"id": c.id, "passed": c.passed, "severity": c.severity}
                    for c in cert.conditions
                ],
            }
            severity = extract_gate_severity(df)
            results.append(AuditSnapshot(
                snapshot_date=snapshot_date, variant=variant,
                tickers=tickers, weights_pct=weights,
                cert=cert_dict, regime=snap.regime,
                forward_nav=forward_nav, forward_mae=forward_mae,
                gate_severity=severity,
            ))

    valid = len([r for r in results if r.cert])
    skipped = len([r for r in results if r.skipped_reason])
    LOG.info(f"  collected {valid} snapshots (skipped: {skipped})")
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


def _bootstrap_slope_ci(
    x: list[float], y: list[float], n_iter: int = 5000,
    conf_level: float = 0.95, seed: int = 42,
) -> tuple[float, float, float]:
    """OLS slope + percentile bootstrap CI on (x, y) pairs. (slope, lo, hi).

    x = severity, y = forward_return. 쌍 (x_i, y_i) 를 joint bootstrap.
    """
    if len(x) < 3 or len(x) != len(y):
        return float("nan"), float("nan"), float("nan")
    xa = np.array(x, dtype=float)
    ya = np.array(y, dtype=float)
    # Point estimate
    if xa.std() == 0:
        return float("nan"), float("nan"), float("nan")
    slope = float(np.polyfit(xa, ya, 1)[0])
    rng = np.random.default_rng(seed)
    slopes = np.empty(n_iter)
    n = len(xa)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        bxa = xa[idx]
        bya = ya[idx]
        if bxa.std() == 0:
            slopes[i] = float("nan")
        else:
            slopes[i] = np.polyfit(bxa, bya, 1)[0]
    slopes = slopes[~np.isnan(slopes)]
    if len(slopes) < 10:
        return slope, float("nan"), float("nan")
    alpha = (1 - conf_level) / 2
    lo, hi = np.percentile(slopes, [alpha * 100, (1 - alpha) * 100])
    return slope, float(lo), float(hi)


def analyze_predictivity(
    snapshots: list[AuditSnapshot], n_iter: int = 5000,
) -> list[GateMetric]:
    """Per-gate predictivity — binary Δ primary + continuous severity slope secondary.

    Codex Plan consult acceptance (2026-04-22):
    - Primary keep: 30d `CI_high < 0` AND 60d point estimate < 0
    - Strong keep: 30d AND 60d 모두 `CI_high < 0`
    - Continuous slope: 보조 증거 (direction consistent 시 confidence ↑)

    `audit_incoherent` / `requires_replayed_state` gate 는 metric 생성하되 결과 포함.
    `eligibility` 필드로 report 에서 구분 — codex Biggest Risk fix (§3.8 오해 차단).
    """
    valid = [s for s in snapshots if s.cert is not None]
    if not valid:
        return []

    gates: dict[tuple[str, str], GateMetric] = {}
    for s in valid:
        assert s.cert is not None
        for cond in s.cert["conditions"]:
            key = (cond["id"], cond["severity"])
            if key not in gates:
                eligibility = GATE_ELIGIBILITY.get(cond["id"], "audit_incoherent")
                gates[key] = GateMetric(
                    gate_id=cond["id"], severity=cond["severity"],
                    eligibility=eligibility,
                )

    for (gate_id, severity_level), metric in gates.items():
        fired_per_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
        not_fired_per_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
        # Continuous severity pairs: (severity_magnitude, fwd_return)
        severity_pairs: dict[int, list[tuple[float, float]]] = {h: [] for h in HORIZONS}

        for s in valid:
            assert s.cert is not None
            cond_found = None
            for c in s.cert["conditions"]:
                if c["id"] == gate_id and c["severity"] == severity_level:
                    cond_found = c
                    break
            if cond_found is None:
                continue
            for h in HORIZONS:
                ret = s.forward_nav.get(h)
                if ret is None:
                    continue
                if cond_found["passed"]:
                    not_fired_per_h[h].append(ret)
                else:
                    fired_per_h[h].append(ret)
                # Continuous severity — 3 auditable gate 에 대해서만
                sev_val = s.gate_severity.get(gate_id)
                if sev_val is not None:
                    severity_pairs[h].append((sev_val, ret))

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
            else:
                metric.cond_mean_diff[h] = None
                metric.ci_low[h] = None
                metric.ci_high[h] = None

            # Continuous severity slope (auditable gates only)
            pairs = severity_pairs[h]
            if metric.eligibility == "auditable_now" and len(pairs) >= 3:
                xs = [p[0] for p in pairs]
                ys = [p[1] for p in pairs]
                slope, s_lo, s_hi = _bootstrap_slope_ci(xs, ys, n_iter=n_iter)
                metric.severity_slope[h] = round(slope, 4) if not np.isnan(slope) else None
                metric.severity_slope_ci_low[h] = round(s_lo, 4) if not np.isnan(s_lo) else None
                metric.severity_slope_ci_high[h] = round(s_hi, 4) if not np.isnan(s_hi) else None
            else:
                metric.severity_slope[h] = None
                metric.severity_slope_ci_low[h] = None
                metric.severity_slope_ci_high[h] = None

        # Acceptance — only for auditable_now gates (incoherent 는 의미 없음)
        if metric.eligibility == "auditable_now":
            ci_high_30 = metric.ci_high.get(30)
            ci_high_60 = metric.ci_high.get(60)
            point_60 = metric.cond_mean_diff.get(60)
            metric.primary_keep = bool(
                ci_high_30 is not None and ci_high_30 < 0
                and point_60 is not None and point_60 < 0
            )
            metric.strong_keep = bool(
                ci_high_30 is not None and ci_high_30 < 0
                and ci_high_60 is not None and ci_high_60 < 0
            )

    return list(gates.values())


# ─── report output ──────────────────────────────────────────────────────────


def _format_pct(v: float | None, digits: int = 2) -> str:
    return f"{v:+.{digits}f}%" if v is not None else "—"


def write_report(
    snapshots: list[AuditSnapshot],
    metrics: list[GateMetric],
    output_path: Path,
) -> None:
    """v2 markdown report — gate eligibility matrix + auditable gates primary + appendix."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    valid = [s for s in snapshots if s.cert is not None]
    skipped = [s for s in snapshots if s.skipped_reason]
    variant_counts: dict[str, int] = {}
    for s in valid:
        variant_counts[s.variant] = variant_counts.get(s.variant, 0) + 1

    lines: list[str] = []
    lines.append("# E4-0b v2 — SIEGE Snapshot-Native Gate Predictivity Audit")
    lines.append("")
    lines.append(f"Generated: {today_kst()} KST")
    lines.append("")
    lines.append("**Scope**: \"SIEGE 전체 predictivity 측정\" 이 아닌 **§3.7 hypothesis 중 "
                 "REBALANCE/downside-structure subset 수치화** (codex Plan consult 2026-04-22).")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total snapshots attempted: **{len(snapshots)}**")
    lines.append(f"- Valid (cert + NAV): **{len(valid)}**")
    lines.append(f"- Skipped: **{len(skipped)}** ({_skip_breakdown(skipped)})")
    if valid:
        certified_n = sum(1 for s in valid if s.cert and s.cert["certified"])
        lines.append(f"- CERTIFIED rate: **{certified_n}/{len(valid)} = {certified_n/len(valid)*100:.1f}%**")
    if variant_counts:
        lines.append("- Variants:")
        for v, n in sorted(variant_counts.items()):
            lines.append(f"  - `{v}`: {n}")
    lines.append("")

    # Gate eligibility matrix (codex Biggest Risk)
    lines.append("## Gate eligibility matrix")
    lines.append("")
    lines.append("§3.8 읽을 때 \"11 gate 전부 실측\" 으로 오해하지 않도록 각 gate 를 "
                 "분류. 측정 대상은 `auditable_now` 3 gate 만.")
    lines.append("")
    lines.append("| Category | Gates | Rationale |")
    lines.append("|---|---|---|")
    by_elig: dict[str, list[str]] = {}
    for m in metrics:
        by_elig.setdefault(m.eligibility, []).append(m.gate_id)
    categories = [
        ("auditable_now",
         "snapshot-native portfolio-rule gates — 이번 audit 측정 대상"),
        ("audit_incoherent",
         "current DB state 의존 (freshness/external/volatility/macro/drift/conflict) — snapshot 시점 coherence 없음, 측정 skip"),
        ("requires_replayed_state",
         "historical portfolio pnl/metadata 필요 — 데이터 부재로 측정 불가"),
    ]
    for cat, desc in categories:
        gates = sorted(set(by_elig.get(cat, [])))
        lines.append(f"| `{cat}` | {', '.join(f'`{g}`' for g in gates) or '—'} | {desc} |")
    lines.append("")

    # Primary — auditable gates 만
    auditable = [m for m in metrics if m.eligibility == "auditable_now"]
    incoherent = [m for m in metrics if m.eligibility == "audit_incoherent"]
    replayed = [m for m in metrics if m.eligibility == "requires_replayed_state"]

    lines.append("## Auditable gates — Primary predictivity (binary Δ + 95% CI)")
    lines.append("")
    lines.append("| Gate | Sev | Fire | Not-fire | Δ30d | CI30d | Δ60d | CI60d | Δ90d | CI90d | Keep |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for m in sorted(auditable, key=lambda x: (x.cond_mean_diff.get(30) or float("inf"))):
        def _ci(h):
            lo = m.ci_low.get(h)
            hi = m.ci_high.get(h)
            if lo is None or hi is None:
                return "—"
            return f"[{_format_pct(lo)}, {_format_pct(hi)}]"
        flag = "⭐ strong" if m.strong_keep else ("✓ primary" if m.primary_keep else "—")
        lines.append(
            f"| `{m.gate_id}` | {m.severity} | {m.fire_count} | {m.not_fire_count} | "
            f"{_format_pct(m.cond_mean_diff.get(30))} | {_ci(30)} | "
            f"{_format_pct(m.cond_mean_diff.get(60))} | {_ci(60)} | "
            f"{_format_pct(m.cond_mean_diff.get(90))} | {_ci(90)} | {flag} |"
        )
    lines.append("")
    lines.append("**해석** (codex Plan consult acceptance):")
    lines.append("- Δ = mean(fwd_return | fired) − mean(fwd_return | not fired). downside "
                 "predictivity = CI 전체가 0 아래 (`CI_upper < 0`).")
    lines.append("- `✓ primary`: 30d `CI_upper < 0` AND 60d point estimate < 0")
    lines.append("- `⭐ strong`: 30d + 60d 모두 `CI_upper < 0`")
    lines.append("")

    # Continuous severity secondary
    lines.append("## Auditable gates — Continuous severity slope (secondary)")
    lines.append("")
    lines.append("Binary 경계 대신 severity magnitude 에 따른 forward_return 의 OLS slope.")
    lines.append("음수 slope 이면 severity 클수록 forward return 저조 — binary 결과와 "
                 "direction 일치 시 confidence 상승.")
    lines.append("")
    lines.append("| Gate | 30d slope | CI30d | 60d slope | CI60d | 90d slope | CI90d |")
    lines.append("|---|---|---|---|---|---|---|")
    for m in sorted(auditable, key=lambda x: x.gate_id):
        def _sci(h):
            lo = m.severity_slope_ci_low.get(h)
            hi = m.severity_slope_ci_high.get(h)
            if lo is None or hi is None:
                return "—"
            return f"[{lo:+.4f}, {hi:+.4f}]"
        def _sl(h):
            v = m.severity_slope.get(h)
            return f"{v:+.4f}" if v is not None else "—"
        lines.append(
            f"| `{m.gate_id}` | {_sl(30)} | {_sci(30)} | "
            f"{_sl(60)} | {_sci(60)} | {_sl(90)} | {_sci(90)} |"
        )
    lines.append("")

    # Appendix — non-auditable
    if incoherent or replayed:
        lines.append("## Appendix — Non-auditable gates (eligibility constraint)")
        lines.append("")
        lines.append("아래 gate 는 현재 audit infrastructure 로 snapshot-time coherent 측정 "
                     "불가 — 집계 값은 참고용이지 predictivity 증거로 사용 금지.")
        lines.append("")
        lines.append("| Gate | Eligibility | Fire | Not-fire | 비고 |")
        lines.append("|---|---|---|---|---|")
        for m in sorted(incoherent + replayed, key=lambda x: x.gate_id):
            note = {
                "audit_incoherent": "kst_now() 기준 평가 → snapshot 시점 무관",
                "requires_replayed_state": "synthetic portfolio 에 historical pnl/meta 부재",
            }[m.eligibility]
            lines.append(
                f"| `{m.gate_id}` | {m.eligibility} | {m.fire_count} | {m.not_fire_count} | {note} |"
            )
        lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append(f"- **Variant ladder** (Q1-A2): {len(VARIANT_TEMPLATES)} templates × N months.")
    lines.append("  - `momentum_top10`: baseline (v1 behavior)")
    lines.append("  - `equal_weight_sample`: 10 random tickers × 10% (baseline variance)")
    lines.append("  - `sector_concentrated`: largest-sector 10 tickers (sector_limit fire 유도)")
    lines.append("  - `concentrated_top5`: top-5 × 20% (position_limit fire 유도)")
    lines.append("- **Variant 제거 (known limitation)**: `leverage_included` — production DB 에 "
                 "TQQQ/UPRO prices 0 rows, leveraged ETF backfill 이후 재활성화 예정. "
                 "`leverage_ban` gate 는 현재 non-fire sample 만 확보 (0/N).")
    lines.append("- **Forward NAV**: weighted (per-variant weights) forward return at 30/60/90d + MAE")
    lines.append("- **Regime**: classify_regime(date=snapshot_date) — historical")
    lines.append("- **Primary metric**: binary Δ + 95% percentile bootstrap CI")
    lines.append("- **Secondary**: continuous severity OLS slope + bootstrap CI (auditable gates only)")
    lines.append("- **Caller tag**: `audit:historical` (V2.1 dashboard square shape)")
    lines.append("")
    lines.append("**Synthetic portfolio caveat**: variant ladder 는 hand-crafted construction "
                 "이며 실제 사용자 portfolio 분포와 직접 매핑 불가. 측정 결과는 \"이 5 template "
                 "family 내에서 gate predictivity\" 로만 해석.")
    lines.append("")
    lines.append("See `docs/plans/e4_0b.md` for Plan doc + codex consult archive.")

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


def _parse_args(argv: list[str] | None = None):
    """argparse — unit-testable. argv=None 이면 sys.argv 사용."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE, help="universe.yaml key")
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS, help="number of monthly snapshots")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="momentum top-N positions per snapshot")
    parser.add_argument("--bootstrap-iter", type=int, default=5000, help="bootstrap iterations for CI")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--save", action="store_true", help="persist audit rows to certifications")
    grp.add_argument("--dry-run", action="store_true",
                     help="no DB write (default when --save not given)")
    return parser.parse_args(argv)


def resolve_save_flag(args) -> bool:
    """mutually-exclusive group 에서 실제 save 여부 결정.

    `--save` 명시되고 `--dry-run` 아닐 때만 True. (mutually_exclusive 가
    default=True 와 상호작용 시 버그 방지용 — unit test 에서 직접 검증 가능)
    """
    return bool(args.save) and not bool(args.dry_run)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)

    # 기본은 dry-run. --save 가 명시되면 실제 persist.
    save = resolve_save_flag(args)

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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
