"""
Strategy Monitor — 레짐 전환 감지 + 포지션 전환 알림 + 일일 P&L.

이전 레짐과 현재 레짐을 비교하여 전환 시 포지션 스위치 신호 발생.

사용법:
    python -m nuri.trading.strategy.monitor
"""
import json
import logging

from nuri.core.db import get_db, query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)


def detect_regime_transition(db_path=None) -> dict | None:
    """레짐 전환 감지. 이전 기록과 비교."""
    try:
        from nuri.quant.regime.classifier import classify_regime
        current = classify_regime(db_path=db_path)
    except Exception:
        return None

    if current is None:
        return None

    # 이전 레짐 (가장 최근 기록)
    prev = query(
        "SELECT to_regime FROM regime_transitions ORDER BY id DESC LIMIT 1",
        db_path=db_path,
    )
    prev_regime = prev[0]["to_regime"] if prev else None

    if prev_regime == current.regime:
        return None  # 전환 없음

    # 전환 감지!
    transition = {
        "date": today_kst(),
        "from_regime": prev_regime or "unknown",
        "to_regime": current.regime,
        "confidence": current.confidence,
    }

    # 전환 방향 분류
    if prev_regime:
        prev_trend = prev_regime.split("_")[0]
        curr_trend = current.trend

        if prev_trend == "bull" and curr_trend == "bear":
            transition["switch"] = "BULL→BEAR: 롱 청산 + 숏 전환"
            transition["urgency"] = "high"
        elif prev_trend == "bear" and curr_trend == "bull":
            transition["switch"] = "BEAR→BULL: 숏 청산 + 롱 전환"
            transition["urgency"] = "high"
        elif curr_trend == "sideways":
            transition["switch"] = f"{prev_trend.upper()}→SIDEWAYS: 포지션 축소"
            transition["urgency"] = "medium"
        else:
            transition["switch"] = f"{prev_regime}→{current.regime}: 변동성 변화"
            transition["urgency"] = "low"
    else:
        transition["switch"] = f"초기 레짐 설정: {current.regime}"
        transition["urgency"] = "low"

    # DB에 기록
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) "
            "VALUES (?, ?, ?, ?)",
            (transition["date"], transition["from_regime"], transition["to_regime"],
             json.dumps(transition)),
        )

    logger.info(f"[REGIME TRANSITION] {transition['switch']}")
    return transition


def daily_pnl_summary(db_path=None) -> dict:
    """일일 P&L 요약."""
    from nuri.trading.strategy.position import update_prices

    update_prices(db_path)

    open_pos = query("SELECT * FROM positions WHERE status='open'", db_path=db_path)

    total_pnl = sum(p.get("return_pct", 0) or 0 for p in open_pos)
    long_pnl = sum(p.get("return_pct", 0) or 0 for p in open_pos if p["direction"] == "long")
    short_pnl = sum(p.get("return_pct", 0) or 0 for p in open_pos if p["direction"] == "short")

    core_pnl = sum(p.get("return_pct", 0) or 0 for p in open_pos if p["portfolio_type"] == "core")
    tac_pnl = sum(p.get("return_pct", 0) or 0 for p in open_pos if p["portfolio_type"] == "tactical")

    winners = [p for p in open_pos if (p.get("return_pct", 0) or 0) > 0]
    losers = [p for p in open_pos if (p.get("return_pct", 0) or 0) < 0]

    best = max(open_pos, key=lambda p: p.get("return_pct", 0) or 0) if open_pos else None
    worst = min(open_pos, key=lambda p: p.get("return_pct", 0) or 0) if open_pos else None

    return {
        "total_positions": len(open_pos),
        "total_pnl": round(total_pnl / len(open_pos), 2) if open_pos else 0,
        "long_pnl": round(long_pnl / max(1, len([p for p in open_pos if p["direction"] == "long"])), 2),
        "short_pnl": round(short_pnl / max(1, len([p for p in open_pos if p["direction"] == "short"])), 2),
        "core_pnl": round(core_pnl / max(1, len([p for p in open_pos if p["portfolio_type"] == "core"])), 2),
        "tactical_pnl": round(tac_pnl / max(1, len([p for p in open_pos if p["portfolio_type"] == "tactical"])), 2),
        "winners": len(winners),
        "losers": len(losers),
        "best": {"ticker": best["ticker"], "pnl": best.get("return_pct", 0)} if best else None,
        "worst": {"ticker": worst["ticker"], "pnl": worst.get("return_pct", 0)} if worst else None,
    }


def print_monitor(db_path=None) -> None:
    """전체 모니터 출력: 레짐 + 전환 + 전략 + 포지션."""
    from nuri.quant.regime.classifier import classify_regime, print_regime
    from nuri.trading.strategy.longshort import generate_strategy, print_strategy
    from nuri.trading.strategy.position import print_positions

    # 1. 현재 레짐
    regime = classify_regime(db_path=db_path)
    print_regime(regime)

    # 2. 레짐 전환 체크
    transition = detect_regime_transition(db_path)
    if transition:
        print(f"\n  ⚡ REGIME TRANSITION: {transition['switch']}")
        print(f"     Urgency: {transition['urgency'].upper()}")
        print(f"     {transition['from_regime']} → {transition['to_regime']}")
    else:
        print("\n  레짐 전환 없음 (유지 중)")

    # 3. 전략 액션
    actions = generate_strategy(db_path)
    print_strategy(actions)

    # 4. 포지션 현황
    print_positions(db_path)

    # 5. P&L 요약
    pnl = daily_pnl_summary(db_path)
    if pnl["total_positions"] > 0:
        print("  P&L Summary:")
        print(f"    Total: {pnl['total_pnl']:+.1f}% ({pnl['winners']}W / {pnl['losers']}L)")
        print(f"    Long: {pnl['long_pnl']:+.1f}% | Short: {pnl['short_pnl']:+.1f}%")
        print(f"    Core: {pnl['core_pnl']:+.1f}% | Tactical: {pnl['tactical_pnl']:+.1f}%")
        if pnl["best"]:
            print(f"    Best:  {pnl['best']['ticker']} ({pnl['best']['pnl']:+.1f}%)")
        if pnl["worst"]:
            print(f"    Worst: {pnl['worst']['ticker']} ({pnl['worst']['pnl']:+.1f}%)")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from nuri.core.db import init_db
    init_db()
    print_monitor()
