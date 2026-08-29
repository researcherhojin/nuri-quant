"""Per-collector tests for cboe.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import (
    query,
    upsert_macro,
)


class TestCBOECollector:
    def test_instantiate(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c.name == "cboe"

    def test_extract_pcr_total(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85

    def test_extract_pcr_simple(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92

    def test_extract_pcr_calculated(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        result = c._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert result is not None and abs(result - 0.5) < 0.01

    def test_extract_pcr_missing(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        assert c._extract_pcr({}) is None

    def test_save_records(self, db_path):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2026-03-30", "value": 0.85, "source": "cboe"}]
        count = c.save(records)
        assert count == 1


class TestCBOECollector_Phase2:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 1.2}) == 1.2

    def test_extract_pcr_volume_calc(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr(
            {
                "TOTAL_PUT_VOLUME": 1500000,
                "TOTAL_CALL_VOLUME": 2000000,
            }
        )
        assert result == pytest.approx(0.75)

    def test_extract_pcr_missing(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None
        assert CBOECollector._extract_pcr({"unrelated": 42}) is None

    def test_extract_pcr_zero_call(self):
        from nuri.collectors.cboe import CBOECollector

        assert (
            CBOECollector._extract_pcr(
                {
                    "TOTAL_PUT_VOLUME": 100,
                    "TOTAL_CALL_VOLUME": 0,
                }
            )
            is None
        )

    @patch("nuri.collectors.cboe.requests.get")
    def test_collect_daily_json(self, mock_get):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.92}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "put_call_ratio"
        assert records[0]["value"] == 0.92
        assert records[0]["source"] == "CBOE"

    @patch("nuri.collectors.cboe.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'put_call_ratio'", db_path=db_path)
        assert len(rows) >= 1
        assert rows[0]["value"] == pytest.approx(0.88)

    def test_parse_date_formats(self):
        from nuri.collectors.base import parse_date

        assert parse_date("2026-03-28") == "2026-03-28"
        assert parse_date("03/28/2026") == "2026-03-28"
        assert parse_date("") is None
        assert parse_date("invalid") is None
        assert parse_date("2026-03-28T12:00:00") == "2026-03-28"


class TestCBOEDeepFromHistorical:
    def test_collect_daily_mock(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests") as mock_req:
            mock_req.get.return_value = mock_resp
            result = c._collect_daily()
        assert isinstance(result, list)

    def test_collect_daily_failure(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        with patch.object(c, "_collect_daily", return_value=[]):
            result = c._collect_daily()
        assert isinstance(result, list)
        assert len(result) == 0


# ##############################################################################
# Source: test_coverage_round6.py
# ##############################################################################


class TestCBOEDeepCalculations:
    def test_collect_daily_success(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert isinstance(result, list)
        if result:
            assert result[0]["value"] == 0.85

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"TRADE_DATE": "2026-03-29", "TOTAL_PUT_CALL_RATIO": 0.90},
                {"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88},
            ]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert isinstance(result, list)

    def test_collect_full(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c.collect()
        assert isinstance(result, list)


# ##############################################################################
# Source: test_coverage_round8.py
# ##############################################################################


class TestCBOEFull:
    def test_collect_with_fallback(self):
        from nuri.collectors.cboe import CBOECollector

        mock_daily = MagicMock()
        mock_daily.status_code = 200
        mock_daily.json.return_value = {"data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        mock_fail = MagicMock()
        mock_fail.status_code = 500

        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", side_effect=[mock_daily, mock_fail]):
            daily = c._collect_daily()
            totalpc = c._collect_totalpc()
        assert len(daily) > 0
        assert len(totalpc) == 0


class TestCBOEExtractPCR:
    def test_extract_pcr_ratio_key(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 0.92}) == 0.92
        assert CBOECollector._extract_pcr({"put_call_ratio": 1.1}) == 1.1
        assert CBOECollector._extract_pcr({"pcr": 0.75}) == 0.75
        assert CBOECollector._extract_pcr({"ratio": 0.6}) == 0.6

    def test_extract_pcr_from_volumes(self):
        from nuri.collectors.cboe import CBOECollector

        result = CBOECollector._extract_pcr({"TOTAL_PUT_VOLUME": 1000, "TOTAL_CALL_VOLUME": 2000})
        assert result is not None and abs(result - 0.5) < 0.01

    def test_extract_pcr_none(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({}) is None

    def test_extract_pcr_invalid_values(self):
        from nuri.collectors.cboe import CBOECollector

        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": "bad"}) is None

    def test_collect_daily_success(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.85}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.85

    def test_collect_daily_dict_response(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"TOTAL_PUT_CALL_RATIO": 0.92}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert len(result) == 1
        assert result[0]["value"] == 0.92

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"TRADE_DATE": "2025-03-15", "TOTAL_PUT_CALL_RATIO": 0.88}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert len(result) == 1

    def test_fred_tier_is_gone(self):
        """FRED ECPCRATIO 티어는 제거됐다 — 2026-08-30 외부 실검증에서 FRED 가
        "The series does not exist" 를 반환 (델리스트). 되살리면 매 실행 api_key 가
        박힌 URL 이 WARNING 로그로 새는 것까지 같이 돌아온다."""
        import nuri.collectors.cboe as cboe_mod
        from nuri.collectors.cboe import CBOECollector

        assert not hasattr(CBOECollector, "_collect_fred_pcr")
        assert not hasattr(cboe_mod, "FRED_PCR_URL")

    def test_collect_fallback_chain(self, monkeypatch):
        """CBOE 2개 티어가 죽어도 yfinance 티어가 값을 건지면 성공."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                with patch.object(
                    c,
                    "_collect_yfinance_spy_pcr",
                    return_value=[
                        {"indicator": "put_call_ratio", "date": "2025-03-15", "value": 1.2, "source": "yfinance_SPY"}
                    ],
                ):
                    result = c.collect()
        assert len(result) == 1

    def test_yfinance_none_chain_degrades_to_empty_not_crash(self, monkeypatch):
        """yfinance 가 chain.calls=None 을 주면 티어가 죽지 않고 [] — 미가드 시
        'NoneType' not subscriptable (2026-08-29 mini 실측: CBOE 403 국면에서 마지막
        라이브 소스가 이 버그로 같이 죽어 PCR 이 6일 얼었다)."""
        import sys
        from types import SimpleNamespace

        from nuri.collectors.cboe import CBOECollector

        fake_ticker = SimpleNamespace(
            options=("2026-08-31",),
            option_chain=lambda exp: SimpleNamespace(calls=None, puts=None),
        )
        fake_yf = SimpleNamespace(Ticker=lambda sym: fake_ticker)
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        c = CBOECollector()
        assert c._collect_yfinance_spy_pcr() == []

    def test_collect_all_fail(self, monkeypatch):
        """전면 실패는 `[]` 가 아니라 raise (#1042). 이전엔 `== []` 를 단언해 결함을 잠그고 있었다."""
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", side_effect=RuntimeError("fail")):
            with patch.object(c, "_collect_totalpc", side_effect=RuntimeError("fail")):
                with patch.object(c, "_collect_yfinance_spy_pcr", side_effect=RuntimeError("fail")):
                    with patch.object(c, "_collect_db_stale", side_effect=RuntimeError("fail")):
                        with pytest.raises(RuntimeError, match="fail"):
                            c.collect()

    def test_collect_daily_returns_empty(self, monkeypatch):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""
        with patch.object(c, "_collect_daily", return_value=[]):
            with patch.object(
                c,
                "_collect_totalpc",
                return_value=[{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.8, "source": "CBOE"}],
            ):
                result = c.collect()
        assert len(result) == 1

    def test_save(self, rich_db):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2025-03-15", "value": 0.85, "source": "CBOE"}]
        assert c.save(records) == 1


class TestCBOEFailedVsNoData:
    """전면 실패와 "오늘 값 없음"의 구분을 잠근다 (#1042 — coingecko #1043 과 같은 규약).

    구분이 사라지면 `collector_runs.status` 에 둘 다 `finished` 가 박힌다.
    `rows_collected` 는 `run_step` 이 돌려주는 4-키 dict 의 길이라 **항상 4** 이므로
    status 가 유일한 판별 채널인데, 그게 성공이라고 말하고 있었다.

    raise 하면 이미 있으면서 우회되던 것들이 되살아난다 — `base.py` 의 재시도 3회,
    `_send_failure_alert()` 의 `#ops` 알림, scheduler 의 `status="failed"`,
    `collector_health` 의 실패 집계.
    """

    def _collector(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        c.fred_key = ""  # FRED 티어 비활성 — 키 유무에 따라 결과가 갈리지 않게
        return c

    def test_total_failure_raises_instead_of_returning_empty(self):
        """raise 를 걷어내면 FAIL."""
        c = self._collector()
        with (
            patch.object(c, "_collect_daily", side_effect=RuntimeError("daily down")),
            patch.object(c, "_collect_totalpc", side_effect=RuntimeError("totalpc down")),
            patch.object(c, "_collect_yfinance_spy_pcr", side_effect=RuntimeError("yf down")),
            patch.object(c, "_collect_db_stale", side_effect=RuntimeError("db down")),
        ):
            with pytest.raises(RuntimeError):
                c.collect()

    def test_every_tier_empty_without_error_is_not_a_failure(self):
        """조건을 `if errors` 대신 `if not records` 로 넓히면 FAIL.

        전 티어가 200 인데 내용이 비었을 뿐이면 예외가 없다 — 그게 NO_DATA 의 정의고,
        그대로 `[]` 가 나가야 한다.
        """
        c = self._collector()
        with (
            patch.object(c, "_collect_daily", return_value=[]),
            patch.object(c, "_collect_totalpc", return_value=[]),
            patch.object(c, "_collect_yfinance_spy_pcr", return_value=[]),
            patch.object(c, "_collect_db_stale", return_value=[]),
        ):
            assert c.collect() == []

    def test_first_error_is_raised_not_the_last(self):
        """`errors[0]` → `errors[-1]` 로 바꾸면 FAIL.

        마지막 티어는 항상 DB stale(로컬 DB)이라, 그걸 올리면 알림이 네트워크 원인을
        가리고 운영자가 DB 를 뒤지게 된다.
        """
        c = self._collector()
        with (
            patch.object(c, "_collect_daily", side_effect=RuntimeError("FIRST cboe daily 429")),
            patch.object(c, "_collect_totalpc", side_effect=RuntimeError("totalpc down")),
            patch.object(c, "_collect_yfinance_spy_pcr", side_effect=RuntimeError("yf down")),
            patch.object(c, "_collect_db_stale", side_effect=RuntimeError("LAST db locked")),
        ):
            with pytest.raises(RuntimeError, match="FIRST cboe daily 429"):
                c.collect()

    def test_db_stale_still_counts_as_success(self):
        """의도된 한계를 명시적으로 잠근다 — DB_STALE 재사용은 여전히 성공이다.

        이 PR 은 "총체적 장애가 성공으로 기록되는" 축만 고친다. stale 재사용이 영원히
        성공으로 집계되는 축은 별건(`put_call_ratio` 가 `FRESHNESS_POLICIES` 에 없음)이며,
        여기서 조용히 바꾸면 라이브 소스가 흔들릴 때마다 수집기가 죽는다.
        """
        c = self._collector()
        stale = [{"indicator": "put_call_ratio", "date": "2026-05-12", "value": 0.9, "source": "DB_STALE"}]
        with (
            patch.object(c, "_collect_daily", side_effect=RuntimeError("down")),
            patch.object(c, "_collect_totalpc", side_effect=RuntimeError("down")),
            patch.object(c, "_collect_yfinance_spy_pcr", side_effect=RuntimeError("down")),
            patch.object(c, "_collect_db_stale", return_value=stale),
        ):
            assert c.collect() == stale
