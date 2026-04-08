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


# ##############################################################################
# Source: test_collectors.py
# ##############################################################################
