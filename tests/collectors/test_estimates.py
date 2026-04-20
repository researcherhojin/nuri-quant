"""Per-collector tests for estimates.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock

from nuri.core.db import (
    init_db,
)


class TestEstimatesCollector:
    def test_instantiate(self):
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c.name == "estimates"

    def test_safe_helpers(self):
        from nuri.collectors.estimates import _safe_float, _safe_int

        assert _safe_float(1.5) == 1.5
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None
        assert _safe_int(10) == 10
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None

    def test_save_records(self, db_path):
        from nuri.collectors.estimates import _upsert_estimates

        records = [
            {
                "ticker": "AAPL",
                "date": "2026-03-30",
                "recommendation": "buy",
                "target_high": 250.0,
                "target_low": 190.0,
                "target_mean": 220.0,
                "target_median": 218.0,
                "num_analysts": 30,
                "current_price": 195.0,
            }
        ]
        count = _upsert_estimates(records)
        assert count == 1


class TestEstimatesCollectorMockedYFinance:
    def test_collect_with_mocked_yfinance(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None, source="portfolio": ["AAPL"])
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 200.0,
            "currentPrice": 200.0,
            "recommendationKey": "buy",
            "targetHighPrice": 250.0,
            "targetLowPrice": 180.0,
            "targetMeanPrice": 220.0,
            "targetMedianPrice": 215.0,
            "numberOfAnalystOpinions": 30,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        results = collector.collect()
        assert len(results) == 1
        assert results[0]["recommendation"] == "buy"
        assert results[0]["target_mean"] == 220.0

    def test_collect_empty_info(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None, source="portfolio": ["AAPL"])
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_no_analysts(self, rich_db, monkeypatch):
        """분석가 데이터 없는 종목(VOO 같은 ETF) 스킵."""
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None, source="portfolio": ["VOO"])
        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": 500.0}  # 분석가 필드 없음
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_exception(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None, source="portfolio": ["AAPL"])
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("API fail")
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)
        assert collector.collect() == []

    def test_collect_no_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None, source="portfolio": [])
        assert collector.collect() == []

    def test_collect_skips_kr_tickers(self, rich_db, monkeypatch):
        """한국 종목(.KS)은 yfinance 컨센서스 미지원 — 스킵."""
        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        monkeypatch.setattr(
            collector, "_get_tickers", lambda market=None, source="portfolio": ["005930.KS", "000660.KS"]
        )
        assert collector.collect() == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        assert EstimatesCollector().save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector

        count = EstimatesCollector().save(
            [
                {
                    "ticker": "MSFT",
                    "date": "2025-01-01",
                    "recommendation": "buy",
                    "target_high": 500,
                    "target_low": 400,
                    "target_mean": 450,
                    "target_median": 445,
                    "num_analysts": 40,
                    "current_price": 420,
                }
            ]
        )
        assert count == 1

    def test_safe_float_and_int(self):
        from nuri.collectors.estimates import _safe_float, _safe_int

        assert _safe_float(3.14) == 3.14
        assert _safe_float(float("nan")) is None
        assert _safe_int(42) == 42
        assert _safe_int(float("nan")) is None


class TestEstimatesCollectorErrorHandling:
    def test_collect_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 190.0,
            "currentPrice": 190.0,
            "recommendationKey": "buy",
            "targetHighPrice": 300.0,
            "targetLowPrice": 200.0,
            "targetMeanPrice": 250.0,
            "targetMedianPrice": 248.0,
            "numberOfAnalystOpinions": 30,
        }
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        results = EstimatesCollector().collect()
        assert results[0]["recommendation"] == "buy"
        assert results[0]["target_mean"] == 250.0

    def test_collect_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_ticker = MagicMock()
        mock_ticker.info = {}  # 빈 info
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert EstimatesCollector().collect() == []

    def test_collect_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = Exception("fail")
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        assert EstimatesCollector().collect() == []

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.estimates import EstimatesCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert EstimatesCollector().collect() == []

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_safe_float(self):
        from nuri.collectors.estimates import _safe_float

        assert _safe_float(123.45) == 123.45
        assert _safe_float(float("nan")) is None

    def test_safe_int(self):
        from nuri.collectors.estimates import _safe_int

        assert _safe_int(30) == 30
        assert _safe_int(float("nan")) is None


class TestEstimatesCli:
    """`if __name__ == '__main__'` 블록 coverage — argparse 분기 + main() 직접 호출."""

    def test_parse_args_default_portfolio(self):
        from nuri.collectors.estimates import _parse_args

        args = _parse_args([])
        assert args.source == "portfolio"

    def test_parse_args_universe(self):
        from nuri.collectors.estimates import _parse_args

        args = _parse_args(["--source", "universe"])
        assert args.source == "universe"

    def test_parse_args_all(self):
        from nuri.collectors.estimates import _parse_args

        args = _parse_args(["--source", "all"])
        assert args.source == "all"

    def test_parse_args_invalid_source_rejected(self):
        import pytest as _pytest

        from nuri.collectors.estimates import _parse_args

        with _pytest.raises(SystemExit):
            _parse_args(["--source", "invalid"])

    def test_main_calls_run_with_source_and_returns_count(self, monkeypatch, tmp_path):
        """main(['--source', 'universe']) → run(source='universe') 호출되고 count 반환."""
        import nuri.collectors.estimates as mod

        called = {}

        class _FakeCollector:
            def run(self, source="portfolio"):
                called["source"] = source
                return 7

        monkeypatch.setattr(mod, "EstimatesCollector", _FakeCollector)
        monkeypatch.setattr(mod, "query", lambda *a, **k: [])  # no rows → skip print block

        out = mod.main(["--source", "universe"])
        assert called == {"source": "universe"}
        assert out == 7

    def test_main_default_source_portfolio_when_no_args(self, monkeypatch):
        import nuri.collectors.estimates as mod

        called = {}

        class _FakeCollector:
            def run(self, source="portfolio"):
                called["source"] = source
                return 0

        monkeypatch.setattr(mod, "EstimatesCollector", _FakeCollector)
        monkeypatch.setattr(mod, "query", lambda *a, **k: [])

        mod.main([])
        assert called["source"] == "portfolio"

    def test_main_print_block_when_rows_present(self, monkeypatch, capsys):
        """rows 존재 시 print 블록도 실행 — format branches 커버."""
        import nuri.collectors.estimates as mod

        class _FakeCollector:
            def run(self, source="portfolio"):
                return 2

        fake_rows = [
            {
                "ticker": "AAPL", "recommendation": "buy",
                "target_mean": 250.0, "target_median": 245.0,
                "current_price": 230.0, "num_analysts": 30,
            },
            {
                "ticker": "X", "recommendation": None,
                "target_mean": None, "target_median": None,
                "current_price": None, "num_analysts": None,
            },
        ]
        monkeypatch.setattr(mod, "EstimatesCollector", _FakeCollector)
        monkeypatch.setattr(mod, "query", lambda *a, **k: fake_rows)

        mod.main([])
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "애널리스트 컨센서스" in out
        assert "N/A" in out  # second row 의 None 분기
