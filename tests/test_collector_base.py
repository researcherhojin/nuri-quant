"""BaseCollector 테스트 + 수집 실패율 체크."""
import pytest

from nuri.collectors.base import MAX_FAILURE_RATE, BaseCollector, CollectionFailureError
from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


class GoodCollector(BaseCollector):
    """성공하는 수집기."""
    def __init__(self):
        super().__init__("good")

    def collect(self, **kwargs):
        return [{"data": 1}, {"data": 2}]

    def save(self, data):
        return len(data)


class FailCollector(BaseCollector):
    """collect에서 예외 발생."""
    def __init__(self):
        super().__init__("fail")

    def collect(self, **kwargs):
        raise RuntimeError("API 호출 실패")

    def save(self, data):
        return 0


class HighFailureCollector(BaseCollector):
    """실패율 초과 수집기."""
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
        """실패율 > 10% → CollectionFailureError."""
        c = HighFailureCollector(expected=100, actual_count=80)  # 20% failure
        with pytest.raises(CollectionFailureError):
            c.run()

    def test_acceptable_failure_rate(self):
        """실패율 <= 10% → 정상 저장."""
        c = HighFailureCollector(expected=100, actual_count=95)  # 5% failure
        count = c.run()
        assert count == 95

    def test_no_expected_count_skips_check(self):
        """_expected_count == 0이면 실패율 검사 안 함."""
        c = GoodCollector()
        c._expected_count = 0
        count = c.run()
        assert count == 2


class TestGetTickers:
    def test_filter_us(self, db_path):
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "AAPL", 1, 100, "USD"))
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "005930.KS", 1, 50000, "KRW"))

        c = GoodCollector()
        us = c._get_tickers(market="us")
        assert "AAPL" in us
        assert "005930.KS" not in us

    def test_filter_kr(self, db_path):
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "AAPL", 1, 100, "USD"))
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "005930.KS", 1, 50000, "KRW"))

        c = GoodCollector()
        kr = c._get_tickers(market="kr")
        assert "005930.KS" in kr
        assert "AAPL" not in kr

    def test_filter_all(self, db_path):
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "AAPL", 1, 100, "USD"))
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)", ("t", "005930.KS", 1, 50000, "KRW"))

        c = GoodCollector()
        all_tickers = c._get_tickers()
        assert "AAPL" in all_tickers
        assert "005930.KS" in all_tickers


class TestMaxFailureRate:
    def test_constant(self):
        assert MAX_FAILURE_RATE == 0.10
