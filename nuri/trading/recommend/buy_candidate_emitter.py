"""BUY signal emitter — cash deploy candidate generator (Issue #507 Phase 1).

System core-purpose 결함 (sell-only) 수정. 6 개월간 SIEGE / take-profit /
stop-loss / position-limit / holdings_monitor 7+ sell-biased loops 작동했지만
buy-side candidate emitter 0. 결과: 사용자 cash idle + sell cascade =
opportunity cost 누적. 이 모듈이 매일 0-5 개 candidate emit.

Phase 1 scope (이 PR):
  - factors.composite_score + 5d momentum + RSI + 30d breakout 를 fuse
  - quality_bar threshold + regime 조정 + held/cooldown gate
  - entry/stop/TP1/TP2 derive from rules.yaml (growth ladder default)
  - allocation = regime-gated total × score_weighted split

Phase 2 (deferred): 계좌별 cash gating, USD/KRW FX, ride-winner cap loosen
Phase 3 (deferred): 10-agent consensus auto-fire, LLM why-now, backtest

Hard constraint: STRATEGY §7.1 — recommendation only, never execute.
Output 은 markdown block 또는 dataclass list — 사용자 manual buy.

Run:
  - `make buy-candidates` (CLI)
  - `python -m nuri.trading.recommend.buy_candidate_emitter`
  - `premarket_brief.py` 가 import 해서 일일 brief 에 surface
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nuri.core.db import query_df
from nuri.core.rules import VIX_BLOCK_ABOVE, VIX_CAUTION_ABOVE
from nuri.core.timezone import kst_now
from nuri.quant.factors.relative_strength import leadership_snapshot

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "buy_signals.yaml"

# 레버리지 ETF (스윙 전용, Phase 1 BUY 후보에서 제외)
LEVERAGE_ETFS = frozenset(
    {
        "SOXL",
        "SOXS",
        "TQQQ",
        "SQQQ",
        "TSLL",
        "TSLQ",
        "UPRO",
        "SPXU",
        "SOXX",
        "TNA",
        "TZA",
        "FAS",
        "FAZ",
        "LABU",
        "LABD",
    }
)


@dataclass
class BuyCandidate:
    """Single BUY recommendation — explicit entry/stop/target/allocation."""

    ticker: str
    score: float  # 0-100 fused score
    deploy_pct: float  # % of cash to allocate
    entry: float  # current close (or breakout level)
    stop: float  # entry × (1 + stop_pct/100), -7% default
    tp1: float  # entry × (1 + tp1_pct/100), +21% default
    tp2: float  # entry × (1 + tp2_pct/100), +42% default
    why_now: str  # single-sentence catalyst
    sources: dict[str, float]  # {factor: 0.78, momentum: 0.65, ...}
    sector: str | None = None


@dataclass
class EmitResult:
    """Result of one emitter run — candidates + skipped reasons + meta."""

    candidates: list[BuyCandidate] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # ticker → reason
    regime: str = ""
    vix: float = 0.0
    total_deploy_pct: float = 0.0
    blocked_reason: str | None = None  # if 0 candidates, why?
    timestamp_kst: str = ""


def _load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config/buy_signals.yaml. Path injectable for tests."""
    p = path or CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_held_tickers() -> set[str]:
    """Tickers currently in `portfolio` table — exclude from BUY emit."""
    df = query_df("SELECT DISTINCT ticker FROM portfolio")
    return {str(t) for t in df["ticker"].tolist()} if not df.empty else set()


def _get_cooldown_tickers(days: int) -> set[str]:
    """DEPRECATED — Phase 1 single-window cooldown. Use _get_cooldown_tickers_by_type (#517 Phase 2b).

    유지 이유: 호환성 (외부 caller / 테스트 fixture). 다음 세션에 제거 예정.
    """
    df = query_df(
        f"""SELECT DISTINCT
              json_extract(payload, '$.ticker') as ticker
            FROM pipeline_events
            WHERE event_type IN ('holdings_monitor_alert', 'take_profit_trigger', 'trim_recommendation')
              AND timestamp >= datetime('now', '-{days} days')
              AND json_extract(payload, '$.ticker') IS NOT NULL"""
    )
    return {str(t) for t in df["ticker"].dropna().tolist()} if not df.empty else set()


def _get_cooldown_tickers_by_type(cooldown_cfg: dict) -> set[str]:
    """#517 Phase 2b — Type-aware cooldown.

    payload.action_type ∈ {hard_sell, trim_action, position_reduce, divergence_alert}
    각각 별도 days. action_type IS NULL (legacy) → fallback_days.

    forward-only: 신규 emit 부터 action_type 채워짐 (holdings_monitor.py).
    backfill 폐기 (codex+Qwen B2 STOP — heuristic 위험).

    Returns: ticker set 으로 BUY emit 차단.
    """
    suppressed: set[str] = set()
    type_map = {
        "hard_sell": cooldown_cfg.get("hard_sell_days", 21),
        "trim_action": cooldown_cfg.get("trim_days", 0),
        "position_reduce": cooldown_cfg.get("reduce_days", 7),
        "divergence_alert": cooldown_cfg.get("divergence_days", 3),
    }

    # Type-aware (post-#517 events)
    for action_type, days in type_map.items():
        if days <= 0:
            continue  # trim_days=0 → cooldown 차단 안 함 (re-add 허용)
        df = query_df(
            f"""SELECT DISTINCT json_extract(payload, '$.ticker') AS ticker
                  FROM pipeline_events
                  WHERE json_extract(payload, '$.action_type') = ?
                    AND timestamp >= datetime('now', '-{days} days')
                    AND json_extract(payload, '$.ticker') IS NOT NULL""",
            params=(action_type,),
        )
        if not df.empty:
            suppressed.update(str(t) for t in df["ticker"].dropna().tolist())

    # Legacy fallback (pre-#517: payload.action_type IS NULL)
    fallback = cooldown_cfg.get("fallback_days", 5)
    if fallback > 0:
        df_legacy = query_df(
            f"""SELECT DISTINCT json_extract(payload, '$.ticker') AS ticker
                  FROM pipeline_events
                  WHERE json_extract(payload, '$.action_type') IS NULL
                    AND event_type IN (
                        'holdings_monitor_alert',
                        'holdings_monitor_technical_sell',
                        'holdings_monitor_divergence',
                        'take_profit_trigger',
                        'trim_recommendation'
                    )
                    AND timestamp >= datetime('now', '-{fallback} days')
                    AND json_extract(payload, '$.ticker') IS NOT NULL"""
        )
        if not df_legacy.empty:
            suppressed.update(str(t) for t in df_legacy["ticker"].dropna().tolist())

    return suppressed


def _get_factor_scores() -> dict[str, dict[str, float]]:
    """Latest factor snapshot per ticker (date = MAX). Returns ticker → {composite_score, momentum, value, quality, sentiment}."""
    df = query_df(
        """SELECT ticker, momentum_score, value_score, quality_score,
                  sentiment_score, composite_score
           FROM factors
           WHERE date = (SELECT MAX(date) FROM factors)"""
    )
    if df.empty:
        return {}
    return {
        row["ticker"]: {
            "composite": row["composite_score"] or 0.0,
            "momentum": row["momentum_score"] or 0.0,
            "value": row["value_score"] or 0.0,
            "quality": row["quality_score"] or 0.0,
            "sentiment": row["sentiment_score"] or 0.0,
        }
        for _, row in df.iterrows()
    }


def _get_price_signals() -> dict[str, dict[str, float]]:
    """Compute 5d return + 30d high/low + current close from prices table.

    Returns ticker → {close, ret_5d, high_30d, low_30d, breakout_pct}.
    """
    df = query_df(
        """SELECT ticker, date, close
           FROM prices
           WHERE date >= date('now', '-45 days')
           ORDER BY ticker, date"""
    )
    if df.empty:
        return {}
    out: dict[str, dict[str, float]] = {}
    for ticker_raw, grp in df.groupby("ticker"):
        ticker = str(ticker_raw)
        if len(grp) < 6:
            continue
        closes = grp["close"].tolist()
        last = closes[-1]
        ret_5d = (last / closes[-6] - 1.0) * 100.0 if closes[-6] else 0.0
        recent = closes[-30:] if len(closes) >= 30 else closes
        high_30d = max(recent)
        low_30d = min(recent)
        # breakout % = (last - high_30d) / high_30d. Positive = above prior high.
        breakout_pct = (last / high_30d - 1.0) * 100.0 if high_30d else 0.0
        out[ticker] = {
            "close": last,
            "ret_5d": ret_5d,
            "high_30d": high_30d,
            "low_30d": low_30d,
            "breakout_pct": breakout_pct,
        }
    return out


def _get_rsi_snapshot() -> dict[str, float]:
    """Latest RSI(14) per ticker."""
    df = query_df(
        """SELECT ticker, rsi_14 FROM signals
           WHERE date = (SELECT MAX(date) FROM signals)"""
    )
    if df.empty:
        return {}
    return {row["ticker"]: row["rsi_14"] for _, row in df.iterrows() if row["rsi_14"] is not None}


def _get_regime() -> tuple[str, float]:
    """Current regime + VIX. Phase 1: read from regime_transitions or default."""
    try:
        df = query_df(
            """SELECT to_regime FROM regime_transitions
               ORDER BY date DESC LIMIT 1"""
        )
        regime = df["to_regime"].iloc[0] if not df.empty else "neutral"
    except Exception:
        regime = "neutral"
    try:
        # VIX 는 macro 테이블(indicator='vix')에만 수집된다. prices.VIX 는 미수집이라
        # 과거 prices 경로는 항상 fallback 20.0 으로 떨어져 VIX 게이트가 무력화됐다 (#753).
        df_vix = query_df(
            """SELECT value FROM macro WHERE indicator = 'vix'
               ORDER BY date DESC LIMIT 1"""
        )
        vix = float(df_vix["value"].iloc[0]) if not df_vix.empty else 20.0
    except Exception:
        vix = 20.0
    return regime, vix


def _score_ticker(
    ticker: str,
    factor: dict[str, float],
    price: dict[str, float],
    rsi: float | None,
    weights: dict[str, float],
    rs_rank: float | None = None,
    dollar_volume: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Fuse sources to single 0-100 score. Returns (final_score, source_breakdown).

    Each source normalized to 0-100 then weighted-summed.
    Missing source = 50 (neutral) so partial data doesn't block.

    rs_rank / dollar_volume 은 P2 leadership shadow 채널 — config weight=0 이면 점수에
    기여하지 않고 sources 로만 노출된다. 승격(weight>0)은 P1 walk-forward 후 STRATEGY PR.
    """
    # factor composite already 0-1, scale to 0-100
    factor_pct = (factor.get("composite", 0.5)) * 100.0

    # 5d return: -10% → 0, 0% → 50, +10% → 100. Clipped.
    ret_5d = price.get("ret_5d", 0.0)
    momentum_pct = max(0.0, min(100.0, 50.0 + ret_5d * 5.0))

    # RSI: 30 → 60 (oversold positive), 50 → 70, 65 → 80, 75 → 50 (overbought penalty), 85 → 20
    if rsi is None:
        rsi_pct = 50.0
    elif rsi <= 30:
        rsi_pct = 60.0
    elif rsi <= 50:
        rsi_pct = 50.0 + rsi * 0.4  # 50 at rsi 0, 70 at rsi 50
    elif rsi <= 65:
        rsi_pct = 70.0 + (rsi - 50) * 0.67
    elif rsi <= 75:
        rsi_pct = max(20.0, 80.0 - (rsi - 65) * 3.0)  # rapid decay overbought
    else:
        rsi_pct = max(0.0, 50.0 - (rsi - 75) * 5.0)  # extreme overbought = penalty

    # Breakout: +0% (at high) = 70, +2% above = 90, -5% below = 40, -15% below = 0
    bo = price.get("breakout_pct", 0.0)
    if bo >= 0:
        breakout_pct = min(100.0, 70.0 + bo * 10.0)
    else:
        breakout_pct = max(0.0, 70.0 + bo * 4.0)

    # RS percentile (cross-sectional leadership): 0-100 직접 사용. 없으면 중립.
    rs_pct = 50.0 if rs_rank is None else max(0.0, min(100.0, rs_rank))

    # 거래대금 surge: 완만한 확장은 보상(1.0→50 … 2.5→90), 과열(parabolic) 추격은
    # 페널티 (crowding 가드 — 급등주 추격 금지). surge 는 배수(ratio).
    if dollar_volume is None:
        dv_pct = 50.0
    elif dollar_volume <= 2.5:
        dv_pct = max(0.0, min(90.0, 50.0 + (dollar_volume - 1.0) * 26.667))
    else:
        dv_pct = max(20.0, 90.0 - (dollar_volume - 2.5) * 20.0)

    final = (
        weights.get("factor_composite", 0.4) * factor_pct
        + weights.get("momentum_5d", 0.25) * momentum_pct
        + weights.get("technical_rsi", 0.15) * rsi_pct
        + weights.get("breakout_30d", 0.2) * breakout_pct
        # P2 leadership shadow — weight=0 이면 기여 0 (라이브 점수 무변경)
        + weights.get("rs_rank", 0.0) * rs_pct
        + weights.get("dollar_volume", 0.0) * dv_pct
    )

    return final, {
        "factor": round(factor_pct, 1),
        "momentum": round(momentum_pct, 1),
        "rsi": round(rsi_pct, 1),
        "breakout": round(breakout_pct, 1),
        "rs_rank": round(rs_pct, 1),
        "dollar_volume": round(dv_pct, 1),
    }


def _build_why_now(sources: dict[str, float], price: dict[str, float], rsi: float | None) -> str:
    """Single-sentence catalyst from strongest source.

    P2 leadership shadow 채널(rs_rank/dollar_volume)은 weight=0 이므로 why_now 후보에서
    제외한다 — 점수뿐 아니라 brief 텍스트도 라이브 무변경 (진짜 shadow). 승격(weight>0) 시
    별도 STRATEGY PR 에서 leadership 분기를 추가한다.
    """
    live = {k: v for k, v in sources.items() if k in ("factor", "momentum", "rsi", "breakout")}
    if not live:
        return "Multi-source 강세"  # 라이브 채널 부재 (정상 경로엔 4채널 항상 존재 — 방어)
    name, val = max(live.items(), key=lambda kv: kv[1])
    if name == "factor":
        return f"Multi-factor 상위 (composite {val:.0f}/100)"
    if name == "momentum":
        return f"5d {price.get('ret_5d', 0):+.1f}% 모멘텀"
    if name == "rsi":
        if rsi is not None and rsi <= 35:
            return f"RSI {rsi:.0f} 과매도 반등 setup"
        return f"RSI {rsi:.0f} 정상 구간 (overbought 페널티 없음)" if rsi else "RSI 정상"
    # name == "breakout" (live 의 유일 잔여 키)
    bo = price.get("breakout_pct", 0)
    if bo >= 0:
        return f"30d 고가 돌파 +{bo:.1f}%"
    return f"30d 고가 -{abs(bo):.1f}% 근접 (pullback)"


def emit_buy_candidates(
    config_path: Path | None = None,
    limit: int | None = None,
) -> EmitResult:
    """Main entry: emit BUY candidates for current snapshot.

    Returns EmitResult with candidates + skipped + meta.
    """
    cfg = _load_config(config_path)
    weights = cfg.get("weights", {})
    quality = cfg.get("quality_bar", {})
    gates = cfg.get("gates", {})
    risk = cfg.get("risk", {})
    alloc = cfg.get("allocation", {})

    regime, vix = _get_regime()
    result = EmitResult(
        regime=regime,
        vix=vix,
        timestamp_kst=kst_now().strftime("%Y-%m-%d %H:%M:%S KST"),
    )

    # Hard gate: VIX block — 임계는 rules.yaml(core.rules) canonical 사용 (#760). 차단은 strict >.
    if vix > VIX_BLOCK_ABOVE:
        result.blocked_reason = f"VIX {vix:.1f} > {VIX_BLOCK_ABOVE} (신규 매수 차단)"
        return result

    # Hard gate: regime
    if regime in {"bear", "crash", "extreme_fear"}:
        result.blocked_reason = f"regime={regime} (방어 모드, 신규 매수 차단)"
        return result

    # Quality threshold (regime-adjusted)
    threshold = quality.get("base_threshold", 70)
    threshold += quality.get("per_regime", {}).get(regime, 0)
    if threshold >= 999:
        result.blocked_reason = f"regime={regime} threshold={threshold} (사실상 차단)"
        return result

    held = _get_held_tickers() if cfg.get("exclude_held", True) else set()
    # #517 Phase 2b — type-aware cooldown 우선. legacy gates.cooldown_days 는 fallback 용.
    cooldown_cfg = gates.get("cooldown")
    if cooldown_cfg:
        cooldown = _get_cooldown_tickers_by_type(cooldown_cfg)
    else:
        # 호환성: gates.cooldown 미정의 시 legacy single-window
        cooldown = _get_cooldown_tickers(gates.get("cooldown_days", 5))
    factors = _get_factor_scores()
    prices = _get_price_signals()
    rsi_map = _get_rsi_snapshot()
    # P2 leadership shadow 스냅샷 (weight=0 — sources 노출만, 라이브 점수 무변경)
    lead_cfg = cfg.get("leadership", {})
    leadership = leadership_snapshot(lead_cfg.get("lookback", 120), lead_cfg.get("surge_window", 20))

    if not factors:
        result.blocked_reason = "factors 테이블 비어있음 (composite_score 데이터 부재)"
        return result

    # Score every ticker that has factor + price data
    scored: list[tuple[str, float, dict[str, float], dict[str, float], float | None]] = []
    for ticker, factor in factors.items():
        if ticker in held:
            result.skipped[ticker] = "held (보유 중 — Phase 2 에서 add 모드 도입)"
            continue
        if ticker in cooldown:
            result.skipped[ticker] = f"cooldown {gates.get('cooldown_days', 5)}d (최근 SELL/trim 신호)"
            continue
        if cfg.get("exclude_etf_leverage", True) and ticker in LEVERAGE_ETFS:
            result.skipped[ticker] = "leverage ETF (스윙 전용 — BUY 후보 제외)"
            continue
        price = prices.get(ticker)
        if not price:
            continue  # silent skip if no price — too many to surface
        rsi = rsi_map.get(ticker)
        lead = leadership.get(ticker)
        rs_rank = lead[0] if lead else None
        dollar_volume = lead[1] if lead else None
        score, sources = _score_ticker(ticker, factor, price, rsi, weights, rs_rank, dollar_volume)
        scored.append((ticker, score, sources, price, rsi))

    # Filter by quality bar, sort, top-N
    qualified = [s for s in scored if s[1] >= threshold]
    qualified.sort(key=lambda x: x[1], reverse=True)
    max_cand = limit if limit is not None else quality.get("max_candidates", 5)
    top = qualified[:max_cand]

    if not top:
        top_score = scored[0][1] if scored else 0
        result.blocked_reason = (
            f"top scorer {top_score:.0f}/100 < threshold {threshold} "
            f"(regime={regime}, scored={len(scored)}, qualified=0)"
        )
        return result

    # Allocation
    total_pct = alloc.get("total_pct_by_regime", {}).get(regime, 0.30)
    if vix >= VIX_CAUTION_ABOVE:
        total_pct = total_pct / 2.0  # half-position rule

    sum_score = sum(s[1] for s in top)
    candidates: list[BuyCandidate] = []
    for ticker, score, sources, price, _rsi in top:
        per_pct = total_pct * (score / sum_score) if sum_score > 0 else 0
        entry = price["close"]
        candidates.append(
            BuyCandidate(
                ticker=ticker,
                score=round(score, 1),
                deploy_pct=round(per_pct * 100.0, 2),
                entry=round(entry, 2),
                stop=round(entry * (1 + risk.get("stop_pct", -7.0) / 100.0), 2),
                tp1=round(entry * (1 + risk.get("tp1_pct", 20.0) / 100.0), 2),
                tp2=round(entry * (1 + risk.get("tp2_pct", 40.0) / 100.0), 2),
                why_now=_build_why_now(sources, price, _rsi),
                sources=sources,
            )
        )

    result.candidates = candidates
    result.total_deploy_pct = round(total_pct * 100.0, 1)
    return result


def render_markdown(result: EmitResult) -> str:
    """Render EmitResult as markdown block for premarket_brief integration."""
    lines = []
    if result.blocked_reason:
        lines.append("## BUY Candidates (0 — blocked)")
        lines.append(f"> **{result.blocked_reason}**")
        lines.append(f"> regime={result.regime} · VIX={result.vix:.1f}")
        return "\n".join(lines)

    n = len(result.candidates)
    lines.append(f"## BUY Candidates ({n} — total deploy {result.total_deploy_pct}% of cash)")
    lines.append(f"> regime={result.regime} · VIX={result.vix:.1f} · {result.timestamp_kst}")
    for i, c in enumerate(result.candidates, 1):
        lines.append("")
        lines.append(f"{i}. **{c.ticker}** — score {c.score}/100, deploy {c.deploy_pct}%")
        lines.append(f"   - Why now: {c.why_now}")
        lines.append(
            f"   - Entry ${c.entry} / Stop ${c.stop} ({(c.stop / c.entry - 1) * 100:+.0f}%) / "
            f"TP1 ${c.tp1} ({(c.tp1 / c.entry - 1) * 100:+.0f}%) / "
            f"TP2 ${c.tp2} ({(c.tp2 / c.entry - 1) * 100:+.0f}%)"
        )
        src = " · ".join(f"{k}={v:.0f}" for k, v in c.sources.items())
        lines.append(f"   - Sources: {src}")

    if result.skipped:
        skipped_top = list(result.skipped.items())[:5]
        lines.append("")
        lines.append(f"### Skipped ({len(result.skipped)} — reasons)")
        for t, r in skipped_top:
            lines.append(f"- **{t}**: {r}")
        if len(result.skipped) > 5:
            lines.append(f"- ... +{len(result.skipped) - 5} more")
    return "\n".join(lines)


def main() -> int:
    """CLI entry: print markdown + summary."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = emit_buy_candidates()
    print(render_markdown(result))
    print()
    print(
        f"Summary: {len(result.candidates)} candidates, "
        f"{len(result.skipped)} skipped, regime={result.regime}, VIX={result.vix:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
