"""
리밸런싱 어드바이저 — 투자 규칙 위반 감지 및 매도 수량 추천.

rules.yaml 기반으로 포트폴리오 위반 사항을 탐지하고,
우선순위에 따라 구체적인 매도 수량과 회수 금액을 계산한다.

사용법:
    python -m nuri.analysis.rebalance_advisor
"""
import logging
import math
from pathlib import Path
from typing import Optional

from nuri.analysis.portfolio import analyze_portfolio
from nuri.core.db import query, query_df  # noqa: F401
from nuri.core.rules import (
    LEVERAGE_ETFS,
    MAX_SECTOR_EXPOSURE,
    MAX_SINGLE_POSITION,
    MIN_CASH_RESERVE,  # noqa: F401 — 외부 모듈에서 참조용
    SELL_PRIORITY,
    STOCK_STOP_LOSS,
)

logger = logging.getLogger(__name__)

# SELL_PRIORITY 카테고리 → 우선순위 매핑
_PRIORITY_MAP = {category: idx + 1 for idx, category in enumerate(SELL_PRIORITY)}


def _get_factor_scores(db_path: Optional[Path] = None) -> dict[str, float]:
    """종목별 최신 composite_score 조회. 팩터 점수가 낮을수록 매도 우선."""
    rows = query(
        """
        SELECT f.ticker, f.composite_score
        FROM factors f
        INNER JOIN (
            SELECT ticker, MAX(date) AS max_date FROM factors GROUP BY ticker
        ) latest ON f.ticker = latest.ticker AND f.date = latest.max_date
        """,
        db_path=db_path,
    )
    return {row["ticker"]: row["composite_score"] for row in rows if row["composite_score"] is not None}


def _severity(violation_type: str, current_value: float, limit_value: float) -> str:
    """위반 심각도 판단."""
    if violation_type == "leverage_etf":
        return "critical"
    if violation_type == "stop_loss_exceeded":
        # 손절선 대비 2배 이상 초과하면 critical
        if current_value <= limit_value * 2:
            return "critical"
        return "high"
    if violation_type == "position_limit_exceeded":
        # 한도 대비 10%p 이상 초과하면 high
        excess = current_value / 100 - limit_value
        if excess > 0.10:
            return "high"
        return "medium"
    if violation_type == "sector_limit_exceeded":
        excess = current_value / 100 - limit_value
        if excess > 0.10:
            return "high"
        return "medium"
    return "medium"


def detect_violations(db_path: Optional[Path] = None) -> list[dict]:
    """포트폴리오 투자 규칙 위반 사항 탐지.

    Returns:
        위반 사항 리스트 (priority 순 정렬). 위반 없으면 빈 리스트.
    """
    df = analyze_portfolio()
    if df.empty:
        logger.info("포트폴리오가 비어 있습니다")
        return []

    total_value = df.attrs.get("total_value_usd", df["current_value_usd"].sum())
    violations: list[dict] = []

    # 종목별 합산 (다계좌 동일 종목)
    ticker_agg = df.groupby("ticker").agg(
        weight_pct=("weight_pct", "sum"),
        quantity=("quantity", "sum"),
        current_price=("current_price", "first"),
        pnl_pct=("pnl_pct", "first"),
        current_value_usd=("current_value_usd", "sum"),
        sector=("sector", "first"),
        currency=("currency", "first"),
    ).reset_index()

    # ─── 1. 레버리지 ETF 위반 (priority 1) ───
    for _, row in ticker_agg.iterrows():
        ticker = row["ticker"]
        if ticker in LEVERAGE_ETFS:
            qty = int(row["quantity"])
            sell_value = row["current_value_usd"]
            violations.append({
                "ticker": ticker,
                "violation_type": "leverage_etf",
                "priority": _PRIORITY_MAP.get("leverage_etf", 1),
                "current_value": row["pnl_pct"],
                "limit_value": 0,
                "severity": "critical",
                "action": "SELL_ALL",
                "sell_shares": qty,
                "sell_value_usd": round(sell_value, 2),
                "reason": "레버리지 ETF 금지",
            })

    # ─── 2. 손절선 초과 (priority 2) ───
    stop_loss_violations = []
    for _, row in ticker_agg.iterrows():
        ticker = row["ticker"]
        if ticker in LEVERAGE_ETFS:
            continue  # 이미 레버리지에서 처리
        pnl_pct = row["pnl_pct"]
        if pnl_pct < STOCK_STOP_LOSS:
            qty = int(row["quantity"])
            sell_value = row["current_value_usd"]
            stop_loss_violations.append({
                "ticker": ticker,
                "violation_type": "stop_loss_exceeded",
                "priority": _PRIORITY_MAP.get("stop_loss_exceeded", 2),
                "current_value": pnl_pct,
                "limit_value": STOCK_STOP_LOSS,
                "severity": _severity("stop_loss_exceeded", pnl_pct, STOCK_STOP_LOSS),
                "action": "SELL_ALL",
                "sell_shares": qty,
                "sell_value_usd": round(sell_value, 2),
                "reason": f"손절 {pnl_pct:+.1f}% 초과 (한도 {STOCK_STOP_LOSS}%)",
            })
    # 손실이 큰 순서로 정렬
    stop_loss_violations.sort(key=lambda v: v["current_value"])
    violations.extend(stop_loss_violations)

    # ─── 3. 단일 종목 비중 초과 (priority 4) ───
    for _, row in ticker_agg.iterrows():
        ticker = row["ticker"]
        if ticker in LEVERAGE_ETFS:
            continue
        weight = row["weight_pct"]
        if weight / 100 > MAX_SINGLE_POSITION:
            # 목표 비중까지 줄이기 위한 매도 수량 계산
            target_value = total_value * MAX_SINGLE_POSITION
            excess_value = row["current_value_usd"] - target_value
            current_price = row["current_price"]
            if current_price > 0:
                sell_shares = math.ceil(excess_value / current_price)
            else:
                sell_shares = int(row["quantity"])
            sell_value = sell_shares * current_price

            violations.append({
                "ticker": ticker,
                "violation_type": "position_limit_exceeded",
                "priority": _PRIORITY_MAP.get("position_limit_exceeded", 4),
                "current_value": weight,
                "limit_value": MAX_SINGLE_POSITION,
                "severity": _severity("position_limit_exceeded", weight, MAX_SINGLE_POSITION),
                "action": "REDUCE",
                "sell_shares": sell_shares,
                "sell_value_usd": round(sell_value, 2),
                "reason": f"비중 {weight:.1f}% > 한도 {MAX_SINGLE_POSITION * 100:.0f}%",
            })

    # ─── 4. 섹터 비중 초과 (priority 5) ───
    sector_weights = ticker_agg.groupby("sector")["weight_pct"].sum()
    factor_scores = _get_factor_scores(db_path)

    for sector, sector_weight in sector_weights.items():
        if not sector or sector == "Unknown":
            continue
        if sector_weight / 100 > MAX_SECTOR_EXPOSURE:
            # 해당 섹터 종목 중 팩터 점수가 낮은 순서로 매도
            sector_tickers = ticker_agg[ticker_agg["sector"] == sector].copy()
            sector_tickers["factor_score"] = sector_tickers["ticker"].map(
                lambda t: factor_scores.get(t, 0.0)
            )
            sector_tickers = sector_tickers.sort_values("factor_score", ascending=True)

            excess_weight = sector_weight / 100 - MAX_SECTOR_EXPOSURE
            excess_value = excess_weight * total_value
            remaining_excess = excess_value

            for _, row in sector_tickers.iterrows():
                ticker = row["ticker"]
                if ticker in LEVERAGE_ETFS:
                    continue
                # 이미 다른 위반으로 전량 매도 대상이면 건너뜀
                already_sell_all = any(
                    v["ticker"] == ticker and v["action"] == "SELL_ALL"
                    for v in violations
                )
                if already_sell_all:
                    remaining_excess -= row["current_value_usd"]
                    if remaining_excess <= 0:
                        break
                    continue

                current_price = row["current_price"]
                if current_price <= 0:
                    continue

                if remaining_excess >= row["current_value_usd"]:
                    # 전량 매도
                    sell_shares = int(row["quantity"])
                    sell_value = row["current_value_usd"]
                    action = "SELL_ALL"
                    remaining_excess -= sell_value
                else:
                    # 일부 매도
                    sell_shares = math.ceil(remaining_excess / current_price)
                    sell_shares = min(sell_shares, int(row["quantity"]))
                    sell_value = sell_shares * current_price
                    action = "REDUCE"
                    remaining_excess -= sell_value

                violations.append({
                    "ticker": ticker,
                    "violation_type": "sector_limit_exceeded",
                    "priority": _PRIORITY_MAP.get("sector_limit_exceeded", 5),
                    "current_value": sector_weight,
                    "limit_value": MAX_SECTOR_EXPOSURE,
                    "severity": _severity("sector_limit_exceeded", sector_weight, MAX_SECTOR_EXPOSURE),
                    "action": action,
                    "sell_shares": sell_shares,
                    "sell_value_usd": round(sell_value, 2),
                    "reason": f"섹터({sector}) 비중 {sector_weight:.1f}% > 한도 {MAX_SECTOR_EXPOSURE * 100:.0f}%",
                })

                if remaining_excess <= 0:
                    break

    # priority 순 정렬
    violations.sort(key=lambda v: (v["priority"], -abs(v["current_value"])))
    return violations


def calculate_rebalance_actions(db_path: Optional[Path] = None) -> list[dict]:
    """위반 사항 기반 리밸런싱 액션 계산.

    1. 위반 탐지
    2. SELL_PRIORITY 순서로 정렬
    3. 총 회수 금액 및 예상 현금 비중 계산

    Returns:
        정렬된 액션 리스트. 각 항목에 누적 회수 금액 포함.
    """
    violations = detect_violations(db_path)
    if not violations:
        logger.info("위반 사항 없음 — 리밸런싱 불필요")
        return []

    # SELL_PRIORITY 순서대로 정렬
    priority_order = {cat: idx for idx, cat in enumerate(SELL_PRIORITY)}
    violations.sort(key=lambda v: (
        priority_order.get(v["violation_type"], 99),
        -abs(v.get("current_value", 0)),
    ))

    # 누적 회수 금액 계산
    cumulative_recovery = 0.0
    actions = []
    for v in violations:
        cumulative_recovery += v["sell_value_usd"]
        action = {**v, "cumulative_recovery_usd": round(cumulative_recovery, 2)}
        actions.append(action)

    return actions


def print_rebalance_advisor(actions: list[dict]) -> None:
    """리밸런싱 어드바이저 결과 포맷팅 출력."""
    if not actions:
        print("\n=== Rebalance Advisor ===")
        print("위반 사항 없음. 포트폴리오가 규칙을 준수하고 있습니다.")
        return

    print(f"\n{'=' * 60}")
    print("  Rebalance Advisor — 투자 규칙 위반 정리")
    print(f"{'=' * 60}")

    # 매도 우선순위 라벨
    priority_labels = {
        "leverage_etf": "레버리지 ETF",
        "stop_loss_exceeded": "손절선 초과",
        "no_superinvestor": "슈퍼투자자 미보유",
        "position_limit_exceeded": "비중 한도 초과",
        "sector_limit_exceeded": "섹터 한도 초과",
    }

    for idx, action in enumerate(actions, 1):
        ticker = action["ticker"]
        shares = action["sell_shares"]
        sell_value = action["sell_value_usd"]
        reason = action["reason"]
        priority = action["priority"]
        vtype = action["violation_type"]
        priority_label = priority_labels.get(vtype, vtype)

        if action["action"] == "SELL_ALL":
            qty_text = f"{shares}주 전량"
        else:
            qty_text = f"{shares}주 일부"

        severity_marker = ""
        if action["severity"] == "critical":
            severity_marker = "[!!] "
        elif action["severity"] == "high":
            severity_marker = "[!] "

        print(
            f"  {severity_marker}[P{priority}] SELL {ticker} {qty_text} "
            f"→ {priority_label}: {reason} (회수 ~${sell_value:,.0f})"
        )

    total_recovery = actions[-1].get("cumulative_recovery_usd", 0)
    print(f"\n  총 회수: ~${total_recovery:,.0f}")
    print(f"{'=' * 60}")


def generate_advisor_report(db_path: Optional[Path] = None) -> dict:
    """리밸런싱 어드바이저 전체 리포트 생성.

    Returns:
        {
            "actions": list[dict],        # 매도 액션 목록
            "total_violations": int,       # 위반 건수
            "total_recovery_usd": float,   # 총 회수 예상 금액
            "violations_by_type": dict,    # 유형별 위반 건수
            "violations_by_severity": dict, # 심각도별 위반 건수
            "has_critical": bool,          # critical 위반 존재 여부
        }
    """
    actions = calculate_rebalance_actions(db_path)

    if not actions:
        return {
            "actions": [],
            "total_violations": 0,
            "total_recovery_usd": 0.0,
            "violations_by_type": {},
            "violations_by_severity": {},
            "has_critical": False,
        }

    # 유형별 집계
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in actions:
        vtype = a["violation_type"]
        by_type[vtype] = by_type.get(vtype, 0) + 1
        sev = a["severity"]
        by_severity[sev] = by_severity.get(sev, 0) + 1

    total_recovery = sum(a["sell_value_usd"] for a in actions)

    return {
        "actions": actions,
        "total_violations": len(actions),
        "total_recovery_usd": round(total_recovery, 2),
        "violations_by_type": by_type,
        "violations_by_severity": by_severity,
        "has_critical": by_severity.get("critical", 0) > 0,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report = generate_advisor_report()
    actions = report["actions"]
    print_rebalance_advisor(actions)

    if actions:
        print(f"\n  위반 건수: {report['total_violations']}")
        print(f"  유형별: {report['violations_by_type']}")
        print(f"  심각도: {report['violations_by_severity']}")
        if report["has_critical"]:
            print("  ⚠ CRITICAL 위반 존재 — 즉시 조치 필요")
    else:
        print("\n  포트폴리오 규칙 준수 상태입니다.")
