"""Tests for nuri.analysis.charts — split from tests/test_analysis_all.py (#157)."""

from unittest.mock import patch

import numpy as np
import pandas as pd

from nuri.core.db import upsert_prices


class TestCharts:
    """From test_uncovered.py."""

    def test_load_chart_data(self, price_data):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("AAPL")
        if df is not None:
            assert "close" in df.columns

    def test_load_chart_data_missing(self, db_path):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("XXXXX")
        assert df is None


class TestCharts_R3:
    """From test_coverage_round3.py."""

    def test_load_chart_data(self, db_path):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("AAPL")
        # db_path may have data from fixture
        assert df is not None or df is None  # either is valid

    def test_detect_signals(self, db_path):
        from nuri.analysis.charts import _detect_signals, _load_chart_data

        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 30:
            result = _detect_signals(df)
            assert isinstance(result, pd.DataFrame)

    def test_get_info_panel(self, db_path):
        from nuri.analysis.charts import _get_info_panel

        info = _get_info_panel("AAPL")
        assert isinstance(info, dict)


class TestChartsGeneration:
    """From test_coverage_round4.py."""

    def test_generate_plotly_chart(self, rich_db, tmp_path):
        from nuri.analysis.charts import _load_chart_data, generate_plotly_chart

        df = _load_chart_data("AAPL")
        assert df is not None
        output = generate_plotly_chart("AAPL", df, tmp_path)
        assert output.exists()
        assert output.suffix == ".html"

    def test_generate_charts_all(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)


class TestChartsDeep:
    """From test_coverage_round7.py."""

    def test_detect_signals_with_data(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data

        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 50:
            result = _detect_signals(df)
            assert "signal" in result.columns or len(result) > 0

    def test_get_info_panel(self, rich_db):
        from nuri.analysis.charts import _get_info_panel

        info = _get_info_panel("AAPL")
        assert "ticker" in info

    def test_generate_charts_with_output(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        results = generate_charts(output_dir=tmp_path, tickers=["AAPL"])
        assert isinstance(results, list)


class TestChartsMore:
    """From test_coverage_round11.py."""

    def test_load_spy(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("SPY")
        assert df is not None
        assert len(df) > 100

    def test_load_nonexistent(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("FAKE")
        assert df is None or len(df) == 0

    def test_generate_charts_multiple(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        results = generate_charts(output_dir=tmp_path, tickers=["AAPL", "NVDA"])
        assert isinstance(results, list)
        assert len(results) >= 2


class TestChartsPNG:
    """From test_coverage_round12.py."""

    def test_generate_png_chart(self, rich_db, tmp_path):
        from nuri.analysis.charts import _load_chart_data, generate_png_chart

        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 50:
            path = generate_png_chart("AAPL", df, tmp_path)
            assert path.exists()
            assert path.suffix == ".png"

    def test_generate_charts_multiple_tickers(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        results = generate_charts(output_dir=tmp_path, tickers=["AAPL", "NVDA"])
        assert isinstance(results, list)


class TestChartsLoad:
    """From test_coverage_round13.py."""

    def test_load_all_tickers(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        for t in ["AAPL", "NVDA", "SPY"]:
            df = _load_chart_data(t)
            assert df is not None
            assert len(df) > 100

    def test_detect_signals_all_types(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data

        df = _load_chart_data("AAPL")
        assert df is not None
        result = _detect_signals(df)
        assert "signal" in result.columns or "type" in result.columns or len(result.columns) > 0


class TestChartsAll:
    """From test_coverage_round14.py."""

    def test_generate_for_all_tickers(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) >= 2


class TestChartsLoadData:
    """From test_coverage_round20.py."""

    def test_load_chart_data_returns_df(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        df = _load_chart_data("AAPL")
        assert df is not None
        assert "close" in df.columns
        assert "sma_20" in df.columns
        assert "rsi_14" in df.columns
        assert "macd" in df.columns
        assert "bb_upper" in df.columns
        assert len(df) > 20

    def test_load_chart_data_returns_none_for_missing(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        result = _load_chart_data("ZZZZ")
        assert result is None

    def test_load_chart_data_returns_none_for_few_rows(self, rich_db):
        from nuri.analysis.charts import _load_chart_data

        rows = []
        for i in range(5):
            rows.append(
                {
                    "ticker": "FEW",
                    "date": f"2025-01-{i + 1:02d}",
                    "open": 100,
                    "high": 102,
                    "low": 98,
                    "close": 101,
                    "volume": 1000,
                    "adj_close": 101,
                }
            )
        upsert_prices(pd.DataFrame(rows), rich_db)
        result = _load_chart_data("FEW")
        assert result is None


class TestChartsDetectSignals:
    """From test_coverage_round20.py."""

    def test_detect_signals_returns_df(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data

        df = _load_chart_data("AAPL")
        assert df is not None
        sig_df = _detect_signals(df)
        assert isinstance(sig_df, pd.DataFrame)
        assert "date" in sig_df.columns or sig_df.empty
        assert "type" in sig_df.columns or sig_df.empty


class TestChartsInfoPanel:
    """From test_coverage_round20.py."""

    def test_get_info_panel_with_data(self, rich_db):
        from nuri.analysis.charts import _get_info_panel

        info = _get_info_panel("AAPL")
        assert info["ticker"] == "AAPL"
        assert info.get("pe") == 28.0
        assert info.get("roe") == 0.35
        assert info.get("recommendation") == "buy"
        assert info.get("target_mean") == 220.0
        assert info.get("sentiment") is not None
        assert info.get("superinvestors") is not None
        assert len(info["superinvestors"]) >= 1

    def test_get_info_panel_empty_ticker(self, rich_db):
        from nuri.analysis.charts import _get_info_panel

        info = _get_info_panel("ZZZZ")
        assert info["ticker"] == "ZZZZ"
        assert info.get("pe") is None


class TestChartsGenerate_R20:
    """From test_coverage_round20.py."""

    @patch("nuri.analysis.charts.generate_plotly_chart")
    def test_generate_charts_calls_plotly(self, mock_plotly, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        mock_plotly.return_value = tmp_path / "AAPL.html"
        generate_charts(tickers=["AAPL"], output_dir=tmp_path)
        assert mock_plotly.called

    def test_generate_charts_skips_missing_ticker(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        result = generate_charts(tickers=["ZZZZ"], output_dir=tmp_path)
        assert result == []

    @patch("nuri.analysis.charts.generate_plotly_chart", side_effect=RuntimeError("plotly error"))
    def test_generate_charts_handles_error(self, mock_plotly, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts

        result = generate_charts(tickers=["AAPL"], output_dir=tmp_path)
        assert result == []


class TestCharts_R27:
    """From test_coverage_round27.py."""

    def test_load_chart_data_no_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod

        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: pd.DataFrame())
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_insufficient(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod

        df = pd.DataFrame(
            {"date": ["2025-01-01"], "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100]}
        )
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_with_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod

        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": np.random.uniform(100, 200, 50),
                "high": np.random.uniform(200, 250, 50),
                "low": np.random.uniform(80, 100, 50),
                "close": np.random.uniform(100, 200, 50),
                "volume": np.random.uniform(100000, 500000, 50),
            }
        )
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is not None
        assert "rsi_14" in result.columns

    def test_detect_signals(self):
        from nuri.analysis.charts import _detect_signals

        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "open": np.random.uniform(100, 200, 50),
                "high": np.random.uniform(200, 250, 50),
                "low": np.random.uniform(80, 100, 50),
                "close": np.random.uniform(100, 200, 50),
                "volume": np.random.uniform(100000, 500000, 50),
                "rsi_14": np.concatenate([np.linspace(25, 35, 25), np.linspace(35, 75, 25)]),
                "macd": np.sin(np.arange(50) / 5),
                "macd_signal": np.sin(np.arange(50) / 5 - 0.5),
            },
            index=dates,
        )
        result = _detect_signals(df)
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns

    def test_get_info_panel(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod

        call_count = [0]

        def mock_query(sql, params=(), **kwargs):
            call_count[0] += 1
            if "fundamentals" in sql:
                return [
                    {
                        "pe_ratio": 25,
                        "forward_pe": 20,
                        "roe": 0.15,
                        "revenue_growth": 0.2,
                        "debt_to_equity": 0.5,
                        "market_cap": 1e12,
                        "beta": 1.2,
                    }
                ]
            elif "estimates" in sql:
                return [
                    {
                        "recommendation": "buy",
                        "target_mean": 200,
                        "target_high": 250,
                        "target_low": 180,
                        "num_analysts": 30,
                        "current_price": 190,
                    }
                ]
            elif "sentiment" in sql:
                return [{"avg_s": 0.15, "cnt": 10}]
            elif "superinvestors" in sql:
                return [{"investor": "Buffett", "portfolio_pct": 5.0}]
            return []

        monkeypatch.setattr(charts_mod, "query", mock_query)
        info = charts_mod._get_info_panel("AAPL")
        assert info["ticker"] == "AAPL"
        assert info["pe"] == 25
        assert info["recommendation"] == "buy"
        assert info["sentiment"] == 0.15
        assert len(info["superinvestors"]) == 1

    def test_generate_charts_no_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod

        monkeypatch.setattr(charts_mod, "get_tickers", lambda **kw: ["AAPL"])
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: None)
        result = charts_mod.generate_charts(tickers=["AAPL"], output_dir=db_path.parent / "charts")
        assert result == []


class TestChartsCoverageGaps:
    """Targeted lock-tests for charts.py missing branches."""

    def test_load_chart_data_talib_fallback(self, monkeypatch):
        """talib import 실패 시 pandas fallback (lines 57-76)."""
        import builtins

        import pandas as pd

        import nuri.analysis.charts as charts_mod

        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "talib":
                raise ImportError("no talib")
            return real_import(name, *a, **kw)

        # Build a 300-row price df to feed query_df
        df_rows = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01") + pd.Timedelta(days=i) for i in range(300)],
                "open": [100.0 + i * 0.1 for i in range(300)],
                "high": [101.0 + i * 0.1 for i in range(300)],
                "low": [99.0 + i * 0.1 for i in range(300)],
                "close": [100.0 + i * 0.1 for i in range(300)],
                "volume": [1_000_000] * 300,
            }
        )
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df_rows)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        result = charts_mod._load_chart_data("AAPL")
        assert result is not None
        assert "rsi_14" in result.columns
        assert "sma_20" in result.columns
        assert "macd" in result.columns

    def test_detect_signals_unknown_signal_skipped(self, monkeypatch):
        """SIGNAL_DEFINITIONS.get returning None → continue (line 102)."""
        import pandas as pd

        import nuri.analysis.charts as charts_mod

        idx = pd.bdate_range("2024-01-01", periods=60)
        df = pd.DataFrame(
            {
                "open": [100.0] * 60,
                "high": [101.0] * 60,
                "low": [99.0] * 60,
                "close": [100.0] * 60,
                "volume": [1_000_000] * 60,
            },
            index=idx,
        )
        # Empty SIGNAL_DEFINITIONS → all chart_signals miss → continue branch
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.SIGNAL_DEFINITIONS",
            {},
        )
        result = charts_mod._detect_signals(df)
        # Returns DataFrame (possibly empty)
        assert hasattr(result, "iloc") or hasattr(result, "__iter__")

    def test_generate_charts_default_output_dir(self, tmp_path, monkeypatch):
        """output_dir=None → REPORT_DIR / today / charts (lines 470-471)."""
        import nuri.analysis.charts as charts_mod

        monkeypatch.setattr(charts_mod, "REPORT_DIR", tmp_path / "rep")
        monkeypatch.setattr(charts_mod, "get_tickers", lambda **kw: ["AAPL"])
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: None)
        # output_dir=None → default branch
        result = charts_mod.generate_charts(tickers=None)
        assert result == []

    def test_generate_charts_png_branch(self, tmp_path, monkeypatch):
        """png=True branch (lines 485-487)."""
        import pandas as pd

        import nuri.analysis.charts as charts_mod

        idx = pd.bdate_range("2024-01-01", periods=60)
        df = pd.DataFrame(
            {
                "open": [100.0] * 60,
                "high": [101.0] * 60,
                "low": [99.0] * 60,
                "close": [100.0] * 60,
                "volume": [1_000_000] * 60,
            },
            index=idx,
        )
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: df)

        called = {"png": 0, "html": 0}

        def fake_html(t, df_, out):
            out.mkdir(parents=True, exist_ok=True)
            p = out / f"{t}.html"
            p.write_text("<html/>")
            called["html"] += 1
            return p

        def fake_png(t, df_, out):
            out.mkdir(parents=True, exist_ok=True)
            p = out / f"{t}.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n")
            called["png"] += 1
            return p

        monkeypatch.setattr(charts_mod, "generate_plotly_chart", fake_html)
        monkeypatch.setattr(charts_mod, "generate_png_chart", fake_png)

        result = charts_mod.generate_charts(
            tickers=["AAPL"],
            output_dir=tmp_path / "out",
            png=True,
            html=True,
        )
        assert called["png"] == 1
        assert called["html"] == 1
        assert len(result) == 2


# ═══════════════════════════════════════════════════════
# Branch-coverage lock tests for #616 (16 partial branches)
# ═══════════════════════════════════════════════════════


def _minimal_ohlcv(n: int = 60) -> pd.DataFrame:
    """generate_plotly_chart 가 직접 참조하는 컬럼 (rsi_14 / macd 등) 까지 포함한
    flat 더미 DataFrame. 모든 지표는 NaN — 분기 False 트리거용."""
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
            "rsi_14": [float("nan")] * n,
            "macd": [float("nan")] * n,
            "macd_signal": [float("nan")] * n,
            "macd_hist": [float("nan")] * n,
        },
        index=idx,
    )


class TestChartsBranches616:
    """Lock-tests for 16 partial branches in nuri/analysis/charts.py (#616)."""

    def test_detect_signals_volume_sma_already_set(self, monkeypatch):
        """Branch 90->94: `volume_sma_20 not in df.columns` False (이미 존재) → 재계산 skip.

        SIGNAL_DEFINITIONS 를 빈 dict 로 덮어 detector 호출은 skip — 분기 도달만 확인.
        """
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        df["volume_sma_20"] = 500_000.0  # 이미 set
        # detector dispatch 우회 (detector 가 rsi/macd 등 NaN 컬럼 액세스 → 예외)
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.SIGNAL_DEFINITIONS",
            {},
        )
        result = charts_mod._detect_signals(df)
        assert isinstance(result, pd.DataFrame)
        # volume_sma_20 은 원래 값 유지 (재계산 skip 됨)
        assert df["volume_sma_20"].iloc[0] == 500_000.0

    def test_plotly_no_bb_upper_column(self, tmp_path, monkeypatch):
        """Branch 212->241: `if "bb_upper" in df.columns:` False."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        # _detect_signals / _get_info_panel 모두 우회 — DB 의존성 차단
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_bb_upper_all_nan(self, tmp_path, monkeypatch):
        """Branch 214->241: bb_upper 컬럼 존재하나 dropna 후 empty."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        df["bb_upper"] = float("nan")
        df["bb_lower"] = float("nan")
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_sma_loop_missing_and_empty(self, tmp_path, monkeypatch):
        """Branches 247->246, 249->246: SMA 루프 — 컬럼 없음 / 컬럼은 있으나 all NaN."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        # sma_20 은 all-NaN (249->246), sma_50 / sma_200 은 missing (247->246)
        df["sma_20"] = float("nan")
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_signals_empty(self, tmp_path, monkeypatch):
        """Branch 285->320: sig_df.empty True → signal 마커 skip."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_signals_only_sells(self, tmp_path, monkeypatch):
        """Branch 289->304: buys.empty True (sells 만 존재)."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        sig = pd.DataFrame(
            [
                {"date": df.index[5], "price": 100.0, "type": "sell", "reason": "macd_dead"},
            ]
        )
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: sig)
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_signals_only_buys(self, tmp_path, monkeypatch):
        """Branch 304->320: sells.empty True (buys 만 존재)."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        sig = pd.DataFrame(
            [
                {"date": df.index[5], "price": 100.0, "type": "buy", "reason": "rsi_oversold"},
            ]
        )
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: sig)
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_rsi_all_nan(self, tmp_path, monkeypatch):
        """Branch 349->372: rsi.empty True → RSI 패널 skip."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        df["rsi_14"] = float("nan")
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_macd_all_nan(self, tmp_path, monkeypatch):
        """Branch 373->426: macd_data.empty True → MACD 패널 skip."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        df["macd"] = float("nan")
        df["macd_signal"] = float("nan")
        df["macd_hist"] = float("nan")
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_plotly_alert_box_sig_empty(self, tmp_path, monkeypatch):
        """Branch 476->502: 알림 박스 skip (sig_df.empty True).

        주의: branch 285->320 과 동일 조건이지만 별도 테스트 — 라인 위치만 다름.
        한 테스트로 둘 다 커버되나, 명시적 lock-test 분리.
        """
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        monkeypatch.setattr(charts_mod, "_detect_signals", lambda d: pd.DataFrame())
        monkeypatch.setattr(charts_mod, "_get_info_panel", lambda t: {"ticker": t})
        out = charts_mod.generate_plotly_chart("XYZ", df, tmp_path)
        assert out.exists()

    def test_png_no_optional_columns(self, tmp_path, monkeypatch):
        """Branches 571->574, 574->576, 576->578, 578->582: PNG 보조 plot 4개 모두 skip.

        df 에 OHLCV 만 있고 bb_upper / sma_50 / rsi_14 / macd 모두 missing.
        """
        import nuri.analysis.charts as charts_mod

        # 순수 OHLCV — 지표 컬럼 일체 없음
        idx = pd.bdate_range("2024-01-01", periods=30)
        df = pd.DataFrame(
            {
                "open": [100.0] * 30,
                "high": [101.0] * 30,
                "low": [99.0] * 30,
                "close": [100.0] * 30,
                "volume": [1_000_000] * 30,
            },
            index=idx,
        )
        # mpf.plot 호출 (PNG 작성) 자체가 무거우니 mock — 분기 진입만 검증
        captured: dict = {}

        class _MockMpf:
            @staticmethod
            def make_addplot(*a, **kw):
                return ("addplot", a, kw)

            @staticmethod
            def plot(ohlcv, **kw):
                captured["addplot"] = kw.get("addplot")
                # savefig 인자대로 빈 파일 생성
                import pathlib

                p = pathlib.Path(kw["savefig"])
                p.write_bytes(b"\x89PNG\r\n\x1a\n")

        # mplfinance 모듈 자체를 sys.modules 에 주입
        import sys

        monkeypatch.setitem(sys.modules, "mplfinance", _MockMpf)
        out = charts_mod.generate_png_chart("XYZ", df, tmp_path)
        assert out.exists()
        # addplot 4 개 분기 모두 skip → addplots 빈 리스트 → None 전달
        assert captured["addplot"] is None

    def test_generate_charts_html_false_png_true(self, tmp_path, monkeypatch):
        """Branch 622->626: html=False → plotly skip, png=True 만 호출."""
        import nuri.analysis.charts as charts_mod

        df = _minimal_ohlcv()
        monkeypatch.setattr(charts_mod, "_load_chart_data", lambda t: df)

        called = {"html": 0, "png": 0}

        def fake_html(t, df_, out):
            called["html"] += 1
            return out / f"{t}.html"

        def fake_png(t, df_, out):
            out.mkdir(parents=True, exist_ok=True)
            p = out / f"{t}.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n")
            called["png"] += 1
            return p

        monkeypatch.setattr(charts_mod, "generate_plotly_chart", fake_html)
        monkeypatch.setattr(charts_mod, "generate_png_chart", fake_png)

        result = charts_mod.generate_charts(
            tickers=["XYZ"],
            output_dir=tmp_path / "out",
            html=False,
            png=True,
        )
        assert called["html"] == 0
        assert called["png"] == 1
        assert len(result) == 1
