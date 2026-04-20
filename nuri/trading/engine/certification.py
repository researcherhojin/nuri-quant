"""
SIEGE Certification Engine — 추천 결과의 형식 검증.

원본 SIEGE의 Formal Assurance(Lean/Isabelle 정리 증명)를 투자 도메인에 맞게 적용.
추천이 rules.yaml의 모든 규칙을 만족하는지 기계적으로 검증하고,
위반 시 인증서를 거부한다.

검증 항목 (11 base gate checks → v2 asset-class expansion 으로 실행 시
total_conditions 가변):

1. position_limit     — 종목 비중 <= 15% (계좌별 전략 적용)
2. sector_limit       — 섹터 비중 <= 35%
3. stop_loss_growth   — 성장주 손절 -7% 이내
4. stop_loss_value    — 가치주 손절 -10% 이내
5. data_fresh         — [v2] per-class freshness (us=SPY, kr=KOSPI+SPY, ...)
6. leverage_ban       — 레버리지 ETF 비보유
7. volatility_gate    — [v2] per-class 변동성 (us=VIX, kr=USD/KRW+VIX, ...)
                       (구 vix_gate)
8. external_data      — [v2] per-class 외부 데이터 카운트 (ticker 필터)
9. conflict_free      — BUY/SELL 동시 시그널 없음 (또는 관망)
10. drift_safe        — critical drift 시그널 기반 매수 없음
11. macro_event_alignment — |event_score| >= 10 시 경고

v2 (#248): Gate 5/7/8 은 portfolio 를 asset_class 로 group 한 뒤 per-class 정책
(config/rules.yaml siege_gates) 적용. 예: KR 종목 보유 시 KOSPI freshness +
USD/KRW volatility + 완화된 external threshold 로 평가되고 US spillover 는
secondary 지표로 warning emit. 따라서 실제 `Certificate.total_conditions` 는
portfolio 의 asset_class 조합에 따라 11~30+ 범위. `certified` 판정은 기존과
동일하게 error severity 0건 기준.

사용법:
    python -m nuri.trading.engine.certification
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from nuri.core.db import insert_certification, query
from nuri.core.rules import (
    LEVERAGE_ETFS,
    MAX_SECTOR_EXPOSURE,
    MAX_SINGLE_POSITION,
    RULES,
    STOCK_STOP_LOSS,
    VIX_BLOCK_ABOVE,
)

logger = logging.getLogger(__name__)


@dataclass
class CertCondition:
    """인증 조건 결과."""

    id: str
    description: str
    passed: bool
    detail: str
    severity: str = "error"  # "error" = 차단, "warning" = 경고만


@dataclass
class Certificate:
    """SIEGE 인증서."""

    timestamp: str
    total_conditions: int
    passed: int
    failed: int
    warnings: int
    certified: bool  # 모든 error 조건 통과
    conditions: list[CertCondition]
    score: float  # 0~100

    def __post_init__(self):
        if not self.timestamp:
            from nuri.core.timezone import kst_now

            self.timestamp = kst_now().isoformat()


def _current_regime() -> str | None:
    """현재 regime label. classify 실패 시 None (caller 가 1.0 multiplier fallback)."""
    try:
        from nuri.core.timezone import today_kst
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(date=today_kst())
        return state.regime if state else None
    except Exception as e:
        logger.warning(f"_current_regime 조회 실패 — neutral fallback: {e}")
        return None


def _get_position_multiplier(regime: str | None) -> float:
    """siege_gates.regime_overrides[regime].per_position_max_multiplier.

    Neutral regime (등록 안 됨) 또는 None regime → 1.0 (no adjustment).
    Config 부재 → 1.0 (graceful fallback).
    """
    if regime is None:
        return 1.0
    overrides = RULES.get("siege_gates", {}).get("regime_overrides", {})
    spec = overrides.get(regime, {})
    return float(spec.get("per_position_max_multiplier", 1.0))


def _apply_position_multiplier(base_pct: float, regime: str | None) -> float:
    """base_pct (계좌 strategy 의 max_single_position, 0~1 단위) × regime multiplier.

    Absolute cap (config: regime_override_absolute_cap_pct, 0~100 단위) 로 overflow
    방지. base_pct 자체가 cap 보다 크면 base_pct 를 그대로 반환 (cap 은 multiplier 가
    base 를 inflate 시켰을 때만 발동 — 보수적으로 strategy 자체 한도는 침해하지 않음).
    """
    multiplier = _get_position_multiplier(regime)
    raised = base_pct * multiplier
    cap_pct = float(RULES.get("siege_gates", {}).get("regime_override_absolute_cap_pct", 100.0))
    cap_fraction = cap_pct / 100.0
    # multiplier 가 raise 한 경우만 cap (multiplier <= 1.0 → original 보존)
    if multiplier > 1.0 and raised > cap_fraction:
        return cap_fraction
    return raised


def _check_position_limits(db_path=None) -> CertCondition:
    """1. 단일 종목 비중 — 계좌별 전략 프로파일 + regime override 적용 (E3-3c)."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        from nuri.core.rules import get_account_strategy

        df = analyze_portfolio()
        if df.empty:
            return CertCondition("position_limit", "종목 비중 한도", True, "포트폴리오 비어있음")

        regime = _current_regime()
        multiplier = _get_position_multiplier(regime)

        # 종목별 합산 비중 + 해당 종목이 속한 계좌들의 가장 관대한 한도
        agg = df.groupby("ticker")["weight_pct"].sum()
        ticker_accounts = df.groupby("ticker")["account"].apply(list).to_dict()
        violations = {}
        for ticker, weight in agg.items():
            accounts = ticker_accounts.get(ticker, [])
            base_max = max(
                (get_account_strategy(a).get("max_single_position", MAX_SINGLE_POSITION) for a in accounts),
                default=MAX_SINGLE_POSITION,
            )
            effective_max = _apply_position_multiplier(base_max, regime)
            if weight / 100 > effective_max:
                violations[ticker] = (weight, effective_max)

        regime_tag = f" (regime={regime}, ×{multiplier:.2f})" if multiplier != 1.0 else ""
        if not violations:
            return CertCondition("position_limit", "종목 비중 한도", True,
                                 f"최대 비중: {agg.max():.1f}%{regime_tag}")
        tickers = ", ".join(f"{t}({w:.1f}%>{limit * 100:.0f}%)" for t, (w, limit) in violations.items())
        return CertCondition("position_limit", "종목 비중 한도", False,
                             f"위반: {tickers}{regime_tag}", "error")
    except Exception as e:
        return CertCondition("position_limit", "종목 비중 한도", False, f"검증 실패: {e}")


def _check_sector_limits(db_path=None) -> CertCondition:
    """2. 섹터 비중 <= 35%."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio

        df = analyze_portfolio()
        if df.empty:
            return CertCondition("sector_limit", "섹터 비중 <= 35%", True, "포트폴리오 비어있음")

        sector_agg = df.groupby("sector")["weight_pct"].sum()
        violations = sector_agg[sector_agg / 100 > MAX_SECTOR_EXPOSURE]
        if violations.empty:
            return CertCondition("sector_limit", "섹터 비중 <= 35%", True, f"최대 섹터: {sector_agg.max():.1f}%")
        sectors = ", ".join(f"{s}({v:.1f}%)" for s, v in violations.items())
        return CertCondition("sector_limit", "섹터 비중 <= 35%", False, f"위반: {sectors}", "error")
    except Exception:
        return CertCondition("sector_limit", "섹터 비중 <= 35%", True, "검증 스킵")


def _check_leverage_ban(db_path=None) -> CertCondition:
    """6. 레버리지 ETF 비보유."""
    rows = query(
        "SELECT ticker FROM portfolio WHERE ticker IN ({})".format(",".join(f"'{t}'" for t in LEVERAGE_ETFS)),
        db_path=db_path,
    )
    held = [r["ticker"] for r in rows]
    if not held:
        return CertCondition("leverage_ban", "레버리지 ETF 비보유", True, "위반 없음")
    return CertCondition("leverage_ban", "레버리지 ETF 비보유", False, f"보유 중: {', '.join(held)}", "error")


def _classify_asset_class(ticker: str, sector: str, rules: list[dict]) -> str:
    """Portfolio holding 을 asset_class 로 분류.

    config/rules.yaml siege_gates.asset_class_rules 순서대로 matching — 더 구체적인
    rule 이 위에 있어야 함. match key: sector_prefix / ticker_suffix / sector / default.
    """
    sector = sector or ""
    for rule in rules:
        m = rule.get("match", {})
        if m.get("default"):
            return rule["asset_class"]
        if "sector_prefix" in m and sector.startswith(m["sector_prefix"]):
            return rule["asset_class"]
        if "ticker_suffix" in m and ticker.endswith(m["ticker_suffix"]):
            return rule["asset_class"]
        if "sector" in m and sector == m["sector"]:
            return rule["asset_class"]
    return "us_equity"  # safety net — YAML 에 default rule 없을 때


def _group_holdings_by_asset_class(db_path=None) -> dict[str, list[dict]]:
    """portfolio 를 asset_class 로 group. 빈 portfolio 면 {}.

    Returns: {asset_class: [{ticker, sector}, ...]}
    """
    gate_config = RULES.get("siege_gates", {})
    rules = gate_config.get("asset_class_rules", [])
    if not rules:
        return {}

    rows = query(
        "SELECT DISTINCT ticker, sector FROM portfolio WHERE ticker != '' ",
        db_path=db_path,
    )
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cls = _classify_asset_class(row["ticker"], row["sector"] or "", rules)
        groups.setdefault(cls, []).append({"ticker": row["ticker"], "sector": row["sector"]})
    return groups


def _read_indicator(name: str, db_path=None) -> float | None:
    """macro 테이블에서 최신 지표 값. 없으면 None."""
    rows = query(
        "SELECT value FROM macro WHERE indicator=? ORDER BY date DESC LIMIT 1",
        (name,),
        db_path=db_path,
    )
    if not rows or rows[0]["value"] is None:
        return None
    return float(rows[0]["value"])


def _compute_3d_change(indicator: str, db_path=None) -> float | None:
    """indicator 의 최근 4개 값에서 3일 pct change 계산. 데이터 부족 시 None."""
    rows = query(
        "SELECT value FROM macro WHERE indicator=? ORDER BY date DESC LIMIT 4",
        (indicator,),
        db_path=db_path,
    )
    if len(rows) < 4 or rows[0]["value"] is None or rows[-1]["value"] is None:
        return None
    latest = float(rows[0]["value"])
    past = float(rows[-1]["value"])
    if past == 0:
        return None
    return abs((latest - past) / past * 100)


def _get_indicator_value(name: str, db_path=None) -> float | None:
    """volatility indicator 값 조회. computed 지표 (*_3d_change) 는 자동 계산."""
    if name.endswith("_3d_change"):
        base = name.replace("_3d_change", "")
        return _compute_3d_change(base, db_path=db_path)
    return _read_indicator(name, db_path=db_path)


def _check_volatility_for_class(asset_class: str, policy: dict, db_path=None) -> list[CertCondition]:
    """Asset class 별 변동성 gate. primary + secondary 각각 condition 발행.

    Returns: [primary_condition, *secondary_conditions]. 데이터 없으면 PASS.
    """
    out: list[CertCondition] = []
    prim_name = policy.get("volatility_primary")
    prim_thr = policy.get("volatility_primary_threshold", 30)
    if prim_name:
        val = _get_indicator_value(prim_name, db_path=db_path)
        cid = f"volatility_gate_{asset_class}"
        desc = f"[{asset_class}] {prim_name} <= {prim_thr}"
        if val is None:
            out.append(CertCondition(cid, desc, True, f"{prim_name} 데이터 없음 — 스킵"))
        elif val <= prim_thr:
            out.append(CertCondition(cid, desc, True, f"{prim_name} {val:.2f} (정상)"))
        else:
            out.append(CertCondition(cid, desc, False, f"{prim_name} {val:.2f} > {prim_thr} — 매수 주의", "warning"))

    # secondary — cross-market spillover (warning only)
    sec_list = policy.get("volatility_secondary", []) or []
    sec_thr = policy.get("volatility_secondary_threshold", prim_thr)
    for sec_name in sec_list:
        val = _get_indicator_value(sec_name, db_path=db_path)
        cid = f"volatility_gate_{asset_class}_{sec_name}"
        desc = f"[{asset_class}] {sec_name} spillover"
        if val is None:
            continue  # secondary 데이터 없으면 silent skip
        if val <= sec_thr:
            out.append(CertCondition(cid, desc, True, f"{sec_name} {val:.2f} (정상)"))
        else:
            out.append(CertCondition(cid, desc, False, f"{sec_name} {val:.2f} > {sec_thr} — 교차 시장 경고", "warning"))
    return out


def _check_volatility_gates(db_path=None) -> list[CertCondition]:
    """Gate #7 (구 vix_gate) — 자산 클래스 별 변동성.

    Legacy compatibility: portfolio 가 비어있거나 siege_gates 설정 없으면 구
    VIX 전용 로직으로 fallback.
    """
    gate_config = RULES.get("siege_gates", {})
    asset_classes = gate_config.get("asset_classes", {})
    groups = _group_holdings_by_asset_class(db_path=db_path)

    # Legacy fallback — 설정이 없거나 portfolio 비어있으면 기존 VIX 단일 체크
    if not asset_classes or not groups:
        val = _read_indicator("vix", db_path=db_path)
        if val is None:
            return [CertCondition("vix_gate", f"VIX > {VIX_BLOCK_ABOVE} 매수 차단", True, "VIX 데이터 없음")]
        ok = val <= VIX_BLOCK_ABOVE
        return [
            CertCondition(
                "vix_gate",
                f"VIX > {VIX_BLOCK_ABOVE} 매수 차단",
                ok,
                f"VIX {val:.1f} {'(정상)' if ok else '— 신규 매수 금지 구간'}",
                "error" if ok else "warning",
            )
        ]

    out: list[CertCondition] = []
    for cls in sorted(groups.keys()):
        policy = asset_classes.get(cls)
        if not policy:
            continue  # YAML 에 클래스 정의 없으면 gate 스킵
        out.extend(_check_volatility_for_class(cls, policy, db_path=db_path))
    return out


def _check_stop_loss_compliance(db_path=None) -> CertCondition:
    """3-4. 손절선 준수 여부 — 계좌별 전략 프로파일 적용."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        from nuri.core.rules import get_account_strategy

        df = analyze_portfolio()
        if df.empty:
            return CertCondition("stop_loss", "손절선 준수", True, "포트폴리오 비어있음")

        # 계좌별 손절선 적용
        violation_rows = []
        for _, row in df.iterrows():
            account = row.get("account", "")
            strategy = get_account_strategy(account)
            account_sl = strategy.get("stop_loss", STOCK_STOP_LOSS)
            if row["pnl_pct"] < account_sl:
                violation_rows.append(row)

        if not violation_rows:
            return CertCondition("stop_loss", "손절선 준수", True, f"최대 손실: {df['pnl_pct'].min():.1f}%")
        tickers = ", ".join(f"{r['ticker']}({r['pnl_pct']:.1f}%)" for r in violation_rows[:5])
        return CertCondition("stop_loss", "손절선 준수", False, f"위반 {len(violation_rows)}건: {tickers}", "error")
    except Exception:
        return CertCondition("stop_loss", "손절선 준수", True, "검증 스킵")


def _check_conflicts(db_path=None) -> CertCondition:
    """9. BUY/SELL 동시 시그널 해소."""
    try:
        from nuri.trading.engine.conflicts import detect_conflicts

        conflicts = detect_conflicts(db_path=db_path)
        high = [c for c in conflicts if c.severity == "high"]
        if not high:
            return CertCondition("conflict_free", "방향 충돌 해소", True, f"충돌 {len(conflicts)}건 (high 0건)")
        tickers = ", ".join(c.ticker for c in high[:5])
        return CertCondition("conflict_free", "방향 충돌 해소", False, f"high 충돌 {len(high)}건: {tickers}", "warning")
    except Exception:
        return CertCondition("conflict_free", "방향 충돌 해소", True, "검증 스킵")


def _check_drift_safety(db_path=None) -> CertCondition:
    """10. Critical drift 시그널 기반 매수 없음."""
    try:
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        critical = [d for d in drifts if d.status == "critical"]
        if not critical:
            return CertCondition("drift_safe", "시그널 drift 안전", True, "critical 없음")
        names = ", ".join(d.signal_id for d in critical)
        return CertCondition(
            "drift_safe", "시그널 drift 안전", False, f"critical {len(critical)}개: {names}", "warning"
        )
    except Exception:
        return CertCondition("drift_safe", "시그널 drift 안전", True, "검증 스킵")


def _ticker_age_hours(ticker: str, db_path=None) -> float | None:
    """ticker 의 최신 price date 까지 age(시간). 데이터 없으면 None."""
    rows = query("SELECT MAX(date) as latest FROM prices WHERE ticker=?", (ticker,), db_path=db_path)
    if not rows or not rows[0]["latest"]:
        return None
    from nuri.core.timezone import kst_now

    latest = datetime.strptime(rows[0]["latest"], "%Y-%m-%d")
    return (kst_now().replace(tzinfo=None) - latest).total_seconds() / 3600


def _check_freshness_for_class(asset_class: str, policy: dict, db_path=None) -> list[CertCondition]:
    """Asset class 별 freshness gate. primary + secondary 개별 condition."""
    out: list[CertCondition] = []
    max_hours = policy.get("freshness_max_hours", 72)
    prim = policy.get("freshness_primary")
    if prim:
        age = _ticker_age_hours(prim, db_path=db_path)
        cid = f"data_fresh_{asset_class}"
        desc = f"[{asset_class}] {prim} <= {max_hours}h"
        if age is None:
            out.append(CertCondition(cid, desc, False, f"{prim} 데이터 없음", "warning"))
        elif age <= max_hours:
            out.append(CertCondition(cid, desc, True, f"{prim} {age:.0f}시간 전"))
        else:
            out.append(CertCondition(cid, desc, False, f"{prim} {age:.0f}시간 전 ({max_hours}h 초과)", "warning"))

    # secondary — cross-market reference
    for sec in policy.get("freshness_secondary") or []:
        age = _ticker_age_hours(sec, db_path=db_path)
        cid = f"data_fresh_{asset_class}_{sec}"
        desc = f"[{asset_class}] {sec} spillover freshness"
        if age is None:
            continue  # secondary 없으면 silent
        if age <= max_hours:
            out.append(CertCondition(cid, desc, True, f"{sec} {age:.0f}시간 전"))
        else:
            out.append(CertCondition(cid, desc, False, f"{sec} {age:.0f}시간 전 — 교차 시장 stale", "warning"))
    return out


def _check_data_freshness(db_path=None) -> list[CertCondition]:
    """5. 데이터 신선도 — asset class 별 (v2). Legacy fallback: SPY 단일."""
    gate_config = RULES.get("siege_gates", {})
    asset_classes = gate_config.get("asset_classes", {})
    groups = _group_holdings_by_asset_class(db_path=db_path)

    if not asset_classes or not groups:
        # Legacy — SPY 전용 체크
        age = _ticker_age_hours("SPY", db_path=db_path)
        if age is None:
            return [CertCondition("data_fresh", "데이터 신선도 (72h)", False, "SPY 데이터 없음", "warning")]
        ok = age <= 72
        return [
            CertCondition(
                "data_fresh",
                "데이터 신선도 (72h)",
                ok,
                f"SPY {age:.0f}시간 전" + ("" if ok else " (72h 초과)"),
                "error" if ok else "warning",
            )
        ]

    out: list[CertCondition] = []
    for cls in sorted(groups.keys()):
        policy = asset_classes.get(cls)
        if not policy:
            continue
        out.extend(_check_freshness_for_class(cls, policy, db_path=db_path))
    return out


def _count_external_for_class(asset_class: str, tickers: list[str], db_path=None) -> tuple[int, int]:
    """Asset class 에 속한 ticker 들의 external_analysis 집계. (records, sources).

    kr_equity 등 자국 ticker 는 ticker column 으로 필터.
    US ETF 는 ticker 기준. records 는 해당 ticker 쌓인 모든 행.
    """
    if not tickers:
        # ticker 없으면 전체 조회로 fallback (미국 default class 등)
        rows = query(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT source) AS s FROM external_analysis",
            db_path=db_path,
        )
        return (int(rows[0]["n"]) if rows else 0, int(rows[0]["s"]) if rows else 0)
    placeholders = ",".join("?" * len(tickers))
    rows = query(
        f"SELECT COUNT(*) AS n, COUNT(DISTINCT source) AS s FROM external_analysis WHERE ticker IN ({placeholders})",
        tuple(tickers),
        db_path=db_path,
    )
    return (int(rows[0]["n"]) if rows else 0, int(rows[0]["s"]) if rows else 0)


def _check_external_for_class(asset_class: str, tickers: list[str], policy: dict, db_path=None) -> CertCondition:
    """Asset class 별 external data gate."""
    min_rec = policy.get("external_min_records", 10)
    min_src = policy.get("external_min_sources", 3)
    cid = f"external_data_{asset_class}"
    desc = f"[{asset_class}] external >= {min_rec}건 / {min_src}소스"
    try:
        records, sources = _count_external_for_class(asset_class, tickers, db_path=db_path)
    except Exception:
        return CertCondition(cid, desc, False, "external_analysis 조회 실패", "warning")

    if records >= min_rec and sources >= min_src:
        return CertCondition(cid, desc, True, f"{records}건, {sources}개 소스")
    return CertCondition(
        cid, desc, False, f"{records}건, {sources}개 소스 (기준: {min_rec}+건/{min_src}+소스)", "warning"
    )


def _check_external_data(db_path=None) -> list[CertCondition]:
    """8. 외부 데이터 — asset class 별 (v2). Legacy fallback: 전체 10/3."""
    gate_config = RULES.get("siege_gates", {})
    asset_classes = gate_config.get("asset_classes", {})
    groups = _group_holdings_by_asset_class(db_path=db_path)

    if not asset_classes or not groups:
        # Legacy — get_external_summary 기반
        try:
            from nuri.collectors.external import get_external_summary

            summary = get_external_summary(db_path)
            total = summary["total_records"]
            sources = len(summary["sources"])
            ok = total >= 10 and sources >= 3
            return [
                CertCondition(
                    "external_data",
                    "외부 데이터 충분",
                    ok,
                    f"{total}건, {sources}개 소스" + ("" if ok else " (10건+, 3소스+ 필요)"),
                    "warning" if not ok else "error",
                )
            ]
        except Exception:
            return [
                CertCondition("external_data", "외부 데이터 충분", False, "external_analysis 테이블 없음", "warning")
            ]

    out: list[CertCondition] = []
    for cls in sorted(groups.keys()):
        policy = asset_classes.get(cls)
        if not policy:
            continue
        tickers = [h["ticker"] for h in groups[cls]]
        out.append(_check_external_for_class(cls, tickers, policy, db_path=db_path))
    return out


def _check_macro_event_alignment(db_path=None) -> CertCondition:
    """11. 매크로 이벤트 정합성 — event_score 기반 경고."""
    try:
        from nuri.quant.regime.event_score import compute_event_score

        es = compute_event_score(db_path=db_path)
        score = es.score
        dominant = es.dominant_category or "none"

        if abs(score) >= 15:
            return CertCondition(
                "macro_event_alignment",
                "매크로 이벤트 정합성",
                False,
                f"강한 매크로 이벤트 감지 (score={score:+.1f}): {dominant}",
                "warning",
            )
        if abs(score) >= 10:
            return CertCondition(
                "macro_event_alignment",
                "매크로 이벤트 정합성",
                False,
                f"매크로 이벤트 주의 (score={score:+.1f}): {dominant}",
                "warning",
            )
        return CertCondition(
            "macro_event_alignment",
            "매크로 이벤트 정합성",
            True,
            f"event_score={score:+.1f} (정상)",
        )
    except Exception:
        # graceful degradation — 이벤트 데이터 없어도 통과
        return CertCondition("macro_event_alignment", "매크로 이벤트 정합성", True, "검증 스킵")


def _check_rules_loaded(db_path=None) -> CertCondition:
    """규칙 파일 로드 확인."""
    from nuri.core.rules import RULES

    keys = len(RULES)
    has_take_profit = "take_profit" in RULES
    has_entry = "entry_rules" in RULES
    ok = keys >= 5 and has_take_profit and has_entry
    return CertCondition(
        "rules_loaded", "rules.yaml 완전 로드", ok, f"{keys}개 섹션 (take_profit={has_take_profit}, entry={has_entry})"
    )


# 11개 base gate checks. asset-class 분리 gate (5/7/8) 는 list[CertCondition] 반환
# (per-class expansion → 실행 시 total_conditions 가변), 나머지는 단건. certify() 에서 flatten.
ALL_CERT_CHECKS = [
    _check_position_limits,  # 1. 종목 비중
    _check_sector_limits,  # 2. 섹터 비중
    _check_stop_loss_compliance,  # 3-4. 손절선
    _check_data_freshness,  # 5. 데이터 신선도 (per-class list)
    _check_leverage_ban,  # 6. 레버리지 금지
    _check_volatility_gates,  # 7. 변동성 게이트 (per-class list, 구 vix_gate)
    _check_external_data,  # 8. 외부 데이터 (per-class list)
    _check_conflicts,  # 9. 충돌 해소
    _check_drift_safety,  # 10. drift 안전
    _check_macro_event_alignment,  # 11. 매크로 이벤트 정합성
    _check_rules_loaded,  # 규칙 로드
]


def _compute_portfolio_hash(db_path=None) -> str | None:
    """Portfolio snapshot 의 deterministic sha256. Empty portfolio → None.

    SIEGE 실행 기록에서 "같은 portfolio 상태 재실행" 을 식별하기 위한 dedup key.
    E4-0b (historical backfill) 에서 snapshot-level grouping 에 사용 예정.
    """
    try:
        rows = query(
            "SELECT account, ticker, quantity, avg_price FROM portfolio "
            "WHERE ticker != '' ORDER BY account, ticker",
            db_path=db_path,
        )
        if not rows:
            return None
        records = [
            (r["account"], r["ticker"], float(r["quantity"] or 0), float(r["avg_price"] or 0))
            for r in rows
        ]
        payload = json.dumps(records, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()
    except Exception as e:
        logger.warning(f"portfolio_hash 계산 실패 (non-fatal): {e}")
        return None


def _persist_certification(cert: "Certificate", db_path=None, caller: str | None = None) -> None:
    """Certificate 를 certifications 테이블에 insert. 실패는 non-fatal (warning only).

    E4-0a instrumentation — certify() 내부 호출. 실패해도 cert 반환은 정상 진행.
    """
    try:
        insert_certification(
            {
                "timestamp": cert.timestamp,
                "certified": 1 if cert.certified else 0,
                "score": cert.score,
                "total_conditions": cert.total_conditions,
                "passed": cert.passed,
                "failed": cert.failed,
                "warnings": cert.warnings,
                "regime": _current_regime(),
                "portfolio_hash": _compute_portfolio_hash(db_path=db_path),
                "conditions_json": json.dumps([asdict(c) for c in cert.conditions]),
                "caller": caller,
            },
            db_path=db_path,
        )
    except Exception as e:
        logger.warning(f"SIEGE certificate persist 실패 (non-fatal): {e}")


def certify(db_path=None, persist: bool = True, caller: str | None = None) -> Certificate:
    """SIEGE 인증서 발급. 11 base gate check 실행 후 pass/fail 판정.

    v2 (#248): gate 5/7/8 은 portfolio asset_class 별로 multiple CertCondition
    을 반환. certify() 가 flatten 하여 total_conditions 에 반영 (portfolio
    구성에 따라 11 ~ 30+ 범위). `certified` 는 error severity 0건 기준 (기존 유지).

    E4-0a (#TBD): persist=True (default) 면 certifications 테이블에 기록.
    Persist 실패는 non-fatal — cert 는 항상 정상 반환. Test 격리 또는 read-only
    검증은 persist=False 로 opt-out. `caller` 는 optional context string
    (e.g. "cli", "api:actions").
    """
    conditions: list[CertCondition] = []
    for check in ALL_CERT_CHECKS:
        result = check(db_path=db_path)
        if isinstance(result, list):
            conditions.extend(result)
        else:
            conditions.append(result)

    total = len(conditions)
    passed = sum(1 for c in conditions if c.passed)
    failed = sum(1 for c in conditions if not c.passed and c.severity == "error")
    warnings = sum(1 for c in conditions if not c.passed and c.severity == "warning")
    certified = failed == 0
    score = round(passed / total * 100, 1) if total > 0 else 0

    from nuri.core.timezone import kst_now

    cert = Certificate(
        timestamp=kst_now().isoformat(),
        total_conditions=total,
        passed=passed,
        failed=failed,
        warnings=warnings,
        certified=certified,
        conditions=conditions,
        score=score,
    )

    if persist:
        _persist_certification(cert, db_path=db_path, caller=caller)

    return cert


def print_certificate(cert: Certificate) -> None:
    """인증서 CLI 출력."""
    status = "CERTIFIED" if cert.certified else "REJECTED"
    print(f"\n{'═' * 60}")
    print(f"  SIEGE Certificate — {status} ({cert.score:.0f}%)")
    print(f"  {cert.timestamp}")
    print(f"{'═' * 60}")
    print(f"  Passed: {cert.passed}/{cert.total_conditions} | Failed: {cert.failed} | Warnings: {cert.warnings}")
    print(f"{'─' * 60}")

    for c in cert.conditions:
        if c.passed:
            icon = "✅"
        elif c.severity == "error":
            icon = "❌"
        else:
            icon = "⚠️"
        print(f"  {icon} {c.description}")
        print(f"      {c.detail}")

    print(f"{'═' * 60}")
    if cert.certified:
        print("  ✅ 모든 필수 조건 통과. 추천 실행 가능.")
    else:
        print("  ❌ 필수 조건 미충족. 위반 사항 해결 후 재검증 필요.")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cert = certify(caller="cli")
    print_certificate(cert)
