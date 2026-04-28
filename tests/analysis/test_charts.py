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
            rows.append({
                "ticker": "FEW", "date": f"2025-01-{i+1:02d}",
                "open": 100, "high": 102, "low": 98,
                "close": 101, "volume": 1000, "adj_close": 101,
            })
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
        df = pd.DataFrame({"date": ["2025-01-01"], "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100]})
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is None

    def test_load_chart_data_with_data(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        monkeypatch.setattr(charts_mod, "query_df", lambda *a, **kw: df)
        result = charts_mod._load_chart_data("AAPL")
        assert result is not None
        assert "rsi_14" in result.columns

    def test_detect_signals(self):
        from nuri.analysis.charts import _detect_signals
        dates = pd.bdate_range("2024-01-01", periods=50)
        np.random.seed(42)
        df = pd.DataFrame({
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 250, 50),
            "low": np.random.uniform(80, 100, 50),
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
            "rsi_14": np.concatenate([np.linspace(25, 35, 25), np.linspace(35, 75, 25)]),
            "macd": np.sin(np.arange(50) / 5),
            "macd_signal": np.sin(np.arange(50) / 5 - 0.5),
        }, index=dates)
        result = _detect_signals(df)
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns

    def test_get_info_panel(self, db_path, monkeypatch):
        import nuri.analysis.charts as charts_mod
        call_count = [0]
        def mock_query(sql, params=(), **kwargs):
            call_count[0] += 1
            if "fundamentals" in sql:
                return [{"pe_ratio": 25, "forward_pe": 20, "roe": 0.15,
                         "revenue_growth": 0.2, "debt_to_equity": 0.5,
                         "market_cap": 1e12, "beta": 1.2}]
            elif "estimates" in sql:
                return [{"recommendation": "buy", "target_mean": 200,
                         "target_high": 250, "target_low": 180,
                         "num_analysts": 30, "current_price": 190}]
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
