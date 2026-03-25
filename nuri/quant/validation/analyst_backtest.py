"""
C-3: 애널리스트 목표가 검증 (전향적).

과거 목표가 데이터가 없으므로 즉시 백테스트는 불가.
매주 누적되는 estimates 데이터가 90일+ 경과하면 자동으로 검증 시작.

사용법:
    python -m nuri.quant.validation.analyst_backtest
    python -m nuri.quant.validation.analyst_backtest --min-days 60
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from nuri.db import query, query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


@dataclass
class EstimateResult:
    """개별 목표가 검증 결과."""
    ticker: str
    estimate_date: str
    recommendation: str
    target_mean: float
    price_at_estimate: float    # estimate_date 시점 가격
    actual_price: float         # min_elapsed_days 후 가격
    actual_date: str
    target_gap_pct: float       # (target - price_at_estimate) / price_at_estimate * 100
    actual_return_pct: float    # (actual - price_at_estimate) / price_at_estimate * 100
    target_hit: bool            # actual >= target_mean


def validate_estimates(min_elapsed_days: int = 90) -> list[EstimateResult]:
    """과거 estimates를 현재 가격과 비교하여 검증.

    estimates 테이블에서 min_elapsed_days 이상 경과한 데이터를 찾아
    해당 시점 가격 vs 현재 가격을 비교.

    데이터가 부족하면 빈 리스트 반환 + 안내 메시지.
    """
    cutoff = (datetime.now() - timedelta(days=min_elapsed_days)).strftime("%Y-%m-%d")

    # 검증 가능한 estimates 조회
    estimates = query(
        "SELECT * FROM estimates WHERE date <= ? ORDER BY date, ticker",
        (cutoff,),
    )

    if not estimates:
        # 가장 오래된 estimate 확인
        oldest = query("SELECT MIN(date) as d, COUNT(DISTINCT date) as dates FROM estimates")
        if oldest and oldest[0]["d"]:
            days_elapsed = (datetime.now() - datetime.strptime(oldest[0]["d"], "%Y-%m-%d")).days
            available_date = (datetime.strptime(oldest[0]["d"], "%Y-%m-%d")
                             + timedelta(days=min_elapsed_days)).strftime("%Y-%m-%d")
            logger.warning(
                f"검증 가능한 데이터 없음: 최소 {min_elapsed_days}일 경과된 estimates가 필요합니다.\n"
                f"  가장 오래된 estimate: {oldest[0]['d']} ({days_elapsed}일 경과)\n"
                f"  누적된 수집 일수: {oldest[0]['dates']}일\n"
                f"  예상 검증 가능 시점: {available_date}\n"
                f"  estimates 수집은 매주 자동으로 누적됩니다 (스케줄러 등록 완료)."
            )
        else:
            logger.warning("estimates 테이블이 비어 있습니다.")
        return []

    # TODO: 검증 가능한 estimates가 있을 때의 구현
    #
    # 각 estimate에 대해:
    # 1. estimate_date 시점의 가격 조회 (prices 테이블)
    # 2. estimate_date + min_elapsed_days 시점의 가격 조회
    # 3. EstimateResult 생성
    #
    # 구현 시 주의:
    # - prices에 해당 날짜가 없을 수 있음 (휴장일) → 가장 가까운 거래일 사용
    # - current_price 컬럼은 estimate 수집 시점의 가격 (참고용)
    raise NotImplementedError("C-3: validate_estimates 검증 로직 구현 필요")


def print_results(results: list[EstimateResult]) -> None:
    """검증 결과 출력."""
    if not results:
        return

    print(f"\n{'=' * 70}")
    print(f"  애널리스트 목표가 검증 ({len(results)}건)")
    print(f"{'=' * 70}")
    hit = sum(1 for r in results if r.target_hit)
    print(f"  적중률: {hit}/{len(results)} ({hit/len(results)*100:.1f}%)")
    print(f"  평균 실제수익: {sum(r.actual_return_pct for r in results)/len(results):+.1f}%")

    print(f"\n  {'Ticker':<10} {'의견':<12} {'괴리율':>8} {'실제수익':>8} {'적중':>4}")
    print(f"  {'-' * 46}")
    for r in results:
        hit_mark = "O" if r.target_hit else "X"
        print(f"  {r.ticker:<10} {r.recommendation:<12} "
              f"{r.target_gap_pct:>+7.1f}% {r.actual_return_pct:>+7.1f}% {hit_mark:>4}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="애널리스트 목표가 검증")
    parser.add_argument("--min-days", type=int, default=90, help="최소 경과일 (기본 90)")
    args = parser.parse_args()

    results = validate_estimates(min_elapsed_days=args.min_days)
    print_results(results)
