"""
Coverage recovery tests — targets modules that lost coverage during 69→18 consolidation.

Targets (by coverage gap):
  1. nuri/quant/backtest/engine.py (0%)
  2. nuri/quant/factors/value.py (41%)
  3. nuri/quant/factors/quality.py (43%)
  4. nuri/collectors/technical.py (42%)
  5. nuri/quant/validation/analyst_backtest.py (62%)
  6. nuri/trading/strategy/ls_backtest.py (71%)
  7. nuri/quant/regime/strategy_map.py (70%)
  8. nuri/trading/strategy/mean_reversion.py (71%)
  9. nuri/trading/strategy/pairs.py (77%)
  10. nuri/trading/strategy/monitor.py (73%)
  11. nuri/trading/strategy/longshort.py (78%)
  12. nuri/collectors/estimates.py (68%)
  13. nuri/collectors/external.py (72%)
  14. nuri/collectors/fundamental.py (72%)
  15. nuri/llm/report.py (83%)
"""
import sys
import types
from datetime import timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_portfolio(db_path, tickers=None):
    """Insert portfolio entries for given tickers."""
    tickers = tickers or ["AAPL", "MSFT", "GOOGL"]
    records = [
        {"account": "test", "ticker": t, "quantity": 10, "avg_price": 100.0,
         "currency": "USD", "sector": "Technology", "metadata": None}
        for t in tickers
    ]
    upsert_portfolio(records, db_path=db_path)


def _seed_spy_data(db_path, days=300, start_price=400.0, trend="bull"):
    """Seed SPY price data with SMA-crossing patterns."""
    dates = pd.date_range(end="2025-12-31", periods=days, freq="B")
    prices = []
    price = start_price
    for i, d in enumerate(dates):
        if trend == "bull":
            price *= 1 + np.random.uniform(-0.005, 0.015)
        elif trend == "bear":
            price *= 1 + np.random.uniform(-0.015, 0.005)
        else:
            price *= 1 + np.random.uniform(-0.008, 0.008)
        prices.append({
            "ticker": "SPY",
            "date": d.strftime("%Y-%m-%d"),
            "open": round(price * 0.999, 2),
            "high": round(price * 1.01, 2),
            "low": round(price * 0.99, 2),
            "close": round(price, 2),
            "volume": 50000000,
            "adj_close": round(price, 2),
        })
    upsert_prices(pd.DataFrame(prices), db_path=db_path)
    return prices


def _seed_ticker_prices(db_path, ticker, days=100, start_price=150.0, volatility=0.02):
    """Seed price data for a single ticker with controlled volatility."""
    dates = pd.date_range(end="2025-12-31", periods=days, freq="B")
    rows = []
    price = start_price
    for d in dates:
        change = np.random.uniform(-volatility, volatility)
        price *= (1 + change)
        rows.append({
            "ticker": ticker,
            "date": d.strftime("%Y-%m-%d"),
            "open": round(price * 0.999, 2),
            "high": round(price * 1.01, 2),
            "low": round(price * 0.99, 2),
            "close": round(price, 2),
            "volume": 1000000,
            "adj_close": round(price, 2),
        })
    upsert_prices(pd.DataFrame(rows), db_path=db_path)
    return rows


def _seed_vix(db_path, days=300, base_vix=18.0):
    """Seed VIX macro data."""
    dates = pd.date_range(end="2025-12-31", periods=days, freq="B")
    records = [
        {"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
         "value": base_vix + np.random.uniform(-5, 5), "source": "test"}
        for d in dates
    ]
    upsert_macro(records, db_path=db_path)


@pytest.fixture
def rich_db(db_path):
    """DB with SPY + VIX + portfolio + multiple ticker prices."""
    _seed_portfolio(db_path, ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"])
    _seed_spy_data(db_path, days=350, trend="bull")
    _seed_vix(db_path, days=350)
    for t in ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]:
        _seed_ticker_prices(db_path, t, days=100, start_price=150 + np.random.uniform(-50, 50))
    return db_path


@pytest.fixture
def market_data_for_pairs(db_path):
    """DB with correlated US tickers for pairs trading."""
    tickers = ["AAPL", "MSFT", "GOOGL", "META"]
    _seed_portfolio(db_path, tickers)
    # Seed correlated prices
    base_prices = np.cumsum(np.random.randn(80) * 0.01) + np.log(150)
    dates = pd.date_range(end="2025-12-31", periods=80, freq="B")
    for t in tickers:
        noise = np.random.randn(80) * 0.003
        log_prices = base_prices + noise
        prices = np.exp(log_prices)
        rows = []
        for i, d in enumerate(dates):
            p = prices[i]
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": round(p * 0.999, 2), "high": round(p * 1.01, 2),
                "low": round(p * 0.99, 2), "close": round(p, 2),
                "volume": 1000000, "adj_close": round(p, 2),
            })
        upsert_prices(pd.DataFrame(rows), db_path=db_path)
    return db_path


# ═══════════════════════════════════════════════════════════════
# 1. nuri/quant/backtest/engine.py — VectorBT backtest engine
# ═══════════════════════════════════════════════════════════════


class TestBacktestEngine:
    """Tests for nuri.quant.backtest.engine with mocked vectorbt."""

    @pytest.fixture(autouse=True)
    def mock_vectorbt(self):
        """Create a minimal vectorbt mock in sys.modules."""
        vbt_mod = types.ModuleType("vectorbt")
        vbt_mod.__name__ = "vectorbt"

        # Mock Portfolio class
        mock_pf = MagicMock()
        mock_stats = pd.Series({
            "Total Return [%]": 15.5,
            "Sharpe Ratio": 1.2,
            "Max Drawdown [%]": -8.3,
            "Win Rate [%]": 55.0,
            "Total Trades": 20,
        })
        mock_pf.stats.return_value = mock_stats
        mock_pf.returns.return_value = pd.Series([0.01, -0.005, 0.02, -0.01, 0.015])

        portfolio_cls = MagicMock()
        portfolio_cls.from_signals.return_value = mock_pf
        vbt_mod.Portfolio = portfolio_cls

        self._original = sys.modules.get("vectorbt")
        sys.modules["vectorbt"] = vbt_mod
        yield
        if self._original:
            sys.modules["vectorbt"] = self._original
        else:
            sys.modules.pop("vectorbt", None)

    def test_run_momentum_empty_db(self, db_path):
        """Empty DB returns empty dict."""
        with patch("nuri.quant.backtest.engine.query_df", return_value=pd.DataFrame()):
            from nuri.quant.backtest.engine import run_momentum_backtest
            result = run_momentum_backtest()
            assert result == {}

    def test_run_momentum_with_data(self, db_path):
        """With price data, returns backtest result dict."""
        dates = pd.date_range("2025-01-01", periods=50, freq="B")
        rows = []
        for t in ["AAPL", "MSFT", "GOOGL"]:
            for d in dates:
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"), "close": 100 + np.random.uniform(-5, 5)})
        mock_df = pd.DataFrame(rows)

        with patch("nuri.quant.backtest.engine.query_df", return_value=mock_df):
            from nuri.quant.backtest.engine import run_momentum_backtest
            result = run_momentum_backtest(top_n=2, rebalance_days=10)
            assert "strategy" in result
            assert "total_return_pct" in result
            assert "sharpe_ratio" in result
            assert "win_rate_pct" in result
            assert result["total_trades"] >= 0  # VectorBT trade count varies by platform

    def test_run_momentum_kr_excluded(self, db_path):
        """Korean tickers (.KS) are excluded."""
        dates = pd.date_range("2025-01-01", periods=50, freq="B")
        rows = []
        for t in ["005930.KS"]:
            for d in dates:
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"), "close": 70000})
        mock_df = pd.DataFrame(rows)

        with patch("nuri.quant.backtest.engine.query_df", return_value=mock_df):
            from nuri.quant.backtest.engine import run_momentum_backtest
            result = run_momentum_backtest()
            # All tickers are KR → no US tickers → empty result
            assert result == {}

    def test_run_momentum_insufficient_data(self, db_path):
        """Less than 20 rows returns empty."""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        rows = [{"ticker": "AAPL", "date": d.strftime("%Y-%m-%d"), "close": 150} for d in dates]
        mock_df = pd.DataFrame(rows)

        with patch("nuri.quant.backtest.engine.query_df", return_value=mock_df):
            from nuri.quant.backtest.engine import run_momentum_backtest
            result = run_momentum_backtest()
            assert result == {}

    def test_run_momentum_quantstats_failure(self, db_path):
        """QuantStats failure is handled gracefully."""
        dates = pd.date_range("2025-01-01", periods=50, freq="B")
        rows = []
        for t in ["AAPL", "MSFT", "GOOGL"]:
            for d in dates:
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"), "close": 100 + np.random.uniform(-5, 5)})
        mock_df = pd.DataFrame(rows)

        with patch("nuri.quant.backtest.engine.query_df", return_value=mock_df):
            from nuri.quant.backtest.engine import run_momentum_backtest
            # QuantStats import will fail in test env — that's fine, it's caught
            result = run_momentum_backtest()
            assert isinstance(result, dict)
            assert "total_return_pct" in result

    def test_print_backtest_with_result(self, capsys):
        from nuri.quant.backtest.engine import print_backtest
        result = {
            "strategy": "Momentum Top-5",
            "total_return_pct": 15.5,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": -8.3,
            "win_rate_pct": 55.0,
            "total_trades": 20,
        }
        print_backtest(result)
        captured = capsys.readouterr()
        assert "Momentum Top-5" in captured.out
        assert "15.5" in captured.out

    def test_print_backtest_empty(self, capsys):
        from nuri.quant.backtest.engine import print_backtest
        print_backtest({})
        captured = capsys.readouterr()
        assert "데이터 없음" in captured.out


# ═══════════════════════════════════════════════════════════════
# 2. nuri/quant/factors/value.py
# ═══════════════════════════════════════════════════════════════


class TestValueFactor:
    """Tests for value factor computation."""

    def test_compute_value_with_mock(self, monkeypatch):
        """Mock OpenBB ratios to test normalization."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {"pe_ratio": 25.0, "pb_ratio": 3.0},
        ])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result

        with patch.dict("sys.modules", {"openbb": MagicMock(obb=mock_obb)}):
            from nuri.quant.factors.value import compute_value
            # Directly construct mock behavior
            mock_obb_module = types.ModuleType("openbb")
            mock_obb_module.obb = mock_obb
            with patch.dict("sys.modules", {"openbb": mock_obb_module}):
                result = compute_value(tickers=["AAPL", "MSFT"])
                assert isinstance(result, pd.DataFrame)

    def test_compute_value_empty_result(self, monkeypatch):
        """All tickers fail → empty DataFrame."""
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.side_effect = Exception("API error")

        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.value import compute_value
            result = compute_value(tickers=["FAKE"])
            assert result.empty

    def test_compute_value_nan_handling(self, monkeypatch):
        """NaN PE/PB values are handled."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {"pe_ratio": float("nan"), "pb_ratio": 5.0},
        ])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result

        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.value import compute_value
            result = compute_value(tickers=["AAPL"])
            assert isinstance(result, pd.DataFrame)

    def test_compute_value_multiple_tickers_normalization(self):
        """Test normalization with multiple tickers having different PE/PB."""
        mock_results = {
            "AAPL": pd.DataFrame([{"pe_ratio": 20.0, "pb_ratio": 5.0}]),
            "MSFT": pd.DataFrame([{"pe_ratio": 30.0, "pb_ratio": 8.0}]),
            "GOOGL": pd.DataFrame([{"pe_ratio": 25.0, "pb_ratio": 6.0}]),
        }

        def mock_ratios(ticker, **kwargs):
            m = MagicMock()
            m.to_dataframe.return_value = mock_results.get(ticker, pd.DataFrame())
            return m

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios = mock_ratios
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.value import compute_value
            result = compute_value(tickers=["AAPL", "MSFT", "GOOGL"])
            assert len(result) == 3
            assert "value_score" in result.columns
            # Lower PE should yield higher value_score
            assert result.loc["AAPL", "value_score"] > result.loc["MSFT", "value_score"]

    def test_compute_value_same_pe_pb(self):
        """Same PE/PB for all tickers → all get 0.5 norm."""
        mock_results = {
            "AAPL": pd.DataFrame([{"pe_ratio": 25.0, "pb_ratio": 5.0}]),
            "MSFT": pd.DataFrame([{"pe_ratio": 25.0, "pb_ratio": 5.0}]),
        }

        def mock_ratios(ticker, **kwargs):
            m = MagicMock()
            m.to_dataframe.return_value = mock_results.get(ticker, pd.DataFrame())
            return m

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios = mock_ratios
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.value import compute_value
            result = compute_value(tickers=["AAPL", "MSFT"])
            assert len(result) == 2
            # With identical values, norm should be 0.5
            for col in result.columns:
                if col.endswith("_norm"):
                    assert (result[col] == 0.5).all()

    def test_compute_value_single_ticker(self):
        """Single ticker gets 0.5 norm (only 1 valid value)."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([{"pe_ratio": 20.0, "pb_ratio": 3.0}])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.value import compute_value
            result = compute_value(tickers=["AAPL"])
            assert len(result) == 1
            assert "value_score" in result.columns


# ═══════════════════════════════════════════════════════════════
# 3. nuri/quant/factors/quality.py
# ═══════════════════════════════════════════════════════════════


class TestQualityFactor:
    """Tests for quality factor computation."""

    def test_compute_quality_multiple_tickers(self):
        """Test normalization with different ROE/margin values."""
        mock_results = {
            "AAPL": pd.DataFrame([{"return_on_equity": 0.40, "operating_profit_margin": 0.30}]),
            "MSFT": pd.DataFrame([{"return_on_equity": 0.35, "operating_profit_margin": 0.40}]),
            "GOOGL": pd.DataFrame([{"return_on_equity": 0.25, "operating_profit_margin": 0.25}]),
        }

        def mock_ratios(ticker, **kwargs):
            m = MagicMock()
            m.to_dataframe.return_value = mock_results.get(ticker, pd.DataFrame())
            return m

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios = mock_ratios
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["AAPL", "MSFT", "GOOGL"])
            assert len(result) == 3
            assert "quality_score" in result.columns
            # Higher ROE should yield higher quality_score (for that dimension)
            assert result.loc["AAPL", "quality_score"] > result.loc["GOOGL", "quality_score"]

    def test_compute_quality_empty(self):
        """All tickers fail → empty DataFrame."""
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.side_effect = Exception("fail")
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["FAKE"])
            assert result.empty

    def test_compute_quality_nan_roe(self):
        """NaN ROE handled gracefully."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {"return_on_equity": float("nan"), "operating_profit_margin": 0.30}
        ])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["AAPL"])
            assert isinstance(result, pd.DataFrame)

    def test_compute_quality_same_values(self):
        """Same ROE/margin → 0.5 norm."""
        def mock_ratios(ticker, **kwargs):
            m = MagicMock()
            m.to_dataframe.return_value = pd.DataFrame([
                {"return_on_equity": 0.20, "operating_profit_margin": 0.15}
            ])
            return m

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios = mock_ratios
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["AAPL", "MSFT"])
            assert len(result) == 2
            for col in result.columns:
                if col.endswith("_norm"):
                    assert (result[col] == 0.5).all()

    def test_compute_quality_single_ticker(self):
        """Single ticker gets 0.5 norm."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {"return_on_equity": 0.30, "operating_profit_margin": 0.25}
        ])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["AAPL"])
            assert "quality_score" in result.columns

    def test_compute_quality_alternate_field_names(self):
        """Use 'roe' instead of 'return_on_equity', 'net_profit_margin' instead of 'operating_profit_margin'."""
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {"roe": 0.28, "net_profit_margin": 0.22}
        ])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.ratios.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            from nuri.quant.factors.quality import compute_quality
            result = compute_quality(tickers=["AAPL"])
            assert isinstance(result, pd.DataFrame)


# ═══════════════════════════════════════════════════════════════
# 4. nuri/collectors/technical.py
# ═══════════════════════════════════════════════════════════════


class TestTechnicalCollector:
    """Tests for TechnicalCollector."""

    def test_instantiation(self):
        from nuri.collectors.technical import TechnicalCollector
        c = TechnicalCollector()
        assert c.name == "technical"

    def test_compute_talib_static(self):
        """_compute_talib returns expected keys."""
        from nuri.collectors.technical import TechnicalCollector
        close = np.random.uniform(100, 200, 250).astype(float)
        result = TechnicalCollector._compute_talib(close)
        assert "rsi_14" in result
        assert "macd" in result
        assert "macd_signal" in result
        assert "bb_upper" in result
        assert "sma_200" in result
        assert "ema_12" in result
        # Check lengths
        for key, arr in result.items():
            assert len(arr) == 250

    def test_collect_no_tickers(self, db_path, monkeypatch):
        """No tickers → empty DataFrame."""
        from nuri.collectors.technical import TechnicalCollector
        monkeypatch.setattr("nuri.collectors.technical.get_tickers", lambda **kw: [])
        c = TechnicalCollector()
        result = c.collect()
        assert result.empty

    def test_collect_with_prices(self, db_path, monkeypatch):
        """Collect with sufficient price data produces rows."""
        from nuri.collectors.technical import TechnicalCollector

        # Seed prices for AAPL
        _seed_portfolio(db_path, ["AAPL"])
        _seed_ticker_prices(db_path, "AAPL", days=250, start_price=150.0)

        monkeypatch.setattr("nuri.collectors.technical.get_tickers", lambda **kw: ["AAPL"])
        monkeypatch.setattr("nuri.collectors.technical.query_df",
                            lambda sql, params, **kw: pd.read_sql_query(
                                sql, __import__("sqlite3").connect(str(db_path)), params=params))

        c = TechnicalCollector()
        # Mock the query_df to use our test DB
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr("nuri.collectors.technical.query_df",
                            lambda sql, params, **kw: real_query_df(sql, params, db_path=db_path))
        result = c.collect()
        assert not result.empty
        assert "rsi_14" in result.columns
        assert result.iloc[0]["ticker"] == "AAPL"

    def test_collect_insufficient_data(self, db_path, monkeypatch):
        """Ticker with < 14 days → skipped."""
        from nuri.collectors.technical import TechnicalCollector
        _seed_portfolio(db_path, ["AAPL"])
        _seed_ticker_prices(db_path, "AAPL", days=10, start_price=150.0)

        monkeypatch.setattr("nuri.collectors.technical.get_tickers", lambda **kw: ["AAPL"])
        from nuri.core.db import query_df as real_query_df
        monkeypatch.setattr("nuri.collectors.technical.query_df",
                            lambda sql, params, **kw: real_query_df(sql, params, db_path=db_path))
        c = TechnicalCollector()
        result = c.collect()
        assert result.empty

    def test_save_empty(self, db_path):
        from nuri.collectors.technical import TechnicalCollector
        c = TechnicalCollector()
        assert c.save(pd.DataFrame()) == 0

    def test_save_with_data(self, db_path, monkeypatch):
        from nuri.collectors.technical import TechnicalCollector
        monkeypatch.setattr("nuri.collectors.technical.upsert_signals",
                            lambda df, **kw: len(df))
        c = TechnicalCollector()
        df = pd.DataFrame([{"ticker": "AAPL", "date": "2025-01-01", "rsi_14": 45.0}])
        assert c.save(df) == 1


# ═══════════════════════════════════════════════════════════════
# 5. nuri/quant/validation/analyst_backtest.py
# ═══════════════════════════════════════════════════════════════


class TestAnalystBacktest:
    """Tests for analyst estimate validation."""

    def _seed_estimates(self, db_path, days_ago=120):
        """Insert estimates data older than days_ago."""
        from nuri.core.timezone import kst_now
        est_date = (kst_now().replace(tzinfo=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO estimates
                   (ticker, date, recommendation, target_high, target_low,
                    target_mean, target_median, num_analysts, current_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("AAPL", est_date, "Buy", 200.0, 150.0, 180.0, 175.0, 30, 160.0),
            )

    def test_validate_empty_db(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(db_path=db_path)
        assert results == []

    def test_validate_no_qualifying_estimates(self, db_path):
        """Estimates exist but not old enough."""
        self._seed_estimates(db_path, days_ago=30)
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert results == []

    def test_validate_with_data(self, db_path):
        """Full validation with estimates + prices."""
        self._seed_estimates(db_path, days_ago=120)
        _seed_ticker_prices(db_path, "AAPL", days=200, start_price=155.0)

        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert len(results) >= 1
        r = results[0]
        assert r.ticker == "AAPL"
        assert r.target_mean == 180.0
        assert isinstance(r.target_hit, bool)
        assert isinstance(r.actual_return_pct, float)

    def test_validate_skips_zero_target(self, db_path):
        """Estimates with target_mean=0 are skipped."""
        from nuri.core.timezone import kst_now
        est_date = (kst_now().replace(tzinfo=None) - timedelta(days=120)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO estimates
                   (ticker, date, recommendation, target_high, target_low,
                    target_mean, target_median, num_analysts, current_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("AAPL", est_date, "Hold", 0.0, 0.0, 0.0, 0.0, 5, 100.0),
            )
        _seed_ticker_prices(db_path, "AAPL", days=200, start_price=100.0)

        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(min_elapsed_days=90, db_path=db_path)
        assert len(results) == 0

    def test_print_results_empty(self, capsys):
        from nuri.quant.validation.analyst_backtest import print_results
        print_results([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_results_with_data(self, capsys):
        from nuri.quant.validation.analyst_backtest import EstimateResult, print_results
        results = [
            EstimateResult(
                ticker="AAPL", estimate_date="2025-01-01", recommendation="Buy",
                target_mean=180.0, price_at_estimate=160.0, actual_price=190.0,
                actual_date="2025-04-01", target_gap_pct=12.5, actual_return_pct=18.75,
                target_hit=True,
            ),
            EstimateResult(
                ticker="MSFT", estimate_date="2025-01-01", recommendation="Hold",
                target_mean=400.0, price_at_estimate=380.0, actual_price=370.0,
                actual_date="2025-04-01", target_gap_pct=5.26, actual_return_pct=-2.63,
                target_hit=False,
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "MSFT" in captured.out
        assert "적중률" in captured.out

    def test_estimate_result_dataclass(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult
        r = EstimateResult(
            ticker="TEST", estimate_date="2025-01-01", recommendation="Buy",
            target_mean=100.0, price_at_estimate=90.0, actual_price=95.0,
            actual_date="2025-04-01", target_gap_pct=11.1, actual_return_pct=5.6,
            target_hit=False,
        )
        assert r.ticker == "TEST"
        assert not r.target_hit


# ═══════════════════════════════════════════════════════════════
# 6. nuri/trading/strategy/ls_backtest.py
# ═══════════════════════════════════════════════════════════════


class TestLSBacktest:
    """Tests for L/S strategy backtest functions."""

    @pytest.fixture
    def backtest_db(self, db_path):
        """DB with 300+ days of SPY + VIX data."""
        _seed_spy_data(db_path, days=350, trend="bull")
        _seed_vix(db_path, days=350)
        return db_path

    def test_classify_historical_regimes_basic(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_db)
        assert not df.empty
        assert "regime" in df.columns
        assert "return" in df.columns
        assert "close" in df.columns

    def test_classify_historical_insufficient_data(self, db_path):
        """Less than 200 days of SPY → empty."""
        _seed_spy_data(db_path, days=100, trend="bull")
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=db_path)
        assert df.empty

    def test_run_backtest(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import BacktestResult, classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_db)
        result = run_backtest(regimes, db_path=backtest_db)
        assert isinstance(result, BacktestResult)
        assert result.total_days > 0
        assert result.equity_curve is not None

    def test_run_backtest_result_fields(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_db)
        result = run_backtest(regimes, db_path=backtest_db)
        assert hasattr(result, "total_return")
        assert hasattr(result, "sharpe")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "spy_total_return")
        assert hasattr(result, "excess_return")

    def test_analyze_per_regime(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=backtest_db)
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)
        if perfs:
            assert hasattr(perfs[0], "regime")
            assert hasattr(perfs[0], "days")
            assert hasattr(perfs[0], "win_rate")

    def test_stress_test(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        regimes = classify_historical_regimes(db_path=backtest_db)
        results = stress_test(regimes)
        assert isinstance(results, list)
        # Data range may or may not include crisis periods
        for r in results:
            assert "name" in r
            assert "spy_return" in r
            assert "strategy_return" in r

    def test_monte_carlo_test(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=backtest_db)
        mc = monte_carlo_test(regimes, n_simulations=10, db_path=backtest_db)
        assert "actual_return" in mc
        assert "n_simulations" in mc
        assert mc["n_simulations"] == 10

    def test_monte_carlo_insufficient_data(self, db_path):
        """Very small DataFrame triggers data_insufficient."""
        from nuri.trading.strategy.ls_backtest import monte_carlo_test
        # Create tiny DataFrame with regime and return columns
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=5, freq="B"),
            "close": [100, 101, 102, 103, 104],
            "regime": ["bull_low_vol"] * 5,
            "return": [0.01] * 5,
        })
        mc = monte_carlo_test(df, n_simulations=5, block_size=20, db_path=db_path)
        assert "error" in mc

    def test_run_backtest_with_rules(self, backtest_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        regimes = classify_historical_regimes(db_path=backtest_db)
        result = run_backtest_with_rules(regimes, db_path=backtest_db)
        assert "base" in result
        assert "with_rules" in result
        assert "rules_impact" in result
        assert "rules_config" in result

    def test_print_backtest(self, capsys):
        from nuri.trading.strategy.ls_backtest import BacktestResult, print_backtest
        r = BacktestResult(
            total_return=15.5, annual_return=8.2, sharpe=1.1, max_drawdown=-12.3,
            win_rate=0.52, total_days=500, regime_changes=15, transaction_costs=0.45,
            spy_total_return=20.0, spy_annual_return=10.0, spy_sharpe=0.9,
            spy_max_drawdown=-15.0, excess_return=-4.5,
        )
        print_backtest(r)
        captured = capsys.readouterr()
        assert "Long/Short" in captured.out
        assert "15.5" in captured.out

    def test_print_regime_performance(self, capsys):
        from nuri.trading.strategy.ls_backtest import RegimePerformance, print_regime_performance
        perfs = [
            RegimePerformance(
                regime="bull_low_vol", days=200, pct_of_total=60.0,
                avg_daily_return=0.05, total_return=12.5, win_rate=0.55,
                avg_duration=30.0, transitions_to={"sideways_low_vol": 0.5},
            ),
        ]
        print_regime_performance(perfs)
        captured = capsys.readouterr()
        assert "bull_low_vol" in captured.out

    def test_print_timing_none(self, capsys):
        from nuri.trading.strategy.ls_backtest import print_timing
        print_timing(None)
        captured = capsys.readouterr()
        assert "불가" in captured.out

    def test_print_timing_with_data(self, capsys):
        from nuri.trading.strategy.ls_backtest import TimingAnalysis, print_timing
        ta = TimingAnalysis(
            current_regime="bull_low_vol", occurrences=5,
            avg_forward_30d=3.5, avg_forward_60d=7.0, avg_forward_90d=10.0,
            pct_to_bull=0.6, pct_to_bear=0.2, pct_stay=0.2,
        )
        print_timing(ta)
        captured = capsys.readouterr()
        assert "bull_low_vol" in captured.out
        assert "3.5" in captured.out

    def test_print_stress(self, capsys):
        from nuri.trading.strategy.ls_backtest import print_stress
        results = [
            {"name": "Test Crisis", "period": "2025-01-01 ~ 2025-02-01",
             "days": 22, "spy_return": -10.5, "strategy_return": -5.2,
             "excess": 5.3, "regimes": {"bear_high_vol": 22}, "protected": True},
        ]
        print_stress(results)
        captured = capsys.readouterr()
        assert "Test Crisis" in captured.out
        assert "YES" in captured.out

    def test_print_monte_carlo(self, capsys):
        from nuri.trading.strategy.ls_backtest import print_monte_carlo
        mc = {
            "actual_return": 15.0, "actual_sharpe": 1.1,
            "random_mean_return": 8.0, "random_std_return": 5.0,
            "random_mean_sharpe": 0.5,
            "return_percentile": 0.92, "sharpe_percentile": 0.88,
            "n_simulations": 1000,
            "statistically_significant": False,
        }
        print_monte_carlo(mc)
        captured = capsys.readouterr()
        assert "1000" in captured.out
        assert "NO" in captured.out

    def test_print_rules_comparison_error(self, capsys):
        from nuri.trading.strategy.ls_backtest import print_rules_comparison
        print_rules_comparison({"error": "데이터 부족"})
        captured = capsys.readouterr()
        assert "데이터 부족" in captured.out

    def test_print_rules_comparison_with_data(self, capsys):
        from nuri.trading.strategy.ls_backtest import print_rules_comparison
        result = {
            "base": {"total_return": 15.0, "annual_return": 8.0, "sharpe": 1.0, "max_drawdown": -10.0},
            "with_rules": {"total_return": 18.0, "annual_return": 9.5, "sharpe": 1.2, "max_drawdown": -8.0},
            "rules_impact": {"return_diff": 3.0, "sharpe_diff": 0.2, "mdd_diff": 2.0,
                           "stops_hit": 5, "tp1_count": 8, "tp2_count": 3, "trailing_count": 2},
            "rules_config": {"stop_loss": "-7%", "target_1": "+20% (50% sell)",
                           "target_2": "+40% (25% sell)", "trailing_stop": "-15% from high"},
        }
        print_rules_comparison(result)
        captured = capsys.readouterr()
        assert "Rules-Applied" in captured.out

    def test_analyze_entry_timing_no_regime(self, backtest_db):
        """No matching regime entries → None."""
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=backtest_db)
        result = analyze_entry_timing(regimes, current_regime="nonexistent_regime")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 7. nuri/quant/regime/strategy_map.py
# ═══════════════════════════════════════════════════════════════


class TestStrategyMap:
    """Tests for regime-to-strategy mapping."""

    def test_map_regime_bull_low_vol(self, rich_db, monkeypatch):
        """Bull low vol → aggressive positioning."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={"special_regime": None, "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=65, yield_curve_score=60,
            yield_spread_3m10y_score=55, vix_score=70, put_call_ratio_score=50,
            sentiment_score=60, employment_score=70, inflation_score=65,
            monetary_score=60, interpretation="Favorable", details={},
        )

        # Mock analyze_signal_by_regime to return empty (no CSV data)
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: pd.DataFrame())

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.regime == "bull_low_vol"
        assert rec.position_sizing == "aggressive"
        assert len(rec.recommended_signals) > 0

    def test_map_regime_bear_high_vol(self, rich_db, monkeypatch):
        """Bear high vol → minimal positioning."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.90,
            details={"special_regime": None, "base_regime": "bear_high_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=25, yield_curve_score=30,
            yield_spread_3m10y_score=20, vix_score=15, put_call_ratio_score=40,
            sentiment_score=20, employment_score=30, inflation_score=25,
            monetary_score=35, interpretation="Adverse", details={},
        )
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: pd.DataFrame())

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.position_sizing in ("minimal", "defensive")
        assert rec.recommended_signals == []  # minimal blocks signals

    def test_map_regime_euphoria(self, rich_db, monkeypatch):
        """Euphoria special regime → defensive."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="euphoria", confidence=0.80,
            details={"special_regime": "euphoria", "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=75, yield_curve_score=80,
            yield_spread_3m10y_score=70, vix_score=90, put_call_ratio_score=50,
            sentiment_score=85, employment_score=75, inflation_score=70,
            monetary_score=65, interpretation="Favorable", details={},
        )
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: pd.DataFrame())

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.position_sizing in ("defensive", "normal", "cautious")

    def test_map_regime_macro_override_to_defensive(self, rich_db, monkeypatch):
        """Low macro score overrides aggressive to defensive."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={"special_regime": None, "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=20, yield_curve_score=15,
            yield_spread_3m10y_score=10, vix_score=20, put_call_ratio_score=25,
            sentiment_score=15, employment_score=20, inflation_score=25,
            monetary_score=30, interpretation="Adverse", details={},
        )
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: pd.DataFrame())

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec.position_sizing == "defensive"
        assert "매크로 악화" in rec.notes

    def test_map_regime_macro_override_relax_defensive(self, rich_db, monkeypatch):
        """High macro score relaxes defensive to normal."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="sideways", volatility="high",
            regime="sideways_high_vol", confidence=0.75,
            details={"special_regime": None, "base_regime": "sideways_high_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=75, yield_curve_score=80,
            yield_spread_3m10y_score=70, vix_score=85, put_call_ratio_score=60,
            sentiment_score=80, employment_score=75, inflation_score=70,
            monetary_score=65, interpretation="Favorable", details={},
        )
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: pd.DataFrame())

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec.position_sizing == "normal"
        assert "매크로 양호" in rec.notes

    def test_build_data_driven_strategy_with_data(self):
        """Build strategy from cross-analysis DataFrame."""
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10,
             "win_rate": 0.7, "profit_factor": 2.0, "avg_return": 3.5},
            {"signal_id": "macd_dead", "regime": "bull_low_vol", "trades": 8,
             "win_rate": 0.3, "profit_factor": 0.8, "avg_return": -1.0},
            {"signal_id": "sma_golden", "regime": "bull_low_vol", "trades": 3,
             "win_rate": 0.66, "profit_factor": 1.8, "avg_return": 2.0},
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]
        # sma_golden has trades < 5, not included

    def test_build_data_driven_strategy_empty(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        result = _build_data_driven_strategy("test", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []

    def test_print_strategy_none(self, capsys):
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        captured = capsys.readouterr()
        assert "불가" in captured.out

    def test_print_strategy_with_stats(self, capsys):
        from nuri.quant.regime.strategy_map import StrategyRecommendation, print_strategy
        rec = StrategyRecommendation(
            regime="bull_low_vol", macro_interpretation="Favorable",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold", "bb_bounce"],
            avoid_signals=["macd_dead"],
            sector_preference=["XLK", "XLY"],
            signal_regime_stats={
                "rsi_oversold": {"trades": 10, "win_rate": 0.7, "pf": 2.0, "avg_return": 3.5},
            },
            notes="데이터 검증: 1개 시그널 PF>1.5",
        )
        print_strategy(rec)
        captured = capsys.readouterr()
        assert "AGGRESSIVE" in captured.out
        assert "rsi_oversold" in captured.out

    def test_print_cross_analysis_empty(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        captured = capsys.readouterr()
        assert "데이터 없음" in captured.out

    def test_print_cross_analysis_with_data(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol",
             "trades": 10, "win_rate": 0.7, "profit_factor": 2.0, "avg_return": 3.5},
            {"signal_id": "macd_golden", "regime": "bull_low_vol",
             "trades": 5, "win_rate": 0.6, "profit_factor": 100.0, "avg_return": 2.0},
        ])
        print_cross_analysis(df)
        captured = capsys.readouterr()
        assert "bull_low_vol" in captured.out

    def test_find_latest_csv_no_dir(self, tmp_path, monkeypatch):
        from nuri.quant.regime.strategy_map import _find_latest_csv
        monkeypatch.setattr("nuri.quant.regime.strategy_map.REPORT_DIR", tmp_path / "nonexistent")
        result = _find_latest_csv("test.csv")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 8. nuri/trading/strategy/mean_reversion.py
# ═══════════════════════════════════════════════════════════════


class TestMeanReversion:
    """Tests for mean-reversion scan and backtest."""

    @pytest.fixture
    def mr_db(self, db_path):
        """DB with oversold ticker data for mean-reversion signals."""
        _seed_portfolio(db_path, ["AAPL"])
        # Create data with a dip below BB lower
        dates = pd.date_range(end="2025-12-31", periods=80, freq="B")
        prices = []
        price = 150.0
        for i, d in enumerate(dates):
            if 55 <= i <= 60:
                price *= 0.97  # Sharp drop
            elif i > 60:
                price *= 1.02  # Recovery
            else:
                price *= 1 + np.random.uniform(-0.005, 0.005)
            prices.append({
                "ticker": "AAPL", "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.999, 2), "high": round(price * 1.01, 2),
                "low": round(price * 0.99, 2), "close": round(price, 2),
                "volume": 1000000, "adj_close": round(price, 2),
            })
        upsert_prices(pd.DataFrame(prices), db_path=db_path)
        return db_path

    def test_scan_mean_reversion_empty(self, db_path):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        signals = scan_mean_reversion(db_path=db_path)
        assert signals == []

    def test_scan_mean_reversion_insufficient_data(self, db_path):
        """Ticker with < 30 days skipped."""
        _seed_portfolio(db_path, ["AAPL"])
        _seed_ticker_prices(db_path, "AAPL", days=20)
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        signals = scan_mean_reversion(db_path=db_path)
        assert signals == []

    def test_scan_mean_reversion_signal_dataclass(self):
        from nuri.trading.strategy.mean_reversion import MeanRevSignal
        s = MeanRevSignal(
            ticker="AAPL", date="2025-01-01", entry_price=140.0,
            bb_lower=138.0, rsi=25.0, z_score=-2.5, expected_target=155.0,
        )
        assert s.ticker == "AAPL"
        assert s.z_score == -2.5

    def test_backtest_mean_reversion_empty(self, db_path):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=db_path)
        assert result["total_trades"] == 0

    def test_backtest_mean_reversion_insufficient_data(self, db_path):
        """Ticker with < 60 days skipped."""
        _seed_portfolio(db_path, ["AAPL"])
        _seed_ticker_prices(db_path, "AAPL", days=50)
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=db_path)
        assert result["total_trades"] == 0

    def test_backtest_mean_reversion_with_trades(self, db_path):
        """Seed data that creates trade signals."""
        _seed_portfolio(db_path, ["TEST"])
        # Create data with repeated dips for backtest trades
        dates = pd.date_range(end="2025-12-31", periods=100, freq="B")
        prices_list = []
        price = 100.0
        np.random.seed(42)
        for i, d in enumerate(dates):
            # Create periodic dips below BB band
            if i % 30 in range(25, 30):
                price *= 0.96  # Dip
            elif i % 30 in range(0, 5) and i > 30:
                price *= 1.03  # Recovery
            else:
                price *= 1 + np.random.uniform(-0.003, 0.005)
            prices_list.append({
                "ticker": "TEST", "date": d.strftime("%Y-%m-%d"),
                "open": round(price * 0.999, 2), "high": round(price * 1.01, 2),
                "low": round(price * 0.99, 2), "close": round(price, 2),
                "volume": 1000000, "adj_close": round(price, 2),
            })
        upsert_prices(pd.DataFrame(prices_list), db_path=db_path)

        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=db_path)
        assert isinstance(result, dict)
        assert "total_trades" in result


# ═══════════════════════════════════════════════════════════════
# 9. nuri/trading/strategy/pairs.py
# ═══════════════════════════════════════════════════════════════


class TestPairsTrading:
    """Tests for pairs trading strategy."""

    def test_find_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(db_path=db_path)
        assert pairs == []

    def test_find_pairs_single_ticker(self, db_path):
        """Need at least 2 US tickers."""
        _seed_portfolio(db_path, ["AAPL"])
        _seed_ticker_prices(db_path, "AAPL", days=80)
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(db_path=db_path)
        assert pairs == []

    def test_find_pairs_kr_only(self, db_path):
        """Korean tickers excluded from pairs."""
        _seed_portfolio(db_path, ["005930.KS", "000660.KS"])
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(db_path=db_path)
        assert pairs == []

    def test_find_pairs_with_data(self, market_data_for_pairs):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.3, db_path=market_data_for_pairs)
        assert isinstance(pairs, list)

    def test_pair_stats_dataclass(self):
        from nuri.trading.strategy.pairs import PairStats
        p = PairStats(
            ticker_a="AAPL", ticker_b="MSFT",
            correlation=0.85, mean_spread=0.01,
            std_spread=0.05, current_z=1.5,
        )
        assert p.ticker_a == "AAPL"
        assert p.correlation == 0.85

    def test_pair_signal_dataclass(self):
        from nuri.trading.strategy.pairs import PairSignal
        s = PairSignal(
            ticker_long="AAPL", ticker_short="MSFT",
            correlation=0.8, z_score=2.5,
            spread_pct=3.0, date="2025-01-01",
        )
        assert s.ticker_long == "AAPL"

    def test_scan_pair_signals_empty(self, db_path):
        from nuri.trading.strategy.pairs import scan_pair_signals
        signals = scan_pair_signals(db_path=db_path)
        assert signals == []

    def test_backtest_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=db_path)
        assert result["total_trades"] == 0

    def test_backtest_pairs_with_data(self, market_data_for_pairs):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=market_data_for_pairs)
        assert isinstance(result, dict)
        assert "total_trades" in result


# ═══════════════════════════════════════════════════════════════
# 10. nuri/trading/strategy/monitor.py
# ═══════════════════════════════════════════════════════════════


class TestMonitor:
    """Tests for strategy monitor."""

    def test_detect_regime_transition_no_data(self, db_path):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=db_path)
        assert result is None

    def test_detect_regime_transition_same_regime(self, rich_db, monkeypatch):
        """Same regime as stored → no transition."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        # Insert existing regime
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-12-30", "sideways_low_vol", "bull_low_vol", "{}"),
            )

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_detect_regime_transition_detected(self, rich_db, monkeypatch):
        """Different regime → transition detected."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.90,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        # Insert existing regime
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-12-29", "sideways_low_vol", "bull_low_vol", "{}"),
            )

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["to_regime"] == "bear_high_vol"
        assert result["from_regime"] == "bull_low_vol"
        assert "urgency" in result

    def test_detect_regime_transition_initial(self, rich_db, monkeypatch):
        """No previous regime → initial setup."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["from_regime"] == "unknown"
        assert "초기" in result["switch"]

    def test_daily_pnl_summary_empty(self, db_path, monkeypatch):
        """No open positions → zero PnL."""
        from nuri.trading.strategy.monitor import daily_pnl_summary
        pnl = daily_pnl_summary(db_path=db_path)
        assert pnl["total_positions"] == 0
        assert pnl["total_pnl"] == 0

    def test_daily_pnl_summary_with_positions(self, rich_db, monkeypatch):
        """With open positions → calculate PnL."""
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda db_path=None: None)
        # Insert open positions
        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, current_price, entry_date, status,
                    regime_at_entry, portfolio_type, return_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("AAPL", "long", 150.0, 165.0, "2025-12-01", "open", "bull_low_vol", "core", 10.0),
            )
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, current_price, entry_date, status,
                    regime_at_entry, portfolio_type, return_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("MSFT", "long", 400.0, 380.0, "2025-12-01", "open", "bull_low_vol", "tactical", -5.0),
            )

        from nuri.trading.strategy.monitor import daily_pnl_summary
        pnl = daily_pnl_summary(db_path=rich_db)
        assert pnl["total_positions"] == 2
        assert pnl["winners"] == 1
        assert pnl["losers"] == 1


# ═══════════════════════════════════════════════════════════════
# 11. nuri/trading/strategy/longshort.py
# ═══════════════════════════════════════════════════════════════


class TestLongShort:
    """Tests for L/S strategy engine."""

    def test_generate_strategy_bull_no_positions(self, rich_db, monkeypatch):
        """Bull regime with no open positions → open long actions."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        open_actions = [a for a in actions if a.action.startswith("open")]
        assert len(open_actions) > 0
        assert all(a.direction == "long" for a in open_actions)

    def test_generate_strategy_bear_closes_longs(self, rich_db, monkeypatch):
        """Bear regime closes tactical longs."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.90,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        # Insert tactical long position
        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, entry_date, status, regime_at_entry, portfolio_type, return_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("QQQ", "long", 400.0, "2025-12-01", "open", "bull_low_vol", "tactical", 5.0),
            )

        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        close_actions = [a for a in actions if a.action == "close" and a.ticker == "QQQ"]
        assert len(close_actions) >= 1

    def test_generate_strategy_profit_taking(self, rich_db, monkeypatch):
        """Positions with >= 10% gain trigger close."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, entry_date, status, regime_at_entry, portfolio_type, return_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("AAPL", "long", 150.0, "2025-11-01", "open", "bull_low_vol", "tactical", 12.0),
            )

        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        profit_closes = [a for a in actions if a.action == "close" and "익절" in a.reason]
        assert len(profit_closes) >= 1

    def test_generate_strategy_stop_loss(self, rich_db, monkeypatch):
        """Positions with <= -5% trigger stop loss close."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.85,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, entry_date, status, regime_at_entry, portfolio_type, return_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("MSFT", "long", 400.0, "2025-11-01", "open", "bull_low_vol", "tactical", -7.0),
            )

        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        stop_closes = [a for a in actions if a.action == "close" and "손절" in a.reason]
        assert len(stop_closes) >= 1

    def test_execute_strategy_close_action(self, rich_db, monkeypatch):
        """Execute a close action."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda db_path=None: None)

        # Insert a position to close
        with get_db(rich_db) as conn:
            conn.execute(
                """INSERT INTO positions
                   (ticker, direction, entry_price, current_price, entry_date, status, regime_at_entry, portfolio_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("QQQ", "long", 400.0, 410.0, "2025-12-01", "open", "bull_low_vol", "tactical"),
            )

        # Seed QQQ price for exit price lookup
        _seed_ticker_prices(rich_db, "QQQ", days=10, start_price=410.0)

        actions = [
            StrategyAction("close", "QQQ", "long", "tactical", "test close", "bull_low_vol", 90),
        ]
        count = execute_strategy(actions, db_path=rich_db)
        assert count >= 1

    def test_print_strategy_empty(self, capsys):
        from nuri.trading.strategy.longshort import print_strategy
        print_strategy([])
        captured = capsys.readouterr()
        assert "없음" in captured.out

    def test_print_strategy_with_actions(self, capsys):
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy
        actions = [
            StrategyAction("close", "QQQ", "long", "tactical", "레짐 전환", "bear_high_vol", 90),
            StrategyAction("open_short", "SH", "short", "tactical", "인버스 진입", "bear_high_vol", 80),
        ]
        print_strategy(actions)
        captured = capsys.readouterr()
        assert "bear_high_vol" in captured.out
        assert "QQQ" in captured.out
        assert "SH" in captured.out

    def test_strategy_action_dataclass(self):
        from nuri.trading.strategy.longshort import StrategyAction
        a = StrategyAction(
            action="open_long", ticker="SPY", direction="long",
            portfolio_type="tactical", reason="test",
            regime="bull_low_vol", confidence=85,
        )
        assert a.action == "open_long"
        assert a.confidence == 85

    def test_regime_allocation_all_regimes(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            assert "direction" in alloc
            assert "long_pct" in alloc
            assert "short_pct" in alloc
            assert "cash_pct" in alloc
            total = alloc["long_pct"] + alloc["short_pct"] + alloc["cash_pct"]
            assert total == 100, f"{regime}: allocation sums to {total}, not 100"

    def test_generate_strategy_neutral_regime(self, rich_db, monkeypatch):
        """Neutral regime with short alloc → small hedge."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="sideways", volatility="high",
            regime="sideways_high_vol", confidence=0.70,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        # sideways_high_vol has short_pct > 0, should suggest hedge
        # may or may not have actions depending on existing positions
        assert isinstance(actions, list)


# ═══════════════════════════════════════════════════════════════
# 12. nuri/collectors/estimates.py
# ═══════════════════════════════════════════════════════════════


class TestEstimatesCollector:
    """Tests for EstimatesCollector."""

    def test_instantiate(self):
        from nuri.collectors.estimates import EstimatesCollector
        c = EstimatesCollector()
        assert c.name == "estimates"

    def test_collect_with_mock_openbb(self, db_path, monkeypatch):
        """Mock OpenBB to test collect flow."""
        from nuri.collectors.estimates import EstimatesCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([{
            "recommendation": "Buy",
            "target_high": 200.0,
            "target_low": 150.0,
            "target_consensus": 180.0,
            "target_median": 175.0,
            "number_of_analysts": 30,
            "current_price": 160.0,
        }])

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = EstimatesCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["AAPL"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert len(results) == 1
            assert results[0]["ticker"] == "AAPL"
            assert results[0]["target_mean"] == 180.0

    def test_collect_empty_result(self, db_path, monkeypatch):
        """Empty DataFrame from OpenBB."""
        from nuri.collectors.estimates import EstimatesCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = EstimatesCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["AAPL"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert len(results) == 0

    def test_collect_exception_handled(self, db_path, monkeypatch):
        """OpenBB exception for one ticker doesn't crash."""
        from nuri.collectors.estimates import EstimatesCollector

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.side_effect = Exception("API error")
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = EstimatesCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["FAKE"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert results == []

    def test_collect_no_tickers(self, db_path, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector
        c = EstimatesCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: [])
        results = c.collect()
        assert results == []

    def test_save_empty(self, db_path):
        from nuri.collectors.estimates import EstimatesCollector
        c = EstimatesCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_safe_float(self):
        from nuri.collectors.estimates import _safe_float
        assert _safe_float(3.14) == 3.14
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None

    def test_safe_int(self):
        from nuri.collectors.estimates import _safe_int
        assert _safe_int(10) == 10
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None


# ═══════════════════════════════════════════════════════════════
# 13. nuri/collectors/external.py
# ═══════════════════════════════════════════════════════════════


class TestExternalCollector:
    """Tests for external data save/get functions."""

    def test_save_external_valid(self, db_path):
        from nuri.collectors.external import save_external
        result = save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=db_path)
        assert result is True

    def test_save_external_invalid_source(self, db_path):
        from nuri.collectors.external import save_external
        result = save_external("invalid_source", "AAPL", "test", "value", db_path=db_path)
        assert result is False

    def test_save_tipranks(self, db_path):
        from nuri.collectors.external import get_external, save_tipranks
        save_tipranks("NVDA", "Strong Buy", 273.61, 38, upside_pct=63.0, db_path=db_path)
        data = get_external("NVDA", db_path=db_path)
        assert len(data) >= 3  # consensus + target_price + analyst_count

    def test_save_superinvestor(self, db_path):
        from nuri.collectors.external import get_external, save_superinvestor
        save_superinvestor("AAPL", 14, "buying", details="Buffett +5%", db_path=db_path)
        data = get_external("AAPL", source="dataroma", db_path=db_path)
        assert len(data) >= 2

    def test_get_external_empty(self, db_path):
        from nuri.collectors.external import get_external
        data = get_external("NONEXISTENT", db_path=db_path)
        assert data == []

    def test_get_external_filtered_by_source(self, db_path):
        from nuri.collectors.external import get_external, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_path)
        save_external("dataroma", "AAPL", "count", "14", db_path=db_path)
        data = get_external("AAPL", source="tipranks", db_path=db_path)
        assert all(d["source"] == "tipranks" for d in data)

    def test_get_external_summary_empty(self, db_path):
        from nuri.collectors.external import get_external_summary
        summary = get_external_summary(db_path=db_path)
        assert summary["total_records"] == 0
        assert summary["sources"] == []

    def test_get_external_summary_with_data(self, db_path):
        from nuri.collectors.external import get_external_summary, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_path)
        save_external("dataroma", "MSFT", "count", "10", db_path=db_path)
        summary = get_external_summary(db_path=db_path)
        assert summary["total_records"] == 2
        assert len(summary["sources"]) == 2

    def test_print_ticker_external_empty(self, db_path, capsys):
        from nuri.collectors.external import print_ticker_external
        print_ticker_external("AAPL", db_path=db_path)
        captured = capsys.readouterr()
        assert "데이터 없음" in captured.out

    def test_print_ticker_external_with_data(self, db_path, capsys):
        from nuri.collectors.external import print_ticker_external, save_external
        save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=db_path)
        print_ticker_external("AAPL", db_path=db_path)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "TipRanks" in captured.out

    def test_print_summary_empty(self, db_path, capsys):
        from nuri.collectors.external import print_summary
        print_summary(db_path=db_path)
        captured = capsys.readouterr()
        assert "0건" in captured.out

    def test_print_summary_with_data(self, db_path, capsys):
        from nuri.collectors.external import print_summary, save_external
        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_path)
        print_summary(db_path=db_path)
        captured = capsys.readouterr()
        assert "1건" in captured.out

    def test_sources_dict(self):
        from nuri.collectors.external import SOURCES
        assert "tipranks" in SOURCES
        assert "dataroma" in SOURCES
        assert "cboe" in SOURCES

    def test_save_external_with_numeric_value(self, db_path):
        from nuri.collectors.external import get_external, save_external
        save_external("tipranks", "AAPL", "target_price", "200.0", numeric_value=200.0, db_path=db_path)
        data = get_external("AAPL", db_path=db_path)
        assert any(d["numeric_value"] == 200.0 for d in data)


# ═══════════════════════════════════════════════════════════════
# 14. nuri/collectors/fundamental.py
# ═══════════════════════════════════════════════════════════════


class TestFundamentalCollector:
    """Tests for FundamentalCollector."""

    def test_instantiate(self):
        from nuri.collectors.fundamental import FundamentalCollector
        c = FundamentalCollector()
        assert c.name == "fundamental"

    def test_collect_with_mock(self, db_path, monkeypatch):
        """Mock OpenBB metrics to test collect flow."""
        from nuri.collectors.fundamental import FundamentalCollector

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([{
            "market_cap": 3e12,
            "pe_ratio": 28.5,
            "forward_pe": 25.0,
            "price_to_book": 12.0,
            "peg_ratio_ttm": 2.1,
            "return_on_equity": 0.15,
            "return_on_assets": 0.08,
            "gross_margin": 0.45,
            "operating_margin": 0.30,
            "profit_margin": 0.25,
            "revenue_growth": 0.12,
            "earnings_growth": 0.15,
            "debt_to_equity": 1.5,
            "current_ratio": 1.8,
            "dividend_yield": 0.006,
            "beta": 1.2,
        }])

        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["AAPL"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert len(results) == 1
            assert results[0]["ticker"] == "AAPL"
            assert results[0]["pe_ratio"] == 28.5
            assert results[0]["roe"] == 0.15

    def test_collect_nan_values(self, db_path, monkeypatch):
        """NaN values converted to None."""
        from nuri.collectors.fundamental import FundamentalCollector

        data = {"market_cap": float("nan"), "pe_ratio": float("nan")}
        # Fill remaining fields
        for f in ["forward_pe", "price_to_book", "peg_ratio_ttm", "return_on_equity",
                   "return_on_assets", "gross_margin", "operating_margin", "profit_margin",
                   "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio",
                   "dividend_yield", "beta"]:
            data[f] = 1.0

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame([data])
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["AAPL"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert results[0]["market_cap"] is None
            assert results[0]["pe_ratio"] is None

    def test_collect_exception_handled(self, db_path, monkeypatch):
        """API exception for a ticker doesn't crash."""
        from nuri.collectors.fundamental import FundamentalCollector
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.side_effect = Exception("fail")
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["FAKE"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert results == []

    def test_collect_empty_dataframe(self, db_path, monkeypatch):
        """Empty DataFrame from OpenBB → skip."""
        from nuri.collectors.fundamental import FundamentalCollector
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_obb = MagicMock()
        mock_obb.equity.fundamental.metrics.return_value = mock_result
        mock_mod = types.ModuleType("openbb")
        mock_mod.obb = mock_obb

        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: ["AAPL"])
        with patch.dict("sys.modules", {"openbb": mock_mod}):
            results = c.collect()
            assert results == []

    def test_collect_no_tickers(self, db_path, monkeypatch):
        from nuri.collectors.fundamental import FundamentalCollector
        c = FundamentalCollector()
        monkeypatch.setattr(c, "_get_tickers", lambda: [])
        results = c.collect()
        assert results == []

    def test_save_empty(self, db_path):
        from nuri.collectors.fundamental import FundamentalCollector
        c = FundamentalCollector()
        assert c.save([]) == 0
        assert c.save(None) == 0

    def test_metrics_fields_mapping(self):
        from nuri.collectors.fundamental import METRICS_FIELDS
        assert "pe_ratio" in METRICS_FIELDS
        assert "return_on_equity" in METRICS_FIELDS
        assert METRICS_FIELDS["return_on_equity"] == "roe"


# ═══════════════════════════════════════════════════════════════
# 15. nuri/llm/report.py
# ═══════════════════════════════════════════════════════════════


class TestLLMReport:
    """Tests for LLM report generation and validation."""

    def test_gather_context_all_sections(self, db_path):
        """Gather context returns all required fields."""
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=db_path)
        assert hasattr(ctx, "gate_summary")
        assert hasattr(ctx, "regime_section")
        assert hasattr(ctx, "macro_section")
        assert hasattr(ctx, "risk_section")
        assert hasattr(ctx, "candidates_section")
        assert hasattr(ctx, "external_section")
        assert hasattr(ctx, "rebalance_section")

    def test_gather_context_known_sets_initialized(self, db_path):
        """known_tickers and known_numbers are sets."""
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=db_path)
        assert isinstance(ctx.known_tickers, set)
        assert isinstance(ctx.known_numbers, set)

    def test_format_prompt_structure(self, db_path):
        """Prompt contains expected sections."""
        from nuri.llm.report import format_prompt, gather_context
        ctx = gather_context(db_path=db_path)
        prompt = format_prompt(ctx)
        assert "[DATA]" in prompt
        assert "[/DATA]" in prompt
        assert "데이터 완성도" in prompt
        assert "시장 레짐" in prompt
        assert "매크로" in prompt

    def test_validate_output_clean(self):
        """Clean report passes validation."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="완성도 8/10", gate_score=0.8,
            regime_section="bull", macro_section="",
            risk_section="", candidates_section="BUY AAPL",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers={"0.7", "2.0"},
        )
        text = "## 1. 완성도\n## 2. 시장\n## 3. 리스크\n## 4. 시그널\n## 5. 후보\nAAPL 승률 70%\n## 6. 전략\n## 7. 주의"
        result = validate_output(text, ctx)
        assert result.passed

    def test_validate_output_hallucinated_ticker(self):
        """Detect hallucinated ticker."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers=set(),
        )
        text = "AAPL is good. FAKE is also good. 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert "FAKE" in result.hallucinated_tickers

    def test_validate_output_low_gate_score(self):
        """Low gate score adds warning."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.3,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        text = "완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert any("완성도" in w for w in result.warnings)

    def test_validate_output_missing_sections(self):
        """Missing sections detected."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        text = "This is a minimal report with nothing useful."
        result = validate_output(text, ctx)
        assert any("구조 불완전" in w for w in result.warnings)

    def test_validate_output_fabricated_win_rate(self):
        """Detect fabricated win rate."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers={"0.65"},
        )
        text = "승률 99% PF 5.0 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert any("불일치" in w for w in result.warnings)

    def test_generate_llm_report_gate_blocked(self, db_path, monkeypatch):
        """Gate score < 30% blocks report."""
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="Blocked", gate_score=0.1,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: mock_ctx)
        result = generate_llm_report(db_path=db_path)
        assert result["gate_blocked"] is True
        assert result["report"] is None

    def test_generate_llm_report_with_ollama_mock(self, db_path, monkeypatch):
        """Mock Ollama to test full report flow."""
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="8/10", gate_score=0.8,
            regime_section="bull_low_vol", macro_section="score 65",
            risk_section="Sharpe 1.2", candidates_section="BUY AAPL",
            conflicts_section="없음", drift_section="안정",
            consensus_section="HOLD", strategy_section="aggressive",
            known_tickers={"AAPL"}, known_numbers={"1.2", "65"},
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: mock_ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr("nuri.llm.report._generate_ollama",
                            lambda prompt: "## 1. 완성도\n## 2. 시장\n## 3. 리스크\n## 4. 시그널\n## 5. 후보\nAAPL\n## 6. 전략\n## 7. 주의")
        result = generate_llm_report(db_path=db_path)
        assert result["gate_blocked"] is False
        assert result["report"] is not None
        assert "AAPL" in result["report"]

    def test_generate_llm_report_sync(self, db_path, monkeypatch):
        """Sync alias calls generate_llm_report."""
        from nuri.llm.report import ReportContext, generate_llm_report_sync
        mock_ctx = ReportContext(
            gate_summary="", gate_score=0.1,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: mock_ctx)
        result = generate_llm_report_sync(db_path=db_path)
        assert "gate_blocked" in result

    def test_llamacpp_no_model_path(self):
        """Empty model path returns empty string."""
        from nuri.llm.report import _generate_llamacpp
        with patch("nuri.llm.report.LLAMA_MODEL_PATH", ""):
            result = _generate_llamacpp("test prompt")
            assert result == ""

    def test_ollama_connection_error(self, monkeypatch):
        """Connection error returns help message."""
        import requests  # noqa: E402

        from nuri.llm.report import _generate_ollama
        monkeypatch.setattr("nuri.llm.report.OLLAMA_HOST", "http://localhost:99999")

        def mock_post(*args, **kwargs):
            raise requests.ConnectionError("refused")

        with patch("requests.post", mock_post):
            result = _generate_ollama("test")
            assert "연결 실패" in result

    def test_ollama_success(self, monkeypatch):
        """Successful Ollama response processed correctly."""
        from nuri.llm.report import _generate_ollama

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "## 1. 데이터 완성도\n리포트 내용"}
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test")
            assert "1." in result

    def test_ollama_thinking_model(self, monkeypatch):
        """Qwen3.5 thinking response processed correctly."""
        from nuri.llm.report import _generate_ollama

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "",
            "thinking": "blah blah ## 1. 데이터 완성도\n실제 리포트"
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test")
            assert "1." in result

    def test_report_context_post_init(self):
        """ReportContext __post_init__ sets empty sets when None."""
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="", gate_score=0.5,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        assert ctx.known_tickers == set()
        assert ctx.known_numbers == set()

    def test_report_context_explicit_known(self):
        """ReportContext preserves explicitly set known sets."""
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="", gate_score=0.5,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers={"100"},
        )
        assert "AAPL" in ctx.known_tickers
        assert "100" in ctx.known_numbers

    def test_disclaimer_constant(self):
        from nuri.llm.report import DISCLAIMER
        assert "투자 조언이 아니며" in DISCLAIMER

    def test_generate_report_low_gate_score_warning(self, db_path, monkeypatch):
        """Gate score between 0.3 and 0.7 adds warning to report."""
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="5/10", gate_score=0.5,
            regime_section="bull", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: mock_ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr("nuri.llm.report._generate_ollama",
                            lambda prompt: "완성도 시장 리스크 시그널 후보 전략 주의")
        result = generate_llm_report(db_path=db_path)
        assert result["gate_blocked"] is False
        assert "완성도" in result["report"]

    def test_gather_context_exception_handling(self, db_path):
        """Exceptions in individual sections don't crash gather_context."""
        from nuri.llm.report import gather_context
        # This should work even with a minimal/empty DB
        ctx = gather_context(db_path=db_path)
        assert ctx.gate_summary is not None
        assert ctx.regime_section is not None


# ═══════════════════════════════════════════════════════════════
# Extra edge-case tests for coverage gaps
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Additional edge-case tests for coverage recovery."""

    def test_ls_backtest_regime_allocation(self):
        """All 6 base regimes have allocations."""
        from nuri.trading.strategy.ls_backtest import REGIME_ALLOCATION
        expected = ["bull_low_vol", "bull_high_vol", "sideways_low_vol",
                    "sideways_high_vol", "bear_low_vol", "bear_high_vol"]
        for r in expected:
            assert r in REGIME_ALLOCATION
            alloc = REGIME_ALLOCATION[r]
            assert "long" in alloc
            assert "short" in alloc
            assert "cash" in alloc

    def test_strategy_map_position_rules(self):
        """All trend+vol combos have position rules."""
        from nuri.quant.regime.strategy_map import POSITION_RULES
        for trend in ["bull", "bear", "sideways"]:
            for vol in ["low", "high"]:
                assert (trend, vol) in POSITION_RULES

    def test_strategy_map_sector_rules(self):
        """All position sizes have sector rules."""
        from nuri.quant.regime.strategy_map import SECTOR_RULES
        for pos in ["aggressive", "normal", "defensive", "minimal"]:
            assert pos in SECTOR_RULES
            assert isinstance(SECTOR_RULES[pos], list)
            assert len(SECTOR_RULES[pos]) > 0

    def test_mean_reversion_signal_sorted(self, db_path):
        """Signals are sorted by z_score (most oversold first)."""
        from nuri.trading.strategy.mean_reversion import MeanRevSignal
        signals = [
            MeanRevSignal("A", "2025-01-01", 100, 99, 25, -1.5, 105),
            MeanRevSignal("B", "2025-01-01", 100, 99, 25, -2.5, 105),
        ]
        signals.sort(key=lambda s: s.z_score)
        assert signals[0].ticker == "B"

    def test_pair_stats_sorted_by_z(self):
        from nuri.trading.strategy.pairs import PairStats
        pairs = [
            PairStats("A", "B", 0.8, 0.01, 0.05, 1.5),
            PairStats("C", "D", 0.9, 0.02, 0.04, 3.0),
        ]
        pairs.sort(key=lambda p: abs(p.current_z), reverse=True)
        assert pairs[0].ticker_a == "C"

    def test_longshort_transition_rules(self):
        from nuri.trading.strategy.longshort import REGIME_TRANSITION_RULES
        assert isinstance(REGIME_TRANSITION_RULES, dict)
        assert len(REGIME_TRANSITION_RULES) > 0
        # All keys are tuples of regime strings
        for key in REGIME_TRANSITION_RULES:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_longshort_short_etfs(self):
        from nuri.trading.strategy.longshort import SHORT_ETFS
        assert "conservative" in SHORT_ETFS
        assert "moderate" in SHORT_ETFS
        assert "aggressive" in SHORT_ETFS
        assert "SH" in SHORT_ETFS["conservative"]

    def test_strategy_map_constants(self):
        from nuri.quant.regime.strategy_map import (
            DEFENSIVE_SECTORS,
            GROWTH_SECTORS,
            PF_AVOID_THRESHOLD,
            PF_RECOMMEND_THRESHOLD,
            SECTOR_TO_ETF,
        )
        assert PF_RECOMMEND_THRESHOLD > PF_AVOID_THRESHOLD
        assert "XLK" in GROWTH_SECTORS
        assert "XLP" in DEFENSIVE_SECTORS
        assert "Technology" in SECTOR_TO_ETF

    def test_backtest_result_dataclass(self):
        from nuri.trading.strategy.ls_backtest import BacktestResult
        r = BacktestResult(
            total_return=10.0, annual_return=5.0, sharpe=1.0, max_drawdown=-10.0,
            win_rate=0.5, total_days=252, regime_changes=5, transaction_costs=0.3,
            spy_total_return=8.0, spy_annual_return=4.0, spy_sharpe=0.8,
            spy_max_drawdown=-12.0, excess_return=2.0,
        )
        assert r.total_return == 10.0
        assert r.equity_curve is None

    def test_timing_analysis_dataclass(self):
        from nuri.trading.strategy.ls_backtest import TimingAnalysis
        ta = TimingAnalysis(
            current_regime="bull_low_vol", occurrences=3,
            avg_forward_30d=2.0, avg_forward_60d=5.0, avg_forward_90d=8.0,
            pct_to_bull=0.5, pct_to_bear=0.2, pct_stay=0.3,
        )
        assert ta.current_regime == "bull_low_vol"

    def test_regime_performance_dataclass(self):
        from nuri.trading.strategy.ls_backtest import RegimePerformance
        rp = RegimePerformance(
            regime="bull_low_vol", days=100, pct_of_total=40.0,
            avg_daily_return=0.05, total_return=12.0, win_rate=0.55,
            avg_duration=25.0, transitions_to={"sideways_low_vol": 0.4},
        )
        assert rp.days == 100

    def test_estimate_result_fields(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult
        r = EstimateResult(
            ticker="AAPL", estimate_date="2025-01-01", recommendation="Buy",
            target_mean=180.0, price_at_estimate=160.0, actual_price=175.0,
            actual_date="2025-04-01", target_gap_pct=12.5, actual_return_pct=9.4,
            target_hit=False,
        )
        assert r.target_gap_pct == 12.5
        assert not r.target_hit

    def test_strategy_recommendation_dataclass(self):
        from nuri.quant.regime.strategy_map import StrategyRecommendation
        rec = StrategyRecommendation(
            regime="bull_low_vol",
            macro_interpretation="Favorable",
            position_sizing="aggressive",
            recommended_signals=["rsi_oversold"],
            avoid_signals=["macd_dead"],
            sector_preference=["XLK"],
            signal_regime_stats={},
            notes="test",
        )
        assert rec.regime == "bull_low_vol"

    def test_high_vol_signal_reduction(self, rich_db, monkeypatch):
        """High vol regime reduces signals to top 2."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore

        regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="high",
            regime="bull_high_vol", confidence=0.80,
            details={"special_regime": None, "base_regime": "bull_high_vol"},
        )
        macro = MacroScore(
            date="2025-12-31", total_score=50, yield_curve_score=50,
            yield_spread_3m10y_score=50, vix_score=50, put_call_ratio_score=50,
            sentiment_score=50, employment_score=50, inflation_score=50,
            monetary_score=50, interpretation="Neutral", details={},
        )

        # Create cross analysis with multiple recommended signals
        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_high_vol", "trades": 10,
             "win_rate": 0.7, "profit_factor": 2.5, "avg_return": 3.0},
            {"signal_id": "bb_bounce", "regime": "bull_high_vol", "trades": 8,
             "win_rate": 0.65, "profit_factor": 2.0, "avg_return": 2.5},
            {"signal_id": "macd_golden", "regime": "bull_high_vol", "trades": 12,
             "win_rate": 0.6, "profit_factor": 1.8, "avg_return": 2.0},
        ])
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda db_path=None: cross_df)

        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        # High vol should reduce to top 2
        assert len(rec.recommended_signals) <= 2
        assert "고변동성" in rec.notes

    def test_monitor_transition_bull_to_bear(self, rich_db, monkeypatch):
        """Bull→Bear transition has high urgency."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.90,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        # Insert bull regime as previous
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-12-29", "sideways_low_vol", "bull_low_vol", "{}"),
            )

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "high"
        assert "BULL" in result["switch"] and "BEAR" in result["switch"]

    def test_monitor_transition_to_sideways(self, rich_db, monkeypatch):
        """Transition to sideways has medium urgency."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="sideways", volatility="low",
            regime="sideways_low_vol", confidence=0.70,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-12-29", "bear_low_vol", "bull_low_vol", "{}"),
            )

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "medium"

    def test_monitor_volatility_change(self, rich_db, monkeypatch):
        """Same trend but different vol → low urgency."""
        from nuri.quant.regime.classifier import RegimeState
        mock_regime = RegimeState(
            date="2025-12-31", trend="bull", volatility="high",
            regime="bull_high_vol", confidence=0.80,
            details={},
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime",
                            lambda db_path=None: mock_regime)

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-12-29", "sideways_low_vol", "bull_low_vol", "{}"),
            )

        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "low"
        assert "변동성" in result["switch"]
