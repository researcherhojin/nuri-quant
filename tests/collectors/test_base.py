"""Per-collector tests for base.

Split from tests/test_collectors_all.py for module-level isolation.
"""

import pytest

from nuri.collectors.base import MAX_FAILURE_RATE, BaseCollector, CollectionFailureError
from nuri.core.db import (
    get_db,
)


class GoodCollector(BaseCollector):
    def __init__(self):
        super().__init__("good")

    def collect(self, **kwargs):
        return [{"data": 1}, {"data": 2}]

    def save(self, data):
        return len(data)


class FailCollector(BaseCollector):
    def __init__(self):
        super().__init__("fail")

    def collect(self, **kwargs):
        raise RuntimeError("API 호출 실패")

    def save(self, data):
        return 0


class HighFailureCollector(BaseCollector):
    def __init__(self, expected, actual_count):
        super().__init__("high_fail")
        self._expected_count = expected
        self._actual = actual_count

    def collect(self, **kwargs):
        return list(range(self._actual))

    def save(self, data):
        return len(data)


class TestBaseCollectorRun:
    def test_successful_run(self):
        c = GoodCollector()
        count = c.run()
        assert count == 2
        assert c._last_run is not None

    def test_collect_failure(self):
        c = FailCollector()
        with pytest.raises(RuntimeError, match="API 호출 실패"):
            c.run()

    def test_high_failure_rate_blocked(self):
        c = HighFailureCollector(expected=100, actual_count=80)
        with pytest.raises(CollectionFailureError):
            c.run()

    def test_acceptable_failure_rate(self):
        c = HighFailureCollector(expected=100, actual_count=95)
        count = c.run()
        assert count == 95

    def test_no_expected_count_skips_check(self):
        c = GoodCollector()
        c._expected_count = 0
        count = c.run()
        assert count == 2

    def test_high_failure_logs_failed_tickers(self, caplog):
        """failed_tickers 가 있으면 별도 로그 라인 출력 (line 105).

        run() 시작 시 _failed_tickers 가 reset 되므로 collect() 내부에서 채워야 함.
        """

        class FailedTickersCollector(BaseCollector):
            def __init__(self):
                super().__init__("ftk")
                self._expected_count = 100

            def collect(self, **kw):
                self._failed_tickers = ["AAA", "BBB", "CCC"]
                return list(range(20))  # 80% 실패율 → CollectionFailureError

            def save(self, data):
                return len(data)

        c = FailedTickersCollector()
        with caplog.at_level("ERROR"):
            with pytest.raises(CollectionFailureError):
                c.run()
        # 실패 종목 메시지 출력 확인
        assert any("실패 종목" in rec.message for rec in caplog.records)


class TestFetchJson:
    """`fetch_json` API call helper (lines 49-51)."""

    def test_returns_parsed_json(self):
        from unittest.mock import MagicMock, patch

        from nuri.collectors.base import fetch_json

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "value"}
        mock_resp.raise_for_status = MagicMock()
        with patch("nuri.collectors.base.requests.get", return_value=mock_resp) as mock_get:
            result = fetch_json("https://example.com/api", params={"q": 1}, headers={"X-Test": "1"})
        assert result == {"key": "value"}
        mock_get.assert_called_once()
        mock_resp.raise_for_status.assert_called_once()

    def test_raises_on_http_error(self):
        from unittest.mock import MagicMock, patch

        import requests

        from nuri.collectors.base import fetch_json

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("nuri.collectors.base.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                fetch_json("https://example.com")


class TestSendFailureAlertOutboxBroken:
    """`_send_failure_alert` 가 outbox stage_ops raise 해도 swallow (lines 150-151)."""

    def test_outbox_failure_does_not_propagate(self, monkeypatch):
        """outbox.stage_ops 가 raise 해도 except 로 swallow → run() 본래 raise 만 발생."""
        # outbox.stage_ops 자체가 raise → except Exception → debug log 만
        import nuri.agents.discord.outbox as outbox_mod

        monkeypatch.setattr(
            outbox_mod, "stage_ops", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB 미초기화"))
        )

        class FailC(BaseCollector):
            def __init__(self):
                super().__init__("outbox_broken")

            def collect(self, **kw):
                raise RuntimeError("collect fail")

            def save(self, data):
                return 0

        c = FailC()
        with pytest.raises(RuntimeError, match="collect fail"):
            c.run()


class TestGetTickers:
    def test_filter_us(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        us = c._get_tickers(market="us")
        assert "AAPL" in us
        assert "005930.KS" not in us

    def test_filter_kr(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        kr = c._get_tickers(market="kr")
        assert "005930.KS" in kr
        assert "AAPL" not in kr

    def test_filter_all(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "AAPL", 1, 100, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("t", "005930.KS", 1, 50000, "KRW"),
            )

        c = GoodCollector()
        all_tickers = c._get_tickers()
        assert "AAPL" in all_tickers
        assert "005930.KS" in all_tickers


class TestRetryLogic:
    def test_retry_succeeds_on_second_attempt(self):
        call_count = 0

        class RetryCollector(BaseCollector):
            def __init__(self):
                super().__init__("retry")

            def collect(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("temporary")
                return [1, 2]

            def save(self, data):
                return len(data)

        c = RetryCollector()
        count = c.run()
        assert count == 2
        assert call_count == 2

    def test_all_retries_fail(self):
        class AlwaysFailCollector(BaseCollector):
            def __init__(self):
                super().__init__("always_fail")

            def collect(self, **kwargs):
                raise ConnectionError("down")

            def save(self, data):
                return 0

        c = AlwaysFailCollector()
        with pytest.raises(ConnectionError, match="down"):
            c.run()

    def test_failure_alert_called(self, monkeypatch):
        alert_called = False

        class AlertCollector(BaseCollector):
            def __init__(self):
                super().__init__("alert")

            def collect(self, **kwargs):
                raise RuntimeError("boom")

            def save(self, data):
                return 0

            def _send_failure_alert(self, msg):
                nonlocal alert_called
                alert_called = True

        c = AlertCollector()
        with pytest.raises(RuntimeError):
            c.run()
        assert alert_called


class TestMaxFailureRate:
    def test_constant(self):
        assert MAX_FAILURE_RATE == 0.10


class TestFailureAlertSingleWriter:
    """`_send_failure_alert` 는 outbox.stage_ops 만 경유해야 한다.

    Lock-test (Gotcha-Test Pair, invariants.md):
    Single-writer Discord rule — 직접 `send_webhook_message` 호출 금지.
    Refactor (PR P0-2) 회귀 시 두 테스트 모두 fail 해야 한다.
    """

    def test_routes_through_stage_ops(self, monkeypatch):
        """retry 3회 모두 실패 → stage_ops 가 정확히 1회 호출되며,
        payload 에 collector name + error_msg 가 박혀 있어야 한다."""
        captured: list[dict] = []

        def _fake_stage_ops(payload, **kwargs):
            captured.append({"payload": payload, "kwargs": kwargs})
            return 1

        # source-level patch — base._send_failure_alert 는 함수 내부에서
        # `from nuri.agents.discord.outbox import stage_ops` 동적 import 하므로
        # 원본 attribute 를 갈아끼운다.
        import nuri.agents.discord.outbox as outbox_mod

        monkeypatch.setattr(outbox_mod, "stage_ops", _fake_stage_ops)

        class AlwaysFailCollector(BaseCollector):
            def __init__(self):
                super().__init__("alert_routing_test")

            def collect(self, **kwargs):
                raise RuntimeError("boom-net-down")

            def save(self, data):
                return 0

        c = AlwaysFailCollector()
        with pytest.raises(RuntimeError, match="boom-net-down"):
            c.run()

        assert len(captured) == 1, f"stage_ops 는 정확히 1회 호출되어야 함 (got {len(captured)})"
        payload = captured[0]["payload"]
        assert payload["collector"] == "alert_routing_test"
        assert payload["event"] == "collector_failure"
        assert "boom-net-down" in payload["error"]
        # 메타 인자 — dedupe_key + actor_name 도 정확히 박혀야 함
        kwargs = captured[0]["kwargs"]
        assert "alert_routing_test" in kwargs["dedupe_key"]
        assert kwargs["actor_name"] == "collector.alert_routing_test"

    def test_does_not_call_direct_webhook(self, monkeypatch):
        """legacy `discord_bot.send_webhook*` 직접 호출 회귀 차단.

        과거 base.py 가 `nuri.alerts.discord_bot` 의 webhook 함수를 직접 부르던
        패턴이 되살아나면 이 테스트가 fail 한다.
        """
        webhook_calls: list[str] = []

        import nuri.alerts.discord_bot as discord_bot_mod

        # discord_bot 모듈의 직접 publish 함수 두 개 모두 spy
        monkeypatch.setattr(
            discord_bot_mod,
            "send_webhook",
            lambda *a, **kw: webhook_calls.append("send_webhook"),
        )
        monkeypatch.setattr(
            discord_bot_mod,
            "send_webhook_text",
            lambda *a, **kw: webhook_calls.append("send_webhook_text"),
        )

        # stage_ops 도 mock 해서 실제 DB 접근 없이 빠져나오게 함
        import nuri.agents.discord.outbox as outbox_mod

        monkeypatch.setattr(outbox_mod, "stage_ops", lambda *a, **kw: None)

        class AlwaysFailCollector(BaseCollector):
            def __init__(self):
                super().__init__("no_direct_webhook")

            def collect(self, **kwargs):
                raise RuntimeError("net-fail")

            def save(self, data):
                return 0

        c = AlwaysFailCollector()
        with pytest.raises(RuntimeError):
            c.run()

        assert webhook_calls == [], f"discord_bot 직접 호출됨: {webhook_calls} — Single-writer Discord 룰 위반"


# ##############################################################################
# Source: test_collectors.py
# ##############################################################################
