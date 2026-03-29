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
    SIGNAL_DEFINITIONS,
    compute_indicators,
    detect_signal_entries,
    merge_data_signals,
    merge_macro_data,
)

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# 매수/매도 분류
BUY_SIGNALS = {
    "rsi_oversold", "macd_golden", "sma_golden", "bb_bounce",
    "volume_spike", "gap_up",
    "vix_reversal", "pcr_reversal", "yield_curve_recovery",
    "insider_cluster", "short_squeeze",
}
SELL_SIGNALS = {"rsi_overbought", "macd_dead", "sma_dead", "gap_down"}


@dataclass
class Candidate:
    """매매 후보."""
    ticker: str
    signal_id: str
    signal_date: str
    direction: str          # "BUY" or "SELL"
    confidence: float       # 0~100
    win_rate: float
    profit_factor: float
    regime_fit: bool
    price: float
    notes: str
    drift_status: str = ""          # "stable", "degrading", "critical" (from Learning Memory)
    conflict: str = ""              # "" or "direction_conflict" (from Conflict Detection)
    scoring_detail: dict | None = None  # confidence 계산 요인 기록


def _load_scorecard() -> tuple[dict[str, dict], int | None]:
    """최신 signal_scorecard.csv에서 시그널별 통계 로드.

    Returns:
        (scorecard_dict, age_days): 스코어카드 데이터와 파일 나이(일). 파일 없으면 ({}, None).
    """
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
    "critical": 0.3,    # 성과 급락 → 70% 할인
    "degrading": 0.6,   # 성과 하락 → 40% 할인
    "improving": 1.1,   # 성과 개선 → 10% 가점
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

    if vix >= VIX_BLOCK_ABOVE:
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
            (ticker,), db_path=db_path,
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
            entries = detect_signal_entries(df, signal_id)
            # cutoff 이후 발생한 시그널만
            recent = [idx for idx in entries if idx >= cutoff_idx]

            for entry_idx in recent:
                stats = scorecard.get(signal_id, {})
                win_rate = stats.get("win_rate", 0.5)
                pf = stats.get("profit_factor", 1.0)

                direction = "BUY" if signal_id in BUY_SIGNALS else "SELL"

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

                # scoring_detail 기록용
                scoring = {
                    "win_rate": round(win_rate, 4),
                    "profit_factor": round(pf, 2),
                    "regime": regime_ctx.get("regime", "") if regime_ctx else "",
                    "regime_fit": regime_fit,
                }

                if sig_in_regime and sig_in_regime.get("trades", 0) >= 5:
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
                    # 폴백: 전체 승률 기반 (레짐 무관)
                    pf_normalized = min(pf / 5.0, 1.0)
                    regime_bonus = 1.0 if regime_fit else 0.3
                    confidence = (win_rate * 40 + pf_normalized * 30 + regime_bonus * 30)
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

                candidates.append(Candidate(
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
                ))

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
        for c in candidates:
            if c.ticker in conflict_tickers:
                c.conflict = "direction_conflict"
                sev = conflict_tickers[c.ticker]
                conflict_penalty = 1.0
                if sev == "high":
                    conflict_penalty = 0.5
                    c.confidence *= conflict_penalty
                    if "충돌" not in c.notes:
                        c.notes += "; BUY/SELL 충돌(관망 권장)" if c.notes else "BUY/SELL 충돌(관망 권장)"
                # scoring_detail에 충돌 페널티 기록
                if c.scoring_detail is not None:
                    c.scoring_detail["conflict_penalty"] = conflict_penalty
                    c.scoring_detail["final_confidence"] = round(c.confidence, 2)
    except Exception as e:
        logger.debug(f"Conflict detection 실패: {e}")

    # ── VIX Gate: 매수 후보 confidence 조정 ──
    if vix_gate["gate"] == "blocked":
        for c in candidates:
            if c.direction == "BUY":
                c.confidence = 0  # VIX > 30: BUY 후보 전부 차단
                c.notes = (c.notes + "; " if c.notes else "") + vix_gate["msg"]
    elif vix_gate["gate"] == "caution":
        for c in candidates:
            if c.direction == "BUY":
                c.confidence *= 0.5  # VIX 25~30: 절반 포지션
                c.notes = (c.notes + "; " if c.notes else "") + vix_gate["msg"]

    # confidence 내림차순
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def print_candidates(candidates: list[Candidate]) -> None:
    """후보 리스트 CLI 출력."""
    if not candidates:
        print("매매 후보 없음 (최근 시그널 미발생)")
        return

    buys = [c for c in candidates if c.direction == "BUY" and c.regime_fit]
    sells = [c for c in candidates if c.direction == "SELL" and c.regime_fit]
    conflicted = [c for c in candidates if c.conflict]
    avoided = [c for c in candidates if not c.regime_fit]

    # VIX gate 상태 표시
    vix_gate = _check_vix_gate()
    print(f"\n{'=' * 85}")
    if vix_gate["gate"] == "blocked":
        print(f"  ⚠ {vix_gate['msg']}")
    elif vix_gate["gate"] == "caution":
        print(f"  ⚠ {vix_gate['msg']}")
    print(f"  Signal-Based Candidates ({len(candidates)}건, 레짐 적합 {len(buys)+len(sells)}건, 충돌 {len(set(c.ticker for c in conflicted))}종목)")
    print(f"{'=' * 85}")

    def _print_table(title, items, limit=15):
        if not items:
            return
        print(f"\n  {title} ({len(items)}건)")
        print(f"  {'Ticker':<8} {'Signal':<18} {'Date':<12} {'Conf':>5} {'WR':>6} {'PF':>6} {'Price':>10} {'Flags':<12}")
        print(f"  {'-' * 80}")
        for c in items[:limit]:
            flags = []
            if c.drift_status in ("critical", "degrading"):
                flags.append(f"D:{c.drift_status[:4]}")
            if c.conflict:
                flags.append("CONF")
            flag_str = " ".join(flags)
            print(f"  {c.ticker:<8} {c.signal_id:<18} {c.signal_date:<12} "
                  f"{c.confidence:>4.0f} {c.win_rate:>5.0%} {c.profit_factor:>5.1f} ${c.price:>9,.2f} {flag_str:<12}")

    _print_table("BUY Candidates", buys)
    _print_table("SELL Candidates", sells)

    if avoided:
        print(f"\n  Regime-Filtered ({len(avoided)}건 — 현재 레짐에서 비추천)")
        for c in avoided[:5]:
            print(f"    {c.ticker} {c.signal_id} — {c.notes}")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 시그널 기반 매매 후보")
    parser.add_argument("--days", type=int, default=5, help="시그널 탐색 기간 (거래일)")
    args = parser.parse_args()

    candidates = screen_candidates(lookback_days=args.days)
    print_candidates(candidates)
