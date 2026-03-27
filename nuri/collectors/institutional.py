"""
기관/외인 수급 수집기 — 한국: pykrx / 미국: finnhub(선택).

현재 pykrx 수급 API가 불안정하여, 안정화 후 활성화 예정.
finnhub은 FINNHUB_API_KEY 환경변수가 있을 때만 동작.

사용법:
    python -m nuri.collectors.institutional
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db

logger = logging.getLogger(__name__)


class InstitutionalCollector(BaseCollector):
    """기관/외인 수급 수집기."""

    def __init__(self):
        super().__init__("institutional")

    def collect(self, **kwargs) -> list[dict]:
        """수급 데이터 수집."""
        results = []

        # 한국 종목: pykrx
        kr_tickers = self._get_tickers(market="kr")
        if kr_tickers:
            kr_data = self._collect_kr(kr_tickers)
            results.extend(kr_data)

        # 미국 종목: finnhub (API 키 필요)
        finnhub_key = os.getenv("FINNHUB_API_KEY")
        if finnhub_key:
            us_tickers = self._get_tickers(market="us")
            if us_tickers:
                us_data = self._collect_us(us_tickers, finnhub_key)
                results.extend(us_data)
        else:
            self.logger.info("FINNHUB_API_KEY 미설정 — 미국 수급 수집 건너뜀")

        return results

    def _collect_kr(self, tickers: list[str]) -> list[dict]:
        """pykrx로 한국 종목 기관/외인 순매수 수집."""
        from pykrx import stock

        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        results = []

        for ticker_full in tickers:
            ticker_code = ticker_full.replace(".KS", "").replace(".KQ", "")
            try:
                df = stock.get_market_trading_value_by_date(start, today, ticker_code)
                if df.empty:
                    self.logger.debug(f"{ticker_full}: pykrx 수급 데이터 없음")
                    continue

                # 최신 행
                latest = df.iloc[-1]
                date_str = str(df.index[-1])[:10]

                record = {
                    "ticker": ticker_full,
                    "date": date_str,
                    "market": "KR",
                    "institution_net": _safe_float(latest.get("기관합계")),
                    "foreign_net": _safe_float(latest.get("외국인합계")),
                    "individual_net": _safe_float(latest.get("개인")),
                    "source": "pykrx",
                }
                results.append(record)

            except Exception as e:
                self.logger.debug(f"{ticker_full}: pykrx 수급 수집 실패 — {e}")
                continue

        return results

    def _collect_us(self, tickers: list[str], api_key: str) -> list[dict]:
        """finnhub으로 미국 종목 기관 보유 비중 수집."""
        results = []
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            import finnhub
            client = finnhub.Client(api_key=api_key)

            for ticker in tickers:
                try:
                    data = client.ownership(ticker, limit=1)
                    if data and "ownership" in data and data["ownership"]:
                        record = {
                            "ticker": ticker,
                            "date": today,
                            "market": "US",
                            "institution_net": None,
                            "foreign_net": None,
                            "individual_net": None,
                            "source": "finnhub",
                        }
                        results.append(record)
                except Exception as e:
                    self.logger.debug(f"{ticker}: finnhub 수집 실패 — {e}")

        except ImportError:
            self.logger.warning("finnhub-python 미설치. pip install finnhub-python")

        return results

    def save(self, data: Any) -> int:
        if not data:
            return 0
        return _upsert_institutional(data)


def _safe_float(val) -> float | None:
    if val is not None and pd.notna(val):
        return float(val)
    return None


def _upsert_institutional(records: list[dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO institutional_flows
               (ticker, date, market, institution_net, foreign_net,
                individual_net, source)
               VALUES (:ticker, :date, :market, :institution_net, :foreign_net,
                       :individual_net, :source)""",
            records,
        )
        return len(records)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = InstitutionalCollector()
    count = collector.run()
    print(f"수급 데이터 수집 완료: {count}건")

    if count == 0:
        print("  pykrx 수급 API가 현재 데이터를 반환하지 않음 (날짜/API 문제)")
        print("  FINNHUB_API_KEY를 .env에 설정하면 미국 수급도 수집 가능")
