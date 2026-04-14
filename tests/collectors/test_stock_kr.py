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

    def test_collect_no_kr_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock_kr import StockKRCollector

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
        assert StockKRCollector().collect(days=5).empty

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
