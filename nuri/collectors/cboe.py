"""
CBOE Put/Call Ratio 수집기.

CBOE 옵션 데이터에서 Put/Call Ratio를 수집하여 시장 심리 지표로 활용.
PCR > 1.0: 약세 심리 (풋 매수 과다), PCR < 0.7: 강세 심리 (콜 매수 과다).

사용법:
    python -m nuri.collectors.cboe
"""
import logging
from datetime import datetime

import requests

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_macro

# CBOE 일별 시장 통계 (put/call ratio 포함)
CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/daily.json"
# 폴백: 개별 지수
CBOE_TOTPC_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/totalpc.json"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _parse_date(raw: str) -> str | None:
    """날짜 문자열을 YYYY-MM-DD로 변환. 실패 시 None."""
    s = str(raw).strip()
    if not s:
        return None
    try:
        if "/" in s:
            return datetime.strptime(s, "%m/%d/%Y").strftime("%Y-%m-%d")
        # ISO 형식 검증
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except ValueError:
        return None


class CBOECollector(BaseCollector):
    """CBOE Put/Call Ratio 수집."""

    def __init__(self):
        super().__init__("cboe")

    def collect(self, **kwargs) -> list[dict]:
        """CBOE에서 Put/Call Ratio 수집."""
        # 1차: daily.json (전체 통계)
        try:
            return self._collect_daily()
        except Exception as e:
            self.logger.warning("CBOE daily API 실패: %s", e)

        # 2차: totalpc.json 폴백
        try:
            return self._collect_totalpc()
        except Exception as e:
            self.logger.warning("CBOE totalpc 폴백도 실패: %s", e)

        self.logger.error("CBOE 모든 소스 실패")
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
            for item in items[-30:]:  # 최근 30일
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
        # put_volume / call_volume 직접 계산
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
