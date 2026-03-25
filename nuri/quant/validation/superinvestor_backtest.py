"""
C-2: 슈퍼투자자 추종 백테스트.

선행 작업: superinvestors.py에서 과거 8분기 13F 수집 (현재 최신 1분기만 있음).

사용법:
    python -m nuri.quant.validation.superinvestor_backtest
    python -m nuri.quant.validation.superinvestor_backtest --investor "Warren Buffett"
    python -m nuri.quant.validation.superinvestor_backtest --hold-days 252
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from nuri.db import query, query_df

logger = logging.getLogger(__name__)

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
# TODO: 선행 작업 — 과거 13F 수집 확장
# ═══════════════════════════════════════════════════════

# nuri/collectors/superinvestors.py 수정 필요:
#
# 현재:
#   latest = filings[0]
#   filing_obj = latest.obj()
#
# 변경:
#   for filing in filings[:8]:  # 최근 8분기
#       filing_obj = filing.obj()
#       ...
#
# 이후 분기 간 비교로 change_type (NEW/INCREASED/DECREASED/CLOSED) 감지:
#
# def detect_changes(curr_df, prev_df):
#     curr_tickers = set(curr_df["Ticker"])
#     prev_tickers = set(prev_df["Ticker"])
#     new = curr_tickers - prev_tickers          → "NEW"
#     closed = prev_tickers - curr_tickers        → "CLOSED"
#     for ticker in curr_tickers & prev_tickers:
#         curr_shares = curr_df[curr_df.Ticker==ticker].SharesPrnAmount.sum()
#         prev_shares = prev_df[prev_df.Ticker==ticker].SharesPrnAmount.sum()
#         if curr_shares > prev_shares * 1.05:    → "INCREASED"
#         elif curr_shares < prev_shares * 0.95:  → "DECREASED"
#         else:                                   → "UNCHANGED"


# ═══════════════════════════════════════════════════════
# TODO: 핵심 구현
# ═══════════════════════════════════════════════════════


def _check_data_readiness() -> bool:
    """과거 다분기 13F 데이터가 있는지 확인."""
    quarters = query("SELECT DISTINCT filing_date FROM superinvestors ORDER BY filing_date")
    if len(quarters) < 2:
        logger.warning(
            f"슈퍼투자자 13F가 {len(quarters)}분기만 있습니다. "
            f"최소 2분기가 필요합니다 (분기 간 비교를 위해).\n"
            f"  현재 공시일: {[q['filing_date'] for q in quarters]}\n"
            f"  해결: nuri/collectors/superinvestors.py에서 filings[:8]로 확장 후 재수집"
        )
        return False
    return True


def backtest_superinvestor(
    investor: str | None = None,
    hold_days: int = 120,
) -> list[FollowResult]:
    """슈퍼투자자 추종 백테스트.

    구현 순서:
    1. _check_data_readiness()로 데이터 확인
    2. 분기별 NEW/INCREASED 종목 추출
    3. 각 종목에 대해:
       a. 공시일 다음 거래일 가격 = entry_price
       b. entry_date + hold_days 시점 가격 = exit_price
       c. VOO 동기간 수익률 = benchmark
       d. excess = return - benchmark
    4. prices 테이블에 없는 종목은 건너뜀 + 로그
    """
    if not _check_data_readiness():
        return []

    raise NotImplementedError("C-2: backtest_superinvestor 구현 필요")


def generate_scorecard(results: list[FollowResult], hold_days: int) -> list[InvestorScorecard]:
    """투자자별 집계."""
    raise NotImplementedError("C-2: generate_scorecard 구현 필요")


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
