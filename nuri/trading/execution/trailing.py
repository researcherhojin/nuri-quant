"""
트레일링 스톱 추적기 — 고점 대비 하락 시 SELL 시그널 생성.

매일 오픈 포지션의 고점(high water mark)을 갱신하고,
현재가가 고점 대비 일정 비율 하락하면 자동으로 SELL 시그널을 발생시킨다.

규칙:
    - 성장주/가치주: 고점 대비 -15% → SELL (TRAILING_STOP_GROWTH / TRAILING_STOP_VALUE)
    - 변동성 높은 종목: 고점 대비 -20% → SELL (TRAILING_STOP_VOLATILE)

사용법:
    python -m nuri.trading.execution.trailing
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from nuri.core.db import get_db, query
from nuri.core.rules import (
    TRAILING_STOP_GROWTH,
    TRAILING_STOP_VALUE,
    TRAILING_STOP_VOLATILE,
)
from nuri.trading.recommend.price_targets import classify_stock_type

logger = logging.getLogger(__name__)


@dataclass
class TrailingStopSignal:
    """트레일링 스톱 발동 시그널."""
    ticker: str
    position_id: int
    direction: str          # "SELL"
    high_water_mark: float
    current_price: float
    drop_pct: float         # 고점 대비 하락률 (음수)
    threshold_pct: float    # 발동 임계값 (e.g., -15)
    stock_type: str
    note: str


def _get_trailing_threshold(stock_type: str) -> float:
    """종목 유형별 트레일링 스톱 임계값 반환."""
    if stock_type == "swing":
        return TRAILING_STOP_VOLATILE   # -20%
    elif stock_type == "growth":
        return TRAILING_STOP_GROWTH     # -15%
    else:  # value
        return TRAILING_STOP_VALUE      # -15%


def _get_current_price(ticker: str, db_path: Optional[Path] = None) -> Optional[float]:
    """DB에서 최신 종가 조회."""
    rows = query(
        "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    if rows and rows[0]["close"]:
        return float(rows[0]["close"])
    return None


def update_high_water_marks(db_path: Optional[Path] = None) -> int:
    """오픈 포지션의 high water mark를 현재가 기준으로 갱신.

    현재가가 기존 high_water_mark보다 높으면 업데이트한다.
    high_water_mark가 NULL이면 entry_price와 현재가 중 높은 값으로 초기화한다.

    Args:
        db_path: DB 경로 (테스트용)

    Returns:
        갱신된 포지션 수
    """
    open_positions = query(
        "SELECT id, ticker, entry_price, high_water_mark "
        "FROM positions WHERE status = 'open' AND direction = 'long'",
        db_path=db_path,
    )

    updated_count = 0
    for pos in open_positions:
        ticker = pos["ticker"]
        current_price = _get_current_price(ticker, db_path=db_path)
        if current_price is None:
            logger.warning("No price data for %s, skipping", ticker)
            continue

        old_hwm = pos["high_water_mark"]
        entry_price = pos["entry_price"]

        # HWM 초기화: NULL이면 진입가와 현재가 중 높은 값
        if old_hwm is None:
            new_hwm = max(entry_price, current_price)
        else:
            new_hwm = max(old_hwm, current_price)

        if old_hwm is None or new_hwm > old_hwm:
            with get_db(db_path) as conn:
                conn.execute(
                    "UPDATE positions SET high_water_mark = ? WHERE id = ?",
                    (round(new_hwm, 2), pos["id"]),
                )
            updated_count += 1
            logger.debug(
                "[HWM UPDATE] %s: %.2f → %.2f (현재가 %.2f)",
                ticker, old_hwm or 0, new_hwm, current_price,
            )

    logger.info("[TRAILING] high water mark 갱신: %d건", updated_count)
    return updated_count


def check_trailing_stop_signals(db_path: Optional[Path] = None) -> list[TrailingStopSignal]:
    """오픈 포지션 중 트레일링 스톱 발동 종목의 SELL 시그널 생성.

    high_water_mark 대비 현재가 하락률이 임계값 이하면 SELL 시그널을 반환한다.

    Args:
        db_path: DB 경로 (테스트용)

    Returns:
        TrailingStopSignal 리스트
    """
    # 먼저 HWM 갱신
    update_high_water_marks(db_path)

    open_positions = query(
        "SELECT id, ticker, entry_price, high_water_mark "
        "FROM positions WHERE status = 'open' AND direction = 'long'",
        db_path=db_path,
    )

    signals: list[TrailingStopSignal] = []

    for pos in open_positions:
        ticker = pos["ticker"]
        hwm = pos["high_water_mark"]

        # HWM이 없으면 체크 불가
        if hwm is None or hwm <= 0:
            continue

        current_price = _get_current_price(ticker, db_path=db_path)
        if current_price is None:
            logger.warning("No price data for %s, skipping", ticker)
            continue

        stock_type = classify_stock_type(ticker, db_path=db_path)
        threshold = _get_trailing_threshold(stock_type)

        # 고점 대비 하락률 계산
        drop_pct = (current_price - hwm) / hwm * 100

        # 임계값 이하로 하락하면 SELL 시그널 발생
        if drop_pct <= threshold:
            signals.append(TrailingStopSignal(
                ticker=ticker,
                position_id=pos["id"],
                direction="SELL",
                high_water_mark=round(hwm, 2),
                current_price=round(current_price, 2),
                drop_pct=round(drop_pct, 1),
                threshold_pct=threshold,
                stock_type=stock_type,
                note=(
                    f"트레일링 스톱 발동: 고점 ${hwm:.2f} → 현재 ${current_price:.2f} "
                    f"({drop_pct:+.1f}%, 한도 {threshold}%)"
                ),
            ))

    return signals


def run_trailing_stop_check(db_path: Optional[Path] = None) -> dict:
    """일일 트레일링 스톱 파이프라인 실행.

    1. HWM 갱신
    2. 트레일링 스톱 체크
    3. 결과 반환

    Args:
        db_path: DB 경로 (테스트용)

    Returns:
        dict: {
            "hwm_updated": int,       # HWM 갱신 건수
            "signals": list,          # 발동 시그널
            "total_checked": int,     # 체크한 포지션 수
        }
    """
    # HWM 갱신
    hwm_updated = update_high_water_marks(db_path)

    # 오픈 포지션 수
    open_positions = query(
        "SELECT COUNT(*) as c FROM positions WHERE status = 'open' AND direction = 'long'",
        db_path=db_path,
    )
    total_checked = open_positions[0]["c"] if open_positions else 0

    # 트레일링 스톱 시그널 체크
    signals = check_trailing_stop_signals(db_path)

    if signals:
        logger.warning("[TRAILING STOP] %d건 발동!", len(signals))
        for sig in signals:
            logger.warning("  %s: 고점 $%.2f → 현재 $%.2f (%+.1f%%)",
                           sig.ticker, sig.high_water_mark, sig.current_price, sig.drop_pct)

    return {
        "hwm_updated": hwm_updated,
        "signals": signals,
        "total_checked": total_checked,
    }


def print_trailing_stop_signals(signals: list[TrailingStopSignal]) -> None:
    """트레일링 스톱 시그널 CLI 출력."""
    if not signals:
        print("\n트레일링 스톱 발동 종목 없음")
        return

    print(f"\n{'=' * 60}")
    print("  Trailing Stop Signals — 고점 대비 하락 발동")
    print(f"{'=' * 60}")

    for sig in signals:
        type_labels = {"growth": "성장주", "value": "가치주", "swing": "스윙"}
        label = type_labels.get(sig.stock_type, sig.stock_type)
        print(f"  SELL {sig.ticker} ({label})")
        print(f"    고점: ${sig.high_water_mark:.2f} → 현재: ${sig.current_price:.2f}")
        print(f"    하락: {sig.drop_pct:+.1f}% (한도: {sig.threshold_pct}%)")
        print()

    print(f"{'=' * 60}")
    print(f"총 {len(signals)}건 트레일링 스톱 발동")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = run_trailing_stop_check()
    print(f"\nHWM 갱신: {result['hwm_updated']}건")
    print(f"체크 포지션: {result['total_checked']}건")
    print_trailing_stop_signals(result["signals"])
