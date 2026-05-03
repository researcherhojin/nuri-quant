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
