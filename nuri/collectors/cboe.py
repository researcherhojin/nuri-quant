"""
CBOE Put/Call Ratio 수집기.

CBOE 옵션 데이터에서 Put/Call Ratio를 수집하여 시장 심리 지표로 활용.
PCR > 1.0: 약세 심리 (풋 매수 과다), PCR < 0.7: 강세 심리 (콜 매수 과다).

소스 우선순위: CBOE JSON API → FRED ECPCRATIO → 없으면 스킵.

사용법:
    python -m nuri.collectors.cboe
"""
import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_macro

load_dotenv()

# CBOE 일별 시장 통계
CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/daily.json"
CBOE_TOTPC_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/totalpc.json"
# FRED 폴백: CBOE Equity Put/Call Ratio
FRED_PCR_URL = "https://api.stlouisfed.org/fred/series/observations"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _parse_date(raw: str) -> str | None:
    """날짜 문자열을 YYYY-MM-DD로 변환. 실패 시 None."""
    s = str(raw).strip()
    if not s:
        return None
    try:
        if "/" in s:
            return datetime.strptime(s, "%m/%d/%Y").strftime("%Y-%m-%d")
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except ValueError:
        return None


class CBOECollector(BaseCollector):
    """CBOE Put/Call Ratio 수집."""

    def __init__(self):
        super().__init__("cboe")
        self.fred_key = os.getenv("FRED_API_KEY", "")

    def collect(self, **kwargs) -> list[dict]:
        """CBOE에서 Put/Call Ratio 수집."""
        # 1차: CBOE daily.json
        try:
            records = self._collect_daily()
            if records:
                return records
        except Exception as e:
            self.logger.warning("CBOE daily API 실패: %s", e)

        # 2차: CBOE totalpc.json
        try:
            records = self._collect_totalpc()
            if records:
                return records
        except Exception as e:
            self.logger.warning("CBOE totalpc 폴백도 실패: %s", e)

        # 3차: FRED ECPCRATIO (CBOE Equity Put/Call Ratio)
        if self.fred_key and self.fred_key != "your_fred_api_key_here":
            try:
                records = self._collect_fred_pcr()
                if records:
                    return records
            except Exception as e:
                self.logger.warning("FRED PCR 폴백 실패: %s", e)

        self.logger.error("CBOE 모든 소스 실패 (FRED_API_KEY 설정 시 FRED 폴백 가능)")
        return []

    def _collect_daily(self) -> list[dict]:
        """CBOE daily market statistics JSON에서 PCR 추출."""
        resp = requests.get(CBOE_OPTIONS_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, list) and items:
            latest = items[-1] if len(items) > 1 else items[0]
            pcr = self._extract_pcr(latest)
            if pcr is not None:
                raw_date = latest.get("TRADE_DATE", latest.get("date", today))
                date_str = _parse_date(raw_date) or today
                records.append({
                    "indicator": "put_call_ratio",
                    "date": date_str,
                    "value": float(pcr),
                    "source": "CBOE",
                })
                self.logger.info("CBOE Put/Call Ratio: %.3f (%s)", pcr, date_str)
        elif isinstance(data, dict):
            pcr = self._extract_pcr(data)
            if pcr is not None:
                records.append({
                    "indicator": "put_call_ratio",
                    "date": today,
                    "value": float(pcr),
                    "source": "CBOE",
                })

        return records

    def _collect_totalpc(self) -> list[dict]:
        """CBOE Total Put/Call 폴백."""
        resp = requests.get(CBOE_TOTPC_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        records = []
        items = data.get("data", []) if isinstance(data, dict) else data
        if isinstance(items, list):
            for item in items[-30:]:
                pcr = self._extract_pcr(item)
                raw_date = item.get("TRADE_DATE", item.get("date", ""))
                date_str = _parse_date(raw_date)
                if pcr is not None and date_str:
                    records.append({
                        "indicator": "put_call_ratio",
                        "date": date_str,
                        "value": float(pcr),
                        "source": "CBOE",
                    })

        self.logger.info("CBOE totalpc: %d건", len(records))
        return records

    def _collect_fred_pcr(self) -> list[dict]:
        """FRED ECPCRATIO (CBOE Equity Put/Call Ratio) 폴백."""
        params = {
            "series_id": "ECPCRATIO",
            "api_key": self.fred_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 30,
        }
        resp = requests.get(FRED_PCR_URL, params=params, timeout=15)
        resp.raise_for_status()
        observations = resp.json().get("observations", [])

        records = []
        for obs in observations:
            val = obs.get("value", ".")
            if val == ".":
                continue
            records.append({
                "indicator": "put_call_ratio",
                "date": obs["date"],
                "value": float(val),
                "source": "FRED_ECPCRATIO",
            })

        if records:
            self.logger.info("FRED PCR: %d건 (최신: %s = %.3f)", len(records), records[0]["date"], records[0]["value"])
        return records

    @staticmethod
    def _extract_pcr(item: dict) -> float | None:
        """다양한 키 이름에서 PCR 값 추출."""
        for key in ("TOTAL_PUT_CALL_RATIO", "PUT_CALL_RATIO", "put_call_ratio", "pcr", "ratio"):
            val = item.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        put_vol = item.get("TOTAL_PUT_VOLUME", item.get("put_volume"))
        call_vol = item.get("TOTAL_CALL_VOLUME", item.get("call_volume"))
        if put_vol and call_vol:
            try:
                return float(put_vol) / float(call_vol)
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        return None

    def save(self, data: list[dict]) -> int:
        """매크로 테이블에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = CBOECollector()
    collector.run()
