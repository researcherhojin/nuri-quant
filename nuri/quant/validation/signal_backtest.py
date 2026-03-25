"""
C-1: 기술적 시그널 백테스트 — 시그널별 승률/수익률 측정.

prices 5년 데이터 + TA-Lib으로 시그널을 감지하고,
각 시그널의 진입→청산 수익률을 계산하여 스코어카드 생성.

사용법:
    python -m nuri.quant.validation.signal_backtest
    python -m nuri.quant.validation.signal_backtest --ticker TSLA
    python -m nuri.quant.validation.signal_backtest --signal rsi_oversold
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.db import get_tickers, query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# ═══════════════════════════════════════════════════════
# 데이터 구조
# ═══════════════════════════════════════════════════════


@dataclass
class SignalResult:
    """개별 시그널 거래 결과."""
    signal_id: str
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    holding_days: int
    won: bool


@dataclass
class SignalScorecard:
    """시그널별 집계 스코어카드."""
    signal_id: str
    ticker: str | None       # None = 전체 종목 합산
    total_trades: int
    win_rate: float          # 0.0 ~ 1.0
    avg_return: float        # %
    median_return: float     # %
    max_return: float        # %
    max_loss: float          # %
    profit_factor: float     # 총이익 / 총손실 (손실=0이면 inf)
    avg_holding_days: float


# ═══════════════════════════════════════════════════════
# 시그널 정의
# ═══════════════════════════════════════════════════════

SIGNAL_DEFINITIONS = {
    "rsi_oversold": {
        "description": "RSI 과매도 반등 (30 아래에서 위로)",
        "hold_days": 20,
    },
    "rsi_overbought": {
        "description": "RSI 과매수 이탈 (70 위에서 아래로)",
        "hold_days": 20,
    },
    "macd_golden": {
        "description": "MACD 골든크로스 (MACD > Signal)",
        "hold_days": None,  # MACD < Signal까지
    },
    "macd_dead": {
        "description": "MACD 데드크로스 (MACD < Signal)",
        "hold_days": None,  # MACD > Signal까지
    },
    "sma_golden": {
        "description": "SMA 골든크로스 (SMA50 > SMA200)",
        "hold_days": None,  # SMA50 < SMA200까지
    },
    "sma_dead": {
        "description": "SMA 데드크로스 (SMA50 < SMA200)",
        "hold_days": None,  # SMA50 > SMA200까지
    },
    "bb_bounce": {
        "description": "BB 하단 반등 (종가가 BB Lower 위로)",
        "hold_days": 20,
    },
}


# ═══════════════════════════════════════════════════════
# TODO: 핵심 구현
# ═══════════════════════════════════════════════════════


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DataFrame에 TA-Lib 지표 추가. charts.py의 _load_chart_data와 동일 로직."""
    # TODO: nuri/analysis/charts.py의 _load_chart_data에서 지표 계산 로직을
    #       공통 함수로 추출하여 여기서 재사용.
    #       현재는 charts.py에 직접 구현되어 있음.
    raise NotImplementedError("C-1: _compute_indicators 구현 필요")


def _detect_signal_entries(df: pd.DataFrame, signal_id: str) -> list[int]:
    """시그널 진입 시점의 인덱스 리스트 반환.

    Args:
        df: 지표가 계산된 가격 DataFrame (index=date)
        signal_id: SIGNAL_DEFINITIONS의 키

    Returns:
        진입 시점 인덱스 리스트 (df.index 기준)

    TODO: 각 시그널별 크로스오버 감지 로직 구현.
          charts.py의 _detect_signals와 유사하지만,
          여기서는 모든 발생 시점을 반환 (최근 N개가 아닌 전체).
    """
    raise NotImplementedError(f"C-1: _detect_signal_entries({signal_id}) 구현 필요")


def _compute_exit(df: pd.DataFrame, entry_idx: int, signal_id: str) -> tuple[int, str]:
    """진입 인덱스 → 청산 인덱스 + 청산 사유.

    hold_days가 있는 시그널: entry_idx + hold_days
    hold_days가 None인 시그널: 반대 크로스 발생 시점

    TODO: 구현.
    """
    raise NotImplementedError(f"C-1: _compute_exit({signal_id}) 구현 필요")


def backtest_signals(
    ticker: str | None = None,
    signals: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[SignalResult]:
    """시그널 백테스트 실행.

    Args:
        ticker: 특정 종목만 (None=전체)
        signals: 특정 시그널만 (None=전체)
        start_date: 시작일 (None=전체)
        end_date: 종료일 (None=전체)

    Returns:
        개별 거래 결과 리스트

    구현 순서:
    1. ticker 목록 결정 (get_tickers() 또는 단일)
    2. 종목별로:
       a. prices에서 OHLCV 로드
       b. _compute_indicators로 지표 계산
       c. 각 시그널에 대해:
          - _detect_signal_entries로 진입 시점 감지
          - _compute_exit로 청산 시점 결정
          - return_pct = (exit_price - entry_price) / entry_price * 100
          - SignalResult 생성
    3. 전체 결과 반환
    """
    raise NotImplementedError("C-1: backtest_signals 구현 필요")


def generate_scorecard(results: list[SignalResult]) -> list[SignalScorecard]:
    """SignalResult → 시그널별 집계 스코어카드.

    집계 기준: (signal_id, ticker) + (signal_id, None) 전체합산
    """
    raise NotImplementedError("C-1: generate_scorecard 구현 필요")


def print_scorecard(scorecards: list[SignalScorecard]) -> None:
    """스코어카드 CLI 출력."""
    if not scorecards:
        print("스코어카드 데이터가 없습니다.")
        return

    # 전체 합산 (ticker=None)만 출력
    total = [s for s in scorecards if s.ticker is None]
    total.sort(key=lambda s: s.profit_factor, reverse=True)

    print(f"\n{'=' * 75}")
    print(f"  시그널 스코어카드")
    print(f"{'=' * 75}")
    print(f"  {'시그널':<20} {'횟수':>5} {'승률':>7} {'평균수익':>8} {'PF':>6} {'최대익':>8} {'최대손':>8}")
    print(f"  {'-' * 65}")
    for s in total:
        pf = f"{s.profit_factor:.2f}" if s.profit_factor < 100 else "∞"
        print(f"  {s.signal_id:<20} {s.total_trades:>5} {s.win_rate:>6.1%} "
              f"{s.avg_return:>+7.1f}% {pf:>6} {s.max_return:>+7.1f}% {s.max_loss:>+7.1f}%")
    print()


# ═══════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 시그널 백테스트")
    parser.add_argument("--ticker", help="특정 종목")
    parser.add_argument("--signal", help="특정 시그널 (예: rsi_oversold)")
    args = parser.parse_args()

    sigs = [args.signal] if args.signal else None
    results = backtest_signals(ticker=args.ticker, signals=sigs)
    scorecards = generate_scorecard(results)
    print_scorecard(scorecards)

    # CSV 저장
    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = REPORT_DIR / today
    output_dir.mkdir(parents=True, exist_ok=True)

    if results:
        pd.DataFrame([asdict(r) for r in results]).to_csv(
            output_dir / "signal_results.csv", index=False
        )
    if scorecards:
        pd.DataFrame([asdict(s) for s in scorecards]).to_csv(
            output_dir / "signal_scorecard.csv", index=False
        )
