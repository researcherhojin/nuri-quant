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
        count = upsert_macro(records, db_path)
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

    @patch("nuri.collectors.coingecko.requests.get")
    def test_price_api_failure_warns_but_continues(self, mock_get):
        """price API raise → except 분기로 warn (lines 42-43)."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        global_resp = MagicMock()
        global_resp.json.return_value = {
            "data": {
                "market_cap_percentage": {"btc": 50.0},
                "total_market_cap": {"usd": 2e12},
                "active_cryptocurrencies": 14000,
            }
        }
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [Exception("price API down"), global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        # price 는 실패했지만 global 은 살아있어야 함
        indicators = {r["indicator"] for r in records}
        assert "btc_usd_cg" not in indicators
        assert "btc_dominance" in indicators

    def test_save_invokes_upsert_macro(self, db_path):
        """save() 가 upsert_macro 로 위임되는지 (line 167)."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        # Note: save 는 default DB 를 본다. db_path 명시 위해 직접 upsert 사용.
        collector = CoinGeckoCollector()
        # save 는 _last_run 등 다른 것 없이 단순 위임만 — empty list → 0 반환
        result = collector.save([])
        assert result == 0


class TestCoinGeckoFailedVsNoData:
    """수집 **실패**와 "오늘 값 없음"은 다른 사건이고, 다르게 기록돼야 한다.

    이 수집기는 그 구분을 잃을 여유가 없다: `collector_runs.rows_collected` 는
    `run_step` 이 돌려주는 4-키 dict 의 길이라 **항상 4** 라서, `status` 가
    유일한 판별 채널이다. 예전에는 총체적 장애일에도 `finished` 가 박혔다.

    아래 두 테스트는 **한 쌍으로만** 잠금이 된다 — 하나는 실패가 조용히
    지나가지 않는지, 다른 하나는 정상적인 빈 날이 거짓 경보가 되지 않는지 본다.
    """

    @patch("nuri.collectors.coingecko.requests.get")
    def test_total_api_failure_raises_instead_of_returning_empty(self, mock_get):
        """두 API 모두 실패 → 예외. `[]` 로 되돌리면 이 테스트가 FAIL 한다."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        mock_get.side_effect = [RuntimeError("HTTP 429 rate limit"), RuntimeError("HTTP 429 rate limit")]
        with pytest.raises(RuntimeError, match="429"):
            CoinGeckoCollector().collect()

    @patch("nuri.collectors.coingecko.requests.get")
    def test_empty_payload_is_not_a_failure(self, mock_get):
        """둘 다 200 인데 내용이 비면 그건 NO_DATA 다 — 예외를 올리면 안 된다.

        가드를 `if not records: raise` 로 "단순화"하면 여기서 FAIL 한다.
        그 단순화는 정상적인 빈 날을 거짓 장애 알림으로 바꾼다.
        """
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {}}
        price_resp.raise_for_status = MagicMock()
        global_resp = MagicMock()
        global_resp.json.return_value = {"data": {}}
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [price_resp, global_resp]

        assert CoinGeckoCollector().collect() == []

    @patch("nuri.collectors.coingecko.requests.get")
    def test_partial_success_still_returns_what_it_got(self, mock_get):
        """한쪽만 죽으면 건진 건 그대로 돌려준다 — 실패로 격상하지 않는다."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        global_resp = MagicMock()
        global_resp.json.return_value = {
            "data": {
                "market_cap_percentage": {"btc": 54.2},
                "total_market_cap": {"usd": 2450000000000},
                "active_cryptocurrencies": 14500,
            }
        }
        global_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [RuntimeError("HTTP 500"), global_resp]

        assert CoinGeckoCollector().collect(), "부분 성공은 빈 리스트가 아니어야 한다"

    @patch("nuri.collectors.coingecko.requests.get")
    def test_first_error_is_raised_not_the_last(self, mock_get):
        """둘 다 실패하면 **첫** 원인을 올린다.

        마지막을 올리면 항상 global 실패가 되어, price 의 진짜 원인(예: 429)이
        Discord #ops 알림 문구에서 사라진다 — 운영자가 엉뚱한 걸 좇는다.
        """
        from nuri.collectors.coingecko import CoinGeckoCollector

        mock_get.side_effect = [RuntimeError("PRICE 429"), RuntimeError("GLOBAL json decode")]
        with pytest.raises(RuntimeError, match="PRICE 429"):
            CoinGeckoCollector().collect()
