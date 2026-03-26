"""
C-3: 애널리스트 목표가 검증 (전향적).

과거 목표가 데이터가 없으므로 즉시 백테스트는 불가.
매주 누적되는 estimates 데이터가 90일+ 경과하면 자동으로 검증 시작.

사용법:
    python -m nuri.validation.analyst_backtest
    python -m nuri.validation.analyst_backtest --min-days 60
"""
import argparse
import logging
from dataclasses import dataclass, asdict  # noqa: F401 (asdict used in __main__)
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from nuri.core.db import query, query_df

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


def validate_estimates(min_elapsed_days: int = 90, db_path=None) -> list[EstimateResult]:
    """과거 estimates를 현재 가격과 비교하여 검증.

    estimates 테이블에서 min_elapsed_days 이상 경과한 데이터를 찾아
    해당 시점 가격 vs 현재 가격을 비교.

    데이터가 부족하면 빈 리스트 반환 + 안내 메시지.
    """
    cutoff = (datetime.now() - timedelta(days=min_elapsed_days)).strftime("%Y-%m-%d")

    # 검증 가능한 estimates 조회
    estimates = query(
        "SELECT * FROM estimates WHERE date <= ? ORDER BY date, ticker",
        (cutoff,), db_path=db_path,
    )

    if not estimates:
        # 가장 오래된 estimate 확인
        oldest = query("SELECT MIN(date) as d, COUNT(DISTINCT date) as dates FROM estimates",
                       db_path=db_path)
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

    results = []

    for est in estimates:
        ticker = est["ticker"]
        est_date = est["date"]
        target_mean = est.get("target_mean")
        rec = est.get("recommendation", "")

        if not target_mean or target_mean <= 0:
            continue

        # estimate_date 시점의 가격 (가장 가까운 거래일)
        price_at = query(
            "SELECT close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (ticker, est_date), db_path=db_path,
        )
        if not price_at:
            continue
        price_at_estimate = price_at[0]["close"]
        if price_at_estimate <= 0:
            continue

        # min_elapsed_days 후 가격
        actual_date = (datetime.strptime(est_date, "%Y-%m-%d") + timedelta(days=min_elapsed_days)).strftime("%Y-%m-%d")
        price_after = query(
            "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (ticker, actual_date), db_path=db_path,
        )
        if not price_after:
            continue

        actual_price = price_after[0]["close"]
        actual_date_real = price_after[0]["date"]

        target_gap_pct = (target_mean - price_at_estimate) / price_at_estimate * 100
        actual_return_pct = (actual_price - price_at_estimate) / price_at_estimate * 100
        target_hit = actual_price >= target_mean

        results.append(EstimateResult(
            ticker=ticker,
            estimate_date=est_date,
            recommendation=rec,
            target_mean=round(target_mean, 2),
            price_at_estimate=round(price_at_estimate, 2),
            actual_price=round(actual_price, 2),
            actual_date=actual_date_real,
            target_gap_pct=round(target_gap_pct, 2),
            actual_return_pct=round(actual_return_pct, 2),
            target_hit=target_hit,
        ))

    return results


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

    # CSV 저장
    if results:
        today = datetime.now().strftime("%Y-%m-%d")
        output_dir = REPORT_DIR / today
        output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([asdict(r) for r in results]).to_csv(
            output_dir / "analyst_results.csv", index=False
        )
