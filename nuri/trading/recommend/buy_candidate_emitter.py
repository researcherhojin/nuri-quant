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

from nuri.core.db import DatabaseError, OperationalError, query_df
from nuri.core.rules import VIX_BLOCK_ABOVE, VIX_CAUTION_ABOVE
from nuri.core.timezone import kst_now
from nuri.quant.factors.relative_strength import leadership_snapshot
from nuri.quant.regime.classifier import UNKNOWN_REGIME
from nuri.trading.recommend.vix_gate import latest_vix

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "buy_signals.yaml"

# 레버리지/인버스 ETF (스윙 전용 — BUY 후보에서 제외)는 config/buy_signals.yaml 의
# exclude_etfs 가 source of truth (#761). SIEGE hard-ban(rules.yaml banned_etfs)과는
# 목적이 다르다(BUY 제외 ≠ 인증 차단).


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
    # None = VIX 미상(부재·조회실패·노후). 0.0 을 기본값으로 두면
    # '측정된 VIX 0' 과 구분되지 않는다.
    vix: float | None = None
    total_deploy_pct: float = 0.0
    blocked_reason: str | None = None  # if 0 candidates, why?
    timestamp_kst: str = ""
    # 미실행 원장(#1094)이 "왜 0건이었나" 를 답하려면 분모가 필요하다. 후보 목록만으로는
    # "채점 대상이 0" 과 "200개를 채점했는데 아무도 임계를 못 넘음" 이 구분되지 않는다.
    # 차단 경로(VIX/regime)에서는 채점 자체를 안 하므로 0 으로 남는다 — 그것도 정보다.
    n_scored: int = 0
    n_qualified: int = 0
    threshold: float | None = None


def format_vix(vix: float | None) -> str:
    """VIX 표기 — 미상은 숫자로 찍지 않는다.

    과거엔 부재를 `20.0` 으로 메워 브리핑에 측정값처럼 찍혔다. 사용자가 "VIX 20" 을
    읽고 평온하다고 판단할 수 있었으므로 표기 자체가 결함이었다.
    """
    return "미상" if vix is None else f"{vix:.1f}"


def _load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config/buy_signals.yaml. Path injectable for tests."""
    p = path or CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_held_tickers(db_path=None) -> set[str]:
    """Tickers currently in `portfolio` table — exclude from BUY emit."""
    df = query_df("SELECT DISTINCT ticker FROM portfolio", db_path=db_path)
    return {str(t) for t in df["ticker"].tolist()} if not df.empty else set()


def _get_cooldown_tickers(days: int, db_path=None) -> set[str]:
    """DEPRECATED — Phase 1 single-window cooldown. Use _get_cooldown_tickers_by_type (#517 Phase 2b).

    유지 이유: 호환성 (외부 caller / 테스트 fixture). 다음 세션에 제거 예정.
    """
    df = query_df(
        f"""SELECT DISTINCT
              json_extract(payload, '$.ticker') as ticker
            FROM pipeline_events
            WHERE event_type IN ('holdings_monitor_alert', 'take_profit_trigger', 'trim_recommendation')
              AND timestamp >= datetime('now', '-{days} days')
              AND json_extract(payload, '$.ticker') IS NOT NULL""",
        db_path=db_path,
    )
    return {str(t) for t in df["ticker"].dropna().tolist()} if not df.empty else set()


def _get_cooldown_tickers_by_type(cooldown_cfg: dict, db_path=None) -> set[str]:
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
            db_path=db_path,
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
                    AND json_extract(payload, '$.ticker') IS NOT NULL""",
            db_path=db_path,
        )
        if not df_legacy.empty:
            suppressed.update(str(t) for t in df_legacy["ticker"].dropna().tolist())

    return suppressed


def _get_factor_scores(db_path=None) -> dict[str, dict[str, float]]:
    """Latest factor snapshot per ticker (date = MAX). Returns ticker → {composite_score, momentum, value, quality, sentiment}."""
    df = query_df(
        """SELECT ticker, momentum_score, value_score, quality_score,
                  sentiment_score, composite_score
           FROM factors
           WHERE date = (SELECT MAX(date) FROM factors)""",
        db_path=db_path,
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


def _get_price_signals(db_path=None) -> dict[str, dict[str, float]]:
    """Compute 5d return + 30d high/low + current close from prices table.

    Returns ticker → {close, ret_5d, high_30d, low_30d, breakout_pct}.
    """
    df = query_df(
        """SELECT ticker, date, close
           FROM prices
           WHERE date >= date('now', '-45 days')
           ORDER BY ticker, date""",
        db_path=db_path,
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
        # 돌파는 **직전** 고점 대비다. 오늘 종가를 포함한 `high_30d` 와 비교하면
        # `high_30d >= last` 가 항상 참이라 `breakout_pct` 가 **양수가 될 수 없다**.
        # 그러면 `_score_ticker` 의 `bo >= 0 → 70 + bo*10` 분기가 오직 70 만 반환해
        # 70~100 구간이 통째로 죽고, 0.20 가중치의 최대 기여가 20 이 아니라 14 가 된다.
        # 프로덕션 실측(2026-08-18): 753종목 중 `breakout_pct > 0` **0건**, max 정확히
        # 0.0000. 그 14 가 BUY 임계 70 을 도달 불가로 만든 세 원인 중 하나였다 (#1100).
        prior_high = max(closes[-31:-1]) if len(closes) >= 2 else last
        breakout_pct = (last / prior_high - 1.0) * 100.0 if prior_high else 0.0
        out[ticker] = {
            "close": last,
            "ret_5d": ret_5d,
            "high_30d": high_30d,
            "low_30d": low_30d,
            "breakout_pct": breakout_pct,
        }
    return out


def _get_rsi_snapshot(db_path=None) -> dict[str, float]:
    """Latest RSI(14) per ticker — 티커별 최신, 7일 컷오프.

    전역 `MAX(date)` 하루치만 읽으면 **시장이 섞이는 순간 한쪽이 통째로 빠진다**:
    KR 은 KST 당일, US 는 전일 날짜로 signals 가 갈라지므로 최신 날짜 하나를 고르면
    다른 시장 전부가 스냅샷에서 사라진다 (#1101 — universe 확장 직후엔 backfill 날짜
    간극 때문에 751행을 쓰고도 보유분만 읽히는 형태로 재현됐다). 그래서 티커별 최신
    행을 잡되, 7일보다 낡은 값은 버린다 — 낡은 RSI 를 쓰는 것과 없는 값을 중립 50 으로
    치는 것 사이의 절충이고, 컷오프가 없으면 상장폐지 종목의 마지막 RSI 가 영원히 남는다.
    """
    from datetime import timedelta

    from nuri.core.timezone import kst_now

    # 컷오프는 KST 로 계산해 파라미터로 넘긴다 — SQLite 의 `date('now')` 는 UTC 라
    # 09:00 KST 이전(아침 배치 시간대 전부)에는 어제 날짜가 되어 컷오프가 하루
    # 느슨해진다. 레포 불변식은 KST 단일 시간대다 (Codex 리뷰 3차).
    cutoff = (kst_now() - timedelta(days=7)).strftime("%Y-%m-%d")
    df = query_df(
        """SELECT ticker, rsi_14, MAX(date) AS date FROM signals
           WHERE date >= ? AND rsi_14 IS NOT NULL
           GROUP BY ticker""",
        (cutoff,),
        db_path=db_path,
    )
    if df.empty:
        return {}
    return {row["ticker"]: row["rsi_14"] for _, row in df.iterrows() if row["rsi_14"] is not None}


def _get_regime(db_path=None) -> tuple[str, float | None]:
    """Current regime + VIX. 둘 다 모르면 지어내지 않고 미상으로 표면화한다.

    **레짐은 매번 새로 분류한다** (#1131). 이전엔 `regime_transitions` 의 최신 행을
    읽었다. 그 테이블의 유일한 writer 는 `strategy/monitor.py:78` 의
    `detect_regime_transition()` 이고, 그걸 부르는 예약 job 이 없다 — 진입점은
    `Makefile` 의 `strategy:` 수동 타깃뿐이다. 게다가 그 함수는 레짐이 **바뀔 때만**
    행을 넣으므로 "마지막 전환 = 현재 레짐" 이 성립하려면 감지기가 주기적으로 돌아야
    하는데 돌지 않는다. dev 스냅샷 실측(2026-08-20): 2행, 최신 2026-04-21 — **121일**.
    그 값이 하드 차단(`:438`) · 임계 조정(`:444`) · 배분(`:508`) 셋을 지배했다.

    `classify_regime()` 로 옮기면 신선도 강제가 따라온다: SPY 데이터가 120시간을 넘으면
    그쪽이 `None` 을 돌려준다 (`classifier.py:366`). 낡은 레짐이 현재값 행세를 하는
    경로 자체가 사라진다는 뜻이고, `regime_transitions` 는 히스토리 전용으로 남는다.

    `None` 은 `UNKNOWN_REGIME` 으로 표면화한다. 그 라벨은 `ALL_REGIMES` 밖이라 config 의
    레짐별 조정 표에 매치되지 않는다 — 미상은 완화도 강화도 받지 않는다.

    VIX 쪽은 종전과 같다: 부재·조회실패·노후를 `20.0` 으로 메우면 측정 불가가 조용히
    '평온'으로 둔갑해 게이트를 연다 (#753). `None` 을 돌려주고 부르는 쪽이 caution 과
    동일하게(절반 포지션) 처리한다 — STRATEGY §2.6 Soft penalty.
    """
    from nuri.quant.regime.classifier import classify_regime

    try:
        state = classify_regime(db_path=db_path)
    except (OperationalError, DatabaseError):
        # DB 오류만 삼킨다. 넓게 잡으면 `classify_regime` 안의 **코딩 오류**까지 미상으로
        # 위장돼 게이트가 조용히 보수 경로로 빠진다 — 이 모듈이 VIX 쪽에서 이미 명시적으로
        # 거부한 형태다 (`test_a_coding_error_is_not_disguised_as_unknown_vix`).
        # 데이터 부족·노후라는 **예상된** 열화는 예외가 아니라 `None` 으로 온다.
        logger.warning("regime 분류 실패 — 미상 처리", exc_info=True)
        state = None

    if state is None:
        logger.warning("[emitter] 레짐 미상 — 레짐별 조정 없이 보수 배분 적용")
        return UNKNOWN_REGIME, latest_vix(db_path=db_path)
    return state.regime, latest_vix(db_path=db_path)


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
    db_path: Path | None = None,
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
    exclude_etfs = set(cfg.get("exclude_etfs", []))  # 레버리지/인버스 ETF — BUY 제외 (#761)

    regime, vix = _get_regime(db_path=db_path)
    result = EmitResult(
        regime=regime,
        vix=vix,
        timestamp_kst=kst_now().strftime("%Y-%m-%d %H:%M:%S KST"),
    )

    # Hard gate: VIX block — 임계는 rules.yaml(core.rules) canonical 사용 (#760). 차단은 strict >.
    if vix is not None and vix > VIX_BLOCK_ABOVE:
        result.blocked_reason = f"VIX {vix:.1f} > {VIX_BLOCK_ABOVE} (신규 매수 차단)"
        return result

    # Hard gate: regime — 차단 집합은 config SSoT 다 (#1130).
    # 코드에 `{bear, crash, extreme_fear}` 로 하드코딩돼 있었는데 셋 다 `ALL_REGIMES`
    # 밖이라 `classify_regime()` 이 내는 어떤 값과도 겹치지 않았고, 도입(2026-04-30,
    # #508) 이래 **한 번도 발화하지 못했다**. 현재 config 기본값은 빈 집합 — 레짐 축은
    # soft penalty(배분 축소)로만 운용하고 hard veto 승격은 STRATEGY PR + 백테스트를
    # 요구한다 (Escalation Ladder). 코드가 아니라 config 에 두는 이유는 그 승격이
    # 값 변경이어야지 코드 변경이어서는 안 되기 때문이다.
    blocking = set(gates.get("blocking_regimes") or [])
    if regime in blocking:
        result.blocked_reason = f"regime={regime} (방어 모드, 신규 매수 차단)"
        return result

    # Quality threshold (regime-adjusted)
    threshold = quality.get("base_threshold", 70)
    threshold += quality.get("per_regime", {}).get(regime, 0)
    result.threshold = threshold
    if threshold >= 999:
        result.blocked_reason = f"regime={regime} threshold={threshold} (사실상 차단)"
        return result

    held = _get_held_tickers(db_path=db_path) if cfg.get("exclude_held", True) else set()
    # #517 Phase 2b — type-aware cooldown 우선. legacy gates.cooldown_days 는 fallback 용.
    cooldown_cfg = gates.get("cooldown")
    if cooldown_cfg:
        cooldown = _get_cooldown_tickers_by_type(cooldown_cfg, db_path=db_path)
    else:
        # 호환성: gates.cooldown 미정의 시 legacy single-window
        cooldown = _get_cooldown_tickers(gates.get("cooldown_days", 5), db_path=db_path)
    factors = _get_factor_scores(db_path=db_path)
    prices = _get_price_signals(db_path=db_path)
    rsi_map = _get_rsi_snapshot(db_path=db_path)
    # P2 leadership shadow 스냅샷 (weight=0 — sources 노출만, 라이브 점수 무변경)
    lead_cfg = cfg.get("leadership", {})
    leadership = leadership_snapshot(lead_cfg.get("lookback", 120), lead_cfg.get("surge_window", 20), db_path=db_path)

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
        if cfg.get("exclude_etf_leverage", True) and ticker in exclude_etfs:
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
    result.n_scored = len(scored)
    result.n_qualified = len(qualified)
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
    by_regime = alloc.get("total_pct_by_regime", {})
    if regime == UNKNOWN_REGIME:
        # 미상은 레짐 표의 기본값이 아니라 **별도 키**로 내린다. 이전엔 미상의 라벨이
        # `"neutral"` 이었고 표에 `neutral: 0.40` 이 있어서, 레짐을 모를 때 표에서 가장
        # 공격적인 배분이 나갔다 (#1131). 표에 `unknown` 을 넣지 않는 이유는 그게 정식
        # 레짐이 아니기 때문이다 — 넣으면 #1130 이 걷어내는 비정식 키가 다시 생긴다.
        total_pct = float(alloc.get("unknown_regime_pct", 0.10))
    elif regime in by_regime:
        total_pct = float(by_regime[regime])
    else:
        # 표에 없는 정식 레짐은 선언된 기본값으로 떨어지되 **그 사실을 남긴다**.
        # 이 경로가 조용하던 동안 `.get(regime, 0.30)` 이 어휘 불일치(#1130)를 정상
        # 동작처럼 삼켰다 — 예외도 경고도 없이 "그 레짐은 조정 없음" 으로 읽혔다.
        total_pct = float(alloc.get("default_pct", 0.30))
        logger.info(
            "[emitter] regime=%s 는 total_pct_by_regime 미등재 — 기본 배분 %.2f 적용",
            regime,
            total_pct,
        )
    # VIX 미상(None)도 caution 과 동일 취급 — 절반 포지션. STRATEGY §2.6 Soft penalty.
    # 측정 불가를 '평온'으로 읽지 않는다는 뜻이고, 차단(hard veto)까지는 가지 않는다.
    if vix is None or vix >= VIX_CAUTION_ABOVE:
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
        lines.append(f"> regime={result.regime} · VIX={format_vix(result.vix)}")
        return "\n".join(lines)

    n = len(result.candidates)
    lines.append(f"## BUY Candidates ({n} — total deploy {result.total_deploy_pct}% of cash)")
    lines.append(f"> regime={result.regime} · VIX={format_vix(result.vix)} · {result.timestamp_kst}")
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


def main(argv: list[str] | None = None) -> int:
    """CLI entry: print markdown + summary.

    기본은 **조회만** 한다. 원장 기록은 `--persist` 를 줄 때만 — 그래서 후보를 눈으로
    보려고 돌리는 것이 `recommendations` 를 오염시키지 않는다.

    ⚠️ 즉 "발행한 후보는 전부 원장에 남는다" 가 아니라 **"예약 발행(premarket brief)과
    명시 `--persist` 만 남는다"** 이다. Discord `/buy-candidates` 는 이 CLI 를 그대로
    타므로 기록되지 않는다 — 같은 날 브리핑이 이미 같은 계산을 기록했고
    `UNIQUE(date, ticker)` 로 중복도 막히지만, 규칙을 정확히 적어 둔다 (#1078 Codex P1).
    """
    import argparse

    parser = argparse.ArgumentParser(description="BUY 후보 emit (#507)")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="후보를 recommendations 원장에 기록 (기본: 조회만)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = emit_buy_candidates()
    print(render_markdown(result))
    print()
    print(
        f"Summary: {len(result.candidates)} candidates, "
        f"{len(result.skipped)} skipped, regime={result.regime}, VIX={format_vix(result.vix)}"
    )
    if args.persist:
        from nuri.trading.recommend.tracker import save_buy_candidates

        n = save_buy_candidates(result)
        print(f"원장 기록: {n}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
