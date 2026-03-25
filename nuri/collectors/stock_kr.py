"""
한국 주가 데이터 수집기 — pykrx 기반 KOSPI/KOSDAQ 수집.

pykrx는 KRX/네이버 금융 데이터를 사용하며, EOD(종가) 데이터만 지원.
티커는 DB에 '005930.KS' 형태로 저장되지만, pykrx에는 '005930'으로 전달.

사용법:
    python -m nuri.collectors.stock_kr
    python -m nuri.collectors.stock_kr --days 30
"""
import argparse
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from pykrx import stock as krx

from nuri.collectors.base import BaseCollector
from nuri.db import upsert_prices


class StockKRCollector(BaseCollector):
    """pykrx로 한국 주가 수집 (KOSPI/KOSDAQ)."""

    def __init__(self):
        super().__init__("stock_kr")

    def collect(self, days: int = 5, **kwargs) -> pd.DataFrame:
        """pykrx로 한국 보유 종목 OHLCV 수집."""
        tickers = self._get_tickers(market="kr")
        if not tickers:
            self.logger.warning("수집할 한국 종목이 없습니다")
            return pd.DataFrame()

        self.logger.info(f"수집 대상: {len(tickers)} 한국 종목 ({days}일)")

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        frames = []
        for ticker_with_suffix in tickers:
            df = self._collect_ticker(ticker_with_suffix, start_date, end_date)
            if df is not None and not df.empty:
                frames.append(df)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _collect_ticker(
        self, ticker_full: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """단일 한국 종목 수집."""
        # .KS 접미사 제거 (pykrx는 순수 숫자 코드 사용)
        ticker_code = ticker_full.replace(".KS", "").replace(".KQ", "")

        try:
            raw = krx.get_market_ohlcv(start_date, end_date, ticker_code)
            if raw.empty:
                self.logger.warning(f"{ticker_full}: 데이터 없음")
                return None

            # pykrx 한국어 컬럼 → Nuri-Quant 표준 컬럼 매핑
            df = pd.DataFrame({
                "ticker": ticker_full,
                "date": raw.index.strftime("%Y-%m-%d"),
                "open": raw["시가"].values,
                "high": raw["고가"].values,
                "low": raw["저가"].values,
                "close": raw["종가"].values,
                "volume": raw["거래량"].values,
                "adj_close": raw["종가"].values,  # pykrx는 수정종가 미제공
            })

            return df

        except Exception as e:
            self.logger.warning(f"{ticker_full} ({ticker_code}): 수집 실패 — {e}")
            return None

    def save(self, data: pd.DataFrame) -> int:
        """수집된 주가를 DB에 저장."""
        if data.empty:
            return 0
        return upsert_prices(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nuri-Quant 한국 주가 수집기 (pykrx)")
    parser.add_argument("--days", type=int, default=5,
                        help="수집 일수 (기본 5일)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = StockKRCollector()
    collector.run(days=args.days)
