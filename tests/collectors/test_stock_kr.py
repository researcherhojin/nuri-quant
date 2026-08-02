"""Per-collector tests for stock_kr.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import (
    init_db,
    upsert_portfolio,
)


class TestStockKRCollector:
    def test_instantiate(self):
        from nuri.collectors.stock_kr import StockKRCollector

        c = StockKRCollector()
        assert c.name == "stock_kr"


# ##############################################################################
# Source: test_collectors_phase2.py
# ##############################################################################


class TestStockKRCollectorScenarios:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))
        df = StockKRCollector().collect(days=5)
        assert not df.empty

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=pd.DataFrame()))
        assert StockKRCollector().collect(days=5).empty

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr(
            "nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(side_effect=Exception("pykrx error"))
        )
        assert StockKRCollector().collect(days=5).empty

    def test_collect_without_kr_holdings_still_gets_reference(self, monkeypatch, tmp_path):
        """KR 보유가 0이어도 기준 티커는 수집한다.

        브리프의 KR 벤치마크는 보유 종목이 아니라 `source=portfolio` 에 안 잡히고,
        `universe.yaml` 은 KRX 구성종목 자동 동기화라 ETF 를 넣어도 지워진다. 그래서
        어느 경로로도 안 잡혀 프로덕션 `prices` 에 0행이었다 (2026-08-02 실측).

        회귀 잠금: 기준 티커 union 을 지우면 다시 빈 DataFrame 이 되고, KR 벤치마크·
        섹터 무버 fallback 이 조용히 죽는다.
        """
        import nuri.core.db as db_mod
        from nuri.collectors.stock_kr import StockKRCollector, _reference_tickers

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "AAPL",
                    "quantity": 10,
                    "avg_price": 190,
                    "currency": "USD",
                    "sector": "Tech",
                }
            ],
            path,
        )
        mock_ohlcv = pd.DataFrame(
            {"시가": [40000], "고가": [41000], "저가": [39000], "종가": [40500], "거래량": [1000000]},
            index=pd.to_datetime(["2026-07-31"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))

        df = StockKRCollector().collect(days=5)

        assert set(df["ticker"]) == set(_reference_tickers()), "기준 티커만 — 보유 KR 은 없다"

    def test_reference_tickers_come_from_config_not_a_second_list(self):
        """기준 티커는 config 선언에서 뽑는다 — 목록을 또 하드코딩하면 갈라진다."""
        from nuri.collectors.stock_kr import _reference_tickers
        from nuri.core.rules import BRIEF_BENCHMARK

        assert _reference_tickers() == [BRIEF_BENCHMARK["kr"]]
        assert BRIEF_BENCHMARK["us"] not in _reference_tickers(), "US 벤치마크는 KR 수집기 소관이 아니다"

    def test_collect_includes_indices(self, monkeypatch, db_with_portfolio):
        """KOSPI/KOSDAQ 지수가 같이 수집되는지 확인 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        # pykrx OHLCV mock
        mock_ohlcv = pd.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))

        # yfinance mock for index
        mock_index_df = pd.DataFrame(
            {"Open": [5800.0], "High": [5900.0], "Low": [5700.0], "Close": [5850.0], "Volume": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        import yfinance

        mock_download = MagicMock(return_value=mock_index_df)
        monkeypatch.setattr(yfinance, "download", mock_download)

        df = StockKRCollector().collect(days=5)
        assert not df.empty
        tickers = df["ticker"].unique().tolist()
        assert "KOSPI" in tickers
        assert "KOSDAQ" in tickers

    def test_collect_indices_empty(self, monkeypatch, db_with_portfolio):
        """yfinance가 빈 데이터 반환 시 지수 스킵 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=pd.DataFrame()))
        import yfinance

        monkeypatch.setattr(yfinance, "download", MagicMock(return_value=pd.DataFrame()))

        df = StockKRCollector().collect(days=5)
        # 개별 종목도 빈 데이터, 지수도 빈 데이터 → 전체 빈 DataFrame
        assert df.empty

    def test_collect_indices_exception(self, monkeypatch, db_with_portfolio):
        """yfinance 지수 수집 실패 시 에러 없이 스킵 (#247)."""
        from nuri.collectors.stock_kr import StockKRCollector

        mock_ohlcv = pd.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd.to_datetime(["2025-01-29"]),
        )
        monkeypatch.setattr("nuri.collectors.stock_kr.krx.get_market_ohlcv", MagicMock(return_value=mock_ohlcv))
        import yfinance

        monkeypatch.setattr(yfinance, "download", MagicMock(side_effect=Exception("yfinance error")))

        df = StockKRCollector().collect(days=5)
        # 개별 종목은 수집되지만 지수는 스킵
        assert not df.empty
        assert "KOSPI" not in df["ticker"].unique().tolist()

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock_kr import StockKRCollector

        assert StockKRCollector().save(pd.DataFrame()) == 0


class TestCallWithTimeout:
    """#272 Phase 2c: pykrx hang 방지 timeout 헬퍼."""

    def test_normal_return(self):
        from nuri.collectors.stock_kr import _call_with_timeout

        assert _call_with_timeout(lambda x: x * 2, 5, 21) == 42

    def test_timeout_returns_none(self):
        """timeout 시 None — 호출 hang 방지."""
        import time

        from nuri.collectors.stock_kr import _call_with_timeout

        result = _call_with_timeout(lambda: time.sleep(2), 1)
        assert result is None

    def test_exception_propagates(self):
        """Exception은 timeout과 별개로 호출자에게 전파."""
        import pytest as _pytest

        from nuri.collectors.stock_kr import _call_with_timeout

        with _pytest.raises(ValueError, match="boom"):
            _call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("boom")), 5)

    def test_timeout_helper_used_in_collect_ticker(self, monkeypatch, db_with_portfolio):
        """_collect_ticker가 _call_with_timeout 통해 pykrx 호출."""
        import pandas as pd_

        from nuri.collectors.stock_kr import StockKRCollector

        mock_df = pd_.DataFrame(
            {"시가": [60000], "고가": [61000], "저가": [59000], "종가": [60500], "거래량": [1000000]},
            index=pd_.to_datetime(["2025-01-29"]),
        )

        captured = {"called": False}

        def fake_helper(func, timeout, *args, **kwargs):
            captured["called"] = True
            captured["timeout"] = timeout
            return mock_df

        monkeypatch.setattr("nuri.collectors.stock_kr._call_with_timeout", fake_helper)
        c = StockKRCollector()
        df = c._collect_ticker("005930.KS", "20250101", "20250131")
        assert df is not None
        assert captured["called"] is True
        assert captured["timeout"] == 5  # 5초 타임아웃 (parallel batch와 함께)

    def test_collect_ticker_returns_none_on_timeout(self, monkeypatch, db_with_portfolio):
        """timeout 시 _collect_ticker가 None 반환 (warning log + skip)."""
        from nuri.collectors.stock_kr import StockKRCollector

        # _call_with_timeout이 None 반환 (timeout 시뮬레이션)
        monkeypatch.setattr("nuri.collectors.stock_kr._call_with_timeout", lambda *a, **kw: None)
        c = StockKRCollector()
        df = c._collect_ticker("005930.KS", "20250101", "20250131")
        assert df is None  # timeout → skip


class TestSourceParam:
    """#272 Phase 2c bug 1 fix: source 파라미터 wiring."""

    def test_source_universe_passed_to_get_tickers(self, monkeypatch, db_with_portfolio):
        """source='universe' → _get_tickers(market='kr', source='universe')."""
        from nuri.collectors.stock_kr import StockKRCollector

        c = StockKRCollector()
        captured = {}

        def fake_get(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr(c, "_get_tickers", fake_get)
        c.collect(days=5, source="universe")
        assert captured.get("market") == "kr"
        assert captured.get("source") == "universe"

    def test_source_in_log_message(self, monkeypatch, db_with_portfolio, caplog):
        """수집 대상 메시지에 source 표시."""
        import logging as _logging

        from nuri.collectors.stock_kr import StockKRCollector

        c = StockKRCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["005930.KS"])
        monkeypatch.setattr("nuri.collectors.stock_kr._call_with_timeout", lambda *a, **kw: pd.DataFrame())

        with caplog.at_level(_logging.INFO):
            c.collect(days=5, source="universe")

        info = [r for r in caplog.records if "source=universe" in r.message]
        assert len(info) >= 1


class TestCallWithTimeoutBranch:
    """`_call_with_timeout` (line 42) — Future timeout → None 반환.

    ThreadPoolExecutor.submit 을 patch 해 timeout 발생을 강제 → conftest.py 의
    sleep mock 영향을 받지 않는다.
    """

    def test_future_timeout_returns_none(self, monkeypatch):
        """future.result(timeout=N) → TimeoutError → None (line 42)."""
        import concurrent.futures as cf

        from nuri.collectors.stock_kr import _call_with_timeout

        # Future 가 timeout 발생하도록 강제: future.result 가 항상 TimeoutError raise
        class _TimeoutFuture:
            def result(self, timeout=None):
                raise cf.TimeoutError()

        class _StubExecutor:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, *a, **kw):
                return _TimeoutFuture()

        monkeypatch.setattr(cf, "ThreadPoolExecutor", _StubExecutor)
        result = _call_with_timeout(lambda: 42, timeout_sec=1)
        assert result is None


class TestCollectTickerTimeoutNone:
    """`_collect_ticker` 가 _call_with_timeout 으로부터 None 받으면 (pykrx 타임아웃)
    None 반환 + debug log (lines 123-124)."""

    def test_timeout_returns_none_with_log(self, monkeypatch, caplog):
        import logging as _logging

        from nuri.collectors.stock_kr import StockKRCollector

        # _call_with_timeout 이 None 반환 (pykrx hang simulation)
        monkeypatch.setattr(
            "nuri.collectors.stock_kr._call_with_timeout",
            lambda *a, **kw: None,
        )

        c = StockKRCollector()
        with caplog.at_level(_logging.DEBUG, logger="nuri.collectors.stock_kr"):
            result = c._collect_ticker("005930.KS", "20260101", "20260115")
        assert result is None
        assert any("timeout" in rec.message.lower() for rec in caplog.records)


class TestCollectIndicesMultiIndexColumns:
    """`_collect_indices` MultiIndex 컬럼 분기 (line 166)."""

    def test_yfinance_multiindex_columns_normalized(self, monkeypatch):
        """yfinance.download 가 MultiIndex 컬럼을 반환할 때 get_level_values(0) 호출."""
        import sys

        from nuri.collectors.stock_kr import StockKRCollector

        # MultiIndex 컬럼 가진 가짜 DF (yfinance multi-symbol 모드 시 발생)
        idx = pd.MultiIndex.from_tuples(
            [("Open", "x"), ("High", "x"), ("Low", "x"), ("Close", "x"), ("Volume", "x"), ("Adj Close", "x")]
        )
        df = pd.DataFrame(
            [[100.0, 110.0, 90.0, 105.0, 1000, 105.0]] * 3,
            columns=idx,
            index=pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"]),
        )

        mock_yf = MagicMock()
        mock_yf.download.return_value = df
        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        c = StockKRCollector()
        results = c._collect_indices(days=3)
        # MultiIndex normalize → KOSPI/KOSDAQ 각각 3 rows = 최소 1+ row 생성
        assert results is not None
        assert len(results) > 0
