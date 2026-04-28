"""Per-collector tests for macro.

Split from tests/test_collectors_all.py for module-level isolation.
"""
from unittest.mock import MagicMock

import pandas as pd


class TestMacroCollector:
    def test_instantiate(self):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        assert c.name == "macro"

    def test_save_empty(self, db_path):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        assert c.save([]) == 0

    def test_save_records(self, db_path):
        from nuri.collectors.macro import MacroCollector

        c = MacroCollector()
        records = [
            {"indicator": "vix", "date": "2026-03-30", "value": 25.5, "source": "test"},
            {"indicator": "fear_greed", "date": "2026-03-30", "value": 45.0, "source": "test"},
        ]
        count = c.save(records)
        assert count == 2



class TestMacroCollectorFREDAndYFinance:
    def test_collect_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5, 4.3], index=pd.to_datetime(["2025-01-15", "2025-01-16"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_fred_key"
        results = collector._collect_fred(days=30)
        assert len(results) > 0

    def test_collect_fred_series_failure(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("FRED API error")
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "test_key"
        assert collector._collect_fred(days=30) == []

    def test_collect_yfinance_fallback(self, monkeypatch, db_with_portfolio):
        import yfinance as yf

        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({
            "Date": pd.to_datetime(["2025-01-15"]),
            "Close": [4.5], "Open": [4.4], "High": [4.6], "Low": [4.3], "Volume": [0],
        })
        monkeypatch.setattr(yf, "download", lambda *a, **kw: mock_df)
        collector = MacroCollector()
        collector.api_key = ""
        assert len(collector._collect_yfinance(days=30)) > 0

    def test_collect_yfinance_empty_df(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_yfinance_exception(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_obb = MagicMock()
        mock_obb.equity.price.historical.side_effect = Exception("connection error")
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        assert MacroCollector()._collect_yfinance(days=30) == []

    def test_collect_prefers_fred(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_series = pd.Series([4.5], index=pd.to_datetime(["2025-01-15"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)
        assert all(r["source"] == "FRED" for r in results)

    def test_collect_nan_value_skipped(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15", "2025-01-16"]), "close": [float("nan"), 4.3]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        results = MacroCollector()._collect_yfinance(days=30)
        for r in results:
            assert not pd.isna(r["value"])

    def test_save(self, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        assert MacroCollector().save([{"indicator": "vix", "date": "2025-01-30", "value": 18.5, "source": "test"}]) == 1



class TestMacroCollectorEdgeCases:
    def test_collect_uses_yfinance_when_no_fred_key(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        import sys

        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = ""
        assert isinstance(collector.collect(days=30), list)

    def test_collect_fred_returns_empty_falls_to_yfinance(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.macro import MacroCollector

        mock_fred = MagicMock()
        mock_fred.get_series.return_value = pd.Series(dtype=float)
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        mock_df = pd.DataFrame({"date": pd.to_datetime(["2025-01-15"]), "close": [4.5]})
        mock_result = MagicMock()
        mock_result.to_df.return_value = mock_df
        mock_obb = MagicMock()
        mock_obb.equity.price.historical.return_value = mock_result
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(obb=mock_obb))
        collector = MacroCollector()
        collector.api_key = "real_key"
        assert isinstance(collector.collect(days=30), list)


class TestPartAIndicatorRegistry:
    """Issue #362 Part A — 10 신규 yfinance 지표 등록 lock-in."""

    def test_part_a_indicators_present_in_registry(self):
        """YFINANCE_SYMBOLS 에 #362 Part A 10개 indicator key 가 모두 존재."""
        from nuri.collectors.macro import YFINANCE_SYMBOLS

        expected = {
            "nasdaq_composite", "sp500", "dow", "nasdaq100_futures", "sox",
            "dxy", "silver", "natgas", "copper", "wheat",
        }
        missing = expected - set(YFINANCE_SYMBOLS.keys())
        assert not missing, (
            f"#362 Part A indicator key 누락: {missing}. 한 줄이라도 빠지면 "
            f"daily macro collect 가 그 지표를 silently 스킵."
        )

    def test_part_a_symbols_match_2026_04_28_live_probe(self):
        """2026-04-28 live probe 결과와 등록 symbol 일치 — DXY 는 DX-Y.NYB (DX=F empty)."""
        from nuri.collectors.macro import YFINANCE_SYMBOLS

        expected_mapping = {
            "nasdaq_composite": "^IXIC",
            "sp500": "^GSPC",
            "dow": "^DJI",
            "nasdaq100_futures": "NQ=F",
            "sox": "^SOX",
            "dxy": "DX-Y.NYB",  # NOT DX=F (issue body 의 'DX=F' 는 yfinance empty — live probe)
            "silver": "SI=F",
            "natgas": "NG=F",
            "copper": "HG=F",
            "wheat": "ZW=F",
        }
        for key, expected_sym in expected_mapping.items():
            actual = YFINANCE_SYMBOLS.get(key)
            assert actual == expected_sym, (
                f"{key}: expected {expected_sym!r}, got {actual!r}. "
                f"DXY 가 DX=F 로 되돌아가면 yfinance empty → DB 영구 누락 (live probe 2026-04-28)."
            )

    def test_part_a_does_not_displace_existing_indicators(self):
        """기존 vix/gold/wti_oil/us_*_yield/usd_krw 가 그대로 남아있음 — 회귀 방지."""
        from nuri.collectors.macro import YFINANCE_SYMBOLS

        legacy = {"us_10y_yield", "us_2y_yield", "us_5y_yield", "us_30y_yield",
                  "vix", "wti_oil", "usd_krw", "gold"}
        missing = legacy - set(YFINANCE_SYMBOLS.keys())
        assert not missing, f"기존 지표 회귀 — {missing} 사라짐"
