"""
CoinGecko BTC/Crypto 리스크 지표 수집기.

BTC 가격, 시가총액, 거래량, 도미넌스 등 암호화폐 리스크 지표 수집.
BTC는 리스크 자산 프록시로 활용 — 급락 시 전반적 위험선호 감소 신호.

무료 API (키 불필요, 분당 10-30회 제한).

사용법:
    python -m nuri.collectors.coingecko
"""
import logging
from datetime import datetime

import requests

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_macro

# CoinGecko 무료 API
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}


class CoinGeckoCollector(BaseCollector):
    """CoinGecko BTC/Crypto 리스크 지표 수집."""

    def __init__(self):
        super().__init__("coingecko")

    def collect(self, **kwargs) -> list[dict]:
        """BTC 가격 + 글로벌 암호화폐 지표 수집."""
        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. BTC 현재가 + 시가총액 + 24h 거래량
        try:
            price_records = self._collect_price(today)
            records.extend(price_records)
        except Exception as e:
            self.logger.warning("CoinGecko price API 실패: %s", e)

        # 2. 글로벌 시장 지표 (BTC 도미넌스, 총 시가총액)
        try:
            global_records = self._collect_global(today)
            records.extend(global_records)
        except Exception as e:
            self.logger.warning("CoinGecko global API 실패: %s", e)

        return records

    def _collect_price(self, today: str) -> list[dict]:
        """BTC 가격/시총/거래량 수집."""
        params = {
            "ids": "bitcoin",
            "vs_currencies": "usd",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        }
        resp = requests.get(COINGECKO_PRICE_URL, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        btc = data.get("bitcoin", {})
        records = []

        if "usd" in btc:
            records.append({
                "indicator": "btc_usd_cg",
                "date": today,
                "value": float(btc["usd"]),
                "source": "CoinGecko",
            })
            self.logger.info("BTC 가격: $%,.0f", btc["usd"])

        if "usd_market_cap" in btc:
            # 조 단위로 변환 (1T = 1e12)
            market_cap_t = btc["usd_market_cap"] / 1e12
            records.append({
                "indicator": "btc_market_cap_t",
                "date": today,
                "value": round(market_cap_t, 3),
                "source": "CoinGecko",
            })

        if "usd_24h_vol" in btc:
            # 십억 단위 (1B = 1e9)
            vol_b = btc["usd_24h_vol"] / 1e9
            records.append({
                "indicator": "btc_24h_volume_b",
                "date": today,
                "value": round(vol_b, 2),
                "source": "CoinGecko",
            })

        if "usd_24h_change" in btc:
            records.append({
                "indicator": "btc_24h_change_pct",
                "date": today,
                "value": round(float(btc["usd_24h_change"]), 2),
                "source": "CoinGecko",
            })

        return records

    def _collect_global(self, today: str) -> list[dict]:
        """글로벌 암호화폐 시장 지표."""
        resp = requests.get(COINGECKO_GLOBAL_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        records = []

        # BTC 도미넌스 (%)
        btc_dom = data.get("market_cap_percentage", {}).get("btc")
        if btc_dom is not None:
            records.append({
                "indicator": "btc_dominance",
                "date": today,
                "value": round(float(btc_dom), 2),
                "source": "CoinGecko",
            })
            self.logger.info("BTC 도미넌스: %.1f%%", btc_dom)

        # 총 암호화폐 시가총액 (조 달러)
        total_mcap = data.get("total_market_cap", {}).get("usd")
        if total_mcap is not None:
            total_mcap_t = total_mcap / 1e12
            records.append({
                "indicator": "crypto_total_mcap_t",
                "date": today,
                "value": round(total_mcap_t, 3),
                "source": "CoinGecko",
            })

        # 활성 암호화폐 수
        active = data.get("active_cryptocurrencies")
        if active is not None:
            records.append({
                "indicator": "crypto_active_count",
                "date": today,
                "value": float(active),
                "source": "CoinGecko",
            })

        return records

    def save(self, data: list[dict]) -> int:
        """매크로 테이블에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = CoinGeckoCollector()
    collector.run()
