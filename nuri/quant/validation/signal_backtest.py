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
from nuri.core.signal_config import (
    SIGNAL_CONFIG,
    get_signal_params,
    list_buy_signals,
    list_sell_signals,
)
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
    threshold = get_signal_params("rsi_oversold").get("threshold", 30)
    rsi, rsi_prev = df["rsi_14"].iloc[i], df["rsi_14"].iloc[i - 1]
    return bool(pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev < threshold and rsi >= threshold)


def _entry_rsi_overbought(df: pd.DataFrame, i: int) -> bool:
    threshold = get_signal_params("rsi_overbought").get("threshold", 70)
    rsi, rsi_prev = df["rsi_14"].iloc[i], df["rsi_14"].iloc[i - 1]
    return bool(pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev > threshold and rsi <= threshold)


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
    multiplier = get_signal_params("volume_spike").get("multiplier", 3.0)
    vol, vol_avg = df["volume"].iloc[i], df["volume_sma_20"].iloc[i]
    return bool(pd.notna(vol) and pd.notna(vol_avg) and vol_avg > 0 and vol > vol_avg * multiplier)


def _entry_gap_up(df: pd.DataFrame, i: int) -> bool:
    if "open" not in df.columns:
        return False
    threshold = get_signal_params("gap_up").get("threshold", 0.02)
    op, cp = df["open"].iloc[i], df["close"].iloc[i - 1]
    return bool(pd.notna(op) and pd.notna(cp) and op > cp * (1 + threshold))


def _entry_gap_down(df: pd.DataFrame, i: int) -> bool:
    if "open" not in df.columns:
        return False
    threshold = get_signal_params("gap_down").get("threshold", 0.02)
    op, cp = df["open"].iloc[i], df["close"].iloc[i - 1]
    return bool(pd.notna(op) and pd.notna(cp) and op < cp * (1 - threshold))


def _entry_vix_reversal(df: pd.DataFrame, i: int) -> bool:
    params = get_signal_params("vix_reversal")
    vix_high = params.get("vix_high", 30)
    vix_low = params.get("vix_low", 25)
    consecutive = params.get("consecutive_days", 3)
    if "macro_vix" not in df.columns or i < consecutive:
        return False
    vix_now = df["macro_vix"].iloc[i]
    if not (pd.notna(vix_now) and bool(vix_now <= vix_low)):
        return False
    prev_n = [df["macro_vix"].iloc[i - k] for k in range(1, consecutive + 1)]
    return all(pd.notna(v) and bool(v >= vix_high) for v in prev_n)


def _entry_pcr_reversal(df: pd.DataFrame, i: int) -> bool:
    params = get_signal_params("pcr_reversal")
    pcr_high = params.get("pcr_high", 1.2)
    pcr_low = params.get("pcr_low", 0.8)
    lookback = params.get("lookback_days", 20)
    if "macro_pcr" not in df.columns or i < lookback:
        return False
    pcr_now = df["macro_pcr"].iloc[i]
    if not (pd.notna(pcr_now) and bool(pcr_now <= pcr_low)):
        return False
    window = df["macro_pcr"].iloc[max(0, i - lookback):i].dropna()
    if len(window) == 0:
        return False
    peak_val = window.max()
    if not bool(peak_val >= pcr_high):
        return False
    # window 은 reset_index 된 positional index 기반이므로 idxmax 는 int. 그러나
    # Pylance 는 Index 타입을 Hashable (int|str 등) 로 보므로 명시적 int() cast.
    return bool(int(window.idxmax()) < i)  # 고점이 먼저


def _entry_yield_curve_recovery(df: pd.DataFrame, i: int) -> bool:
    if "macro_yield_spread" not in df.columns:
        return False
    spread = df["macro_yield_spread"].iloc[i]
    spread_prev = df["macro_yield_spread"].iloc[i - 1]
    return bool(pd.notna(spread) and pd.notna(spread_prev) and spread_prev < 0 and spread >= 0)


def _entry_insider_cluster(df: pd.DataFrame, i: int) -> bool:
    if "insider_buy_count_10d" not in df.columns:
        return False
    min_count = get_signal_params("insider_cluster").get("min_count", 3)
    count = int(df["insider_buy_count_10d"].iloc[i])
    count_prev = int(df["insider_buy_count_10d"].iloc[i - 1])
    return count >= min_count and count_prev < min_count


def _entry_short_squeeze(df: pd.DataFrame, i: int) -> bool:
    params = get_signal_params("short_squeeze")
    min_si = params.get("min_short_interest", 10)
    consecutive = params.get("consecutive_up_days", 3)
    if "short_interest" not in df.columns or i < consecutive:
        return False
    si = df["short_interest"].iloc[i]
    if not (pd.notna(si) and bool(si >= min_si)):
        return False
    return all(df["close"].iloc[i - k] > df["close"].iloc[i - k - 1] for k in range(consecutive))


# ── 차트 패턴 시그널 (chart_analysis.py와 동일 컨셉) ──


def _entry_macd_bullish_turn(df: pd.DataFrame, i: int) -> bool:
    """MACD 히스토그램 음→양 전환 (모멘텀 회복)."""
    if "macd_hist" not in df.columns or i < 1:
        return False
    h, h_prev = df["macd_hist"].iloc[i], df["macd_hist"].iloc[i - 1]
    return bool(pd.notna(h) and pd.notna(h_prev) and h_prev < 0 and h >= 0)


def _entry_macd_bearish_turn(df: pd.DataFrame, i: int) -> bool:
    """MACD 히스토그램 양→음 전환 (모멘텀 둔화)."""
    if "macd_hist" not in df.columns or i < 1:
        return False
    h, h_prev = df["macd_hist"].iloc[i], df["macd_hist"].iloc[i - 1]
    return bool(pd.notna(h) and pd.notna(h_prev) and h_prev > 0 and h <= 0)


def _entry_bb_squeeze_breakout(df: pd.DataFrame, i: int) -> bool:
    """BB squeeze 후 상단 돌파 (변동성 압축 → 방향성 출현)."""
    params = get_signal_params("bb_squeeze_breakout")
    squeeze_ratio = params.get("squeeze_ratio", 0.7)
    lookback = params.get("lookback_days", 20)
    required = {"bb_upper", "bb_lower", "bb_middle", "close"}
    if not required.issubset(df.columns) or i < lookback:
        return False
    upper = df["bb_upper"].iloc[i]
    lower = df["bb_lower"].iloc[i]
    middle = df["bb_middle"].iloc[i]
    close = df["close"].iloc[i]
    close_prev = df["close"].iloc[i - 1]
    upper_prev = df["bb_upper"].iloc[i - 1]
    if pd.isna(upper) or pd.isna(lower) or pd.isna(middle) or middle == 0:
        return False
    width = (upper - lower) / middle
    widths = ((df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]).iloc[max(0, i - lookback):i]
    avg_width = widths.mean()
    if pd.isna(avg_width) or avg_width == 0:
        return False
    is_squeezed = width < avg_width * squeeze_ratio
    is_breakout = bool(close > upper and close_prev <= upper_prev)
    return bool(is_squeezed and is_breakout)


def _entry_near_52w_low_bounce(df: pd.DataFrame, i: int) -> bool:
    """52주 저점 근접에서 반등 (가치 반등)."""
    params = get_signal_params("near_52w_low_bounce")
    proximity = params.get("proximity_pct", 0.10)
    bounce = params.get("bounce_pct", 0.03)
    bounce_days = params.get("bounce_days", 3)
    lookback = params.get("lookback_days", 252)
    if "close" not in df.columns or i < lookback:
        return False
    window = df["close"].iloc[max(0, i - lookback):i + 1]
    low_window = window.min()
    close = df["close"].iloc[i]
    close_back = df["close"].iloc[i - bounce_days] if i >= bounce_days else close
    if pd.isna(low_window) or low_window == 0:
        return False
    near_low = (close - low_window) / low_window <= proximity
    bounced = (close - close_back) / close_back >= bounce
    return bool(near_low and bounced)


def _entry_volume_profile_resistance(df: pd.DataFrame, i: int) -> bool:
    """매물대(POC) 구간 통과 + 거래량 급증."""
    params = get_signal_params("volume_profile_resistance")
    proximity = params.get("poc_proximity", 0.02)
    vol_mult = params.get("volume_multiplier", 1.5)
    lookback = params.get("lookback_days", 120)
    required = {"close", "volume"}
    if not required.issubset(df.columns) or i < lookback:
        return False
    sub = df[["close", "volume"]].iloc[max(0, i - lookback):i].dropna()
    if sub.empty or sub["volume"].sum() == 0:
        return False
    vwap = (sub["close"] * sub["volume"]).sum() / sub["volume"].sum()
    close = df["close"].iloc[i]
    vol = df["volume"].iloc[i]
    avg_vol = sub["volume"].mean()
    near_poc = abs(close - vwap) / vwap <= proximity
    high_vol = pd.notna(vol) and vol > avg_vol * vol_mult
    return bool(near_poc and high_vol)


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
#
# 시그널 메타데이터 (description, hold_days, type=BUY/SELL, enabled, params)는
# config/signals.yaml에서 관리. 본 모듈은 detector 함수만 등록하고,
# _build_signal_definitions()가 YAML + detector를 결합해 SIGNAL_DEFINITIONS를 빌드.

# detector 함수 레지스트리 (entry)
_ENTRY_DETECTORS: dict[str, EntryDetector] = {
    "rsi_oversold": _entry_rsi_oversold,
    "rsi_overbought": _entry_rsi_overbought,
    "macd_golden": _entry_macd_golden,
    "macd_dead": _entry_macd_dead,
    "sma_golden": _entry_sma_golden,
    "sma_dead": _entry_sma_dead,
    "bb_bounce": _entry_bb_bounce,
    "volume_spike": _entry_volume_spike,
    "gap_up": _entry_gap_up,
    "gap_down": _entry_gap_down,
    "vix_reversal": _entry_vix_reversal,
    "pcr_reversal": _entry_pcr_reversal,
    "yield_curve_recovery": _entry_yield_curve_recovery,
    "insider_cluster": _entry_insider_cluster,
    "short_squeeze": _entry_short_squeeze,
    "macd_bullish_turn": _entry_macd_bullish_turn,
    "macd_bearish_turn": _entry_macd_bearish_turn,
    "bb_squeeze_breakout": _entry_bb_squeeze_breakout,
    "near_52w_low_bounce": _entry_near_52w_low_bounce,
    "volume_profile_resistance": _entry_volume_profile_resistance,
}

# detector 함수 레지스트리 (exit, hold_days=null 시그널용)
_EXIT_DETECTORS: dict[str, ExitDetector] = {
    "macd_golden": _exit_macd_golden,
    "macd_dead": _exit_macd_dead,
    "sma_golden": _exit_sma_golden,
    "sma_dead": _exit_sma_dead,
    "yield_curve_recovery": _exit_yield_curve_recovery,
}


def _build_signal_definitions() -> dict[str, dict]:
    """config/signals.yaml + detector 레지스트리에서 SIGNAL_DEFINITIONS 빌드.

    YAML 메타데이터 (description/hold_days/enabled) + Python detector 결합.
    `enabled=false` 시그널은 제외. `scope: market_wide` 시그널 (SHADOW crash
    precursors, PR C #436) 은 per-ticker 백테스트 엔진에 들어가지 않음 — 별도
    `nuri/quant/validation/market_signals.py::DETECTORS` 에 등록되어 daily brief
    및 SHADOW surface 에서만 사용. silent skip (warning 발생 안 함).
    """
    cfg = SIGNAL_CONFIG.get("signals", {})
    result: dict[str, dict] = {}
    for sid, meta in cfg.items():
        if not meta.get("enabled", True):
            continue
        if meta.get("scope") == "market_wide":
            # SHADOW market-wide signals — market_signals.DETECTORS 가 처리.
            # per-ticker backtest 와 등록 경로 분리 (PR C codex Plan consult).
            continue
        if sid not in _ENTRY_DETECTORS:
            logger.warning("signals.yaml에 정의된 %s에 대응하는 detector 함수 없음", sid)
            continue
        result[sid] = {
            "description": meta.get("description", sid),
            "hold_days": meta.get("hold_days"),
            "entry": _ENTRY_DETECTORS[sid],
        }
        if sid in _EXIT_DETECTORS:
            result[sid]["exit"] = _EXIT_DETECTORS[sid]
    return result


SIGNAL_DEFINITIONS: dict[str, dict] = _build_signal_definitions()

# 매크로 시그널 ID 목록 (DB macro 테이블 데이터 필요)
MACRO_SIGNAL_IDS = {"vix_reversal", "pcr_reversal", "yield_curve_recovery"}

# 데이터 의존 시그널 ID 목록 (DB 별도 테이블 데이터 필요)
DATA_SIGNAL_IDS = {"insider_cluster", "short_squeeze"}

# 매수/매도 시그널 분류 — config/signals.yaml의 type 필드에서 자동 빌드
BUY_SIGNALS: set[str] = list_buy_signals()
SELL_SIGNALS: set[str] = list_sell_signals()


# ═══════════════════════════════════════════════════════
# 지표 계산 + 데이터 병합
# ═══════════════════════════════════════════════════════


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DataFrame에 TA-Lib 지표 추가."""
    # talib 는 NDArray[float64] 를 기대. pandas .values 는 ExtensionArray 포함 union
    # 타입으로 추론되므로 명시적 float64 ndarray 변환이 type-safe.
    close = np.asarray(df["close"].values, dtype=np.float64)

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
                raw_return_pct = (exit_price - entry_price) / entry_price * 100
                # SELL 시그널은 short/exit 관점 — 가격 하락이 "이김". sign 반전 필수.
                # 2026-04-17 STRATEGY §2.1 Evidence-first 위반 버그 수정 (codex audit).
                # 이전까지 SELL 시그널도 buy 와 동일 공식으로 측정 → 모든 SELL 의 scorecard
                # avg_return/PF 가 "매도 후 가격 상승 = 이김" 으로 계산되던 문제.
                if sig_id in SELL_SIGNALS:
                    return_pct = -raw_return_pct
                else:
                    return_pct = raw_return_pct
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
            avg_return=round(float(np.mean(returns)), 2),
            median_return=round(float(np.median(returns)), 2),
            max_return=round(max(returns), 2),
            max_loss=round(min(returns), 2),
            profit_factor=round(pf, 2) if pf != float("inf") else float("inf"),
            avg_holding_days=round(float(np.mean([r.holding_days for r in group])), 1),
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
