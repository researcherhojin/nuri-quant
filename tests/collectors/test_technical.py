"""Per-collector tests for technical.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import patch

import pandas as pd
import pytest


class TestTechnicalCollector:
    def test_compute_talib(self):
        import numpy as np

        from nuri.collectors.technical import TechnicalCollector

        close = np.array([100 + i * 0.5 + np.sin(i) for i in range(50)], dtype=float)
        result = TechnicalCollector._compute_talib(close)
        assert "rsi_14" in result
        assert "macd" in result
        assert len(result["rsi_14"]) == 50


class TestCollectUniverseMode:
    """#272 Phase 2b: source 파라미터 + tqdm + summary 패치 커버리지."""

    def test_collect_no_tickers(self, monkeypatch):
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [])
        result = c.collect()
        assert result.empty

    def test_collect_universe_source_passed(self, monkeypatch):
        """source 파라미터가 _get_tickers로 전달되는지."""
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        captured = {}

        def fake_get(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr(c, "_get_tickers", fake_get)
        c.collect(source="universe")
        assert captured.get("source") == "universe"

    def test_collect_summary_logged_for_large_set(self, monkeypatch, caplog):
        """20+ tickers 시 summary log fire 확인."""
        import logging

        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        # 25개 ticker — 모두 데이터 부족 (None 반환)
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: [f"T{i}" for i in range(25)])
        monkeypatch.setattr(c, "_compute_for_ticker", lambda t: None)

        with caplog.at_level(logging.INFO):
            c.collect(source="universe")

        # summary log가 떴는지
        summary_logs = [r for r in caplog.records if "기술적 지표:" in r.message]
        assert len(summary_logs) >= 1, "Expected summary log for 25 tickers"

    def test_collect_no_summary_for_small_set(self, monkeypatch, caplog):
        """20 미만 tickers 시 summary 미출력 (조용함)."""
        import logging

        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["A", "B"])
        monkeypatch.setattr(c, "_compute_for_ticker", lambda t: None)

        with caplog.at_level(logging.INFO):
            c.collect()

        summary_logs = [r for r in caplog.records if "기술적 지표:" in r.message]
        assert len(summary_logs) == 0, "Should NOT log summary for <20 tickers"

    def test_collect_aggregates_results(self, monkeypatch):
        """결과 frame이 합쳐지는지."""
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["A", "B"])

        def fake_compute(ticker):
            return pd.DataFrame({"ticker": [ticker], "rsi_14": [50.0]})

        monkeypatch.setattr(c, "_compute_for_ticker", fake_compute)
        result = c.collect()
        assert len(result) == 2
        assert set(result["ticker"]) == {"A", "B"}


# ##############################################################################
# Source: test_collectors_coverage.py
# ##############################################################################


class TestComputeForTicker:
    """_compute_for_ticker (lines 65-86) — DB 가격에서 지표 계산."""

    def test_insufficient_data(self, tmp_path, monkeypatch):
        """< 14 일 → None + warning."""
        from nuri.collectors.technical import TechnicalCollector
        from nuri.core.db import init_db, upsert_prices

        path = tmp_path / "test.db"
        init_db(path)
        # 5 일만 시드
        df = pd.DataFrame(
            {
                "ticker": ["AAA"] * 5,
                "date": [f"2024-01-0{i + 1}" for i in range(5)],
                "open": [100.0] * 5,
                "high": [101.0] * 5,
                "low": [99.0] * 5,
                "close": [100.0] * 5,
                "volume": [1000] * 5,
                "adj_close": [100.0] * 5,
            }
        )
        upsert_prices(df, path)

        # query_df 는 글로벌 DB 를 사용 → monkeypatch
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", path)

        c = TechnicalCollector()
        assert c._compute_for_ticker("AAA") is None

    def test_sufficient_data(self, tmp_path, monkeypatch):
        """30 일 → 정상 DataFrame 반환."""
        import numpy as np

        from nuri.collectors.technical import TechnicalCollector
        from nuri.core.db import init_db, upsert_prices

        path = tmp_path / "test.db"
        init_db(path)
        n = 50
        closes = [100.0 + i * 0.1 for i in range(n)]
        df = pd.DataFrame(
            {
                "ticker": ["AAA"] * n,
                "date": [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)],
                "open": closes,
                "high": [c + 1 for c in closes],
                "low": [c - 1 for c in closes],
                "close": closes,
                "volume": [1000] * n,
                "adj_close": closes,
            }
        )
        upsert_prices(df, path)

        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", path)

        c = TechnicalCollector()
        result = c._compute_for_ticker("AAA")
        assert result is not None
        assert "rsi_14" in result.columns


class TestSaveEmpty:
    """save(empty) → 0 (line 112)."""

    def test_empty_returns_zero(self):
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        assert c.save(pd.DataFrame()) == 0

    def test_non_empty_calls_upsert(self, monkeypatch):
        """non-empty → upsert_signals 호출 (line 113)."""
        from nuri.collectors import technical as tech_mod

        called = {"n": 0}

        def stub_upsert(df):
            called["n"] += 1
            return len(df)

        monkeypatch.setattr(tech_mod, "upsert_signals", stub_upsert)
        c = tech_mod.TechnicalCollector()
        df = pd.DataFrame({"ticker": ["AAA"], "date": ["2024-01-01"], "rsi_14": [50.0]})
        result = c.save(df)
        assert result == 1
        assert called["n"] == 1


class TestTechnicalExpectedCountGuard:
    """MAX_FAILURE_RATE 가드 활성화 lock-test (PR #590 후속).

    Reason: 직전 audit 에서 _expected_count 가 25/26 collector 에 unset 인 상태로
    base.py 의 'asymmetric data age 방지' 가드가 dead code 였음을 확인. PR #590 이
    fundamental + estimates (list[dict] 반환) 활성화. technical 은 1 row/ticker 반환
    DataFrame 이라 len(df) == ticker count 매칭 가능 — 본 PR 에서 활성화.
    이 테스트가 회귀를 차단함.
    """

    def test_collect_sets_expected_count(self, monkeypatch):
        """collect() 진입 시 self._expected_count 가 len(tickers) 로 설정됨."""
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        # initial state — 0 (불활성)
        assert c._expected_count == 0

        monkeypatch.setattr(c, "_get_tickers", lambda **kw: ["AAA", "BBB", "CCC"])
        # _compute_for_ticker 결과는 가드 trigger 와 무관 (count 만 검증)
        monkeypatch.setattr(
            c,
            "_compute_for_ticker",
            lambda t: pd.DataFrame({"ticker": [t], "date": ["2024-01-01"], "rsi_14": [50.0]}),
        )

        c.collect()
        assert c._expected_count == 3, "collect() 가 ticker 수로 _expected_count 설정 안 함"

    def test_run_blocks_save_when_failure_rate_exceeds_threshold(self, monkeypatch):
        """run() 이 80% 실패 시 CollectionFailureError 발생 + save() 미호출."""
        from nuri.collectors.base import CollectionFailureError
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        # 10 ticker 중 2개만 성공 → failure_rate 80% > 10% threshold
        tickers = [f"T{i}" for i in range(10)]
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: tickers)

        def fake_compute(ticker):
            # T0/T1 만 valid row, 나머지 8개는 None (데이터 부족 시뮬레이션)
            if ticker in ("T0", "T1"):
                return pd.DataFrame({"ticker": [ticker], "date": ["2024-01-01"], "rsi_14": [50.0]})
            return None

        monkeypatch.setattr(c, "_compute_for_ticker", fake_compute)

        save_called = []
        monkeypatch.setattr(c, "save", lambda data: save_called.append(len(data)) or len(data))

        with pytest.raises(CollectionFailureError, match="실패율 80%"):
            c.run()

        assert save_called == [], "실패율 초과 시 save() 호출되면 안 됨 (asymmetric save 차단)"

    def test_run_allows_save_when_failure_rate_below_threshold(self, monkeypatch):
        """failure_rate 5% < 10% 면 save() 정상 호출."""
        from nuri.collectors.technical import TechnicalCollector

        c = TechnicalCollector()
        # 20 ticker 중 19개 성공 → failure_rate 5%
        tickers = [f"T{i}" for i in range(20)]
        monkeypatch.setattr(c, "_get_tickers", lambda **kw: tickers)

        def fake_compute(ticker):
            if ticker == "T0":
                return None  # 1개만 결손
            return pd.DataFrame({"ticker": [ticker], "date": ["2024-01-01"], "rsi_14": [50.0]})

        monkeypatch.setattr(c, "_compute_for_ticker", fake_compute)

        save_called = []
        monkeypatch.setattr(c, "save", lambda data: save_called.append(len(data)) or len(data))

        # 가드 통과 — retry 없이 첫 시도에서 save 호출
        result = c.run()
        assert result == 19, "save() 가 19 records 받아야 함"
        assert save_called == [19], "save() 1회 호출"
