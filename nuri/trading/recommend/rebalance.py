"""
E-2: 레짐 적응 리밸런싱.

기존 MVO/RP 최적화 결과에 레짐 맥락(포지션 사이징, 섹터 틸트)을 반영하여
최종 리밸런싱 액션을 생성한다.

사용법:
    python -m nuri.trading.recommend.rebalance
    python -m nuri.trading.recommend.rebalance --method rp
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nuri.core.sectors import classify_sector

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

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
    action: str  # "BUY", "TRIM", "REDUCE", "HOLD"
    current_weight: float
    target_weight: float
    trade_value: float
    signals: list[str]  # 근거 시그널
    regime_note: str
    portfolio_action: str | None = None  # "REBALANCE" | "TRIM" | None


def _resolve_portfolio_total_value(base_df, db_path=None) -> float:
    """포트폴리오 총 평가액(USD) 계산.

    우선순위:
    1. base_df 에 `value_usd` 컬럼이 있으면 합계 사용.
    2. DB `portfolio` × 최신 `prices.close` 합계 조회 (`db_path` 전달).
    3. DB 미시드(mock 테스트 등) 시 `base_df` 의 `trade_value_usd / (opt_w - cur_w)` 로 역산.
    """
    if "value_usd" in base_df.columns:
        col_sum = float(base_df["value_usd"].fillna(0).sum())
        if col_sum > 0:
            return col_sum

    from nuri.core.db import query

    rows = query(
        """
        SELECT SUM(p.quantity * latest.close) AS total_value
        FROM portfolio p
        JOIN (
            SELECT ticker, close
            FROM prices
            WHERE (ticker, date) IN (
                SELECT ticker, MAX(date) FROM prices GROUP BY ticker
            )
        ) latest ON p.ticker = latest.ticker
        WHERE p.quantity > 0
        """,
        db_path=db_path,
    )
    if rows and rows[0]["total_value"] and rows[0]["total_value"] > 0:
        return float(rows[0]["total_value"])

    sum_trade = 0.0
    sum_diff = 0.0
    for _, row in base_df.iterrows():
        base_diff = abs((row["optimal_weight"] - row["current_weight"]) / 100.0)
        tv = abs(float(row.get("trade_value_usd") or 0.0))
        if base_diff > 1e-6 and tv > 0:
            sum_trade += tv
            sum_diff += base_diff
    if sum_diff > 0:
        return sum_trade / sum_diff
    return 0.0


def regime_aware_rebalance(method: str = "rp", db_path=None) -> list[RebalanceAction]:
    """레짐 맥락을 반영한 리밸런싱 액션 생성. Gate 검증 후 실행."""
    # Gate 검증
    try:
        from nuri.trading.engine.gate import check_gate

        gate = check_gate("recommend", db_path)
        if not gate.ready:
            failed = [c for c in gate.conditions if not c.passed]
            logger.warning(f"[GATE BLOCKED] recommend 단계 실행 불가. 미충족 조건: {', '.join(c.id for c in failed)}")
            # 블로킹하지 않고 경고만 (데이터 부족해도 가능한 범위에서 실행)
    except Exception:
        pass

    import inspect

    from nuri.analysis.rebalance import analyze_rebalance
    from nuri.core import db as _db_facade
    from nuri.quant.regime.classifier import classify_regime
    from nuri.quant.regime.strategy_map import map_regime_to_strategy

    # 1. 기존 MVO/RP 결과 (db_path 전달 — 미지원 시 호출 구간만 facade DB_PATH 바인딩)
    sig = inspect.signature(analyze_rebalance)
    accepts_db_path = "db_path" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_db_path:
        analyze_fn: Any = analyze_rebalance
        base_df = analyze_fn(method=method, db_path=db_path)
    elif db_path is not None:
        prev_db_path = _db_facade.DB_PATH
        _db_facade.DB_PATH = db_path
        try:
            base_df = analyze_rebalance(method=method)
        finally:
            _db_facade.DB_PATH = prev_db_path
    else:
        base_df = analyze_rebalance(method=method)
    if base_df.empty:
        logger.warning("기존 리밸런싱 결과 없음")
        return []

    # 2. 레짐 + 전략
    regime = classify_regime(db_path=db_path)
    strategy = map_regime_to_strategy(regime, db_path=db_path) if regime else None

    position = strategy.position_sizing if strategy else "normal"
    cash_target = CASH_TARGETS.get(position, 0.05)
    regime_name = regime.regime if regime else "unknown"

    # 3. E-1 후보 시그널 매핑 + Conflict 감지 — actionable tier 만 (B-2-ext codex P1).
    signal_map: dict[str, list[str]] = {}
    conflict_tickers: set[str] = set()
    try:
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE, screen_candidates

        candidates = screen_candidates(lookback_days=5, db_path=db_path)
        for c in candidates:
            if c.regime_fit and c.tier == TIER_ACTIONABLE:
                signal_map.setdefault(c.ticker, []).append(f"{c.signal_id}({c.direction})")

        from nuri.trading.engine.conflicts import detect_conflicts

        conflicts = detect_conflicts(candidates, db_path=db_path)
        conflict_tickers = {
            cf.ticker for cf in conflicts if cf.conflict_type == "direction_conflict" and cf.severity == "high"
        }
        if conflict_tickers:
            logger.info(f"Conflict 종목 HOLD 강제: {', '.join(conflict_tickers)}")
    except Exception:
        pass

    # 4. 비중 조정
    actions = []
    portfolio_total_value = _resolve_portfolio_total_value(base_df, db_path=db_path)

    for _, row in base_df.iterrows():
        ticker = row["ticker"]
        sector = row.get("sector", "")
        cur_w = row["current_weight"] / 100
        opt_w = row["optimal_weight"] / 100

        # 현금 비중 반영: 모든 최적 비중을 축소
        adj_w = opt_w * (1 - cash_target)

        # 섹터 틸트: 명시적 분류 기반 가점/감점
        if sector and position in ("defensive", "minimal"):
            sector_type = classify_sector(sector)
            if sector_type == "defensive":
                adj_w *= 1.1  # 방어 섹터 10% 가점
            elif sector_type == "growth":
                adj_w *= 0.85  # 성장 섹터 15% 감점

        # 액션 결정 (리밸런싱 비중 축소는 포트폴리오 축 — alpha SELL/FLAT 으로 혼동 금지)
        diff = adj_w - cur_w
        portfolio_action: str | None = None

        if ticker in conflict_tickers and diff > 0:
            action = "HOLD"  # 방향 충돌 종목은 매수 차단
            adj_w = cur_w
            regime_note = f"[{regime_name}] BUY/SELL 충돌 → 관망"
        elif position == "minimal" and diff > 0:
            action = "HOLD"  # minimal에서는 신규 매수 차단
            adj_w = cur_w
            regime_note = f"[{regime_name}] 신규 매수 차단"
        elif diff < -0.02:
            action = "TRIM" if diff < -0.05 else "REDUCE"
            portfolio_action = "TRIM"
            regime_note = f"[{regime_name}] 비중 축소"
        elif diff > 0.02:
            action = "BUY"
            portfolio_action = "REBALANCE"
            regime_note = f"[{regime_name}] 비중 확대"
        else:
            action = "HOLD"
            regime_note = f"[{regime_name}]"

        trade_val = round((adj_w - cur_w) * portfolio_total_value, 2)
        signals = signal_map.get(ticker, [])

        actions.append(
            RebalanceAction(
                ticker=ticker,
                sector=sector,
                action=action,
                current_weight=round(cur_w * 100, 2),
                target_weight=round(adj_w * 100, 2),
                trade_value=trade_val,
                signals=signals,
                regime_note=regime_note,
                portfolio_action=portfolio_action,
            )
        )

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
            print(
                f"  {a.ticker:<8} {a.action:<8} {a.current_weight:>6.1f}% {a.target_weight:>6.1f}% "
                f"{diff:>+6.1f}% {sig_str:<30}"
            )

    holds = [a for a in actions if a.action == "HOLD"]
    if holds:
        print(f"\n  HOLD: {', '.join(a.ticker for a in holds)}")

    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — regime-aware rebalance runner."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 레짐 적응 리밸런싱")
    parser.add_argument("--method", choices=["mvo", "rp"], default="rp")
    args = parser.parse_args(argv)

    actions = regime_aware_rebalance(method=args.method)
    print_rebalance(actions)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
