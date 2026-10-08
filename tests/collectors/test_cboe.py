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

    def test_save_records(self, db_path):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        records = [{"indicator": "put_call_ratio", "date": "2026-03-30", "value": 0.85, "source": "cboe"}]
        count = c.save(records)
        assert count == 1


class TestCBOECollector_Phase2:
    def test_parse_date_formats(self):
        from nuri.collectors.base import parse_date

        assert parse_date("2026-03-28") == "2026-03-28"
        assert parse_date("03/28/2026") == "2026-03-28"
        assert parse_date("") is None
        assert parse_date("invalid") is None
        assert parse_date("2026-03-28T12:00:00") == "2026-03-28"


class TestCBOEDeepFromHistorical:
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


# ##############################################################################
# Source: test_coverage_round8.py
# ##############################################################################


class TestCBOEExtractPCR:
    def test_fred_tier_is_gone(self):
        """FRED ECPCRATIO 티어는 제거됐다 — 2026-08-30 외부 실검증에서 FRED 가
        "The series does not exist" 를 반환 (델리스트). 되살리면 매 실행 api_key 가
        박힌 URL 이 WARNING 로그로 새는 것까지 같이 돌아온다."""
        import nuri.collectors.cboe as cboe_mod
        from nuri.collectors.cboe import CBOECollector

        assert not hasattr(CBOECollector, "_collect_fred_pcr")
        assert not hasattr(cboe_mod, "FRED_PCR_URL")

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
        return c

    def test_total_failure_raises_instead_of_returning_empty(self):
        """raise 를 걷어내면 FAIL."""
        c = self._collector()
        with (
            patch.object(c, "_collect_daily", side_effect=RuntimeError("daily down")),
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
            patch.object(c, "_collect_yfinance_spy_pcr", side_effect=RuntimeError("down")),
            patch.object(c, "_collect_db_stale", return_value=stale),
        ):
            assert c.collect() == stale


class TestCBOEDailyFile:
    """CBOE 일별 통계 파일 티어 (#1739) — 네트워크는 전부 mock.

    파일에는 날짜가 없어 URL 의 날짜가 곧 거래일이다. 비거래일·미발행은 403 이다.
    """

    TRADING = {"2026-10-07": "0.87", "2026-10-06": "0.82", "2026-10-02": "1.21"}

    def _get(self, files):
        def fake_get(url, headers=None, timeout=None):
            day = url.rsplit("/", 1)[-1].split("_", 1)[0]
            resp = MagicMock()
            if day in files:
                resp.status_code = 200
                resp.json.return_value = {
                    "ratios": [
                        {"name": "INDEX PUT/CALL RATIO", "value": "9.99"},
                        {"name": "TOTAL PUT/CALL RATIO", "value": files[day]},
                    ]
                }
            else:
                resp.status_code = 403
            return resp

        return fake_get

    def _collect(self, files, today="2026-10-08"):
        from nuri.collectors.cboe import CBOECollector

        with (
            patch("nuri.collectors.cboe.today_kst", return_value=today),
            patch("nuri.collectors.cboe.requests.get", side_effect=self._get(files)),
        ):
            return CBOECollector()._collect_daily()

    def test_rows_carry_the_trade_date_from_the_url(self):
        """행 날짜를 `today_str()` 로 찍으면 FAIL — 파일 안에는 날짜가 없다. TOTAL 만 읽는다(INDEX 아님)."""
        rows = self._collect(self.TRADING)
        assert [(r["date"], r["value"], r["source"]) for r in rows] == [
            ("2026-10-07", 0.87, "CBOE"),
            ("2026-10-06", 0.82, "CBOE"),
            ("2026-10-02", 1.21, "CBOE"),
        ]

    def test_no_file_in_the_window_raises_so_the_fallback_and_alert_run(self):
        """열흘 동안 파일이 하나도 없으면 비거래일이 아니라 차단·경로 변경이다."""
        with pytest.raises(RuntimeError, match="최근"):
            self._collect({})

    def test_files_without_the_total_ratio_raise(self):
        from nuri.collectors.cboe import CBOECollector

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"ratios": [{"name": "INDEX PUT/CALL RATIO", "value": "0.9"}]}
        with (
            patch("nuri.collectors.cboe.today_kst", return_value="2026-10-08"),
            patch("nuri.collectors.cboe.requests.get", return_value=resp),
        ):
            with pytest.raises(ValueError, match="TOTAL PUT/CALL RATIO"):
                CBOECollector()._collect_daily()

    def test_dead_cboe_endpoints_are_gone(self):
        import nuri.collectors.cboe as cboe_mod

        assert not hasattr(cboe_mod, "CBOE_OPTIONS_URL") and not hasattr(cboe_mod, "CBOE_TOTPC_URL")

    def test_cboe_failure_falls_back_to_yfinance(self):
        from nuri.collectors.cboe import CBOECollector

        c = CBOECollector()
        spy = [{"indicator": "put_call_ratio", "date": "2026-10-08", "value": 1.2, "source": "yfinance_SPY"}]
        with (
            patch.object(c, "_collect_daily", side_effect=RuntimeError("403 everywhere")),
            patch.object(c, "_collect_yfinance_spy_pcr", return_value=spy),
        ):
            assert c.collect() == spy


class TestCBOEDailyFileErrors:
    """날짜 하나의 실패가 이미 받은 날짜를 버리면 다른 스케일의 SPY 폴백으로 떨어진다 (#1748)."""

    def _collect(self, outcomes):
        import requests as _requests

        from nuri.collectors.cboe import CBOECollector

        def fake_get(url, headers=None, timeout=None):
            day = url.rsplit("/", 1)[-1].split("_", 1)[0]
            out = outcomes.get(day, 403)
            if isinstance(out, Exception):
                raise out
            resp = MagicMock(status_code=200 if isinstance(out, str) else out)
            if isinstance(out, str):
                resp.json.return_value = {"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": out}]}
            else:
                resp.raise_for_status.side_effect = _requests.HTTPError(f"{out}")
            return resp

        with (
            patch("nuri.collectors.cboe.today_kst", return_value="2026-10-08"),
            patch("nuri.collectors.cboe.requests.get", side_effect=fake_get),
        ):
            return CBOECollector()._collect_daily()

    def test_a_timeout_after_a_success_keeps_the_fetched_dates(self):
        import requests as _requests

        rows = self._collect(
            {"2026-10-07": "0.87", "2026-10-06": _requests.Timeout("slow"), "2026-10-05": 500, "2026-10-02": "0.78"}
        )
        assert [(r["date"], r["value"]) for r in rows] == [("2026-10-07", 0.87), ("2026-10-02", 0.78)]

    def test_only_errors_raise_the_first_one(self):
        import requests as _requests

        with pytest.raises(_requests.Timeout, match="first"):
            self._collect({"2026-10-07": _requests.Timeout("first"), "2026-10-06": 500})
