"""
Conflict Detection — SIEGE 패턴 적용.

같은 종목에 대해 상반된 시그널이 동시 발생할 때 이를 감지하고,
충돌 유형을 분류하여 사용자에게 명시적으로 보여준다.

충돌 유형:
- direction_conflict: 같은 종목에 BUY/SELL 동시 발생
- strength_mismatch: 약한 시그널과 강한 시그널 공존
- regime_contradiction: 시그널 방향이 현재 레짐과 모순

사용법:
    python -m nuri.trading.engine.conflicts
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SignalConflict:
    """시그널 충돌."""
    ticker: str
    conflict_type: str      # direction_conflict, strength_mismatch, regime_contradiction
    severity: str           # "high", "medium", "low"
    buy_signals: list[str]  # 매수 시그널 목록
    sell_signals: list[str] # 매도 시그널 목록
    detail: str
    recommendation: str     # 사용자에게 권장 행동


def detect_conflicts(candidates=None, db_path=None) -> list[SignalConflict]:
    """매매 후보에서 시그널 충돌을 감지.

    Args:
        candidates: E-1 screen_candidates() 결과. None이면 자동 호출.
    """
    if candidates is None:
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=5, db_path=db_path)

    if not candidates:
        return []

    # B-2-ext codex P2: advisory/avoid 는 direction_conflict 산정에서 제외.
    # 포함 시 actionable BUY + unscored SELL 이 "direction conflict" 로 flagged
    # 되어 actionable BUY 의 confidence 가 0.5x 로 할인되는 regression 발생
    # (약한 증거가 강한 증거를 suppress). 이전 B-2 패치에서 unscored 만 제외했으나
    # low-sample/negative-edge (advisory/avoid) 도 동일 논리로 제외해야 함.
    from nuri.trading.recommend.candidates import TIER_ACTIONABLE
    # A-6: `Candidate.tier` 는 dataclass default 가 있어 항상 존재 → `getattr` 불필요.
    candidates = [c for c in candidates if c.tier == TIER_ACTIONABLE]

    if not candidates:
        return []

    # 종목별로 시그널 분류
    ticker_signals: dict[str, dict[str, list]] = {}
    for c in candidates:
        t = c.ticker
        if t not in ticker_signals:
            ticker_signals[t] = {"buy": [], "sell": [], "candidates": []}
        if c.direction == "BUY":
            ticker_signals[t]["buy"].append(c)
        else:
            ticker_signals[t]["sell"].append(c)
        ticker_signals[t]["candidates"].append(c)

    conflicts = []

    for ticker, sigs in ticker_signals.items():
        buy_list = sigs["buy"]
        sell_list = sigs["sell"]

        # ── 1. Direction Conflict: 같은 종목에 BUY + SELL ──
        if buy_list and sell_list:
            buy_names = list(set(c.signal_id for c in buy_list))
            sell_names = list(set(c.signal_id for c in sell_list))

            # 심각도: 둘 다 regime_fit이면 high, 한쪽만이면 medium
            fit_buys = [c for c in buy_list if c.regime_fit]
            fit_sells = [c for c in sell_list if c.regime_fit]

            if fit_buys and fit_sells:
                severity = "high"
                detail = (f"BUY({', '.join(buy_names)})와 SELL({', '.join(sell_names)})이 "
                         f"모두 레짐 적합. 방향 판단 불가.")
                recommendation = "관망 권장. 추가 정보(펀더멘탈, 뉴스) 확인 후 판단."
            else:
                severity = "medium"
                detail = (f"BUY({', '.join(buy_names)})와 SELL({', '.join(sell_names)}) 공존. "
                         f"레짐 적합 시그널 우선.")
                recommendation = "레짐 적합 시그널 방향 따르되, 포지션 축소."

            conflicts.append(SignalConflict(
                ticker=ticker,
                conflict_type="direction_conflict",
                severity=severity,
                buy_signals=buy_names,
                sell_signals=sell_names,
                detail=detail,
                recommendation=recommendation,
            ))

        # ── 2. Strength Mismatch: PF 격차 큰 시그널 공존 ──
        # Tier 필터가 이미 direction_conflict 스텝에서 적용됨 (actionable 만 통과)
        # → sigs["candidates"] 는 전부 actionable. 추가 unscored 필터 불필요.
        all_cands = sigs["candidates"]
        if len(all_cands) >= 2:
            pfs = [c.profit_factor for c in all_cands]
            max_pf = max(pfs)
            min_pf = min(pfs)

            if max_pf > 3 * min_pf and min_pf < 1.5:
                strong = [c for c in all_cands if c.profit_factor == max_pf][0]
                weak = [c for c in all_cands if c.profit_factor == min_pf][0]

                conflicts.append(SignalConflict(
                    ticker=ticker,
                    conflict_type="strength_mismatch",
                    severity="low",
                    buy_signals=[c.signal_id for c in buy_list],
                    sell_signals=[c.signal_id for c in sell_list],
                    detail=(f"강한 시그널({strong.signal_id}, PF={strong.profit_factor:.1f})과 "
                           f"약한 시그널({weak.signal_id}, PF={weak.profit_factor:.1f}) 공존."),
                    recommendation=f"강한 시그널({strong.signal_id}) 우선 신뢰.",
                ))

    # ── 3. Regime Contradiction: 레짐과 모순되는 시그널 ──
    regime_ctx = None
    try:
        from nuri.quant.regime.classifier import classify_regime
        regime = classify_regime(db_path=db_path)
        if regime:
            regime_ctx = regime.trend
    except Exception:
        pass

    if regime_ctx:
        for ticker, sigs in ticker_signals.items():
            # bear인데 BUY 시그널만 있는 경우
            if regime_ctx == "bear" and sigs["buy"] and not sigs["sell"]:
                buy_names = list(set(c.signal_id for c in sigs["buy"]))
                fit = [c for c in sigs["buy"] if c.regime_fit]
                if fit:  # 레짐 적합이라고 판정됐지만 추세와 반대
                    continue  # 교차분석에서 이미 검증됨
                conflicts.append(SignalConflict(
                    ticker=ticker,
                    conflict_type="regime_contradiction",
                    severity="medium",
                    buy_signals=buy_names,
                    sell_signals=[],
                    detail=f"하락장(bear)에서 매수 시그널({', '.join(buy_names)}) 발생.",
                    recommendation="역추세 매수는 높은 리스크. 분할매수 또는 관망.",
                ))

            # bull인데 SELL 시그널만 있는 경우
            if regime_ctx == "bull" and sigs["sell"] and not sigs["buy"]:
                sell_names = list(set(c.signal_id for c in sigs["sell"]))
                fit = [c for c in sigs["sell"] if c.regime_fit]
                if fit:
                    continue
                conflicts.append(SignalConflict(
                    ticker=ticker,
                    conflict_type="regime_contradiction",
                    severity="medium",
                    buy_signals=[],
                    sell_signals=sell_names,
                    detail=f"상승장(bull)에서 매도 시그널({', '.join(sell_names)}) 발생.",
                    recommendation="추세 매도는 조기일 수 있음. 부분 매도 고려.",
                ))

    # 심각도 순 정렬 (high > medium > low)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    conflicts.sort(key=lambda c: severity_order.get(c.severity, 3))

    return conflicts


def print_conflicts(conflicts: list[SignalConflict]) -> None:
    if not conflicts:
        print("시그널 충돌 없음")
        return

    print(f"\n{'=' * 65}")
    print(f"  Signal Conflicts ({len(conflicts)}건)")
    print(f"{'=' * 65}")

    for c in conflicts:
        sev_icon = {"high": "[!!!]", "medium": "[!!]", "low": "[!]"}
        print(f"\n  {sev_icon.get(c.severity, '[ ]')} {c.ticker} — {c.conflict_type}")
        print(f"      {c.detail}")
        print(f"      -> {c.recommendation}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conflicts = detect_conflicts()
    print_conflicts(conflicts)
