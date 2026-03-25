"""
주가 데이터 수집기 — yfinance 기반 OHLCV 수집.

사용법:
    python -m iris.collectors.stock               # 전체 종목
    python -m iris.collectors.stock --market kr    # 한국 종목만
    python -m iris.collectors.stock --period 1mo   # 1개월 데이터
"""
import argparse
import logging
import time
from typing import Optional

import pandas as pd
import yfinance as yf

from iris.collectors.base import BaseCollector
from iris.db import upsert_prices


class StockCollector(BaseCollector):
    """yfinance로 보유 종목 OHLCV 수집."""

    def __init__(self):
        super().__init__("stock")

    def collect(
        self,
        market: Optional[str] = None,
        period: str = "5d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """yfinance 배치 다운로드로 주가 수집."""
        tickers = self._get_tickers(market=market)
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return pd.DataFrame()

        self.logger.info(f"수집 대상: {len(tickers)}종목 ({period}, {interval})")

        # 배치 다운로드 시도
        try:
            raw = yf.download(
                tickers=tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as e:
            self.logger.error(f"배치 다운로드 실패, 개별 다운로드 시도: {e}")
            return self._collect_individual(tickers, period, interval)

        return self._reshape(raw, tickers)

    def _collect_individual(
        self, tickers: list[str], period: str, interval: str
    ) -> pd.DataFrame:
        """배치 실패 시 개별 종목 다운로드 (2초 딜레이)."""
        frames = []
        for ticker in tickers:
            try:
                data = yf.download(
                    ticker, period=period, interval=interval,
                    auto_adjust=False, progress=False,
                )
                if data.empty:
                    self.logger.warning(f"{ticker}: 데이터 없음 (상장폐지/유효하지 않은 티커)")
                    continue
                df = self._single_ticker_df(data, ticker)
                frames.append(df)
            except Exception as e:
                self.logger.warning(f"{ticker}: 수집 실패 — {e}")
            time.sleep(2)  # Rate limit 방어

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _reshape(self, raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
        """yfinance MultiIndex DataFrame → flat DataFrame으로 변환.

        yfinance >=1.2: MultiIndex level 0 = Ticker, level 1 = Price
        yfinance <1.2:  MultiIndex level 0 = Price, level 1 = Ticker
        """
        if raw.empty:
            return pd.DataFrame()

        frames = []

        # 단일 종목인 경우 MultiIndex가 아님
        if len(tickers) == 1 or not isinstance(raw.columns, pd.MultiIndex):
            ticker = tickers[0] if len(tickers) == 1 else tickers[0]
            df = self._single_ticker_df(raw, ticker)
            if not df.empty:
                frames.append(df)
        else:
            # MultiIndex 레벨 탐지: level 0이 Ticker인지 Price인지 판별
            level0_values = raw.columns.get_level_values(0).unique().tolist()
            ticker_in_level0 = any(t in level0_values for t in tickers)

            for ticker in tickers:
                try:
                    if ticker_in_level0:
                        # yfinance >=1.2: (Ticker, Price) 구조
                        if ticker not in level0_values:
                            self.logger.warning(f"{ticker}: 배치 결과에 없음")
                            continue
                        subset = raw[ticker]
                    else:
                        # yfinance <1.2: (Price, Ticker) 구조
                        level1_values = raw.columns.get_level_values(1).unique().tolist()
                        if ticker not in level1_values:
                            self.logger.warning(f"{ticker}: 배치 결과에 없음")
                            continue
                        subset = raw.xs(ticker, level=1, axis=1)

                    df = self._single_ticker_df(subset, ticker)
                    if not df.empty:
                        frames.append(df)
                except (KeyError, TypeError) as e:
                    self.logger.warning(f"{ticker}: 파싱 실패 — {e}")

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    @staticmethod
    def _single_ticker_df(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """단일 종목 데이터를 표준 컬럼 형태로 변환."""
        df = data.copy()
        df = df.dropna(subset=["Close"] if "Close" in df.columns else [])
        if df.empty:
            return pd.DataFrame()

        # 컬럼명 표준화 (yfinance는 대문자 또는 소문자 혼용)
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower().replace(" ", "_")
            if col_lower == "adj_close" or col_lower == "adj close":
                col_map[col] = "adj_close"
            else:
                col_map[col] = col_lower
        df = df.rename(columns=col_map)

        # 날짜 처리
        df = df.reset_index()
        date_col = "date" if "date" in df.columns else "Date"
        if date_col in df.columns:
            df = df.rename(columns={date_col: "date"})

        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["ticker"] = ticker

        # adj_close가 없으면 close 사용
        if "adj_close" not in df.columns:
            df["adj_close"] = df.get("close", None)

        # 필요한 컬럼만 선택
        cols = ["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        return df[cols]

    def save(self, data: pd.DataFrame) -> int:
        """수집된 주가를 DB에 저장."""
        if data.empty:
            return 0
        return upsert_prices(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRIS 주가 수집기")
    parser.add_argument("--market", choices=["us", "kr"], default=None,
                        help="시장 필터 (us/kr)")
    parser.add_argument("--period", default="5d",
                        help="수집 기간 (1d/5d/1mo/3mo/1y)")
    parser.add_argument("--interval", default="1d",
                        help="데이터 간격 (1m/5m/1h/1d)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = StockCollector()
    collector.run(market=args.market, period=args.period, interval=args.interval)
