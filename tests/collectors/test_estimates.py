"""Per-collector tests for estimates.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock

import pytest

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

    def test_upsert_empty_records_returns_zero(self):
        """line 148 — _upsert_estimates([]) early return."""
        from nuri.collectors.estimates import _upsert_estimates

        assert _upsert_estimates([]) == 0


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
                "ticker": "AAPL",
                "recommendation": "buy",
                "target_mean": 250.0,
                "target_median": 245.0,
                "current_price": 230.0,
                "num_analysts": 30,
            },
            {
                "ticker": "X",
                "recommendation": None,
                "target_mean": None,
                "target_median": None,
                "current_price": None,
                "num_analysts": None,
            },
        ]
        monkeypatch.setattr(mod, "EstimatesCollector", _FakeCollector)
        monkeypatch.setattr(mod, "query", lambda *a, **k: fake_rows)

        mod.main([])
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "애널리스트 컨센서스" in out
        assert "N/A" in out  # second row 의 None 분기


class TestEstimatesCoverageExtra:
    """Lines 65 / 116-117 cover — source!=portfolio 분기 + bulk log summary."""

    def test_collect_universe_mode_triggers_yfinance_log_suppression(self, rich_db, monkeypatch):
        """line 65 — source != 'portfolio' 분기: yfinance logger 레벨 CRITICAL 로 변경.

        실제 change 여부를 로거 level 로 검증 (universe 모드 종료 후 원복).
        """
        import logging as _logging

        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        # 21개 ticker — len(us_tickers) >= 20 분기도 같이 커버 (line 116-117)
        tickers = [f"T{i:02d}" for i in range(21)]
        monkeypatch.setattr(
            collector,
            "_get_tickers",
            lambda market=None, source="portfolio": tickers,
        )

        # yfinance Ticker mock — info 없음 → skipped 로 처리 (네트워크 호출 없음)
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.info = {}  # empty → return skipped
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)

        # universe 시작 전 yfinance logger level 기록
        yf_logger = _logging.getLogger("yfinance")
        initial_level = yf_logger.level

        results = collector.collect(source="universe")

        # 실행 후 원복됨 (initial_level 과 동일해야)
        assert yf_logger.level == initial_level
        # 21 tickers 전부 skipped (info={}) → results empty, but log branch 도 실행됨
        assert results == []

    def test_collect_bulk_log_branch_all_failed(self, rich_db, monkeypatch, caplog):
        """line 116-117 — us_tickers >= 20 시 summary log 포맷 (failed list)."""
        import logging as _logging

        from nuri.collectors.estimates import EstimatesCollector

        collector = EstimatesCollector()
        tickers = [f"F{i:02d}" for i in range(20)]
        monkeypatch.setattr(
            collector,
            "_get_tickers",
            lambda market=None, source="portfolio": tickers,
        )

        # yfinance 전부 raise → failed list 에 20개 누적
        mock_yf = MagicMock()

        class _Exploding:
            @property
            def info(self):
                raise RuntimeError("network down")

        mock_yf.Ticker.side_effect = lambda t: _Exploding()
        monkeypatch.setitem(__import__("sys").modules, "yfinance", mock_yf)

        with caplog.at_level(_logging.INFO, logger="nuri.collectors.estimates"):
            collector.collect(source="portfolio")

        # Bulk summary log — "✅" 로 시작하는 line 이 line 117 의 진짜 대상.
        # (line 53 "수집: 20종목" 과 구별)
        summary = [r for r in caplog.records if "✅" in r.message]
        assert summary, "bulk summary log 가 emit 되지 않음"
        # 20개 전부 failed + '외 N개' truncation branch 확인 (15 remaining)
        assert "외 15개" in summary[0].message


class TestEstimatesExpectedCountGuard:
    """MAX_FAILURE_RATE 가드 활성화 lock-test.

    Reason: estimates.collect() 가 us_tickers 수로 _expected_count 동적 설정 →
    asymmetric data age 방지 가드 활성화. 회귀 차단.
    """

    def test_collect_sets_expected_count(self, monkeypatch):
        """collect() 가 KR 제외 후 us_tickers 수로 _expected_count 설정."""
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        assert c._expected_count == 0

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 100.0,
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": 30,
            "targetMeanPrice": 120.0,
        }
        mock_yf.Ticker.return_value = mock_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["AAPL", "MSFT", "GOOGL", "TSLA", "005930.KS"])

        c.collect()
        assert c._expected_count == 4, "KR 제외 후 us_tickers 수로 _expected_count 설정 안 함"

    def test_run_blocks_when_failure_rate_exceeds_threshold(self, monkeypatch):
        """run() 이 us_tickers 80% 실패 시 CollectionFailureError 발생."""
        from nuri.collectors.base import CollectionFailureError
        from nuri.collectors.estimates import EstimatesCollector

        c = EstimatesCollector()
        # 10 us_tickers 중 2개만 valid (T0/T1) → 80% 실패
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(10)])

        def make_ticker(t):
            mock = MagicMock()
            if t in ("T0", "T1"):
                mock.info = {
                    "regularMarketPrice": 100.0,
                    "recommendationKey": "buy",
                    "numberOfAnalystOpinions": 30,
                    "targetMeanPrice": 120.0,
                }
            else:
                mock.info = {}
            return mock

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = make_ticker
        import sys

        monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

        save_called = []
        monkeypatch.setattr(c, "save", lambda data: save_called.append(len(data)) or len(data))

        with pytest.raises(CollectionFailureError, match="실패율 80%"):
            c.run()
        assert save_called == [], "실패율 초과 시 save() 호출되면 안 됨"
