"""가격 수집기 실패율 가드 + 거부 알림 (#1872).

가격 수집기는 종목당 여러 날짜 행을 돌려준다. 가드가 행 수를 세면 기대치(종목 수)와
단위가 어긋나 늘 통과하므로, `ticker` 열이 있으면 종목 수를 센다. 소규모 집합
(portfolio 7 · freshness 3)은 1종목 실패가 곧 10% 초과라 가드를 끈다. 거부는 알림을
남긴다 — 2026-07~08 fundamental 거부가 몇 주 동안 조용했다.
"""

import pandas as pd
import pytest

from nuri.collectors import stock as stock_mod
from nuri.collectors import stock_kr as stock_kr_mod
from nuri.collectors.base import MIN_GUARDED_TICKERS, BaseCollector, CollectionFailureError
from nuri.collectors.stock import StockCollector
from nuri.collectors.stock_kr import StockKRCollector


def _price_frame(tickers: list[str], days: int = 5) -> pd.DataFrame:
    rows = [{"ticker": t, "date": f"2026-10-{13 + d:02d}", "close": 1.0} for t in tickers for d in range(days)]
    return pd.DataFrame(rows)


class _FrameCollector(BaseCollector):
    """종목당 여러 행을 돌려주는 가격 수집기 모양."""

    def __init__(self, expected: int, frame: pd.DataFrame):
        super().__init__("frame")
        self._expected_count = expected
        self._frame = frame
        self.saved: pd.DataFrame | None = None

    def collect(self, **kwargs):
        return self._frame

    def save(self, data):
        self.saved = data
        return len(data)


class _ListCollector(BaseCollector):
    """종목당 1건을 돌려주는 기존 수집기 모양 (fundamental / estimates)."""

    def __init__(self, expected: int, actual: int):
        super().__init__("listy")
        self._expected_count = expected
        self._actual = actual

    def collect(self, **kwargs):
        return list(range(self._actual))

    def save(self, data):
        return len(data)


@pytest.fixture
def alerts(monkeypatch):
    sent: list[tuple[str, str]] = []

    def _record(self, error_msg):
        sent.append((self.name, error_msg))

    monkeypatch.setattr(BaseCollector, "_send_failure_alert", _record)
    return sent


class TestGuardCountsTickersNotRows:
    def test_multi_day_frame_missing_30pct_is_rejected(self, alerts):
        tickers = [f"T{i:02d}" for i in range(40)]
        c = _FrameCollector(expected=40, frame=_price_frame(tickers[:28]))
        # 행 수(140)로 세면 기대치 40 을 넘어 통과한다 — 종목 수 28 로 세야 30% 실패다
        with pytest.raises(CollectionFailureError, match="실패율 30%"):
            c.run()
        assert c.saved is None

    def test_multi_day_frame_missing_5pct_is_saved(self, alerts):
        tickers = [f"T{i:02d}" for i in range(40)]
        c = _FrameCollector(expected=40, frame=_price_frame(tickers[:38]))
        assert c.run() == 38 * 5
        assert alerts == []

    def test_empty_frame_counts_zero(self, alerts):
        c = _FrameCollector(expected=40, frame=pd.DataFrame())
        with pytest.raises(CollectionFailureError, match="실패율 100%"):
            c.run()
        assert c.saved is None


class TestRejectionAlerts:
    @pytest.mark.parametrize(
        "collector",
        [
            lambda: _ListCollector(expected=100, actual=80),
            lambda: _FrameCollector(expected=40, frame=_price_frame([f"T{i}" for i in range(10)])),
        ],
        ids=["one-record-per-ticker", "multi-day-frame"],
    )
    def test_rejection_alerts_exactly_once(self, alerts, collector):
        c = collector()
        with pytest.raises(CollectionFailureError):
            c.run()
        assert len(alerts) == 1
        name, msg = alerts[0]
        assert name == c.name
        assert "저장 거부" in msg


def _tickers(n: int, suffix: str = "") -> list[str]:
    return [f"{i:06d}{suffix}" for i in range(n)]


class TestStockExpectation:
    @pytest.fixture
    def collector(self, monkeypatch):
        monkeypatch.setattr(StockCollector, "_collect_ticker", lambda self, t, s, e: None)
        return StockCollector()

    def _collect_with(self, collector, monkeypatch, tickers, **kwargs):
        monkeypatch.setattr(StockCollector, "_get_tickers", lambda self, **kw: tickers)
        collector.collect(**kwargs)
        return collector._expected_count

    def test_large_set_is_guarded(self, collector, monkeypatch):
        assert self._collect_with(collector, monkeypatch, _tickers(MIN_GUARDED_TICKERS)) == MIN_GUARDED_TICKERS

    def test_small_set_is_unguarded(self, collector, monkeypatch):
        assert self._collect_with(collector, monkeypatch, _tickers(MIN_GUARDED_TICKERS - 1)) == 0

    def test_empty_set_resets_a_previous_expectation(self, collector, monkeypatch):
        # 인스턴스 재사용(e3_3_backfill) 시 이전 기대치가 남으면 빈 실행이 거부된다
        self._collect_with(collector, monkeypatch, _tickers(30))
        assert self._collect_with(collector, monkeypatch, []) == 0

    def test_freshness_path_is_unguarded(self, collector, monkeypatch):
        monkeypatch.setattr(stock_mod, "_load_freshness_tickers", lambda: ["SPY", "TLT", "GC=F"])
        collector._expected_count = 30
        collector.collect(source="freshness")
        assert collector._expected_count == 0


class TestStockKRExpectation:
    @pytest.fixture
    def collector(self, monkeypatch):
        monkeypatch.setattr(StockKRCollector, "_collect_ticker", lambda self, t, s, e: None)
        monkeypatch.setattr(StockKRCollector, "_collect_indices", lambda self, days: None)
        monkeypatch.setattr(stock_kr_mod, "_reference_tickers", lambda: [])
        monkeypatch.setattr("time.sleep", lambda s: None)
        return StockKRCollector()

    def _collect_with(self, collector, monkeypatch, tickers):
        monkeypatch.setattr(StockKRCollector, "_get_tickers", lambda self, **kw: tickers)
        collector.collect()
        return collector._expected_count

    def test_large_set_adds_the_index_tickers(self, collector, monkeypatch):
        # 지수 행(KOSPI/KOSDAQ)도 프레임에 들어간다 — 기대치에 없으면 종목 실패 2건을 가린다
        got = self._collect_with(collector, monkeypatch, _tickers(MIN_GUARDED_TICKERS, ".KS"))
        assert got == MIN_GUARDED_TICKERS + len(StockKRCollector.INDEX_TICKERS)

    def test_small_set_is_unguarded(self, collector, monkeypatch):
        assert self._collect_with(collector, monkeypatch, _tickers(11, ".KS")) == 0

    def test_empty_set_resets_a_previous_expectation(self, collector, monkeypatch):
        self._collect_with(collector, monkeypatch, _tickers(30, ".KS"))
        assert self._collect_with(collector, monkeypatch, []) == 0
