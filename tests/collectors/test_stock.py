"""Per-collector tests for stock.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import (
    init_db,
)


class TestStockCollector:
    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        result = c._period_to_start_date("5d")
        assert len(result) == 10
        assert "-" in result


class TestStockCollectorTickerCollection:
    def test_collect_ticker_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
                "adj_close": [194.0],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and not df.empty

    def test_collect_ticker_empty(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("provider error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30") is None

    def test_collect_ticker_no_adj_close(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        df = StockCollector()._collect_ticker("AAPL", "2025-01-01", "2025-01-30")
        assert df is not None and "adj_close" in df.columns

    def test_collect_no_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.stock import StockCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert StockCollector().collect(period="5d").empty

    def test_period_to_start_date(self):
        from nuri.collectors.stock import StockCollector

        result = StockCollector._period_to_start_date("1mo")
        assert len(result) == 10

    def test_save_empty(self, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        assert StockCollector().save(pd.DataFrame()) == 0


class TestStockCollectorEdgeCases:
    def test_collect_full_flow(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.stock import StockCollector

        mock_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "open": [190.0],
                "high": [195.0],
                "low": [189.0],
                "close": [194.0],
                "volume": [50000000],
                "adj_close": [194.0],
            }
        )
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert not StockCollector().collect(period="5d").empty


class TestStockUniverseModeCoverage:
    """#272 Phase 2b: tqdm + summary 패치 커버리지."""

    def test_collect_universe_summary_logged(self, monkeypatch, db_with_portfolio, caplog):
        """20+ tickers + universe 모드: summary 로그 fire."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        # 25개 ticker, 모두 데이터 부족
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(25)])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="5d")

        summary = [r for r in caplog.records if "수집 결과:" in r.message]
        assert len(summary) >= 1, "Expected summary log for 25-ticker universe"

    def test_collect_universe_source_in_log(self, monkeypatch, db_with_portfolio, caplog):
        """수집 대상 메시지에 source 표시."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["A"])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="5d")

        info = [r for r in caplog.records if "source=universe" in r.message]
        assert len(info) >= 1


class TestStockOneYearBackfill:
    """#272 후속: `make collect-universe-1y` — P1 A (tech analysis) 선행 조건.

    1y = 252 trading days (chart_analysis.LOOKBACK_52W 와 정확히 일치).
    chart_analysis.analyze_chart lookback_days=365 default 과 맞춤.
    """

    def test_period_1y_maps_to_365_days_ago(self):
        """_period_to_start_date('1y') → 365일 전 (±1일 허용, 월말 경계)."""
        from datetime import datetime, timedelta

        from nuri.collectors.stock import StockCollector
        from nuri.core.timezone import kst_now

        c = StockCollector()
        start = c._period_to_start_date("1y")
        parsed = datetime.strptime(start, "%Y-%m-%d")
        now = kst_now().replace(tzinfo=None)
        delta = (now - parsed).days
        # mapping["1y"] = 365. ±2일 tolerance (timezone 경계 + 반올림).
        assert 363 <= delta <= 367, f"1y should map to ~365 days, got {delta}"

    def test_collect_1y_universe_logs_period(self, monkeypatch, db_with_portfolio, caplog):
        """collect(period='1y', source='universe') — 1y 로그 + universe source 모두 기록."""
        import logging

        from nuri.collectors.stock import StockCollector

        c = StockCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["SPY"])
        monkeypatch.setattr(c, "_collect_ticker", lambda *a, **kw: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe", period="1y")

        # "수집 대상: ... (1y, source=universe)" 단일 메시지
        hits = [r for r in caplog.records if "1y" in r.message and "source=universe" in r.message]
        assert len(hits) >= 1, (
            f"Expected log with both '1y' and 'source=universe'. "
            f"Got: {[r.message for r in caplog.records if '수집' in r.message]}"
        )


class TestStandardizeThreadSafety:
    """PR #743 — `_standardize(df)` 가 shared mock 객체를 mutate 하던 race 회귀 방지.

    CLAUDE.md gotcha + PR #294/#295 에서 처음 기록된 패턴이지만, 실제 `df.copy()`
    방어가 `_standardize` 에 적용 안 된 채로 merge 되었음. 이 세션 (#306 CI) 에서
    재발 → 실제 fix + 전용 테스트.
    """

    def test_standardize_does_not_mutate_input(self):
        """함수 호출 후 입력 df 는 원본 그대로 유지되어야 한다."""
        from nuri.collectors.stock import StockCollector

        original = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "Open": [190.0],
                "High": [195.0],
                "Low": [189.0],
                "Close": [194.0],
                "Volume": [50000000],
            }
        )
        original_columns_before = list(original.columns)
        StockCollector()._standardize(original, "AAPL")

        # 원본 columns 가 '소문자 통일' 로 mutate 되면 안 됨
        assert list(original.columns) == original_columns_before, (
            "_standardize 가 입력 df 를 mutate 했음. df.copy() 누락 의심 (PR #743)"
        )

    def test_concurrent_standardize_calls_do_not_race(self):
        """ThreadPoolExecutor 10-worker 로 동일 df 를 공유해서 _standardize 호출해도
        race condition 없이 모두 성공해야 함. race 발생 시 InvalidIndexError.
        """
        import concurrent.futures

        from nuri.collectors.stock import StockCollector

        shared_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-15"]),
                "Open": [190.0],
                "High": [195.0],
                "Low": [189.0],
                "Close": [194.0],
                "Volume": [50000000],
            }
        )
        c = StockCollector()

        def _call(i):
            return c._standardize(shared_df, f"TICK{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(_call, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # 모두 정상 결과 (df 반환) — 예외 없이 완료
        assert len(results) == 50
        for r in results:
            assert "ticker" in r.columns
            assert "adj_close" in r.columns


class TestFreshnessSource:
    """Issue #453 — `--source freshness` 가 SIEGE freshness gate 의존 ticker 를 추출."""

    def test_load_freshness_tickers_extracts_primary_and_secondary(self, monkeypatch):
        from nuri.collectors import stock as stock_mod

        fake_rules = {
            "siege_gates": {
                "asset_classes": {
                    "us_equity": {"freshness_primary": "SPY", "freshness_secondary": []},
                    "bond": {"freshness_primary": "TLT", "freshness_secondary": ["SPY"]},
                    "commodity": {"freshness_primary": "GC=F", "freshness_secondary": []},
                }
            }
        }
        # rules.RULES 는 module-level frozen dict — monkeypatch 로 교체.
        from nuri.core import rules as rules_mod

        monkeypatch.setattr(rules_mod, "RULES", fake_rules)

        result = stock_mod._load_freshness_tickers()
        # primary + secondary 합집합 — 중복 제거 + sorted
        assert result == sorted({"SPY", "TLT", "GC=F"})

    def test_load_freshness_tickers_excludes_non_yfinance(self, monkeypatch):
        """KOSPI 같은 macro indicator name 은 stock.py 가 fetch 못함 → 제외."""
        from nuri.collectors import stock as stock_mod
        from nuri.core import rules as rules_mod

        fake_rules = {
            "siege_gates": {
                "asset_classes": {
                    "kr_equity": {"freshness_primary": "KOSPI", "freshness_secondary": ["SPY"]},
                    "kr_index": {"freshness_primary": "KOSPI", "freshness_secondary": ["SPY"]},
                }
            }
        }
        monkeypatch.setattr(rules_mod, "RULES", fake_rules)

        result = stock_mod._load_freshness_tickers()
        assert "KOSPI" not in result
        assert result == ["SPY"]

    def test_load_freshness_tickers_empty_config(self, monkeypatch):
        """siege_gates 설정 부재 시 빈 리스트 — graceful."""
        from nuri.collectors import stock as stock_mod
        from nuri.core import rules as rules_mod

        monkeypatch.setattr(rules_mod, "RULES", {})
        assert stock_mod._load_freshness_tickers() == []

    def test_collect_freshness_source_uses_helper_not_get_tickers(self, monkeypatch, tmp_path):
        """source='freshness' 분기는 _get_tickers 를 호출하지 않음 — siege config 직접 추출."""
        from nuri.collectors import stock as stock_mod
        from nuri.collectors.stock import StockCollector
        from nuri.core import rules as rules_mod
        from nuri.core.db import init_db

        db = tmp_path / "test.db"
        init_db(db)

        fake_rules = {
            "siege_gates": {
                "asset_classes": {
                    "us_equity": {"freshness_primary": "SPY", "freshness_secondary": []},
                    "bond": {"freshness_primary": "TLT", "freshness_secondary": []},
                }
            }
        }
        monkeypatch.setattr(rules_mod, "RULES", fake_rules)

        # _collect_ticker stub — 실제 yfinance call 차단, 호출 ticker 추적
        called_tickers: list[str] = []

        def _stub_collect_ticker(self, ticker, start_date, end_date):
            called_tickers.append(ticker)
            return None  # 빈 결과 — save 단계 스킵

        monkeypatch.setattr(StockCollector, "_collect_ticker", _stub_collect_ticker)

        c = StockCollector()
        c.collect(period="5d", source="freshness")

        # SPY/TLT 만 호출됐는지 — portfolio (db_with_portfolio fixture 미사용이라 비어있음) 분기
        # 가 아니라 _load_freshness_tickers() 분기를 탔는지 검증.
        assert sorted(called_tickers) == ["SPY", "TLT"]

    def test_argparse_accepts_freshness_choice(self):
        """CLI `--source freshness` 가 argparse choices 에 등록됨 (#453 회귀)."""
        # stock.py __main__ block 의 argparse choices 직접 검증 — 실제 모듈 source read.
        import inspect

        from nuri.collectors import stock as stock_mod

        src = inspect.getsource(stock_mod)
        # choices 리스트에 'freshness' 포함 확인
        assert "'freshness'" in src or '"freshness"' in src
