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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from nuri.core.db import get_tickers, query_df
from nuri.core.timezone import today_kst

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

# 진입 감지 함수 시그니처: (df: DataFrame, i: int) -> bool
EntryDetector = Callable[[pd.DataFrame, int], bool]
# 청산 감지 함수 시그니처: (df: DataFrame, i: int) -> bool
ExitDetector = Callable[[pd.DataFrame, int], bool]


# ── 진입 감지 함수 ──

def _entry_rsi_oversold(df: pd.DataFrame, i: int) -> bool:
    rsi, rsi_prev = df["rsi_14"].iloc[i], df["rsi_14"].iloc[i - 1]
    return bool(pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev < 30 and rsi >= 30)


def _entry_rsi_overbought(df: pd.DataFrame, i: int) -> bool:
    rsi, rsi_prev = df["rsi_14"].iloc[i], df["rsi_14"].iloc[i - 1]
    return bool(pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev > 70 and rsi <= 70)


def _entry_macd_golden(df: pd.DataFrame, i: int) -> bool:
    m, ms = df["macd"].iloc[i], df["macd_signal"].iloc[i]
    mp, msp = df["macd"].iloc[i - 1], df["macd_signal"].iloc[i - 1]
    return bool(pd.notna(m) and pd.notna(ms) and pd.notna(mp) and pd.notna(msp)
                and mp < msp and m >= ms)


def _entry_macd_dead(df: pd.DataFrame, i: int) -> bool:
    m, ms = df["macd"].iloc[i], df["macd_signal"].iloc[i]
    mp, msp = df["macd"].iloc[i - 1], df["macd_signal"].iloc[i - 1]
    return bool(pd.notna(m) and pd.notna(ms) and pd.notna(mp) and pd.notna(msp)
                and mp > msp and m <= ms)


def _entry_sma_golden(df: pd.DataFrame, i: int) -> bool:
    if "sma_50" not in df.columns or "sma_200" not in df.columns:
        return False
    s50, s200 = df["sma_50"].iloc[i], df["sma_200"].iloc[i]
    s50p, s200p = df["sma_50"].iloc[i - 1], df["sma_200"].iloc[i - 1]
    return bool(pd.notna(s50) and pd.notna(s200) and pd.notna(s50p) and pd.notna(s200p)
                and s50p < s200p and s50 >= s200)


def _entry_sma_dead(df: pd.DataFrame, i: int) -> bool:
    if "sma_50" not in df.columns or "sma_200" not in df.columns:
        return False
    s50, s200 = df["sma_50"].iloc[i], df["sma_200"].iloc[i]
    s50p, s200p = df["sma_50"].iloc[i - 1], df["sma_200"].iloc[i - 1]
    return bool(pd.notna(s50) and pd.notna(s200) and pd.notna(s50p) and pd.notna(s200p)
                and s50p > s200p and s50 <= s200)


def _entry_bb_bounce(df: pd.DataFrame, i: int) -> bool:
    if "bb_lower" not in df.columns:
        return False
    bl, blp = df["bb_lower"].iloc[i], df["bb_lower"].iloc[i - 1]
    c, cp = df["close"].iloc[i], df["close"].iloc[i - 1]
    return bool(pd.notna(bl) and pd.notna(blp) and cp < blp and c >= bl)


def _entry_volume_spike(df: pd.DataFrame, i: int) -> bool:
    if "volume" not in df.columns or "volume_sma_20" not in df.columns:
        return False
    vol, vol_avg = df["volume"].iloc[i], df["volume_sma_20"].iloc[i]
    return bool(pd.notna(vol) and pd.notna(vol_avg) and vol_avg > 0 and vol > vol_avg * 3)


def _entry_gap_up(df: pd.DataFrame, i: int) -> bool:
    if "open" not in df.columns:
        return False
    op, cp = df["open"].iloc[i], df["close"].iloc[i - 1]
    return bool(pd.notna(op) and pd.notna(cp) and op > cp * 1.02)


def _entry_gap_down(df: pd.DataFrame, i: int) -> bool:
    if "open" not in df.columns:
        return False
    op, cp = df["open"].iloc[i], df["close"].iloc[i - 1]
    return bool(pd.notna(op) and pd.notna(cp) and op < cp * 0.98)


def _entry_vix_reversal(df: pd.DataFrame, i: int) -> bool:
    if "macro_vix" not in df.columns or i < 3:
        return False
    vix_now = df["macro_vix"].iloc[i]
    if not (pd.notna(vix_now) and bool(vix_now <= 25)):
        return False
    prev_3 = [df["macro_vix"].iloc[i - k] for k in range(1, 4)]
    return all(pd.notna(v) and bool(v >= 30) for v in prev_3)


def _entry_pcr_reversal(df: pd.DataFrame, i: int) -> bool:
    if "macro_pcr" not in df.columns or i < 20:
        return False
    pcr_now = df["macro_pcr"].iloc[i]
    if not (pd.notna(pcr_now) and bool(pcr_now <= 0.8)):
        return False
    window = df["macro_pcr"].iloc[max(0, i - 20):i].dropna()
    if len(window) == 0:
        return False
    peak_val = window.max()
    if not bool(peak_val >= 1.2):
        return False
    return bool(window.idxmax() < i)  # 고점이 먼저


def _entry_yield_curve_recovery(df: pd.DataFrame, i: int) -> bool:
    if "macro_yield_spread" not in df.columns:
        return False
    spread = df["macro_yield_spread"].iloc[i]
    spread_prev = df["macro_yield_spread"].iloc[i - 1]
    return bool(pd.notna(spread) and pd.notna(spread_prev) and spread_prev < 0 and spread >= 0)


def _entry_insider_cluster(df: pd.DataFrame, i: int) -> bool:
    if "insider_buy_count_10d" not in df.columns:
        return False
    count = int(df["insider_buy_count_10d"].iloc[i])
    count_prev = int(df["insider_buy_count_10d"].iloc[i - 1])
    return count >= 3 and count_prev < 3


def _entry_short_squeeze(df: pd.DataFrame, i: int) -> bool:
    if "short_interest" not in df.columns or i < 3:
        return False
    si = df["short_interest"].iloc[i]
    if not (pd.notna(si) and bool(si >= 10)):
        return False
    return all(df["close"].iloc[i - k] > df["close"].iloc[i - k - 1] for k in range(3))


# ── 청산 감지 함수 (hold_days=None 시그널용) ──

def _exit_macd_golden(df: pd.DataFrame, i: int) -> bool:
    m, ms = df["macd"].iloc[i], df["macd_signal"].iloc[i]
    return bool(pd.notna(m) and pd.notna(ms) and m < ms)


def _exit_macd_dead(df: pd.DataFrame, i: int) -> bool:
    m, ms = df["macd"].iloc[i], df["macd_signal"].iloc[i]
    return bool(pd.notna(m) and pd.notna(ms) and m > ms)


def _exit_sma_golden(df: pd.DataFrame, i: int) -> bool:
    s50, s200 = df["sma_50"].iloc[i], df["sma_200"].iloc[i]
    return bool(pd.notna(s50) and pd.notna(s200) and s50 < s200)


def _exit_sma_dead(df: pd.DataFrame, i: int) -> bool:
    s50, s200 = df["sma_50"].iloc[i], df["sma_200"].iloc[i]
    return bool(pd.notna(s50) and pd.notna(s200) and s50 > s200)


def _exit_yield_curve_recovery(df: pd.DataFrame, i: int) -> bool:
    if "macro_yield_spread" not in df.columns:
        return False
    spread = df["macro_yield_spread"].iloc[i]
    return bool(pd.notna(spread) and spread < 0)


# ── 시그널 레지스트리 ──

SIGNAL_DEFINITIONS: dict[str, dict] = {
    "rsi_oversold": {
        "description": "RSI 과매도 반등 (30 아래에서 위로)",
        "hold_days": 20,
        "entry": _entry_rsi_oversold,
    },
    "rsi_overbought": {
        "description": "RSI 과매수 이탈 (70 위에서 아래로)",
        "hold_days": 20,
        "entry": _entry_rsi_overbought,
    },
    "macd_golden": {
        "description": "MACD 골든크로스 (MACD > Signal)",
        "hold_days": None,
        "entry": _entry_macd_golden,
        "exit": _exit_macd_golden,
    },
    "macd_dead": {
        "description": "MACD 데드크로스 (MACD < Signal)",
        "hold_days": None,
        "entry": _entry_macd_dead,
        "exit": _exit_macd_dead,
    },
    "sma_golden": {
        "description": "SMA 골든크로스 (SMA50 > SMA200)",
        "hold_days": None,
        "entry": _entry_sma_golden,
        "exit": _exit_sma_golden,
    },
    "sma_dead": {
        "description": "SMA 데드크로스 (SMA50 < SMA200)",
        "hold_days": None,
        "entry": _entry_sma_dead,
        "exit": _exit_sma_dead,
    },
    "bb_bounce": {
        "description": "BB 하단 반등 (종가가 BB Lower 위로)",
        "hold_days": 20,
        "entry": _entry_bb_bounce,
    },
    # ── 가격 기반 시그널 ──
    "volume_spike": {
        "description": "거래량 급증 (20일 평균 대비 3배 초과)",
        "hold_days": 10,
        "entry": _entry_volume_spike,
    },
    "gap_up": {
        "description": "갭 상승 (시가 > 전일 종가 × 1.02)",
        "hold_days": 10,
        "entry": _entry_gap_up,
    },
    "gap_down": {
        "description": "갭 하락 (시가 < 전일 종가 × 0.98)",
        "hold_days": 10,
        "entry": _entry_gap_down,
    },
    # ── 매크로 기반 시그널 ──
    "vix_reversal": {
        "description": "VIX 공포 반전 (30+ 3일 연속 → 25 이하)",
        "hold_days": 20,
        "entry": _entry_vix_reversal,
    },
    "pcr_reversal": {
        "description": "PCR 반전 (1.2+ → 0.8 이하, 고점→저점 순서)",
        "hold_days": 15,
        "entry": _entry_pcr_reversal,
    },
    "yield_curve_recovery": {
        "description": "수익률곡선 정상화 (3M-10Y 음수→양수)",
        "hold_days": None,
        "entry": _entry_yield_curve_recovery,
        "exit": _exit_yield_curve_recovery,
    },
    # ── 데이터 의존 시그널 ──
    "insider_cluster": {
        "description": "내부자 집중 매수 (10일 내 3건+ 매수)",
        "hold_days": 20,
        "entry": _entry_insider_cluster,
    },
    "short_squeeze": {
        "description": "숏 스퀴즈 가능성 (short_interest 높음 + 가격 반등)",
        "hold_days": 15,
        "entry": _entry_short_squeeze,
    },
}

# 매크로 시그널 ID 목록 (DB macro 테이블 데이터 필요)
MACRO_SIGNAL_IDS = {"vix_reversal", "pcr_reversal", "yield_curve_recovery"}

# 데이터 의존 시그널 ID 목록 (DB 별도 테이블 데이터 필요)
DATA_SIGNAL_IDS = {"insider_cluster", "short_squeeze"}


# ═══════════════════════════════════════════════════════
# 지표 계산 + 데이터 병합
# ═══════════════════════════════════════════════════════


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DataFrame에 TA-Lib 지표 추가."""
    close = df["close"].values

    try:
        import talib
        df["rsi_14"] = talib.RSI(close, timeperiod=14)
        macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        df["macd"], df["macd_signal"], df["macd_hist"] = macd, signal, hist
        upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
        df["bb_upper"], df["bb_middle"], df["bb_lower"] = upper, middle, lower
        df["sma_20"] = talib.SMA(close, timeperiod=20)
        df["sma_50"] = talib.SMA(close, timeperiod=50)
        df["sma_200"] = talib.SMA(close, timeperiod=200)
    except ImportError:
        # TA-Lib 없으면 pandas 폴백
        df["sma_20"] = df["close"].rolling(20).mean()
        df["sma_50"] = df["close"].rolling(50).mean()
        df["sma_200"] = df["close"].rolling(200).mean()
        bb_mid = df["sma_20"]
        bb_std = df["close"].rolling(20).std()
        df["bb_upper"] = bb_mid + 2 * bb_std
        df["bb_middle"] = bb_mid
        df["bb_lower"] = bb_mid - 2 * bb_std
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        df["rsi_14"] = 100 - (100 / (1 + rs))
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

    # 거래량 이동평균 (volume_spike 시그널용)
    if "volume" in df.columns:
        df["volume_sma_20"] = df["volume"].rolling(20).mean()

    return df


def _merge_asof_from_db(
    df: pd.DataFrame,
    sql: str,
    params: tuple,
    value_col: str,
    target_col: str,
    db_path=None,
) -> pd.DataFrame:
    """DB 쿼리 결과를 merge_asof로 가격 DataFrame에 병합하는 공통 헬퍼.

    Args:
        df: date 컬럼이 있는 가격 DataFrame
        sql: SELECT date, {value_col} ... 형태의 SQL
        params: SQL 파라미터
        value_col: DB 결과에서 가져올 값 컬럼명
        target_col: df에 추가할 컬럼명
        db_path: DB 경로
    """
    try:
        ext_df = query_df(sql, params, db_path=db_path)
        if ext_df.empty:
            df[target_col] = np.nan
            return df
        ext_df["date"] = pd.to_datetime(ext_df["date"])
        ext_df = ext_df.rename(columns={value_col: target_col})
        ext_df = ext_df.sort_values("date").drop_duplicates("date")
        df = pd.merge_asof(
            df.sort_values("date"), ext_df[["date", target_col]], on="date", direction="backward"
        )
    except Exception:
        df[target_col] = np.nan
    return df


def merge_macro_data(df: pd.DataFrame, db_path=None) -> pd.DataFrame:
    """가격 DataFrame에 매크로 지표 (VIX, PCR, 수익률) 병합."""
    if "date" not in df.columns:
        return df

    for indicator, col_name, fallback in [
        ("vix", "macro_vix", None),
        ("put_call_ratio", "macro_pcr", None),
        ("us_3m_yield", "macro_3m_yield", "us_2y_yield"),  # ^IRX(13주 T-Bill)가 us_2y_yield로 저장됨
        ("us_10y_yield", "macro_10y_yield", None),
    ]:
        df = _merge_asof_from_db(
            df,
            "SELECT date, value FROM macro WHERE indicator = ? ORDER BY date",
            (indicator,),
            "value", col_name, db_path=db_path,
        )
        # fallback: 주 indicator 데이터 없으면 대체 indicator 시도
        if fallback and col_name in df.columns and df[col_name].isna().all():
            df = df.drop(columns=[col_name])
            df = _merge_asof_from_db(
                df,
                "SELECT date, value FROM macro WHERE indicator = ? ORDER BY date",
                (fallback,),
                "value", col_name, db_path=db_path,
            )

    # 수익률곡선 스프레드 (10Y - 3M)
    if "macro_10y_yield" in df.columns and "macro_3m_yield" in df.columns:
        df["macro_yield_spread"] = df["macro_10y_yield"] - df["macro_3m_yield"]
    else:
        df["macro_yield_spread"] = np.nan

    return df


def merge_data_signals(df: pd.DataFrame, ticker: str, db_path=None) -> pd.DataFrame:
    """insider_cluster / short_squeeze용 데이터 병합."""
    if "date" not in df.columns:
        return df

    # ── insider_cluster: 10일 윈도우 내 매수 건수 ──
    try:
        insider_df = query_df(
            "SELECT date, transaction_type FROM insider_trades WHERE ticker = ? ORDER BY date",
            (ticker,), db_path=db_path,
        )
        if not insider_df.empty:
            insider_df["date"] = pd.to_datetime(insider_df["date"])
            buys = insider_df[insider_df["transaction_type"].str.contains("Purchase|Buy|P-Purchase", case=False, na=False)]
            buy_dates = buys["date"].tolist()
            df["insider_buy_count_10d"] = [
                sum(1 for bd in buy_dates if pd.Timedelta(days=0) <= (d - bd) <= pd.Timedelta(days=10))
                for d in df["date"]
            ]
        else:
            df["insider_buy_count_10d"] = 0
    except Exception:
        df["insider_buy_count_10d"] = 0

    # ── short_squeeze: external_analysis에서 short_interest ──
    df = _merge_asof_from_db(
        df,
        "SELECT date, numeric_value FROM external_analysis "
        "WHERE ticker = ? AND data_type = 'short_interest' ORDER BY date",
        (ticker,),
        "numeric_value", "short_interest", db_path=db_path,
    )

    return df


# ═══════════════════════════════════════════════════════
# 시그널 감지 + 청산 (레지스트리 기반)
# ═══════════════════════════════════════════════════════


def detect_signal_entries(df: pd.DataFrame, signal_id: str) -> list[int]:
    """시그널 진입 시점의 positional 인덱스 리스트 반환."""
    defn = SIGNAL_DEFINITIONS.get(signal_id)
    if defn is None or "entry" not in defn:
        return []

    detector = defn["entry"]
    return [i for i in range(1, len(df)) if detector(df, i)]


def compute_exit(df: pd.DataFrame, entry_idx: int, signal_id: str) -> int | None:
    """진입 positional 인덱스 → 청산 positional 인덱스."""
    hold_days = SIGNAL_DEFINITIONS[signal_id]["hold_days"]

    if hold_days is not None:
        exit_idx = entry_idx + hold_days
        return exit_idx if exit_idx < len(df) else None

    # 반대 크로스까지 보유 (exit 함수가 등록된 시그널만)
    exit_fn = SIGNAL_DEFINITIONS[signal_id].get("exit")
    if exit_fn is None:
        return None

    for i in range(entry_idx + 1, len(df)):
        if exit_fn(df, i):
            return i

    return None


# ═══════════════════════════════════════════════════════
# 하위호환 alias (기존 private import 지원)
# ═══════════════════════════════════════════════════════

_compute_indicators = compute_indicators
_detect_signal_entries = detect_signal_entries
_compute_exit = compute_exit
_merge_macro_data = merge_macro_data
_merge_data_signals = merge_data_signals


# ═══════════════════════════════════════════════════════
# 백테스트 실행
# ═══════════════════════════════════════════════════════


def backtest_signals(
    ticker: str | None = None,
    signals: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db_path=None,
) -> list[SignalResult]:
    """시그널 백테스트 실행."""
    signal_ids = signals or list(SIGNAL_DEFINITIONS.keys())

    if ticker:
        tickers = [ticker]
    else:
        tickers = get_tickers(db_path=db_path)

    results = []

    for tkr in tickers:
        sql = "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ?"
        params = [tkr]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        sql += " ORDER BY date"

        df = query_df(sql, tuple(params), db_path=db_path)
        if df.empty or len(df) < 20:
            logger.debug(f"{tkr}: 데이터 부족 ({len(df)}건)")
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)

        # 매크로 시그널 요청 시 매크로 데이터 병합
        if MACRO_SIGNAL_IDS & set(signal_ids):
            df = merge_macro_data(df, db_path=db_path)

        # 데이터 의존 시그널 요청 시 insider/short 데이터 병합
        if DATA_SIGNAL_IDS & set(signal_ids):
            df = merge_data_signals(df, tkr, db_path=db_path)

        for sig_id in signal_ids:
            entries = detect_signal_entries(df, sig_id)

            for entry_idx in entries:
                exit_idx = compute_exit(df, entry_idx, sig_id)
                if exit_idx is None:
                    continue

                entry_price = df["close"].iloc[entry_idx]
                exit_price = df["close"].iloc[exit_idx]
                return_pct = (exit_price - entry_price) / entry_price * 100
                holding_days = exit_idx - entry_idx

                results.append(SignalResult(
                    signal_id=sig_id,
                    ticker=tkr,
                    entry_date=df["date"].iloc[entry_idx].strftime("%Y-%m-%d"),
                    entry_price=round(float(entry_price), 2),
                    exit_date=df["date"].iloc[exit_idx].strftime("%Y-%m-%d"),
                    exit_price=round(float(exit_price), 2),
                    return_pct=round(float(return_pct), 2),
                    holding_days=int(holding_days),
                    won=bool(return_pct > 0),
                ))

        logger.info(f"{tkr}: {len([r for r in results if r.ticker == tkr])}건 시그널")

    return results


def generate_scorecard(results: list[SignalResult]) -> list[SignalScorecard]:
    """SignalResult → 시그널별 집계 스코어카드."""
    if not results:
        return []

    def _aggregate(group: list[SignalResult], sig_id: str, tkr: str | None) -> SignalScorecard:
        returns = [r.return_pct for r in group]
        wins = sum(1 for r in group if r.won)
        total_gain = sum(r.return_pct for r in group if r.return_pct > 0)
        total_loss = abs(sum(r.return_pct for r in group if r.return_pct < 0))
        pf = total_gain / total_loss if total_loss > 0 else float("inf")

        return SignalScorecard(
            signal_id=sig_id,
            ticker=tkr,
            total_trades=len(group),
            win_rate=wins / len(group),
            avg_return=round(np.mean(returns), 2),
            median_return=round(float(np.median(returns)), 2),
            max_return=round(max(returns), 2),
            max_loss=round(min(returns), 2),
            profit_factor=round(pf, 2) if pf != float("inf") else float("inf"),
            avg_holding_days=round(np.mean([r.holding_days for r in group]), 1),
        )

    scorecards = []

    grouped: dict[tuple[str, str], list[SignalResult]] = {}
    for r in results:
        grouped.setdefault((r.signal_id, r.ticker), []).append(r)
    for (sig_id, tkr), group in grouped.items():
        scorecards.append(_aggregate(group, sig_id, tkr))

    by_signal: dict[str, list[SignalResult]] = {}
    for r in results:
        by_signal.setdefault(r.signal_id, []).append(r)
    for sig_id, group in by_signal.items():
        scorecards.append(_aggregate(group, sig_id, None))

    return scorecards


def print_scorecard(scorecards: list[SignalScorecard]) -> None:
    """스코어카드 CLI 출력."""
    if not scorecards:
        print("스코어카드 데이터가 없습니다.")
        return

    total = [s for s in scorecards if s.ticker is None]
    total.sort(key=lambda s: s.profit_factor, reverse=True)

    print(f"\n{'=' * 75}")
    print("  시그널 스코어카드")
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
    today = today_kst()
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
