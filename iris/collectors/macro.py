"""
매크로 지표 수집기 — FRED API 기반.

수집 지표: 연방기금금리, 10년물/2년물 국채, CPI, WTI 유가, USD/KRW, 실업률, VIX
FRED_API_KEY가 .env에 설정되어 있어야 한다.

사용법:
    python -m iris.collectors.macro
"""
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

from iris.collectors.base import BaseCollector
from iris.db import upsert_macro

load_dotenv()

# FRED 시리즈 ID 매핑
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "us_10y_yield": "DGS10",
    "us_2y_yield": "DGS2",
    "cpi_yoy": "CPIAUCSL",
    "wti_oil": "DCOILWTICO",
    "usd_krw": "DEXKOUS",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
}


class MacroCollector(BaseCollector):
    """FRED API로 매크로 지표 수집."""

    def __init__(self):
        super().__init__("macro")
        self.api_key = os.getenv("FRED_API_KEY", "")

    def collect(self, days: int = 30, **kwargs) -> list[dict]:
        """FRED API에서 매크로 지표 수집."""
        if not self.api_key or self.api_key == "your_fred_api_key_here":
            self.logger.warning("FRED_API_KEY가 설정되지 않음 — 건너뜀")
            return []

        from fredapi import Fred

        fred = Fred(api_key=self.api_key)
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

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
                self.logger.warning(f"{indicator} ({series_id}): 수집 실패 — {e}")

        return records

    def save(self, data: list[dict]) -> int:
        """매크로 지표를 DB에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = MacroCollector()
    collector.run()
