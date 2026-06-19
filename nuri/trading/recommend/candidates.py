"""
E-1: 시그널 기반 후보 스크리너.

오늘(최근 N일) 발생한 시그널 중 과거 검증된 것만 추출하여
레짐 맥락과 함께 ranked 후보 리스트를 생성한다.

사용법:
    python -m nuri.trading.recommend.candidates
    python -m nuri.trading.recommend.candidates --days 3
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from nuri.core.db import get_tickers, query_df
from nuri.quant.validation.signal_backtest import (
    BUY_SIGNALS,
    SIGNAL_DEFINITIONS,
    compute_indicators,
    detect_signal_entries,
    merge_data_signals,
    merge_macro_data,
)

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


# Evidence tier thresholds — B-2-ext per codex mid-review (2026-04-17)
# 증거 품질로 3분류해서 scoring 이 약한 근거를 legitimize 하지 못하도록 차단.
MIN_TRADES_FOR_VALIDATION = 30  # 30+ trades = statistically validated sample
NEGATIVE_EDGE_PF_THRESHOLD = 1.0  # PF < 1.0 = losses > gains = avoid

TIER_ACTIONABLE = "actionable"  # validated + adequate sample + positive edge
TIER_ADVISORY = "advisory"  # unscored OR low-sample (disclosure only)
TIER_AVOID = "avoid"  # validated negative edge (do NOT act on signal alone)


@dataclass
class Candidate:
    """매매 후보."""

    ticker: str
    signal_id: str
    signal_date: str
    direction: str  # "BUY" or "SELL"
    confidence: float  # 0~100
    win_rate: float
    profit_factor: float
    regime_fit: bool
    price: float
    notes: str
    drift_status: str = ""  # "stable", "degrading", "critical" (from Learning Memory)
    conflict: str = ""  # "" or "direction_conflict" (from Conflict Detection)
    scoring_detail: dict | None = None  # confidence 계산 요인 기록
    unscored: bool = False  # True = signal 이 scorecard 에 없음 → 통계 미검증
    # (이전 폴백 win_rate=0.5/pf=1.0 제거, B-2 honesty fix)
    tier: str = TIER_ACTIONABLE  # "actionable" | "advisory" | "avoid"
    # codex B-2-ext: 증거 품질 bucket split. advisory/avoid
    # 는 normal recommendation 에 섞이지 않음 (개별 섹션).


def _load_scorecard() -> tuple[dict[str, dict], int | None]:
    """최신 signal_scorecard.csv에서 시그널별 통계 로드.

    Returns:
        (scorecard_dict, age_days): 스코어카드 데이터와 파일 나이(일). 파일 없으면 ({}, None).

    B-2-ext codex P2: 2026-04-17 이전에 생성된 scorecard 는 SELL 시그널을
    buy-perspective 로 잘못 측정 (B-1 이전). 감지 방법: SELL 시그널이 하나라도
    PF>1 로 읽히면 pre-B-1 데이터. 이 경우 해당 SELL 들을 drop 해 unscored 로
    취급 (conservative — 잘못된 stat 으로 confidence 쌓지 않음).
    """
    from nuri.quant.validation.signal_backtest import SELL_SIGNALS as _SELL_SIGNALS

    if REPORT_DIR.exists():
        for d in sorted(REPORT_DIR.iterdir(), reverse=True):
            csv = d / "signal_scorecard.csv"
            if csv.exists():
                # 디렉토리명에서 날짜 추출 (YYYY-MM-DD 형식)
                age_days = None
                try:
                    from nuri.core.timezone import kst_now

                    dir_date = datetime.strptime(d.name, "%Y-%m-%d")
                    age_days = (kst_now().replace(tzinfo=None) - dir_date).days
                except ValueError:
                    pass

                if age_days is not None and age_days > 7:
                    logger.warning("스코어카드 %d일 경과 (디렉토리: %s). 재검증 필요: make validate", age_days, d.name)

                df = pd.read_csv(csv)
                total = df[df["ticker"].isna()]
                data = {
                    row["signal_id"]: {
                        "win_rate": row["win_rate"],
                        "profit_factor": row["profit_factor"],
                        "avg_return": row["avg_return"],
                        "total_trades": row["total_trades"],
                    }
                    for _, row in total.iterrows()
                }
                # Pre-B-1 cache detection: post-fix SELL 는 전부 PF<1 여야 함.
                # SELL 중 PF>1 가 있으면 옛 측정 → 해당 시그널만 drop (unscored 로 fallback).
                stale_sells = [sid for sid in _SELL_SIGNALS if sid in data and data[sid]["profit_factor"] > 1.0]
                if stale_sells:
                    logger.warning(
                        "scorecard pre-B-1 (buy-perspective SELL) 데이터 감지: %s. "
                        "`make validate` 재실행 필요. 이 SELL 시그널들은 unscored 로 강제 처리.",
                        stale_sells,
                    )
                    for sid in stale_sells:
                        data.pop(sid, None)
                return data, age_days
    return {}, None


def _get_drift_map(db_path=None) -> dict[str, dict]:
    """Learning Memory에서 시그널별 성과 변화(drift) 로드."""
    try:
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        return {d.signal_id: {"status": d.status, "drift_pct": d.drift_pct} for d in drifts}
    except Exception:
        return {}


# drift 상태별 confidence 배수
DRIFT_MULTIPLIERS = {
    "critical": 0.3,  # 성과 급락 → 70% 할인
    "degrading": 0.6,  # 성과 하락 → 40% 할인
    "improving": 1.1,  # 성과 개선 → 10% 가점
    "stable": 1.0,
}


def _get_regime_context(db_path=None) -> dict | None:
    """현재 레짐 + 전략 추천 + 교차분석 데이터."""
    try:
        from nuri.quant.regime.classifier import classify_regime
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = classify_regime(db_path=db_path)
        if regime is None:
            return None
        strategy = map_regime_to_strategy(regime, db_path=db_path)

        # 교차분석 데이터: 현재 레짐에서의 시그널별 실제 성과
        regime_stats = {}
        if strategy and strategy.signal_regime_stats:
            regime_stats = strategy.signal_regime_stats

        return {
            "regime": regime.regime,
            "recommended": strategy.recommended_signals if strategy else [],
            "avoid": strategy.avoid_signals if strategy else [],
            "position": strategy.position_sizing if strategy else "normal",
            "regime_stats": regime_stats,
        }
    except Exception as e:
        logger.warning(f"레짐 컨텍스트 로드 실패: {e}")
        return None


def _check_vix_gate(db_path=None) -> dict:
    """VIX 기반 매수 게이트 체크. rules.yaml의 vix_gate 규칙 적용."""
    from nuri.core.rules import VIX_BLOCK_ABOVE, VIX_CAUTION_ABOVE

    vix_rows = query_df(
        "SELECT value FROM macro WHERE indicator = 'vix' ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    vix = float(vix_rows.iloc[0]["value"]) if not vix_rows.empty else 0.0

    # 차단은 strict > (rules.yaml 주석/사용자 룰: "VIX > 30 금지", "25-30 절반") — vix==30 은 caution (#760).
    if vix > VIX_BLOCK_ABOVE:
        return {"vix": vix, "gate": "blocked", "msg": f"VIX {vix:.1f} > {VIX_BLOCK_ABOVE} → 신규 매수 금지"}
    elif vix >= VIX_CAUTION_ABOVE:
        return {"vix": vix, "gate": "caution", "msg": f"VIX {vix:.1f} > {VIX_CAUTION_ABOVE} → 절반 포지션만"}
    return {"vix": vix, "gate": "normal", "msg": ""}


def screen_candidates(lookback_days: int = 5, db_path=None) -> list[Candidate]:
    """최근 N일 내 발생한 시그널 기반 매매 후보 스크리닝.

    Args:
        lookback_days: 시그널 탐색 기간 (거래일 기준)
        db_path: DB 경로 (테스트용)

    Returns:
        confidence 내림차순 정렬된 후보 리스트
    """
    scorecard, scorecard_age_days = _load_scorecard()
    scorecard_stale = scorecard_age_days is not None and scorecard_age_days > 7
    regime_ctx = _get_regime_context(db_path)
    drift_map = _get_drift_map(db_path)
    tickers = get_tickers(db_path=db_path)

    # VIX 게이트 체크
    vix_gate = _check_vix_gate(db_path)
    if vix_gate["gate"] == "blocked":
        logger.debug("⚠ %s", vix_gate["msg"])  # debug로 변경 (매 호출마다 반복 방지)

    if not tickers:
        return []

    candidates = []

    for ticker in tickers:
        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            (ticker,),
            db_path=db_path,
        )
        if df.empty or len(df) < 50:
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)

        # 매크로/데이터 시그널용 데이터 병합
        df = merge_macro_data(df, db_path=db_path)
        df = merge_data_signals(df, ticker, db_path=db_path)

        # 최근 lookback_days 거래일 범위
        cutoff_idx = max(0, len(df) - lookback_days)

        for signal_id in SIGNAL_DEFINITIONS:
            # PR C (codex bubble-bear #3): SHADOW 신호는 scorecard 집계에만 참여,
            # candidates 추천 흐름에는 절대 스며들지 못하게 여기서 구조적 차단.
            # codex Plan consult Biggest Risk: "shadow 를 validated signal 경로에
            # 섞어 confidence/tier 에 간접 반영하지 않도록 분리". surface 는 별도
            # market_signals.detect_all() 로 UI 노출.
            from nuri.core.signal_config import is_actionable

            if not is_actionable(signal_id):
                continue

            entries = detect_signal_entries(df, signal_id)
            # cutoff 이후 발생한 시그널만
            recent = [idx for idx in entries if idx >= cutoff_idx]

            for entry_idx in recent:
                stats = scorecard.get(signal_id, {})
                # B-2 honesty fix: no stats → unscored. 이전엔 win_rate=0.5, pf=1.0 으로
                # 폴백해 confidence 수식에 그대로 먹여 "검증됨" 처럼 보였음. 이제 unscored
                # candidate 는 confidence=0 + 명시적 flag 로 노출.
                unscored = not stats
                if unscored:
                    win_rate = 0.0
                    pf = 0.0
                else:
                    win_rate = stats.get("win_rate", 0.0)
                    pf = stats.get("profit_factor", 0.0)

                # B-2-ext: 증거 품질에 따라 3-tier 분류
                total_trades = stats.get("total_trades", 0) if not unscored else 0
                if unscored:
                    tier = TIER_ADVISORY  # 통계 없음
                elif total_trades < MIN_TRADES_FOR_VALIDATION:
                    tier = TIER_ADVISORY  # sample too small
                elif pf < NEGATIVE_EDGE_PF_THRESHOLD:
                    tier = TIER_AVOID  # validated negative edge
                else:
                    tier = TIER_ACTIONABLE  # validated + adequate sample + positive edge

                direction = "BUY" if signal_id in BUY_SIGNALS else "SELL"

                # A-4: non-emergency SELL 은 catalyst 요구 (STRATEGY §2.1 Evidence-first,
                # §2.6 Soft penalty). stop-loss breach 는 risk_agent 경로 — 여기는 signal
                # 기반 SELL 이므로 항상 catalyst 체크 대상. catalyst 없으면 advisory 로
                # downgrade — 사용자가 맥락 없이 매도하지 않도록.
                catalyst_note = ""
                if direction == "SELL" and tier == TIER_ACTIONABLE:
                    from nuri.core.catalyst import has_recent_catalyst

                    has_catalyst, catalyst_reason = has_recent_catalyst(ticker, db_path=db_path)
                    if not has_catalyst:
                        tier = TIER_ADVISORY
                        catalyst_note = f"SELL 근거 없음 ({catalyst_reason}) — advisory"
                    else:
                        catalyst_note = f"catalyst: {catalyst_reason}"

                # 레짐 적합도
                regime_fit = True
                regime_note = ""
                if regime_ctx:
                    if signal_id in regime_ctx.get("avoid", []):
                        regime_fit = False
                        regime_note = f"레짐({regime_ctx['regime']})에서 회피 시그널"
                    elif signal_id in regime_ctx.get("recommended", []):
                        regime_note = f"레짐({regime_ctx['regime']})에서 추천 시그널"

                # 신뢰도: 교차분석 데이터가 있으면 현재 레짐 내 실제 승률 사용
                regime_stats = regime_ctx.get("regime_stats", {}) if regime_ctx else {}
                sig_in_regime = regime_stats.get(signal_id)

                # scoring_detail 기록용. A-2b-pre: `source`/`schema_version` 으로
                # consensus.py scoring_detail (schema: per-agent contributions) 와
                # 구분 — A-2b API/frontend 가 같은 컬럼을 파싱할 때 key-sniffing
                # 대신 discriminator 로 분기.
                scoring = {
                    "source": "candidate",
                    "schema_version": 1,
                    "win_rate": round(win_rate, 4),
                    "profit_factor": round(pf, 2),
                    "regime": regime_ctx.get("regime", "") if regime_ctx else "",
                    "regime_fit": regime_fit,
                    "unscored": unscored,
                    "tier": tier,
                    "total_trades": total_trades,
                    # A-4: SELL 경로의 catalyst 체크 결과 (empty string = BUY 또는 non-actionable SELL)
                    "catalyst_note": catalyst_note,
                }

                if tier in (TIER_ADVISORY, TIER_AVOID):
                    # B-2-ext: advisory (unscored/low-sample) 와 avoid (negative edge)
                    # 모두 confidence=0. actionable 에 섞이지 않음. 노출은 별도 bucket.
                    confidence = 0.0
                    scoring["base_confidence"] = 0.0
                elif sig_in_regime and sig_in_regime.get("trades", 0) >= 5:
                    # 데이터 기반: 현재 레짐에서의 실제 승률 × 100
                    regime_wr = sig_in_regime["win_rate"]
                    regime_pf = sig_in_regime["pf"]
                    pf_cap = min(regime_pf / 5.0, 1.0)
                    # 60% 레짐 내 승률 + 40% 레짐 내 PF (둘 다 실측)
                    confidence = regime_wr * 60 + pf_cap * 40
                    scoring["base_confidence"] = round(confidence, 2)
                    scoring["regime_win_rate"] = round(regime_wr, 4)
                    scoring["regime_pf"] = round(regime_pf, 2)
                else:
                    # 전체 승률 기반 (레짐 무관). win_rate/pf 는 scorecard 실측.
                    pf_normalized = min(pf / 5.0, 1.0)
                    regime_bonus = 1.0 if regime_fit else 0.3
                    confidence = win_rate * 40 + pf_normalized * 30 + regime_bonus * 30
                    scoring["base_confidence"] = round(confidence, 2)

                # 레짐 비적합 시 할인
                regime_fit_penalty = 1.0
                if not regime_fit:
                    regime_fit_penalty = 0.4
                    confidence *= regime_fit_penalty
                scoring["regime_fit_penalty"] = regime_fit_penalty

                # minimal 포지션이면 BUY 신뢰도 대폭 할인
                position_penalty = 1.0
                if regime_ctx and regime_ctx.get("position") == "minimal" and direction == "BUY":
                    position_penalty = 0.3
                    confidence *= position_penalty
                scoring["position_penalty"] = position_penalty

                # Learning Memory drift 페널티
                drift_info = drift_map.get(signal_id, {})
                drift_status = drift_info.get("status", "")
                drift_multiplier = 1.0
                if drift_status in DRIFT_MULTIPLIERS:
                    drift_multiplier = DRIFT_MULTIPLIERS[drift_status]
                    confidence *= drift_multiplier
                scoring["drift_multiplier"] = drift_multiplier
                scoring["drift_status"] = drift_status

                notes_parts = []
                if unscored:
                    notes_parts.append("⚠️ 통계 없음 — 백테스트 미커버 (검증 불가)")
                elif tier == TIER_ADVISORY and catalyst_note.startswith("SELL 근거 없음"):
                    # A-4: tier downgrade 사유가 catalyst 부재 → 그 이유를 우선 노출
                    notes_parts.append(f"⚠️ {catalyst_note}")
                elif tier == TIER_ADVISORY:
                    notes_parts.append(f"⚠️ low-sample ({total_trades}건, {MIN_TRADES_FOR_VALIDATION} 미만)")
                elif tier == TIER_AVOID:
                    notes_parts.append(f"🚫 negative-edge 시그널 (PF={pf:.2f}) — 독립 행동 금지")
                if scorecard_stale:
                    notes_parts.append(f"⚠️ 스코어카드 {scorecard_age_days}일 전")
                if stats.get("total_trades"):
                    notes_parts.append(f"과거 {stats['total_trades']}건")
                if regime_note:
                    notes_parts.append(regime_note)
                if drift_status in ("critical", "degrading"):
                    notes_parts.append(f"성과{drift_status}({drift_info.get('drift_pct', 0):+.0f}%)")

                # 최종 confidence 기록
                scoring["final_confidence"] = round(confidence, 2)

                candidates.append(
                    Candidate(
                        ticker=ticker,
                        signal_id=signal_id,
                        signal_date=df["date"].iloc[entry_idx].strftime("%Y-%m-%d"),
                        direction=direction,
                        confidence=round(confidence, 1),
                        win_rate=round(win_rate, 3),
                        profit_factor=round(pf, 2),
                        regime_fit=regime_fit,
                        price=round(float(df["close"].iloc[entry_idx]), 2),
                        notes="; ".join(notes_parts),
                        drift_status=drift_status,
                        scoring_detail=scoring,
                        unscored=unscored,
                        tier=tier,
                    )
                )

    # ── Conflict Detection: 방향 충돌 감지 + annotate ──
    try:
        from nuri.trading.engine.conflicts import detect_conflicts

        conflicts = detect_conflicts(candidates)
        # 충돌 종목 세트
        conflict_tickers = {}
        for cf in conflicts:
            if cf.conflict_type == "direction_conflict":
                conflict_tickers[cf.ticker] = cf.severity

        # 충돌 종목의 후보에 표시 + high severity면 confidence 할인
        # screen_candidates 가 생성한 candidate 는 항상 fresh (notes 에 "충돌" 사전 부재)
        # 하고 scoring_detail dict 가 항상 set 되므로 None 가드 불필요.
        for c in candidates:
            if c.ticker in conflict_tickers:
                c.conflict = "direction_conflict"
                sev = conflict_tickers[c.ticker]
                conflict_penalty = 1.0
                if sev == "high":
                    conflict_penalty = 0.5
                    c.confidence *= conflict_penalty
                    c.notes += "; BUY/SELL 충돌(관망 권장)" if c.notes else "BUY/SELL 충돌(관망 권장)"
                c.scoring_detail["conflict_penalty"] = conflict_penalty
                c.scoring_detail["final_confidence"] = round(c.confidence, 2)
    except Exception as e:
        logger.debug(f"Conflict detection 실패: {e}")

    # ── VIX Gate: 매수 후보 confidence 조정 ──
    # A-2b-pre: scoring_detail["final_confidence"] 도 함께 업데이트해야 A-2b
    # audit trail 이 stale 하지 않음 (codex A-2b-pre review Medium finding).
    # `vix_penalty` 필드 기록해 어느 경로로 discount 됐는지 surface.
    # screen_candidates 가 생성한 candidate 는 항상 scoring_detail dict 보유 → None 가드 불필요.
    if vix_gate["gate"] == "blocked":
        for c in candidates:
            if c.direction == "BUY":
                c.confidence = 0  # VIX > 30: BUY 후보 전부 차단
                c.notes = (c.notes + "; " if c.notes else "") + vix_gate["msg"]
                c.scoring_detail["vix_penalty"] = 0.0
                c.scoring_detail["final_confidence"] = 0.0
    elif vix_gate["gate"] == "caution":
        for c in candidates:
            if c.direction == "BUY":
                c.confidence *= 0.5  # VIX 25~30: 절반 포지션
                c.notes = (c.notes + "; " if c.notes else "") + vix_gate["msg"]
                c.scoring_detail["vix_penalty"] = 0.5
                c.scoring_detail["final_confidence"] = round(c.confidence, 2)

    # confidence 내림차순
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def print_candidates(candidates: list[Candidate]) -> None:
    """후보 리스트 CLI 출력."""
    if not candidates:
        print("매매 후보 없음 (최근 시그널 미발생)")
        return

    # B-2-ext: actionable vs advisory vs avoid 분리 — disclosure ≠ containment
    actionable = [c for c in candidates if c.tier == TIER_ACTIONABLE and c.regime_fit]
    advisory = [c for c in candidates if c.tier == TIER_ADVISORY and c.regime_fit]
    avoid = [c for c in candidates if c.tier == TIER_AVOID and c.regime_fit]
    buys = [c for c in actionable if c.direction == "BUY"]
    sells = [c for c in actionable if c.direction == "SELL"]
    conflicted = [c for c in candidates if c.conflict]
    regime_avoided = [c for c in candidates if not c.regime_fit]

    # VIX gate 상태 표시
    vix_gate = _check_vix_gate()
    print(f"\n{'=' * 85}")
    if vix_gate["gate"] == "blocked":
        print(f"  ⚠ {vix_gate['msg']}")
    elif vix_gate["gate"] == "caution":
        print(f"  ⚠ {vix_gate['msg']}")
    print(
        f"  Signal-Based Candidates — tier split ({len(actionable)} actionable / "
        f"{len(advisory)} advisory / {len(avoid)} avoid, 충돌 "
        f"{len(set(c.ticker for c in conflicted))}종목)"
    )
    print(f"{'=' * 85}")

    def _print_table(title, items, limit=15):
        if not items:
            return
        print(f"\n  {title} ({len(items)}건)")
        print(
            f"  {'Ticker':<8} {'Signal':<18} {'Date':<12} {'Conf':>5} {'WR':>6} {'PF':>6} {'Price':>10} {'Flags':<12}"
        )
        print(f"  {'-' * 80}")
        for c in items[:limit]:
            flags = []
            if c.unscored:
                flags.append("UNSCORED")
            if c.drift_status in ("critical", "degrading"):
                flags.append(f"D:{c.drift_status[:4]}")
            if c.conflict:
                flags.append("CONF")
            flag_str = " ".join(flags)
            if c.unscored:
                # 통계 없음 — 숫자 표시 대신 명시적 "—"
                wr_str = "—"
                pf_str = "—"
            else:
                wr_str = f"{c.win_rate:>5.0%}"
                pf_str = f"{c.profit_factor:>5.1f}"
            print(
                f"  {c.ticker:<8} {c.signal_id:<18} {c.signal_date:<12} "
                f"{c.confidence:>4.0f} {wr_str:>6} {pf_str:>6} ${c.price:>9,.2f} {flag_str:<12}"
            )

    # B-2-ext: tier 분리 표시 — actionable → advisory → avoid
    _print_table("✅ Actionable BUY", buys)
    _print_table("✅ Actionable SELL", sells)
    if advisory:
        _print_table("⚠️  Advisory (unscored / low-sample — 참고만)", advisory, limit=10)
    if avoid:
        _print_table("🚫 Avoid (negative-edge — 독립 행동 금지)", avoid, limit=10)

    if regime_avoided:
        print(f"\n  Regime-Filtered ({len(regime_avoided)}건 — 현재 레짐에서 비추천)")
        for c in regime_avoided[:5]:
            print(f"    {c.ticker} {c.signal_id} — {c.notes}")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 시그널 기반 매매 후보")
    parser.add_argument("--days", type=int, default=5, help="시그널 탐색 기간 (거래일)")
    args = parser.parse_args()

    candidates = screen_candidates(lookback_days=args.days)
    print_candidates(candidates)
