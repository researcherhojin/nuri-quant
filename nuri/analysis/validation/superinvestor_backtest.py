"""
C-2: 슈퍼투자자 추종 백테스트.

선행 작업: superinvestors.py에서 과거 8분기 13F 수집 (현재 최신 1분기만 있음).

사용법:
    python -m nuri.validation.superinvestor_backtest
    python -m nuri.validation.superinvestor_backtest --investor "Warren Buffett"
    python -m nuri.validation.superinvestor_backtest --hold-days 252
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from nuri.core.db import query, query_df, get_tickers

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "VOO"

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


@dataclass
class FollowResult:
    """추종 매수 개별 결과."""
    investor: str
    ticker: str
    filing_date: str
    change_type: str          # NEW, INCREASED
    entry_date: str           # 공시일 다음 거래일
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    benchmark_return_pct: float   # VOO 동기간
    excess_return_pct: float


@dataclass
class InvestorScorecard:
    """투자자별 추종 스코어카드."""
    investor: str
    hold_days: int
    total_follows: int
    win_rate: float
    avg_return: float
    avg_excess_return: float
    best_ticker: str
    best_return: float
    worst_ticker: str
    worst_return: float


# ═══════════════════════════════════════════════════════
# 핵심 구현
# ═══════════════════════════════════════════════════════


def _check_data_readiness(db_path=None) -> bool:
    """과거 다분기 13F 데이터가 있는지 확인."""
    quarters = query("SELECT DISTINCT filing_date FROM superinvestors ORDER BY filing_date",
                     db_path=db_path)
    if len(quarters) < 2:
        logger.warning(
            f"슈퍼투자자 13F가 {len(quarters)}분기만 있습니다. "
            f"최소 2분기가 필요합니다 (분기 간 비교를 위해).\n"
            f"  현재 공시일: {[q['filing_date'] for q in quarters]}\n"
            f"  해결: python -m nuri.collectors.superinvestors 실행 (8분기 자동 수집)"
        )
        return False
    return True


def _get_price_on_or_after(ticker: str, date: str, db_path=None) -> dict | None:
    """특정 날짜 이후 가장 가까운 거래일 가격 반환."""
    rows = query(
        "SELECT date, close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date LIMIT 1",
        (ticker, date), db_path=db_path,
    )
    return rows[0] if rows else None


def _get_price_on_or_before(ticker: str, date: str, db_path=None) -> dict | None:
    """특정 날짜 이전 가장 가까운 거래일 가격 반환."""
    rows = query(
        "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (ticker, date), db_path=db_path,
    )
    return rows[0] if rows else None


def backtest_superinvestor(
    investor: str | None = None,
    hold_days: int = 120,
    db_path=None,
) -> list[FollowResult]:
    """슈퍼투자자 추종 백테스트.

    1. detect_changes로 분기별 NEW/INCREASED 종목 추출
    2. 공시일 다음 거래일에 매수 → hold_days 후 매도
    3. VOO 동기간 수익률과 비교 → 초과수익률
    """
    if not _check_data_readiness(db_path):
        return []

    from nuri.collectors.superinvestors import detect_changes, SUPERINVESTORS

    investors = [investor] if investor else list(SUPERINVESTORS.keys())
    results = []

    for inv_name in investors:
        changes = detect_changes(inv_name, db_path=db_path)
        if changes.empty:
            logger.info(f"{inv_name}: 분기 변화 데이터 없음")
            continue

        # NEW, INCREASED만 추종
        follow = changes[changes["change_type"].isin(["NEW", "INCREASED"])]

        for _, row in follow.iterrows():
            ticker = row["ticker"]
            filing_date = row["filing_date"]

            # 공시일 다음 거래일 가격
            entry = _get_price_on_or_after(ticker, filing_date, db_path)
            if not entry:
                logger.debug(f"{inv_name} {ticker}: prices에 {filing_date} 이후 데이터 없음, 건너뜀")
                continue

            entry_date = entry["date"]
            entry_price = entry["close"]

            # hold_days 후 가격 (거래일 기준)
            from datetime import datetime, timedelta
            target_exit = (datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=hold_days)).strftime("%Y-%m-%d")
            exit_data = _get_price_on_or_before(ticker, target_exit, db_path)
            if not exit_data:
                continue

            exit_date = exit_data["date"]
            exit_price = exit_data["close"]

            if not entry_price or not exit_price or entry_price == 0:
                continue

            return_pct = (exit_price - entry_price) / entry_price * 100

            # VOO 벤치마크 동기간 수익률
            bench_entry = _get_price_on_or_after(BENCHMARK_TICKER, entry_date, db_path)
            bench_exit = _get_price_on_or_before(BENCHMARK_TICKER, exit_date, db_path)
            if bench_entry and bench_exit and bench_entry["close"] > 0:
                bench_return = (bench_exit["close"] - bench_entry["close"]) / bench_entry["close"] * 100
            else:
                bench_return = 0.0

            results.append(FollowResult(
                investor=inv_name,
                ticker=ticker,
                filing_date=filing_date,
                change_type=row["change_type"],
                entry_date=entry_date,
                entry_price=round(entry_price, 2),
                exit_date=exit_date,
                exit_price=round(exit_price, 2),
                return_pct=round(return_pct, 2),
                benchmark_return_pct=round(bench_return, 2),
                excess_return_pct=round(return_pct - bench_return, 2),
            ))

        logger.info(f"{inv_name}: {len([r for r in results if r.investor == inv_name])}건 추종")

    return results


def generate_scorecard(results: list[FollowResult], hold_days: int) -> list[InvestorScorecard]:
    """투자자별 집계."""
    if not results:
        return []

    scorecards = []
    by_investor: dict[str, list[FollowResult]] = {}
    for r in results:
        by_investor.setdefault(r.investor, []).append(r)

    for inv_name, group in by_investor.items():
        wins = sum(1 for r in group if r.return_pct > 0)
        returns = [r.return_pct for r in group]
        excess = [r.excess_return_pct for r in group]

        best = max(group, key=lambda r: r.return_pct)
        worst = min(group, key=lambda r: r.return_pct)

        scorecards.append(InvestorScorecard(
            investor=inv_name,
            hold_days=hold_days,
            total_follows=len(group),
            win_rate=wins / len(group),
            avg_return=round(sum(returns) / len(returns), 2),
            avg_excess_return=round(sum(excess) / len(excess), 2),
            best_ticker=best.ticker,
            best_return=best.return_pct,
            worst_ticker=worst.ticker,
            worst_return=worst.return_pct,
        ))

    return scorecards


def print_scorecard(scorecards: list[InvestorScorecard]) -> None:
    """CLI 출력."""
    if not scorecards:
        print("슈퍼투자자 추종 데이터가 없습니다.")
        return

    print(f"\n{'=' * 70}")
    print(f"  슈퍼투자자 추종 스코어카드")
    print(f"{'=' * 70}")
    for s in scorecards:
        print(f"\n  {s.investor} ({s.hold_days}일 보유)")
        print(f"    추종 횟수: {s.total_follows}, 승률: {s.win_rate:.1%}")
        print(f"    평균 수익: {s.avg_return:+.1f}%, 초과수익: {s.avg_excess_return:+.1f}%")
        print(f"    최고: {s.best_ticker} ({s.best_return:+.1f}%)")
        print(f"    최저: {s.worst_ticker} ({s.worst_return:+.1f}%)")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="슈퍼투자자 추종 백테스트")
    parser.add_argument("--investor", help="특정 투자자")
    parser.add_argument("--hold-days", type=int, default=120, help="보유 기간 (일)")
    args = parser.parse_args()

    results = backtest_superinvestor(investor=args.investor, hold_days=args.hold_days)
    scorecards = generate_scorecard(results, args.hold_days)
    print_scorecard(scorecards)

    # CSV 저장
    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = REPORT_DIR / today
    output_dir.mkdir(parents=True, exist_ok=True)

    if results:
        pd.DataFrame([asdict(r) for r in results]).to_csv(
            output_dir / "superinvestor_results.csv", index=False
        )
    if scorecards:
        pd.DataFrame([asdict(s) for s in scorecards]).to_csv(
            output_dir / "superinvestor_scorecard.csv", index=False
        )
