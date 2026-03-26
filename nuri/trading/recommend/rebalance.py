"""
E-2: 레짐 적응 리밸런싱.

기존 MVO/RP 최적화 결과에 레짐 맥락(포지션 사이징, 섹터 틸트)을 반영하여
최종 리밸런싱 액션을 생성한다.

사용법:
    python -m nuri.recommend.rebalance
    python -m nuri.recommend.rebalance --method rp
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from nuri.core.db import query

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# 포트폴리오 sector 값 → 방어/공격 분류
# portfolio.yaml의 sector 필드가 다양한 형태("SectorA", "Finance", "AI/Cloud" 등)이므로
# 키워드 포함 여부가 아닌 명시적 매핑 사용
DEFENSIVE_SECTOR_KEYWORDS = {
    "Staples", "Utilities", "Health", "Real Estate", "Insurance", "Bond",
    "Defense", "Pharma",
}
GROWTH_SECTOR_KEYWORDS = {
    "Technology", "Tech", "AI", "Cloud", "EV", "Semiconductor", "Software",
    "Consumer Discretionary", "Communication", "Growth", "Innovation",
}


def _classify_sector(sector: str) -> str:
    """포트폴리오 sector 문자열을 defensive/growth/neutral로 분류."""
    if not sector:
        return "neutral"
    upper = sector.upper()
    for kw in DEFENSIVE_SECTOR_KEYWORDS:
        if kw.upper() in upper:
            return "defensive"
    for kw in GROWTH_SECTOR_KEYWORDS:
        if kw.upper() in upper:
            return "growth"
    return "neutral"


# 레짐별 현금 비중
CASH_TARGETS = {
    "aggressive": 0.0,
    "normal": 0.05,
    "defensive": 0.20,
    "minimal": 0.40,
}


@dataclass
class RebalanceAction:
    """레짐 적응 리밸런싱 액션."""
    ticker: str
    sector: str
    action: str             # "BUY", "SELL", "HOLD", "REDUCE"
    current_weight: float
    target_weight: float
    trade_value: float
    signals: list[str]      # 근거 시그널
    regime_note: str


def regime_aware_rebalance(method: str = "rp", db_path=None) -> list[RebalanceAction]:
    """레짐 맥락을 반영한 리밸런싱 액션 생성. Gate 검증 후 실행."""
    # Gate 검증
    try:
        from nuri.engine.gate import check_gate
        gate = check_gate("recommend", db_path)
        if not gate.ready:
            failed = [c for c in gate.conditions if not c.passed]
            logger.warning(
                f"[GATE BLOCKED] recommend 단계 실행 불가. "
                f"미충족 조건: {', '.join(c.id for c in failed)}"
            )
            # 블로킹하지 않고 경고만 (데이터 부족해도 가능한 범위에서 실행)
    except Exception:
        pass

    from nuri.analysis.rebalance import analyze_rebalance
    from nuri.analysis.regime.classifier import classify_regime
    from nuri.analysis.regime.strategy_map import map_regime_to_strategy

    # 1. 기존 MVO/RP 결과
    base_df = analyze_rebalance(method=method)
    if base_df.empty:
        logger.warning("기존 리밸런싱 결과 없음")
        return []

    # 2. 레짐 + 전략
    regime = classify_regime(db_path=db_path)
    strategy = map_regime_to_strategy(regime, db_path=db_path) if regime else None

    position = strategy.position_sizing if strategy else "normal"
    cash_target = CASH_TARGETS.get(position, 0.05)
    preferred_sectors = strategy.sector_preference if strategy else []
    regime_name = regime.regime if regime else "unknown"

    # 3. E-1 후보 시그널 매핑 + Conflict 감지
    signal_map: dict[str, list[str]] = {}
    conflict_tickers: set[str] = set()
    try:
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=5, db_path=db_path)
        for c in candidates:
            if c.regime_fit:
                signal_map.setdefault(c.ticker, []).append(f"{c.signal_id}({c.direction})")

        from nuri.engine.conflicts import detect_conflicts
        conflicts = detect_conflicts(candidates)
        conflict_tickers = {
            cf.ticker for cf in conflicts
            if cf.conflict_type == "direction_conflict" and cf.severity == "high"
        }
        if conflict_tickers:
            logger.info(f"Conflict 종목 HOLD 강제: {', '.join(conflict_tickers)}")
    except Exception:
        pass

    # 4. 비중 조정
    actions = []
    total_value = sum(abs(row["trade_value_usd"]) for _, row in base_df.iterrows()
                      if row["action"] != "HOLD") or 1

    for _, row in base_df.iterrows():
        ticker = row["ticker"]
        sector = row.get("sector", "")
        cur_w = row["current_weight"] / 100
        opt_w = row["optimal_weight"] / 100

        # 현금 비중 반영: 모든 최적 비중을 축소
        adj_w = opt_w * (1 - cash_target)

        # 섹터 틸트: 명시적 분류 기반 가점/감점
        if sector and position in ("defensive", "minimal"):
            sector_type = _classify_sector(sector)
            if sector_type == "defensive":
                adj_w *= 1.1  # 방어 섹터 10% 가점
            elif sector_type == "growth":
                adj_w *= 0.85  # 성장 섹터 15% 감점

        # 액션 결정
        diff = adj_w - cur_w
        trade_val = diff * total_value * 100  # 대략적 거래금액

        if ticker in conflict_tickers and diff > 0:
            action = "HOLD"  # 방향 충돌 종목은 매수 차단
            adj_w = cur_w
            regime_note = f"[{regime_name}] BUY/SELL 충돌 → 관망"
        elif position == "minimal" and diff > 0:
            action = "HOLD"  # minimal에서는 신규 매수 차단
            adj_w = cur_w
            regime_note = f"[{regime_name}] 신규 매수 차단"
        elif diff < -0.02:
            action = "SELL" if diff < -0.05 else "REDUCE"
            regime_note = f"[{regime_name}] 비중 축소"
        elif diff > 0.02:
            action = "BUY"
            regime_note = f"[{regime_name}] 비중 확대"
        else:
            action = "HOLD"
            regime_note = f"[{regime_name}]"

        signals = signal_map.get(ticker, [])

        actions.append(RebalanceAction(
            ticker=ticker,
            sector=sector,
            action=action,
            current_weight=round(cur_w * 100, 2),
            target_weight=round(adj_w * 100, 2),
            trade_value=round(trade_val, 0),
            signals=signals,
            regime_note=regime_note,
        ))

    # 액션 있는 것 우선 정렬
    actions.sort(key=lambda a: (a.action == "HOLD", -abs(a.target_weight - a.current_weight)))
    return actions


def print_rebalance(actions: list[RebalanceAction]) -> None:
    """레짐 적응 리밸런싱 출력."""
    if not actions:
        print("리밸런싱 데이터 없음")
        return

    regime_note = actions[0].regime_note.split("]")[0] + "]" if actions else ""
    actionable = [a for a in actions if a.action != "HOLD"]

    print(f"\n{'=' * 75}")
    print(f"  Regime-Aware Rebalancing {regime_note}")
    print(f"{'=' * 75}")

    if not actionable:
        print("  리밸런싱 불필요")
    else:
        print(f"  {'Ticker':<8} {'Action':<8} {'현재%':>7} {'목표%':>7} {'차이':>7} {'시그널':<30}")
        print(f"  {'-' * 70}")
        for a in actionable:
            sig_str = ", ".join(a.signals[:2]) if a.signals else "—"
            diff = a.target_weight - a.current_weight
            print(f"  {a.ticker:<8} {a.action:<8} {a.current_weight:>6.1f}% {a.target_weight:>6.1f}% "
                  f"{diff:>+6.1f}% {sig_str:<30}")

    holds = [a for a in actions if a.action == "HOLD"]
    if holds:
        print(f"\n  HOLD: {', '.join(a.ticker for a in holds)}")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 레짐 적응 리밸런싱")
    parser.add_argument("--method", choices=["mvo", "rp"], default="rp")
    args = parser.parse_args()

    actions = regime_aware_rebalance(method=args.method)
    print_rebalance(actions)
