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

        mock_df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2025-01-15"]),
                "Close": [4.5],
                "Open": [4.4],
                "High": [4.6],
                "Low": [4.3],
                "Volume": [0],
            }
        )
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
        """FRED 가 cover 하는 indicator 는 source='FRED' (yfinance dup 제외) — #362 merge 후."""
        from nuri.collectors.macro import FRED_SERIES, MacroCollector

        mock_series = pd.Series([4.5], index=pd.to_datetime(["2025-01-15"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        import sys

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        # yfinance 분기 차단 — _collect_yfinance 에서 yfinance.download mock 안 하면
        # 실제 네트워크 호출 됨. conftest.py 의 yfinance.download stub (빈 df) 활용.
        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)
        # FRED 가 cover 하는 indicator 들은 모두 source='FRED'
        fred_keys = set(FRED_SERIES.keys())
        for r in results:
            if r["indicator"] in fred_keys:
                assert r["source"] == "FRED", (
                    f"{r['indicator']} 는 FRED 에 정의됨 → source='FRED' 여야 함 (yfinance dup 제거 실패)"
                )

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


class TestMacroCollectorTossFX:
    """Toss 라이브 USD/KRW → macro usd_krw 배선 (#805 후속).

    Toss `get_exchange_rate` 는 1분 단위 라이브 환율을 주지만 IP allowlist 라
    dev/CI 에선 인증/IP 실패 → graceful skip. production(Mac mini) 에서만 채워짐.
    """

    def test_collect_toss_fx_returns_usd_krw_record(self, monkeypatch):
        from nuri.collectors.macro import MacroCollector
        from nuri.core.timezone import today_kst

        monkeypatch.setattr(
            "nuri.collectors.toss.get_exchange_rate",
            lambda base="USD", quote="KRW": {"rate": 1540.86, "validFrom": "2026-06-24"},
        )
        records = MacroCollector()._collect_toss_fx()
        assert records == [{"indicator": "usd_krw", "date": today_kst(), "value": 1540.86, "source": "toss"}]

    def test_collect_toss_fx_uses_midrate_when_rate_missing(self, monkeypatch):
        from nuri.collectors.macro import MacroCollector

        monkeypatch.setattr(
            "nuri.collectors.toss.get_exchange_rate",
            lambda base="USD", quote="KRW": {"midRate": 1535.0},
        )
        records = MacroCollector()._collect_toss_fx()
        assert records[0]["value"] == 1535.0

    def test_collect_toss_fx_graceful_on_creds_error(self, monkeypatch):
        """creds/IP 미설정(dev/CI) → [] 반환, 예외 전파 안 함."""
        from nuri.collectors.macro import MacroCollector
        from nuri.collectors.toss import TossCredentialsError

        def _raise(base="USD", quote="KRW"):
            raise TossCredentialsError("IP address not allowed")

        monkeypatch.setattr("nuri.collectors.toss.get_exchange_rate", _raise)
        assert MacroCollector()._collect_toss_fx() == []

    def test_collect_toss_fx_graceful_on_generic_error(self, monkeypatch):
        from nuri.collectors.macro import MacroCollector

        def _raise(base="USD", quote="KRW"):
            raise RuntimeError("network down")

        monkeypatch.setattr("nuri.collectors.toss.get_exchange_rate", _raise)
        assert MacroCollector()._collect_toss_fx() == []

    def test_collect_toss_fx_skips_when_no_rate(self, monkeypatch):
        """rate/midRate 모두 없거나 0 → []."""
        from nuri.collectors.macro import MacroCollector

        monkeypatch.setattr("nuri.collectors.toss.get_exchange_rate", lambda base="USD", quote="KRW": {})
        assert MacroCollector()._collect_toss_fx() == []

    def test_collect_appends_toss_fx_overriding_usd_krw(self, monkeypatch, db_with_portfolio):
        """collect() 가 toss usd_krw 를 마지막에 붙여 upsert 시 오늘자 환율을 override."""
        import sys

        import pandas as pd

        from nuri.collectors.macro import MacroCollector
        from nuri.core.timezone import today_kst

        # FRED stub — usd_krw 를 옛 값(어제)으로 채움
        mock_series = pd.Series([1500.0], index=pd.to_datetime(["2026-06-23"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series
        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))
        monkeypatch.setattr(MacroCollector, "_collect_yfinance", lambda self, days: [])
        monkeypatch.setattr(
            "nuri.collectors.toss.get_exchange_rate",
            lambda base="USD", quote="KRW": {"rate": 1540.86},
        )

        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)

        toss_rows = [r for r in results if r["indicator"] == "usd_krw" and r["source"] == "toss"]
        assert toss_rows == [{"indicator": "usd_krw", "date": today_kst(), "value": 1540.86, "source": "toss"}]
        # toss 레코드가 마지막 (upsert OR REPLACE 가 오늘자 usd_krw 를 toss 로 확정)
        assert results[-1] == toss_rows[0]


class TestPartAIndicatorRegistry:
    """Issue #362 Part A — 10 신규 yfinance 지표 등록 lock-in."""

    def test_part_a_indicators_present_in_registry(self):
        """YFINANCE_SYMBOLS 에 #362 Part A 10개 indicator key 가 모두 존재."""
        from nuri.collectors.macro import YFINANCE_SYMBOLS

        expected = {
            "nasdaq_composite",
            "sp500",
            "dow",
            "nasdaq100_futures",
            "sox",
            "dxy",
            "silver",
            "natgas",
            "copper",
            "wheat",
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

        legacy = {"us_10y_yield", "us_2y_yield", "us_5y_yield", "us_30y_yield", "vix", "wti_oil", "usd_krw", "gold"}
        missing = legacy - set(YFINANCE_SYMBOLS.keys())
        assert not missing, f"기존 지표 회귀 — {missing} 사라짐"

    def test_collect_merges_yf_supplement_when_fred_set(self, monkeypatch, db_with_portfolio):
        """FRED_API_KEY 설정 시 — yfinance-only indicator (#362 Part A) 가 보충 수집됨.

        Codex Review #362 P1: FRED 가 일부 indicator 만 cover 하는데 collect() 가
        FRED 결과 있으면 즉시 return → yfinance-only 영구 미수집.

        Fix: collect() 가 두 source 모두 호출 + indicator dedupe (FRED 우선).
        Lock-in: 이 test 가 fail 하면 P1 회귀.
        """
        import sys

        import pandas as pd

        from nuri.collectors.macro import MacroCollector

        # FRED stub — vix 만 응답 (cover 일부)
        mock_series = pd.Series([18.5], index=pd.to_datetime(["2025-01-15"]))
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = mock_series

        monkeypatch.setitem(sys.modules, "fredapi", MagicMock(Fred=MagicMock(return_value=mock_fred)))

        # yfinance stub — _collect_yfinance 가 호출되면 fake 새 indicator 반환
        # (실제 yfinance.download 는 conftest mock 으로 빈 df → records=[] 반환됨)
        # 따라서 _collect_yfinance 자체를 monkeypatch.
        def stub_yf(self, days):
            return [
                {"indicator": "vix", "date": "2025-01-15", "value": 19.0, "source": "yfinance"},  # FRED dup
                {"indicator": "sp500", "date": "2025-01-15", "value": 7000.0, "source": "yfinance"},  # yf-only
                {"indicator": "dxy", "date": "2025-01-15", "value": 98.5, "source": "yfinance"},  # yf-only
            ]

        monkeypatch.setattr(MacroCollector, "_collect_yfinance", stub_yf)

        collector = MacroCollector()
        collector.api_key = "real_key"
        results = collector.collect(days=30)

        indicators = {r["indicator"]: r["source"] for r in results}
        # FRED-covered indicator (vix) 는 FRED 우선 (yfinance dup 제외)
        # vix 는 fred_records 도 있고 yf 도 있는데, FRED 우선이라 source='FRED' 여야 함
        # FRED_SERIES 에 vix 가 있어 _collect_fred 가 vix records 생성
        assert "sp500" in indicators, "yfinance-only indicator 보충 안 됨 — P1 회귀"
        assert "dxy" in indicators, "yfinance-only indicator 보충 안 됨 — P1 회귀"
        assert indicators["sp500"] == "yfinance"
        assert indicators["dxy"] == "yfinance"
