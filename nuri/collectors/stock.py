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
from datetime import timedelta
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
        source: str = "portfolio",
        **kwargs,
    ) -> pd.DataFrame:
        """OpenBB로 미국 종목 OHLCV 수집.

        Args:
            source: 'portfolio' (default) | 'universe' | 'all'. #272 Phase 2b.
        """
        # 한국 종목은 stock_kr.py에서 처리
        tickers = self._get_tickers(market="us", source=source)
        if not tickers:
            self.logger.warning("수집할 미국 종목이 없습니다")
            return pd.DataFrame()

        self.logger.info(f"수집 대상: {len(tickers)} 미국 종목 ({period}, source={source})")

        # 기간 계산 (KST 기준 — 수집은 한국 시간대에서 실행)
        from nuri.core.timezone import kst_now

        end_date = kst_now().strftime("%Y-%m-%d")
        start_date = self._period_to_start_date(period)

        # yfinance ERROR 노이즈 억제 (universe 모드 시 수십~수백 traceback 방지)
        # ANSS, HES 같은 delisted 종목은 정상 케이스이지 buggy code 아님
        import logging as _logging

        _yflog = _logging.getLogger("yfinance")
        _orig_level = _yflog.level
        if source != "portfolio":
            _yflog.setLevel(_logging.CRITICAL)

        # tqdm progress bar — universe (543종목) / all 모드에서 진행 가시성 필수
        from tqdm import tqdm

        frames: list[pd.DataFrame] = []
        succeeded: list[str] = []
        failed: list[str] = []
        try:
            iterator = tqdm(tickers, desc=f"  prices [{source}]", unit="tk", disable=len(tickers) < 20)
            for ticker in iterator:
                df = self._collect_ticker(ticker, start_date, end_date)
                if df is not None and not df.empty:
                    frames.append(df)
                    succeeded.append(ticker)
                else:
                    failed.append(ticker)
        finally:
            _yflog.setLevel(_orig_level)

        # 명확한 요약 — 어디서 X 했는지 한눈에
        self._failed_tickers = failed
        if len(tickers) >= 20:
            sample_failed = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
            self.logger.info(
                "📊 수집 결과: ✅ %d 성공 / ❌ %d 실패 (%.1f%%) — failed: %s",
                len(succeeded),
                len(failed),
                len(succeeded) / len(tickers) * 100,
                sample_failed or "없음",
            )

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _collect_ticker(self, ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """단일 종목 수집. OpenBB → yfinance 직접 폴백."""
        # 1차: OpenBB
        try:
            from openbb import obb

            result = obb.equity.price.historical(
                symbol=ticker,
                start_date=start_date,
                end_date=end_date,
                provider="yfinance",
            )
            df = result.to_dataframe()
            if not df.empty:
                return self._standardize(df, ticker)
        except Exception as e:
            self.logger.debug(f"{ticker}: OpenBB 실패 — {e}")

        # 2차: yfinance 직접 호출 (OpenBB 장애 시 폴백)
        try:
            import yfinance as yf

            raw = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not raw.empty:
                df = raw.reset_index()
                # MultiIndex 컬럼 처리 (yfinance가 단일 종목도 MultiIndex로 반환할 수 있음)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if c[1] == ticker or c[1] == "" else c[0] for c in df.columns]
                return self._standardize(df, ticker)
        except Exception as e:
            self.logger.debug(f"{ticker}: yfinance 직접 호출도 실패 — {e}")

        self.logger.warning(f"{ticker}: 모든 프로바이더 실패")
        return None

    def _standardize(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """DataFrame을 표준 OHLCV 포맷으로 변환."""
        df = df.reset_index() if "date" not in df.columns and "Date" not in df.columns else df

        # 컬럼명 소문자 통일
        df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
        df["ticker"] = ticker

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        if "adj_close" not in df.columns:
            df["adj_close"] = df.get("close")

        cols = ["ticker", "date", "open", "high", "low", "close", "volume", "adj_close"]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        return df[cols]

    @staticmethod
    def _period_to_start_date(period: str) -> str:
        """기간 문자열 -> 시작 날짜 (KST 기준)."""
        from nuri.core.timezone import kst_now

        now = kst_now()
        mapping = {
            "1d": 1,
            "5d": 5,
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 730,
            "3y": 1095,
            "5y": 1825,
            "10y": 3650,
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
    parser.add_argument("--period", default="5d", help="수집 기간 (1d/5d/1mo/3mo/1y)")
    parser.add_argument(
        "--source",
        default="portfolio",
        choices=["portfolio", "universe", "all"],
        help="ticker 소스 (#272 Phase 2b). portfolio=보유만, universe=yaml 전체, all=합집합",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = StockCollector()
    collector.run(period=args.period, source=args.source)
