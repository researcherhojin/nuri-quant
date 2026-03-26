"""
미국 주가 데이터 수집기 — OpenBB Platform 기반.

OpenBB가 다중 프로바이더(yfinance, polygon, tiingo 등)를 지원하며,
에러 핸들링과 재시도 로직이 내장되어 있다.
한국 종목은 stock_kr.py에서 pykrx로 별도 처리.

사용법:
    python -m nuri.collectors.stock               # 미국 전체 종목
    python -m nuri.collectors.stock --period 1mo   # 1개월 데이터
"""
import argparse
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_prices

# OpenBB 프로바이더 우선순위 (무료)
PROVIDERS = ["yfinance"]


class StockCollector(BaseCollector):
    """OpenBB Platform으로 미국 주가 수집."""

    def __init__(self):
        super().__init__("stock")

    def collect(
        self,
        market: Optional[str] = None,
        period: str = "5d",
        **kwargs,
    ) -> pd.DataFrame:
        """OpenBB로 미국 보유 종목 OHLCV 수집."""
        # 한국 종목은 stock_kr.py에서 처리
        tickers = self._get_tickers(market="us")
        if not tickers:
            self.logger.warning("수집할 미국 종목이 없습니다")
            return pd.DataFrame()

        self.logger.info(f"수집 대상: {len(tickers)} 미국 종목 ({period})")

        # 기간 계산
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = self._period_to_start_date(period)

        frames = []
        for ticker in tickers:
            df = self._collect_ticker(ticker, start_date, end_date)
            if df is not None and not df.empty:
                frames.append(df)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _collect_ticker(self, ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """단일 종목 수집. 프로바이더 폴백 적용."""
        from openbb import obb

        for provider in PROVIDERS:
            try:
                result = obb.equity.price.historical(
                    symbol=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    provider=provider,
                )
                df = result.to_dataframe()
                if df.empty:
                    continue

                # 표준화
                df = df.reset_index()
                df["ticker"] = ticker
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

                # adj_close가 없으면 close 사용
                if "adj_close" not in df.columns:
                    df["adj_close"] = df["close"]

                cols = ["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = None

                return df[cols]

            except Exception as e:
                self.logger.debug(f"{ticker}: {provider} 실패 — {e}")
                continue

        self.logger.warning(f"{ticker}: 모든 프로바이더 실패")
        return None

    @staticmethod
    def _period_to_start_date(period: str) -> str:
        """기간 문자열 → 시작 날짜."""
        now = datetime.now()
        mapping = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
            "6mo": 180, "1y": 365, "2y": 730, "3y": 1095,
            "5y": 1825, "10y": 3650,
        }
        days = mapping.get(period, 5)
        return (now - timedelta(days=days)).strftime("%Y-%m-%d")

    def save(self, data: pd.DataFrame) -> int:
        """수집된 주가를 DB에 저장."""
        if data.empty:
            return 0
        return upsert_prices(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nuri-Quant 미국 주가 수집기 (OpenBB)")
    parser.add_argument("--period", default="5d",
                        help="수집 기간 (1d/5d/1mo/3mo/1y)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = StockCollector()
    collector.run(period=args.period)
