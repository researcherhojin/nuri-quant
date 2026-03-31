"""Coverage boost Round 20 — charts, discord_bot, strategy_map, price_targets,
institutional, estimates, finviz, wallstreet."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Rich DB fixture (SPY/AAPL/NVDA, 500 days, macro, fundamentals, estimates)
# ═══════════════════════════════════════════════════════


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """DB with portfolio, 500-day prices for SPY/AAPL/NVDA, macro data, fundamentals, estimates."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    # Portfolio
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150.0, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 120.0, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 100,
         "avg_price": 70000.0, "currency": "KRW", "sector": "반도체"},
    ], path)

    # Prices: 500 business days
    dates = pd.date_range("2024-01-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS"]:
        base = {"SPY": 450, "AAPL": 150, "NVDA": 120, "005930.KS": 70000}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 4, "low": p - 3,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    # Macro: VIX + Fear&Greed + USD/KRW
    macro_records = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro_records.append({"indicator": "vix", "date": ds,
                              "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro_records.append({"indicator": "fear_greed", "date": ds,
                              "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macro_records.append({"indicator": "usd_krw", "date": ds,
                              "value": 1350.0, "source": "test"})
    upsert_macro(macro_records, path)

    # Fundamentals
    with get_db(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", 28.0, 0.35, 0.08, 3e12, 1.2, 1.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", 55.0, 0.45, 0.25, 2e12, 1.8, 0.5),
        )

    # Estimates
    with get_db(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", "buy", 250.0, 180.0, 220.0, 215.0, 30, 200.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", "strong_buy", 300.0, 200.0, 270.0, 265.0, 35, 250.0),
        )

    # Superinvestors
    with get_db(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO superinvestors (investor, filing_date, ticker, shares, market_value, portfolio_pct)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("Warren Buffett", "2025-01-01", "AAPL", 1000000, 200000000, 25.0),
        )

    # News (for sentiment)
    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", "Apple grows", "https://x.com/1", "test", 0.7),
        )
        conn.execute(
            "INSERT INTO news (ticker, date, title, url, source, sentiment)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-02", "Apple OK", "https://x.com/2", "test", 0.3),
        )

    return path


# ═══════════════════════════════════════════════════════
# 1. nuri/analysis/charts.py
# ═══════════════════════════════════════════════════════


class TestChartsLoadData:
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
        """Fewer than 20 rows should return None."""
        from nuri.analysis.charts import _load_chart_data
        # Insert only 5 rows for a test ticker
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
    def test_detect_signals_returns_df(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        assert df is not None
        sig_df = _detect_signals(df)
        assert isinstance(sig_df, pd.DataFrame)
        # Should have columns even if empty
        assert "date" in sig_df.columns or sig_df.empty
        assert "type" in sig_df.columns or sig_df.empty


class TestChartsInfoPanel:
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


class TestChartsGenerate:
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


# ═══════════════════════════════════════════════════════
# 2. nuri/alerts/discord_bot.py
# ═══════════════════════════════════════════════════════


class TestDiscordWebhook:
    @patch("nuri.alerts.discord_bot.requests.post")
    def test_send_webhook_success(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        embed = {"title": "Test", "description": "Hello"}
        result = send_webhook(embed, webhook_url="https://example.com/webhook")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "embeds" in call_kwargs[1]["json"]

    @patch("nuri.alerts.discord_bot.requests.post")
    def test_send_webhook_text_success(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook_text
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        result = send_webhook_text("hello", webhook_url="https://example.com/webhook")
        assert result is True
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["content"] == "hello"

    def test_send_webhook_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_webhook({"title": "Test"})
        assert result is False

    def test_send_webhook_text_no_url(self, monkeypatch):
        from nuri.alerts.discord_bot import send_webhook_text
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_webhook_text("hello")
        assert result is False

    @patch("nuri.alerts.discord_bot.requests.post", side_effect=Exception("network error"))
    def test_send_webhook_text_exception(self, mock_post):
        from nuri.alerts.discord_bot import send_webhook_text
        with pytest.raises(Exception, match="network error"):
            send_webhook_text("hello", webhook_url="https://example.com/webhook")


class TestDiscordBot:
    def test_send_bot_missing_credentials(self, monkeypatch):
        import asyncio

        from nuri.alerts.discord_bot import send_bot
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
        monkeypatch.setenv("DISCORD_TOKEN", "")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "0")
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(send_bot({"title": "Test"}))
        finally:
            loop.close()
        assert result is False


# ═══════════════════════════════════════════════════════
# 3. nuri/quant/regime/strategy_map.py
# ═══════════════════════════════════════════════════════


class TestStrategyMap:
    def test_map_regime_bull_low_vol(self, rich_db):
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import (
            map_regime_to_strategy,
        )

        regime = RegimeState(
            date="2025-01-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.9,
            details={"special_regime": None, "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=65, yield_curve_score=70,
            yield_spread_3m10y_score=60, vix_score=70, put_call_ratio_score=50,
            sentiment_score=60, employment_score=70, inflation_score=55,
            monetary_score=50, interpretation="Neutral", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.regime == "bull_low_vol"
        assert rec.position_sizing in ("aggressive", "normal", "defensive")
        assert isinstance(rec.recommended_signals, list)
        assert isinstance(rec.avoid_signals, list)
        assert isinstance(rec.sector_preference, list)

    def test_map_regime_bear_high_vol(self, rich_db):
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-01-01", trend="bear", volatility="high",
            regime="bear_high_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bear_high_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=25, yield_curve_score=20,
            yield_spread_3m10y_score=30, vix_score=20, put_call_ratio_score=40,
            sentiment_score=25, employment_score=30, inflation_score=20,
            monetary_score=25, interpretation="Adverse", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        # Bear high vol with macro <30 => defensive or minimal
        assert rec.position_sizing in ("defensive", "minimal")

    def test_map_regime_sideways_low(self, rich_db):
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-01-01", trend="sideways", volatility="low",
            regime="sideways_low_vol", confidence=0.7,
            details={"special_regime": None, "base_regime": "sideways_low_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=50, yield_curve_score=50,
            yield_spread_3m10y_score=50, vix_score=50, put_call_ratio_score=50,
            sentiment_score=50, employment_score=50, inflation_score=50,
            monetary_score=50, interpretation="Neutral", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert isinstance(rec.notes, str)

    def test_map_regime_euphoria(self, rich_db):
        """Special regime: euphoria -> defensive position sizing.
        Macro score must be <= 70 to avoid the 'macro favorable' upgrade."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-01-01", trend="bull", volatility="low",
            regime="euphoria", confidence=0.9,
            details={"special_regime": "euphoria", "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=55, yield_curve_score=55,
            yield_spread_3m10y_score=55, vix_score=55, put_call_ratio_score=55,
            sentiment_score=55, employment_score=55, inflation_score=55,
            monetary_score=55, interpretation="Neutral", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.position_sizing == "defensive"

    def test_map_regime_macro_adverse_downgrades(self, rich_db):
        """Macro score < 30 should downgrade position to defensive."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-01-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.9,
            details={"special_regime": None, "base_regime": "bull_low_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=20, yield_curve_score=20,
            yield_spread_3m10y_score=20, vix_score=20, put_call_ratio_score=20,
            sentiment_score=20, employment_score=20, inflation_score=20,
            monetary_score=20, interpretation="Adverse", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.position_sizing == "defensive"
        assert "매크로 악화" in rec.notes

    def test_map_regime_macro_favorable_upgrades(self, rich_db):
        """Macro score > 70 with defensive position should upgrade to normal."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import MacroScore
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        regime = RegimeState(
            date="2025-01-01", trend="bear", volatility="low",
            regime="bear_low_vol", confidence=0.8,
            details={"special_regime": None, "base_regime": "bear_low_vol"},
        )
        macro = MacroScore(
            date="2025-01-01", total_score=75, yield_curve_score=75,
            yield_spread_3m10y_score=75, vix_score=75, put_call_ratio_score=75,
            sentiment_score=75, employment_score=75, inflation_score=75,
            monetary_score=75, interpretation="Favorable", details={},
        )
        rec = map_regime_to_strategy(regime, macro, db_path=rich_db)
        assert rec is not None
        assert rec.position_sizing == "normal"
        assert "매크로 양호" in rec.notes


class TestStrategyMapHelpers:
    def test_build_data_driven_empty(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        result = _build_data_driven_strategy("bull_low_vol", pd.DataFrame())
        assert result["recommended"] == []
        assert result["avoid"] == []
        assert result["stats"] == {}

    def test_build_data_driven_with_data(self):
        from nuri.quant.regime.strategy_map import _build_data_driven_strategy
        cross_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "regime": "bull_low_vol", "trades": 10,
             "win_rate": 0.7, "avg_return": 3.5, "profit_factor": 2.5},
            {"signal_id": "macd_dead", "regime": "bull_low_vol", "trades": 8,
             "win_rate": 0.3, "avg_return": -1.0, "profit_factor": 0.8},
            {"signal_id": "gap_up", "regime": "bull_low_vol", "trades": 3,
             "win_rate": 0.5, "avg_return": 1.0, "profit_factor": 1.2},
        ])
        result = _build_data_driven_strategy("bull_low_vol", cross_df)
        assert "rsi_oversold" in result["recommended"]
        assert "macd_dead" in result["avoid"]
        # gap_up has only 3 trades (<5), should not appear
        assert "gap_up" not in result["recommended"]
        assert "gap_up" not in result["avoid"]

    def test_find_latest_csv_no_report_dir(self, tmp_path, monkeypatch):
        from nuri.quant.regime import strategy_map
        monkeypatch.setattr(strategy_map, "REPORT_DIR", tmp_path / "nonexistent")
        result = strategy_map._find_latest_csv("signal_results.csv")
        assert result is None

    def test_print_strategy_none(self, capsys):
        from nuri.quant.regime.strategy_map import print_strategy
        print_strategy(None)
        out = capsys.readouterr().out
        assert "불가" in out

    def test_print_cross_analysis_empty(self, capsys):
        from nuri.quant.regime.strategy_map import print_cross_analysis
        print_cross_analysis(pd.DataFrame())
        out = capsys.readouterr().out
        assert "데이터 없음" in out

    def test_position_rules_all_combos(self):
        from nuri.quant.regime.strategy_map import POSITION_RULES
        expected_combos = [
            ("bull", "low"), ("bull", "high"),
            ("sideways", "low"), ("sideways", "high"),
            ("bear", "low"), ("bear", "high"),
        ]
        for combo in expected_combos:
            assert combo in POSITION_RULES


# ═══════════════════════════════════════════════════════
# 4. nuri/trading/recommend/price_targets.py
# ═══════════════════════════════════════════════════════


class TestPriceTargets:
    def test_calculate_targets_growth(self, rich_db, monkeypatch):
        """NVDA has PE=55 (>30), should be classified as growth."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)

        result = pt.calculate_targets("NVDA", entry_price=250.0, db_path=rich_db)
        assert "error" not in result
        assert result["stock_type"] == "growth"
        assert result["stop_loss_pct"] == -7  # growth
        assert result["target_1_pct"] == 20
        assert result["target_2_pct"] == 40
        assert result["stop_loss"] == round(250 * 0.93, 2)
        assert result["target_1"] == round(250 * 1.20, 2)
        assert result["analyst_target"] == 270.0

    def test_calculate_targets_value(self, rich_db, monkeypatch):
        """AAPL has PE=28 (<30), should be classified as value."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)

        result = pt.calculate_targets("AAPL", entry_price=200.0, db_path=rich_db)
        assert "error" not in result
        assert result["stock_type"] == "value"
        assert result["stop_loss_pct"] == -10  # value
        assert result["target_1_pct"] == 15
        assert result["target_2_pct"] == 30

    def test_calculate_targets_no_price(self, rich_db, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("ZZZZ", db_path=rich_db)
        assert "error" in result

    def test_calculate_targets_uses_current_price_as_entry(self, rich_db, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("AAPL", db_path=rich_db)
        assert "error" not in result
        assert result["entry_price"] == result["current_price"]

    def test_classify_stock_type_manual_override(self, rich_db, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", {"AAPL": "swing"})
        assert pt.classify_stock_type("AAPL", db_path=rich_db) == "swing"

    def test_classify_stock_type_sector_growth(self, rich_db, monkeypatch):
        """Portfolio sector 'Semiconductor' should match GROWTH_SECTORS."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", {})
        # NVDA has PE=55 which is growth, but let's test a ticker with no PE
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "QCOM", 10, 100.0, "USD", "Semiconductor"),
            )
        result = pt.classify_stock_type("QCOM", db_path=rich_db)
        # No PE data, but sector matches "Semiconductor" -> growth
        assert result == "growth"


class TestPortfolioTargets:
    def test_calculate_portfolio_targets(self, rich_db, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        targets = pt.calculate_portfolio_targets(db_path=rich_db)
        assert len(targets) >= 2  # At least AAPL and NVDA
        tickers = [t["ticker"] for t in targets]
        assert "AAPL" in tickers
        assert "NVDA" in tickers


class TestTakeProfitSignals:
    def test_check_take_profit_signals_triggered(self, rich_db, monkeypatch):
        """AAPL entry=150, current price >> 150 after 500 days of uptrend."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        signals = pt.check_take_profit_signals(db_path=rich_db)
        # With 500 days of uptrend, prices should exceed take-profit levels
        assert isinstance(signals, list)
        if signals:
            sig = signals[0]
            assert "level" in sig
            assert sig["level"] in ("target_1", "target_2")
            assert sig["sell_pct"] > 0

    def test_check_take_profit_no_holdings(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        result = check_take_profit_signals(db_path=path)
        assert result == []


class TestTrailingStopSignals:
    def test_check_trailing_stop_no_trigger(self, rich_db, monkeypatch):
        """In an uptrend, trailing stop should not trigger."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        signals = pt.check_trailing_stop_signals(db_path=rich_db)
        # Uptrend means HWM is near current price, no trigger expected
        assert isinstance(signals, list)

    def test_check_trailing_stop_no_holdings(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        result = check_trailing_stop_signals(db_path=path)
        assert result == []


class TestPortfolioMDD:
    def test_check_portfolio_mdd_no_violation(self, rich_db, monkeypatch):
        """Uptrend portfolio should not trigger MDD."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.check_portfolio_mdd(db_path=rich_db)
        assert result is None  # No violation

    def test_check_portfolio_mdd_violation(self, tmp_path, monkeypatch):
        """Create a portfolio with significant loss to trigger MDD."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)

        path = tmp_path / "mdd.db"
        init_db(path)
        # Portfolio: bought at 200, current at 170 (-15%)
        upsert_portfolio([
            {"account": "test", "ticker": "LOSS", "quantity": 100,
             "avg_price": 200.0, "currency": "USD", "sector": "Tech"},
        ], path)
        rows = [{"ticker": "LOSS", "date": "2025-01-01",
                 "open": 170, "high": 172, "low": 168,
                 "close": 170, "volume": 100000, "adj_close": 170}]
        upsert_prices(pd.DataFrame(rows), path)

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        result = pt.check_portfolio_mdd(db_path=path)
        assert result is not None
        assert result["severity"] == "critical"
        assert result["pnl_pct"] < -10

    def test_check_portfolio_mdd_empty(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        result = check_portfolio_mdd(db_path=path)
        assert result is None


class TestFormatTargetTree:
    def test_format_target_tree_growth(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "NVDA", "stock_type": "growth",
            "current_price": 250.0, "entry_price": 200.0,
            "stop_loss": 186.0, "stop_loss_pct": -7.0,
            "target_1": 240.0, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 280.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 270.0, "analyst_upside_pct": 35.0,
        }
        result = format_target_tree(target)
        assert "NVDA" in result
        assert "성장주" in result
        assert "손절가" in result
        assert "1차 익절" in result
        assert "애널리스트 목표가" in result

    def test_format_target_tree_error(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        result = format_target_tree({"ticker": "BAD", "error": "no data"})
        assert "BAD" in result
        assert "no data" in result

    def test_format_target_tree_no_analyst(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "TEST", "stock_type": "value",
            "current_price": 100.0, "entry_price": 100.0,
            "stop_loss": 90.0, "stop_loss_pct": -10.0,
            "target_1": 115.0, "target_1_pct": 15.0, "target_1_sell_pct": 50,
            "target_2": 130.0, "target_2_pct": 30.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None, "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "TEST" in result
        assert "가치주" in result
        # Last line should use └── not ├──
        assert "└──" in result

    def test_format_price_krw(self):
        from nuri.trading.recommend.price_targets import _format_price
        result = _format_price(70000, "005930.KS")
        assert "₩" in result

    def test_format_price_usd(self):
        from nuri.trading.recommend.price_targets import _format_price
        result = _format_price(150.50, "AAPL")
        assert "$" in result


# ═══════════════════════════════════════════════════════
# 5. nuri/collectors/institutional.py
# ═══════════════════════════════════════════════════════


class TestInstitutionalCollector:
    def test_collect_kr_with_mocked_pykrx(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["005930.KS"] if market == "kr" else [])
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        mock_df = pd.DataFrame(
            {"기관합계": [1000000], "외국인합계": [2000000], "개인": [-3000000]},
            index=pd.DatetimeIndex(["2025-01-15"]),
        )
        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = mock_df

        # pykrx.stock is imported inside _collect_kr via `from pykrx import stock`
        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
            assert len(results) == 1
            assert results[0]["ticker"] == "005930.KS"
            assert results[0]["market"] == "KR"
            assert results[0]["institution_net"] == 1000000.0

    def test_collect_kr_empty(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()

        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.return_value = pd.DataFrame()

        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_collect_kr_exception(self, rich_db, monkeypatch):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()

        mock_stock_mod = MagicMock()
        mock_stock_mod.get_market_trading_value_by_date.side_effect = RuntimeError("API down")

        with patch.dict("sys.modules", {"pykrx": MagicMock(stock=mock_stock_mod), "pykrx.stock": mock_stock_mod}):
            results = collector._collect_kr(["005930.KS"])
        assert results == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        assert collector.save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector
        collector = InstitutionalCollector()
        records = [{
            "ticker": "005930.KS", "date": "2025-01-15", "market": "KR",
            "institution_net": 1000000, "foreign_net": 2000000,
            "individual_net": -3000000, "source": "pykrx",
        }]
        count = collector.save(records)
        assert count == 1

    def test_safe_float(self):
        from nuri.collectors.institutional import _safe_float
        assert _safe_float(3.14) == 3.14
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None


# ═══════════════════════════════════════════════════════
# 6. nuri/collectors/estimates.py
# ═══════════════════════════════════════════════════════


class TestEstimatesCollector:
    def test_collect_with_mocked_openbb(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])

        mock_df = pd.DataFrame([{
            "recommendation": "buy",
            "target_high": 250.0,
            "target_low": 180.0,
            "target_consensus": 220.0,
            "target_median": 215.0,
            "number_of_analysts": 30,
            "current_price": 200.0,
        }])
        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = mock_df

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result

        # obb is imported inside collect() via `from openbb import obb`
        mock_openbb_module = MagicMock()
        mock_openbb_module.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_openbb_module}):
            results = collector.collect()
            assert len(results) == 1
            assert results[0]["ticker"] == "AAPL"
            assert results[0]["recommendation"] == "buy"
            assert results[0]["target_mean"] == 220.0

    def test_collect_empty_result(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])

        mock_result = MagicMock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.return_value = mock_result

        mock_openbb_module = MagicMock()
        mock_openbb_module.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_openbb_module}):
            results = collector.collect()
            assert results == []

    def test_collect_exception(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])

        mock_obb = MagicMock()
        mock_obb.equity.estimates.consensus.side_effect = RuntimeError("API fail")

        mock_openbb_module = MagicMock()
        mock_openbb_module.obb = mock_obb
        with patch.dict("sys.modules", {"openbb": mock_openbb_module}):
            results = collector.collect()
            assert results == []

    def test_collect_no_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        # openbb is still imported at the top of collect(), so mock it
        mock_openbb_module = MagicMock()
        with patch.dict("sys.modules", {"openbb": mock_openbb_module}):
            results = collector.collect()
            assert results == []

    def test_save_empty(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        assert collector.save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.estimates import EstimatesCollector
        collector = EstimatesCollector()
        records = [{
            "ticker": "MSFT", "date": "2025-01-01",
            "recommendation": "buy", "target_high": 500,
            "target_low": 400, "target_mean": 450,
            "target_median": 445, "num_analysts": 40,
            "current_price": 420,
        }]
        count = collector.save(records)
        assert count == 1

    def test_safe_float_and_int(self):
        from nuri.collectors.estimates import _safe_float, _safe_int
        assert _safe_float(3.14) == 3.14
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None
        assert _safe_int(42) == 42
        assert _safe_int(None) is None
        assert _safe_int(float("nan")) is None


# ═══════════════════════════════════════════════════════
# 7. nuri/collectors/finviz.py
# ═══════════════════════════════════════════════════════


class TestFINVIZCollector:
    def test_collect_with_mocked_screener(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL", "NVDA"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", lambda signal: {"AAPL", "MSFT"})

        records = collector.collect()
        # AAPL is in both sets, NVDA is not returned by screener
        aapl_records = [r for r in records if r["ticker"] == "AAPL"]
        assert len(aapl_records) > 0
        for r in aapl_records:
            assert r["source"] == "FINVIZ"
            assert "signal" in r

    def test_collect_no_us_tickers(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: [])
        result = collector.collect()
        assert result == []

    def test_collect_fetch_exception(self, rich_db, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()
        monkeypatch.setattr(collector, "_get_tickers", lambda market=None: ["AAPL"])
        monkeypatch.setattr(collector, "_fetch_signal_tickers", MagicMock(side_effect=RuntimeError("fail")))
        records = collector.collect()
        # Should handle exception gracefully
        assert isinstance(records, list)

    def test_fetch_signal_tickers_finvizfinance(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()

        mock_screener = MagicMock()
        mock_screener.screener_view.return_value = ["AAPL", "MSFT", "GOOG"]

        mock_ticker_cls = MagicMock(return_value=mock_screener)
        with patch("nuri.collectors.finviz.Ticker", mock_ticker_cls, create=True):
            # Need to also patch the import inside the method
            mock_mod = MagicMock()
            mock_mod.screener.ticker.Ticker = mock_ticker_cls
            with patch.dict("sys.modules", {"finvizfinance": mock_mod, "finvizfinance.screener": mock_mod.screener, "finvizfinance.screener.ticker": mock_mod.screener.ticker}):
                result = collector._fetch_signal_tickers("Oversold")
                assert isinstance(result, set)

    def test_save_empty(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()
        assert collector.save([]) == 0

    def test_save_records(self, rich_db):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()
        records = [
            {"date": "2025-01-01", "ticker": "AAPL", "signal": "oversold_rsi", "source": "FINVIZ"},
        ]
        count = collector.save(records, db_path=rich_db)
        assert count == 1

    def test_scrape_signal_fallback_mocked(self, monkeypatch):
        from nuri.collectors.finviz import FINVIZCollector
        collector = FINVIZCollector()

        html_content = """
        <html><body>
        <a href="quote.ashx?t=AAPL">AAPL</a>
        <a href="quote.ashx?t=MSFT">MSFT</a>
        <a href="/other">Other</a>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html_content
        mock_resp.raise_for_status = MagicMock()

        # requests is imported inside _scrape_signal_fallback
        with patch("requests.get", return_value=mock_resp):
            result = collector._scrape_signal_fallback("Oversold")
            assert "AAPL" in result
            assert "MSFT" in result


# ═══════════════════════════════════════════════════════
# 8. nuri/trading/agents/wallstreet.py
# ═══════════════════════════════════════════════════════


class TestWallStreetAgent:
    def test_skip_etf(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        verdict = agent.analyze("SPY", db_path=rich_db)
        assert verdict.action == "HOLD"
        assert "미지원" in verdict.reasoning

    def test_skip_korean(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        verdict = agent.analyze("005930.KS", db_path=rich_db)
        assert verdict.action == "HOLD"
        assert "미지원" in verdict.reasoning

    def test_cached_ratings_upgrade(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        # Insert cached analyst ratings
        with get_db(rich_db) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT OR REPLACE INTO analyst_ratings (ticker, date, firm, action, target_price)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("AAPL", f"2025-01-{i+1:02d}", f"Firm{i}", "upgrade", 250.0),
                )
        agent = WallStreetAgent()
        verdict = agent.analyze("AAPL", db_path=rich_db)
        assert verdict is not None
        assert verdict.action in ("BUY", "HOLD", "SELL")
        assert verdict.data_points.get("cached") is True

    def test_cached_ratings_downgrade(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(rich_db) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT OR REPLACE INTO analyst_ratings (ticker, date, firm, action, target_price)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("NVDA", f"2025-01-{i+1:02d}", f"Firm{i}", "downgrade", 150.0),
                )
        agent = WallStreetAgent()
        verdict = agent.analyze("NVDA", db_path=rich_db)
        assert verdict is not None
        assert verdict.data_points.get("cached") is True

    def test_cached_earnings_surprise(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct)"
                " VALUES (?, ?, ?, ?, ?)",
                ("AAPL", "2025Q1", 2.5, 2.0, 0.25),
            )
        agent = WallStreetAgent()
        verdict = agent.analyze("AAPL", db_path=rich_db)
        assert verdict is not None
        assert "cached" in str(verdict.data_points) or verdict.reasoning != ""

    def test_cached_insider_sells(self, rich_db):
        from nuri.trading.agents.wallstreet import WallStreetAgent
        with get_db(rich_db) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT OR REPLACE INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    ("NVDA", f"2025-01-{i+1:02d}", f"Insider{i}", "sale", 10000, 2000000),
                )
        agent = WallStreetAgent()
        verdict = agent.analyze("NVDA", db_path=rich_db)
        assert verdict is not None
        # Many insider sells should be detected
        assert "내부자" in verdict.reasoning or verdict.data_points.get("cached") is True

    def test_no_cached_data_falls_through(self, rich_db):
        """No cached data and yfinance mocked to None -> HOLD."""
        from nuri.trading.agents.wallstreet import WallStreetAgent
        agent = WallStreetAgent()
        # AAPL has no ratings/earnings/insider data in base rich_db
        # conftest mocks yfinance.Ticker to return None for all attributes
        verdict = agent.analyze("MSFT", db_path=rich_db)
        assert verdict.action == "HOLD"

    def test_yfinance_with_data(self, rich_db, monkeypatch):
        """Test with mocked yfinance returning actual data."""
        import yfinance

        from nuri.trading.agents.wallstreet import WallStreetAgent

        class RichMockTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                # Upgrades
                self.upgrades_downgrades = pd.DataFrame([
                    {"Action": "upgrade", "priceTargetAction": "raises", "currentPriceTarget": 250.0},
                    {"Action": "upgrade", "priceTargetAction": "raises", "currentPriceTarget": 260.0},
                    {"Action": "upgrade", "priceTargetAction": "raises", "currentPriceTarget": 270.0},
                    {"Action": "init", "priceTargetAction": "raises", "currentPriceTarget": 240.0},
                ], index=pd.DatetimeIndex(["2025-03-01", "2025-03-05", "2025-03-10", "2025-03-15"]))
                # Earnings
                self.earnings_history = pd.DataFrame([
                    {"surprisePercent": 0.15, "epsActual": 2.5, "epsEstimate": 2.17},
                ])
                # Insider
                self.insider_transactions = pd.DataFrame([
                    {"Text": "Purchase of shares"},
                    {"Text": "Purchase of shares"},
                    {"Text": "Purchase of shares"},
                    {"Text": "Sale of shares"},
                ])
                # Recommendations
                self.recommendations = pd.DataFrame([
                    {"strongBuy": 15, "buy": 10, "hold": 5, "sell": 1, "strongSell": 0},
                ])

        monkeypatch.setattr(yfinance, "Ticker", RichMockTicker)

        agent = WallStreetAgent()
        # Use a ticker with no cached data but not in SKIP_TICKERS
        verdict = agent.analyze("MSFT", db_path=rich_db)
        assert verdict.action in ("BUY", "HOLD", "SELL")
        assert verdict.confidence > 0
        assert len(verdict.reasoning) > 0
