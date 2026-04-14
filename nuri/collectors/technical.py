"""
기술적 지표 수집기 — prices 테이블 데이터 기반으로 지표 계산.

RSI(14), MACD(12,26,9), Bollinger Bands(20,2), SMA(20/50/200), EMA(12/26)
TA-Lib 사용 (brew install ta-lib 필요).

사용법:
    python -m nuri.collectors.technical
"""

import logging

import numpy as np
import pandas as pd
import talib

from nuri.collectors.base import BaseCollector
from nuri.core.db import query_df, upsert_signals


class TechnicalCollector(BaseCollector):
    """prices 테이블 기반 기술적 지표 계산."""

    def __init__(self):
        super().__init__("technical")

    def collect(self, source: str = "portfolio", **kwargs) -> pd.DataFrame:
        """전체 보유 종목의 기술적 지표 계산. source='universe' 시 universe.yaml 전체 (#272)."""
        tickers = self._get_tickers(source=source)
        if not tickers:
            self.logger.warning("계산할 종목 없음")
            return pd.DataFrame()

        from tqdm import tqdm

        self.logger.info(f"기술적 지표 대상: {len(tickers)}종목 (source={source})")
        frames: list[pd.DataFrame] = []
        succeeded: list[str] = []
        skipped: list[str] = []
        iterator = tqdm(tickers, desc=f"  technical [{source}]", unit="tk", disable=len(tickers) < 20)
        for ticker in iterator:
            df = self._compute_for_ticker(ticker)
            if df is not None and not df.empty:
                frames.append(df)
                succeeded.append(ticker)
            else:
                skipped.append(ticker)

        if len(tickers) >= 20:
            self.logger.info(
                "📊 기술적 지표: ✅ %d 계산 / ⚠️  %d 데이터부족 (총 %d)",
                len(succeeded),
                len(skipped),
                len(tickers),
            )

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _compute_for_ticker(self, ticker: str) -> pd.DataFrame | None:
        """단일 종목의 기술적 지표 계산."""
        # 최소 200일 데이터 필요 (SMA 200)
        prices = query_df(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            (ticker,),
        )
        if len(prices) < 14:  # RSI 최소 요구
            self.logger.warning(f"{ticker}: 데이터 부족 ({len(prices)}일)")
            return None

        close = prices["close"].values.astype(float)

        result = self._compute_talib(close)

        # 최근 데이터만 추출 (마지막 행)
        last_idx = len(close) - 1
        row = {
            "ticker": ticker,
            "date": prices.iloc[last_idx]["date"],
        }
        for key, arr in result.items():
            row[key] = float(arr[last_idx]) if not np.isnan(arr[last_idx]) else None

        return pd.DataFrame([row])

    @staticmethod
    def _compute_talib(close: np.ndarray) -> dict:
        """TA-Lib으로 지표 계산."""
        macd, macd_signal, macd_hist = talib.MACD(close, 12, 26, 9)
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close, 20, 2.0, 2.0)

        return {
            "rsi_14": talib.RSI(close, 14),
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "sma_20": talib.SMA(close, 20),
            "sma_50": talib.SMA(close, 50),
            "sma_200": talib.SMA(close, 200),
            "ema_12": talib.EMA(close, 12),
            "ema_26": talib.EMA(close, 26),
        }

    def save(self, data: pd.DataFrame) -> int:
        """기술적 지표를 DB에 저장."""
        if data.empty:
            return 0
        return upsert_signals(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = TechnicalCollector()
    collector.run()
