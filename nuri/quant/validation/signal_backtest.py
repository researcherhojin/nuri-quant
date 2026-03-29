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
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import get_tickers, query_df

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
    # ── Phase 3 신규 시그널 (8개) ──
    "volume_spike": {
        "description": "거래량 급증 (20일 평균 대비 3배 이상)",
        "hold_days": 10,
    },
    "gap_up": {
        "description": "갭 상승 (시가 > 전일 종가 × 1.02)",
        "hold_days": 10,
    },
    "gap_down": {
        "description": "갭 하락 (시가 < 전일 종가 × 0.98)",
        "hold_days": 10,
    },
    "pcr_reversal": {
        "description": "Put/Call Ratio 반전 (1.2 → 0.8, 5일 이내)",
        "hold_days": 20,
        "requires_macro": True,
    },
    "short_squeeze": {
        "description": "숏 스퀴즈 (공매도 비율 20%+ AND RSI 브레이크아웃)",
        "hold_days": 15,
        "requires_macro": True,
    },
    "insider_cluster": {
        "description": "내부자 집중 매수 (10일 내 3건 이상 매수)",
        "hold_days": 30,
        "requires_macro": True,
    },
    "vix_reversal": {
        "description": "VIX 반전 (30+ → 25 이하)",
        "hold_days": 20,
        "requires_macro": True,
    },
    "yield_inversion": {
        "description": "수익률곡선 정상화 (3M-10Y 역전 → 정상 전환)",
        "hold_days": 30,
        "requires_macro": True,
    },
}


# ═══════════════════════════════════════════════════════
# 지표 계산 + 시그널 감지
# ═══════════════════════════════════════════════════════


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DataFrame에 TA-Lib 지표 추가. charts.py의 _load_chart_data와 동일 로직."""
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

    # 거래량 20일 이동평균 (volume_spike 시그널용)
    if "volume" in df.columns:
        df["volume_avg_20"] = df["volume"].rolling(20).mean()

    return df


# ═══════════════════════════════════════════════════════
# 매크로 데이터 로딩 (신규 시그널용)
# ═══════════════════════════════════════════════════════


def _load_macro_series(indicator: str, db_path=None) -> pd.DataFrame:
    """macro 테이블에서 특정 지표 시계열 로드."""
    df = query_df(
        "SELECT date, value FROM macro WHERE indicator = ? ORDER BY date",
        (indicator,), db_path=db_path,
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _load_insider_trades(ticker: str, db_path=None) -> pd.DataFrame:
    """insider_trades 테이블에서 매수 거래 로드."""
    df = query_df(
        "SELECT date, transaction_type FROM insider_trades WHERE ticker = ? ORDER BY date",
        (ticker,), db_path=db_path,
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


# ═══════════════════════════════════════════════════════
# 개별 시그널 감지 함수 (Phase 3 신규)
# ═══════════════════════════════════════════════════════


def _detect_volume_spike(df: pd.DataFrame, i: int) -> bool:
    """거래량 급증: Volume > 3x 20일 평균."""
    if "volume_avg_20" not in df.columns:
        return False
    vol = df["volume"].iloc[i]
    avg = df["volume_avg_20"].iloc[i]
    return bool(pd.notna(avg) and avg > 0 and vol > avg * 3)


def _detect_gap_up(df: pd.DataFrame, i: int) -> bool:
    """갭 상승: 시가 > 전일 종가 × 1.02."""
    if i < 1 or "open" not in df.columns:
        return False
    open_price = df["open"].iloc[i]
    prev_close = df["close"].iloc[i - 1]
    return bool(pd.notna(open_price) and pd.notna(prev_close) and open_price > prev_close * 1.02)


def _detect_gap_down(df: pd.DataFrame, i: int) -> bool:
    """갭 하락: 시가 < 전일 종가 × 0.98."""
    if i < 1 or "open" not in df.columns:
        return False
    open_price = df["open"].iloc[i]
    prev_close = df["close"].iloc[i - 1]
    return bool(pd.notna(open_price) and pd.notna(prev_close) and open_price < prev_close * 0.98)


def _detect_pcr_reversal_entries(dates: pd.Series, pcr_df: pd.DataFrame) -> list[int]:
    """Put/Call Ratio 반전: 5일 이내 1.2 → 0.8 하락.

    매크로 지표 기반 시그널이므로 날짜 매칭으로 감지.
    """
    if pcr_df.empty:
        return []

    entries = []
    pcr_df = pcr_df.set_index("date").sort_index()

    for i in range(5, len(dates)):
        date = dates.iloc[i]
        # 과거 5일 내 PCR 데이터 검색
        window_start = dates.iloc[i - 5]
        pcr_window = pcr_df.loc[
            (pcr_df.index >= window_start) & (pcr_df.index <= date), "value"
        ]
        if len(pcr_window) >= 2:
            # 윈도우 내 최고점 1.2 이상이었다가 현재 0.8 이하로 하락
            max_pcr = pcr_window.max()
            current_pcr = pcr_window.iloc[-1] if not pcr_window.empty else None
            if current_pcr is not None and max_pcr >= 1.2 and current_pcr <= 0.8:
                entries.append(i)

    return entries


def _detect_short_squeeze_entries(
    df: pd.DataFrame, dates: pd.Series, short_df: pd.DataFrame,
) -> list[int]:
    """숏 스퀴즈: 공매도 비율 20%+ AND RSI가 50 상향 돌파."""
    if short_df.empty or "rsi_14" not in df.columns:
        return []

    entries = []
    short_df = short_df.set_index("date").sort_index()

    for i in range(1, len(df)):
        date = dates.iloc[i]
        rsi = df["rsi_14"].iloc[i]
        rsi_prev = df["rsi_14"].iloc[i - 1]

        if not (pd.notna(rsi) and pd.notna(rsi_prev)):
            continue

        # RSI 50 상향 돌파
        if rsi_prev < 50 and rsi >= 50:
            # 해당 날짜에 공매도 비율 20% 이상 확인
            si_rows = short_df.loc[short_df.index <= date, "value"]
            if not si_rows.empty and si_rows.iloc[-1] >= 20:
                entries.append(i)

    return entries


def _detect_insider_cluster_entries(
    dates: pd.Series, insider_df: pd.DataFrame,
) -> list[int]:
    """내부자 집중 매수: 10일 내 3건 이상 매수."""
    if insider_df.empty:
        return []

    # 매수(Purchase/Buy) 거래만 필터
    buy_df = insider_df[
        insider_df["transaction_type"].str.lower().str.contains("purchase|buy", na=False)
    ]
    if buy_df.empty:
        return []

    entries = []
    for i in range(10, len(dates)):
        date = dates.iloc[i]
        window_start = dates.iloc[i - 10]
        # 10일 윈도우 내 매수 건수
        count = buy_df[
            (buy_df["date"] >= window_start) & (buy_df["date"] <= date)
        ].shape[0]
        if count >= 3:
            entries.append(i)

    return entries


def _detect_vix_reversal_entries(dates: pd.Series, vix_df: pd.DataFrame) -> list[int]:
    """VIX 반전: VIX 30+ → 25 이하 하락."""
    if vix_df.empty:
        return []

    entries = []
    vix_df = vix_df.set_index("date").sort_index()

    for i in range(1, len(dates)):
        date = dates.iloc[i]
        prev_date = dates.iloc[i - 1]

        vix_rows = vix_df.loc[vix_df.index <= date, "value"]
        vix_prev_rows = vix_df.loc[vix_df.index <= prev_date, "value"]

        if vix_rows.empty or vix_prev_rows.empty:
            continue

        current_vix = vix_rows.iloc[-1]
        prev_vix = vix_prev_rows.iloc[-1]

        # 전일 30 이상이었다가 당일 25 이하로 하락
        if prev_vix >= 30 and current_vix < 25:
            entries.append(i)

    return entries


def _detect_yield_inversion_entries(
    dates: pd.Series, y3m_df: pd.DataFrame, y10_df: pd.DataFrame,
) -> list[int]:
    """수익률곡선 정상화: 3M-10Y 스프레드가 음수 → 양수 전환."""
    if y3m_df.empty or y10_df.empty:
        return []

    entries = []
    y3m_df = y3m_df.set_index("date").sort_index()
    y10_df = y10_df.set_index("date").sort_index()

    for i in range(1, len(dates)):
        date = dates.iloc[i]
        prev_date = dates.iloc[i - 1]

        y3m_rows = y3m_df.loc[y3m_df.index <= date, "value"]
        y10_rows = y10_df.loc[y10_df.index <= date, "value"]
        y3m_prev = y3m_df.loc[y3m_df.index <= prev_date, "value"]
        y10_prev = y10_df.loc[y10_df.index <= prev_date, "value"]

        if y3m_rows.empty or y10_rows.empty or y3m_prev.empty or y10_prev.empty:
            continue

        spread_now = y10_rows.iloc[-1] - y3m_rows.iloc[-1]
        spread_prev = y10_prev.iloc[-1] - y3m_prev.iloc[-1]

        # 역전(음수) → 정상(양수) 전환
        if spread_prev < 0 and spread_now >= 0:
            entries.append(i)

    return entries


def _detect_signal_entries(df: pd.DataFrame, signal_id: str) -> list[int]:
    """시그널 진입 시점의 positional 인덱스 리스트 반환.

    Args:
        df: 지표가 계산된 가격 DataFrame (positional index 사용)
        signal_id: SIGNAL_DEFINITIONS의 키

    Returns:
        진입 시점 positional 인덱스 리스트
    """
    entries = []

    for i in range(1, len(df)):
        rsi = df["rsi_14"].iloc[i]
        rsi_prev = df["rsi_14"].iloc[i - 1]
        macd = df["macd"].iloc[i]
        macd_sig = df["macd_signal"].iloc[i]
        macd_prev = df["macd"].iloc[i - 1]
        macd_sig_prev = df["macd_signal"].iloc[i - 1]
        sma50 = df["sma_50"].iloc[i] if "sma_50" in df.columns else np.nan
        sma200 = df["sma_200"].iloc[i] if "sma_200" in df.columns else np.nan
        sma50_prev = df["sma_50"].iloc[i - 1] if "sma_50" in df.columns else np.nan
        sma200_prev = df["sma_200"].iloc[i - 1] if "sma_200" in df.columns else np.nan
        close = df["close"].iloc[i]
        close_prev = df["close"].iloc[i - 1]
        bb_lower = df["bb_lower"].iloc[i] if "bb_lower" in df.columns else np.nan
        bb_lower_prev = df["bb_lower"].iloc[i - 1] if "bb_lower" in df.columns else np.nan

        if signal_id == "rsi_oversold":
            if pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev < 30 and rsi >= 30:
                entries.append(i)
        elif signal_id == "rsi_overbought":
            if pd.notna(rsi) and pd.notna(rsi_prev) and rsi_prev > 70 and rsi <= 70:
                entries.append(i)
        elif signal_id == "macd_golden":
            if (pd.notna(macd) and pd.notna(macd_sig) and
                    pd.notna(macd_prev) and pd.notna(macd_sig_prev) and
                    macd_prev < macd_sig_prev and macd >= macd_sig):
                entries.append(i)
        elif signal_id == "macd_dead":
            if (pd.notna(macd) and pd.notna(macd_sig) and
                    pd.notna(macd_prev) and pd.notna(macd_sig_prev) and
                    macd_prev > macd_sig_prev and macd <= macd_sig):
                entries.append(i)
        elif signal_id == "sma_golden":
            if (pd.notna(sma50) and pd.notna(sma200) and
                    pd.notna(sma50_prev) and pd.notna(sma200_prev) and
                    sma50_prev < sma200_prev and sma50 >= sma200):
                entries.append(i)
        elif signal_id == "sma_dead":
            if (pd.notna(sma50) and pd.notna(sma200) and
                    pd.notna(sma50_prev) and pd.notna(sma200_prev) and
                    sma50_prev > sma200_prev and sma50 <= sma200):
                entries.append(i)
        elif signal_id == "bb_bounce":
            if (pd.notna(bb_lower) and pd.notna(bb_lower_prev) and
                    close_prev < bb_lower_prev and close >= bb_lower):
                entries.append(i)
        # ── Phase 3 가격 기반 시그널 ──
        elif signal_id == "volume_spike":
            if _detect_volume_spike(df, i):
                entries.append(i)
        elif signal_id == "gap_up":
            if _detect_gap_up(df, i):
                entries.append(i)
        elif signal_id == "gap_down":
            if _detect_gap_down(df, i):
                entries.append(i)

    return entries


def _compute_exit(df: pd.DataFrame, entry_idx: int, signal_id: str) -> int | None:
    """진입 positional 인덱스 → 청산 positional 인덱스.

    hold_days가 있는 시그널: entry_idx + hold_days (데이터 범위 내)
    hold_days가 None인 시그널: 반대 크로스 발생 시점

    Returns:
        청산 인덱스, 또는 청산 불가 시 None
    """
    hold_days = SIGNAL_DEFINITIONS[signal_id]["hold_days"]

    if hold_days is not None:
        exit_idx = entry_idx + hold_days
        if exit_idx >= len(df):
            return None  # 데이터 부족으로 청산 불가
        return exit_idx

    # 반대 크로스까지 보유
    for i in range(entry_idx + 1, len(df)):
        if signal_id == "macd_golden":
            # MACD < Signal이면 청산
            macd = df["macd"].iloc[i]
            sig = df["macd_signal"].iloc[i]
            if pd.notna(macd) and pd.notna(sig) and macd < sig:
                return i
        elif signal_id == "macd_dead":
            # MACD > Signal이면 청산
            macd = df["macd"].iloc[i]
            sig = df["macd_signal"].iloc[i]
            if pd.notna(macd) and pd.notna(sig) and macd > sig:
                return i
        elif signal_id == "sma_golden":
            # SMA50 < SMA200이면 청산
            sma50 = df["sma_50"].iloc[i]
            sma200 = df["sma_200"].iloc[i]
            if pd.notna(sma50) and pd.notna(sma200) and sma50 < sma200:
                return i
        elif signal_id == "sma_dead":
            # SMA50 > SMA200이면 청산
            sma50 = df["sma_50"].iloc[i]
            sma200 = df["sma_200"].iloc[i]
            if pd.notna(sma50) and pd.notna(sma200) and sma50 > sma200:
                return i

    return None  # 데이터 끝까지 반대 크로스 없음


def backtest_signals(
    ticker: str | None = None,
    signals: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db_path=None,
) -> list[SignalResult]:
    """시그널 백테스트 실행.

    Args:
        ticker: 특정 종목만 (None=전체)
        signals: 특정 시그널만 (None=전체)
        start_date: 시작일 (None=전체)
        end_date: 종료일 (None=전체)
        db_path: DB 경로 (테스트용)

    Returns:
        개별 거래 결과 리스트
    """
    signal_ids = signals or list(SIGNAL_DEFINITIONS.keys())

    # 매크로 기반 시그널과 가격 기반 시그널 분리
    macro_signals = {s for s in signal_ids if SIGNAL_DEFINITIONS.get(s, {}).get("requires_macro")}
    price_signals = [s for s in signal_ids if s not in macro_signals]

    # 매크로 데이터 사전 로드 (필요한 경우만)
    pcr_df = _load_macro_series("put_call_ratio", db_path) if "pcr_reversal" in macro_signals else pd.DataFrame()
    vix_df = _load_macro_series("vix", db_path) if "vix_reversal" in macro_signals else pd.DataFrame()
    y3m_df = _load_macro_series("us_3m_yield", db_path) if "yield_inversion" in macro_signals else pd.DataFrame()
    y10_df = _load_macro_series("us_10y_yield", db_path) if "yield_inversion" in macro_signals else pd.DataFrame()
    short_df_cache: dict[str, pd.DataFrame] = {}  # ticker → short_interest DF

    # 종목 목록 결정
    if ticker:
        tickers = [ticker]
    else:
        tickers = get_tickers(db_path=db_path)

    results = []

    for tkr in tickers:
        # prices에서 OHLCV 로드
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

        # 지표 계산
        df = _compute_indicators(df)

        # 가격 기반 시그널 백테스트
        for sig_id in price_signals:
            entries = _detect_signal_entries(df, sig_id)

            for entry_idx in entries:
                exit_idx = _compute_exit(df, entry_idx, sig_id)
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

        # ── 매크로 기반 시그널 백테스트 ──
        for sig_id in macro_signals:
            if sig_id == "pcr_reversal":
                entries = _detect_pcr_reversal_entries(df["date"], pcr_df)
            elif sig_id == "short_squeeze":
                if tkr not in short_df_cache:
                    short_df_cache[tkr] = _load_macro_series("short_interest", db_path)
                entries = _detect_short_squeeze_entries(df, df["date"], short_df_cache[tkr])
            elif sig_id == "insider_cluster":
                insider_df = _load_insider_trades(tkr, db_path)
                entries = _detect_insider_cluster_entries(df["date"], insider_df)
            elif sig_id == "vix_reversal":
                entries = _detect_vix_reversal_entries(df["date"], vix_df)
            elif sig_id == "yield_inversion":
                entries = _detect_yield_inversion_entries(df["date"], y3m_df, y10_df)
            else:
                entries = []

            for entry_idx in entries:
                exit_idx = _compute_exit(df, entry_idx, sig_id)
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
    """SignalResult → 시그널별 집계 스코어카드.

    집계 기준: (signal_id, ticker) + (signal_id, None) 전체합산
    """
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

    # (signal_id, ticker) 별 집계
    grouped: dict[tuple[str, str], list[SignalResult]] = {}
    for r in results:
        grouped.setdefault((r.signal_id, r.ticker), []).append(r)

    for (sig_id, tkr), group in grouped.items():
        scorecards.append(_aggregate(group, sig_id, tkr))

    # (signal_id, None) 전체합산
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

    # 전체 합산 (ticker=None)만 출력
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
