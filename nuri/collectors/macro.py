"""
매크로 지표 수집기 — FRED API + yfinance fallback.

FRED_API_KEY가 있으면 FRED 우선, 없으면 yfinance에서 핵심 지표를 직접 수집.

사용법:
    python -m nuri.collectors.macro
"""
import logging
import os
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_macro
from nuri.core.timezone import kst_now

load_dotenv()

# FRED 시리즈 ID 매핑 (확장: 풀 수익률 곡선 + 경제 지표)
FRED_SERIES = {
    # 기존
    "fed_funds_rate": "FEDFUNDS",
    "cpi_yoy": "CPIAUCSL",
    "wti_oil": "DCOILWTICO",
    "usd_krw": "DEXKOUS",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
    # 풀 수익률 곡선 (리서치: 3M-10Y 스프레드가 2Y-10Y보다 경기침체 예측력 높음)
    "us_3m_yield": "DGS3MO",     # 3-Month Treasury
    "us_1y_yield": "DGS1",       # 1-Year
    "us_2y_yield": "DGS2",       # 2-Year
    "us_5y_yield": "DGS5",       # 5-Year
    "us_10y_yield": "DGS10",     # 10-Year
    "us_30y_yield": "DGS30",     # 30-Year
    # 추가 경제 지표
    "consumer_sentiment": "UMCSENT",  # 미시건대 소비자 심리
    "ism_manufacturing": "MANEMP",    # ISM 제조업 고용
}

# yfinance fallback 심볼 매핑 (FRED 없을 때 사용)
YFINANCE_SYMBOLS = {
    "us_10y_yield": "^TNX",      # 10Y Treasury Yield
    "us_2y_yield": "^IRX",       # 13-week T-Bill (2Y proxy)
    "us_5y_yield": "^FVX",       # 5Y Treasury Yield
    "us_30y_yield": "^TYX",      # 30Y Treasury Yield
    "vix": "^VIX",               # CBOE VIX
    "wti_oil": "CL=F",           # WTI Crude Oil Futures
    "usd_krw": "KRW=X",          # USD/KRW
    # btc_usd는 CoinGecko collector에서 전담 (btc_usd_cg)
    "gold": "GC=F",              # Gold Futures (안전자산)
}


class MacroCollector(BaseCollector):
    """매크로 지표 수집 (FRED + yfinance fallback)."""

    def __init__(self):
        super().__init__("macro")
        self.api_key = os.getenv("FRED_API_KEY", "")

    def collect(self, days: int = 365, **kwargs) -> list[dict]:
        """매크로 지표 수집. FRED 우선, 실패 시 yfinance fallback."""
        records = []

        # 1. FRED 시도
        if self.api_key and self.api_key != "your_fred_api_key_here":
            records = self._collect_fred(days)
            if records:
                return records

        # 2. yfinance fallback
        self.logger.info("FRED 미사용 → yfinance fallback으로 매크로 수집")
        records = self._collect_yfinance(days)
        return records

    def _collect_fred(self, days: int) -> list[dict]:
        """FRED API에서 매크로 지표 수집."""
        from fredapi import Fred

        fred = Fred(api_key=self.api_key)
        start_date = (kst_now().replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")

        records = []
        for indicator, series_id in FRED_SERIES.items():
            try:
                series = fred.get_series(series_id, observation_start=start_date)
                for date, value in series.dropna().items():
                    records.append({
                        "indicator": indicator,
                        "date": date.strftime("%Y-%m-%d"),
                        "value": float(value),
                        "source": "FRED",
                    })
            except Exception as e:
                self.logger.warning(f"{indicator} ({series_id}): FRED 수집 실패 — {e}")

        return records

    def _collect_yfinance(self, days: int) -> list[dict]:
        """yfinance에서 직접 매크로 지표 수집 (API 키 불필요)."""
        import warnings

        from openbb import obb
        warnings.filterwarnings("ignore")

        start = (kst_now().replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")
        records = []

        for indicator, symbol in YFINANCE_SYMBOLS.items():
            try:
                r = obb.equity.price.historical(symbol, start_date=start, provider="yfinance")
                df = r.to_df().reset_index()
                if df.empty:
                    continue

                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

                for _, row in df.iterrows():
                    value = row.get("close")
                    if pd.isna(value):
                        continue

                    # ^TNX는 수익률을 10배로 반환 → 보정 불필요 (이미 %)
                    # KRW=X는 1 USD = X KRW → 역수 필요 없음
                    records.append({
                        "indicator": indicator,
                        "date": row["date"],
                        "value": float(value),
                        "source": "yfinance",
                    })

                self.logger.info(f"  {indicator} ({symbol}): {len(df)}건")
            except Exception as e:
                self.logger.warning(f"{indicator} ({symbol}): yfinance 수집 실패 — {e}")

        return records

    def save(self, data: list[dict]) -> int:
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = MacroCollector()
    collector.run()
