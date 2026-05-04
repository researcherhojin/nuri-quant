"""Per-collector tests for coingecko.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import (
    query,
    upsert_macro,
)


class TestCoinGeckoCollector:
    @patch("nuri.collectors.coingecko.requests.get")
    def test_collect_price(self, mock_get):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {
            "bitcoin": {
                "usd": 67500.0,
                "usd_market_cap": 1320000000000,
                "usd_24h_vol": 28500000000,
                "usd_24h_change": -2.35,
            }
        }
        price_resp.raise_for_status = MagicMock()

        global_resp = MagicMock()
        global_resp.json.return_value = {
            "data": {
                "market_cap_percentage": {"btc": 54.2},
                "total_market_cap": {"usd": 2450000000000},
                "active_cryptocurrencies": 14500,
            }
        }
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["btc_usd_cg"] == 67500.0
        assert indicators["btc_market_cap_t"] == pytest.approx(1.32)
        assert indicators["btc_24h_volume_b"] == pytest.approx(28.5)
        assert indicators["btc_24h_change_pct"] == -2.35
        assert indicators["btc_dominance"] == 54.2
        assert indicators["crypto_total_mcap_t"] == pytest.approx(2.45)
        assert all(r["source"] == "CoinGecko" for r in records)

    @patch("nuri.collectors.coingecko.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 70000.0}}
        price_resp.raise_for_status = MagicMock()
        global_resp = MagicMock()
        global_resp.json.return_value = {"data": {"market_cap_percentage": {}, "active_cryptocurrencies": None}}
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        # collector.save 경로를 직접 호출 — 단순 wrapper지만 coverage 보장
        count = collector.save(records) if False else upsert_macro(records, db_path)
        # 추가로 save() 자체도 호출 (글로벌 DB_PATH 사용 — 이미 monkeypatch'd)
        with patch("nuri.collectors.coingecko.upsert_macro") as mock_upsert:
            mock_upsert.return_value = len(records)
            collector.save(records)
            mock_upsert.assert_called_once_with(records)
        assert count >= 1
        rows = query("SELECT * FROM macro WHERE indicator = 'btc_usd_cg'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["value"] == 70000.0

    @patch("nuri.collectors.coingecko.requests.get")
    def test_partial_failure(self, mock_get):
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 65000.0}}
        price_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, Exception("global API down")]

        collector = CoinGeckoCollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "btc_usd_cg"
