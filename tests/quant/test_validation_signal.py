"""Tests for validation_signal — split from test_quant_all.py."""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst
from tests.quant._helpers import (  # noqa: F401
    _insert_spy_data,
    _insert_spy_data_trend,
    _seed_macro,
    _seed_portfolio,
    _seed_prices,
    _seed_spy_data,
)


class TestSignalBacktest:
    """C-1 (from test_validation.py)."""

    def test_rsi_oversold_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1
        assert results[0].won is True

    def test_holding_period_exit(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["rsi_oversold"], db_path=sample_prices)
        assert len(results) >= 1
        assert results[0].holding_days == 20

    def test_macd_signal_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["macd_golden", "macd_dead"], db_path=sample_prices)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id in ("macd_golden", "macd_dead")

    def test_bb_bounce_detection(self, sample_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST", signals=["bb_bounce"], db_path=sample_prices)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "bb_bounce"
            assert r.holding_days == 20

    def test_sma_cross_with_long_data(self, long_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="LONG", signals=["sma_golden", "sma_dead"], db_path=long_prices)
        assert isinstance(results, list)

    def test_scorecard_calculation(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "TEST", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "TEST", "2025-02-01", 100, "2025-02-21", 95, -5.0, 20, False),
            SignalResult("rsi_oversold", "TEST", "2025-03-01", 100, "2025-03-21", 108, 8.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None and c.signal_id == "rsi_oversold"]
        assert len(total) == 1
        card = total[0]
        assert card.total_trades == 3
        assert abs(card.win_rate - 2 / 3) < 0.01
        assert abs(card.avg_return - (10 - 5 + 8) / 3) < 0.1
        assert abs(card.profit_factor - 3.6) < 0.1

    def test_scorecard_all_wins(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("bb_bounce", "A", "2025-01-01", 100, "2025-01-21", 110, 10.0, 20, True),
            SignalResult("bb_bounce", "A", "2025-02-01", 100, "2025-02-21", 105, 5.0, 20, True),
        ]
        cards = generate_scorecard(results)
        total = [c for c in cards if c.ticker is None]
        assert total[0].profit_factor == float("inf")
        assert total[0].win_rate == 1.0

    def test_empty_signals(self, db_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NONEXIST", signals=["rsi_oversold"], db_path=db_path)
        assert results == []


class TestSignalBacktest_R60:
    """(from test_sixty_percent.py)."""

    def test_compute_indicators(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty:
            result = compute_indicators(df)
            assert "rsi_14" in result.columns or "sma_20" in result.columns

    def test_backtest_signals(self, full_db, tmp_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(db_path=full_db)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2024-06-01", 150.0, "2024-06-15", 160.0, 6.67, 10, True),
            SignalResult("rsi_oversold", "AAPL", "2024-07-01", 155.0, "2024-07-15", 150.0, -3.23, 10, False),
            SignalResult("macd_golden", "MSFT", "2024-06-01", 300.0, "2024-06-15", 320.0, 6.67, 10, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0

    def test_print_scorecard(self, capsys):
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        scorecards = [
            SignalScorecard(
                signal_id="rsi_oversold", ticker=None,
                total_trades=50, win_rate=0.6,
                avg_return=3.5, median_return=2.5,
                max_return=15.0, max_loss=-8.0,
                profit_factor=2.0, avg_holding_days=10.0,
            ),
        ]
        print_scorecard(scorecards)
        output = capsys.readouterr().out
        assert "rsi_oversold" in output


class TestVolumeSpikeSignal:
    """(from test_signals_extended.py)."""

    def test_volume_spike_detection(self, volume_spike_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="VSPK", signals=["volume_spike"], db_path=volume_spike_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "volume_spike"
        assert results[0].holding_days == 10

    def test_volume_spike_not_triggered_on_normal(self, volume_spike_prices):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("VSPK",), db_path=volume_spike_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)
        entries = detect_signal_entries(df, "volume_spike")
        for idx in entries:
            vol = df["volume"].iloc[idx]
            vol_avg = df["volume_sma_20"].iloc[idx]
            assert vol > vol_avg * 3


class TestGapSignals:
    """(from test_signals_extended.py)."""

    def test_gap_up_detection(self, gap_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="GAPTEST", signals=["gap_up"], db_path=gap_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "gap_up"
        assert results[0].holding_days == 10

    def test_gap_down_detection(self, gap_prices):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="GAPTEST", signals=["gap_down"], db_path=gap_prices)
        assert len(results) >= 1
        assert results[0].signal_id == "gap_down"
        assert results[0].holding_days == 10

    def test_gap_signals_no_false_positive(self, gap_prices):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("GAPTEST",), db_path=gap_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = compute_indicators(df)
        gap_up_entries = detect_signal_entries(df, "gap_up")
        gap_down_entries = detect_signal_entries(df, "gap_down")
        for idx in gap_up_entries:
            assert df["open"].iloc[idx] > df["close"].iloc[idx - 1] * 1.02
        for idx in gap_down_entries:
            assert df["open"].iloc[idx] < df["close"].iloc[idx - 1] * 0.98


class TestSignalDefinitions:
    """(from test_signals_extended.py)."""

    def test_new_signals_in_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "volume_spike" in SIGNAL_DEFINITIONS
        assert "gap_up" in SIGNAL_DEFINITIONS
        assert "gap_down" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["volume_spike"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_up"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_down"]["hold_days"] == 10

    def test_buy_sell_classification(self):
        from nuri.quant.validation.signal_backtest import BUY_SIGNALS, SELL_SIGNALS
        assert "volume_spike" in BUY_SIGNALS
        assert "gap_up" in BUY_SIGNALS
        assert "gap_down" in SELL_SIGNALS

    def test_original_7_signals_unchanged(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        original = ["rsi_oversold", "rsi_overbought", "macd_golden", "macd_dead",
                     "sma_golden", "sma_dead", "bb_bounce"]
        for sig_id in original:
            assert sig_id in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["rsi_oversold"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["macd_golden"]["hold_days"] is None
        assert SIGNAL_DEFINITIONS["sma_golden"]["hold_days"] is None

    def test_macro_signals_in_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "vix_reversal" in SIGNAL_DEFINITIONS
        assert "pcr_reversal" in SIGNAL_DEFINITIONS
        assert "yield_curve_recovery" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["vix_reversal"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["pcr_reversal"]["hold_days"] == 15
        assert SIGNAL_DEFINITIONS["yield_curve_recovery"]["hold_days"] is None

    def test_macro_signals_in_buy_classification(self):
        from nuri.quant.validation.signal_backtest import BUY_SIGNALS
        assert "vix_reversal" in BUY_SIGNALS
        assert "pcr_reversal" in BUY_SIGNALS
        assert "yield_curve_recovery" in BUY_SIGNALS

    def test_total_signal_count_is_20(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        # 15 base + 5 chart pattern signals (macd_bullish_turn, macd_bearish_turn,
        # bb_squeeze_breakout, near_52w_low_bounce, volume_profile_resistance)
        assert len(SIGNAL_DEFINITIONS) == 20

    def test_chart_pattern_signals_in_definitions(self):
        from nuri.quant.validation.signal_backtest import (
            BUY_SIGNALS,
            SELL_SIGNALS,
            SIGNAL_DEFINITIONS,
        )
        chart_signals = {
            "macd_bullish_turn", "macd_bearish_turn", "bb_squeeze_breakout",
            "near_52w_low_bounce", "volume_profile_resistance",
        }
        assert chart_signals.issubset(SIGNAL_DEFINITIONS.keys())
        assert "macd_bullish_turn" in BUY_SIGNALS
        assert "macd_bearish_turn" in SELL_SIGNALS
        assert "bb_squeeze_breakout" in BUY_SIGNALS
        assert "near_52w_low_bounce" in BUY_SIGNALS
        assert "volume_profile_resistance" in BUY_SIGNALS


class TestVixReversal:
    """(from test_signals_extended.py)."""

    def test_vix_reversal_detection(self, vix_reversal_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["vix_reversal"], db_path=vix_reversal_data)
        assert len(results) >= 1
        assert results[0].signal_id == "vix_reversal"
        assert results[0].holding_days == 20

    def test_vix_reversal_no_false_positive_1day(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "TEST1D",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        macro_records = []
        for i, d in enumerate(dates):
            vix = 35.0 if i == 21 else (24.0 if i == 22 else 18.0)
            macro_records.append({"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": vix, "source": "test"})
        upsert_macro(macro_records, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST1D", signals=["vix_reversal"], db_path=db_path)
        assert len(results) == 0


class TestPcrReversal:
    """(from test_signals_extended.py)."""

    def test_pcr_reversal_detection(self, pcr_reversal_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["pcr_reversal"], db_path=pcr_reversal_data)
        assert len(results) >= 1
        assert results[0].signal_id == "pcr_reversal"
        assert results[0].holding_days == 15


class TestYieldCurveRecovery:
    """(from test_signals_extended.py)."""

    def test_yield_curve_recovery_detection(self, yield_curve_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SPY", signals=["yield_curve_recovery"], db_path=yield_curve_data)
        assert len(results) >= 1
        assert results[0].signal_id == "yield_curve_recovery"

    def test_graceful_skip_no_macro_data(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "NOMACRO",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="NOMACRO", signals=["vix_reversal", "pcr_reversal", "yield_curve_recovery"], db_path=db_path,
        )
        assert results == []


class TestInsiderCluster:
    """(from test_signals_extended.py)."""

    def test_insider_cluster_detection(self, insider_cluster_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="INSD", signals=["insider_cluster"], db_path=insider_cluster_data)
        assert len(results) >= 1
        assert results[0].signal_id == "insider_cluster"
        assert results[0].holding_days == 20

    def test_insider_cluster_no_data_graceful(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOINSD",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NOINSD", signals=["insider_cluster"], db_path=db_path)
        assert results == []


class TestShortSqueeze:
    """(from test_signals_extended.py)."""

    def test_short_squeeze_detection(self, short_squeeze_data):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="SQZZ", signals=["short_squeeze"], db_path=short_squeeze_data)
        assert len(results) >= 1
        assert results[0].signal_id == "short_squeeze"
        assert results[0].holding_days == 15

    def test_short_squeeze_no_data_graceful(self, db_path):
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOSI",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="NOSI", signals=["short_squeeze"], db_path=db_path)
        assert results == []


class TestSignalBacktest_R27:
    """(from test_coverage_round27.py)."""

    def test_compute_indicators_pandas_fallback(self):
        from nuri.quant.validation.signal_backtest import compute_indicators
        dates = pd.bdate_range("2024-01-01", periods=50)
        df = pd.DataFrame({
            "date": dates,
            "close": np.random.uniform(100, 200, 50),
            "volume": np.random.uniform(100000, 500000, 50),
        })
        result = compute_indicators(df)
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "bb_lower" in result.columns
        assert "volume_sma_20" in result.columns

    def test_merge_macro_data(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        _seed_macro(db_path)
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-28"]), "close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_data_no_date_column(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_vix" not in result.columns

    def test_merge_macro_data_fallback_yield(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_2y_yield", "2025-03-28", 4.0))
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("us_10y_yield", "2025-03-28", 4.5))
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-28"]), "close": [100.0]})
        result = merge_macro_data(df, db_path=db_path)
        assert "macro_yield_spread" in result.columns

    def test_merge_data_signals(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, transaction_type, shares, value) VALUES (?,?,?,?,?)",
                    ("AAPL", f"2025-03-{20+i:02d}", "Purchase", 100, 15000),
                )
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-25", "2025-03-26", "2025-03-27"]), "close": [150, 151, 152]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_data_signals_no_date(self, db_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        df = pd.DataFrame({"close": [100]})
        result = merge_data_signals(df, "AAPL", db_path=db_path)
        assert "insider_buy_count_10d" not in result.columns

    def test_entry_detectors_individual(self):
        from nuri.quant.validation.signal_backtest import (
            _entry_gap_down,
            _entry_gap_up,
            _entry_insider_cluster,
            _entry_pcr_reversal,
            _entry_short_squeeze,
            _entry_vix_reversal,
            _entry_volume_spike,
        )
        df = pd.DataFrame({"open": [100, 105], "close": [100, 102]})
        assert _entry_gap_up(df, 1) is True
        df = pd.DataFrame({"open": [100, 95], "close": [100, 98]})
        assert _entry_gap_down(df, 1) is True
        df = pd.DataFrame({"volume": [100000] * 20 + [500000], "volume_sma_20": [100000] * 20 + [100000]})
        assert _entry_volume_spike(df, 20) is True
        df = pd.DataFrame({"macro_vix": [35, 32, 31, 30, 24]})
        assert _entry_vix_reversal(df, 4) is True
        df2 = pd.DataFrame({"close": [100, 101]})
        assert _entry_vix_reversal(df2, 1) is False
        pcr_vals = [0.7] * 15 + [1.3, 1.2, 1.1, 1.0, 0.9, 0.75]
        df = pd.DataFrame({"macro_pcr": pcr_vals})
        assert _entry_pcr_reversal(df, len(pcr_vals) - 1) is True
        df = pd.DataFrame({"insider_buy_count_10d": [0, 1, 2, 3]})
        assert _entry_insider_cluster(df, 3) is True
        df = pd.DataFrame({"short_interest": [5, 5, 15, 15, 15, 15], "close": [100, 101, 102, 103, 104, 105]})
        assert _entry_short_squeeze(df, 5) is True

    def test_exit_functions(self):
        from nuri.quant.validation.signal_backtest import (
            _exit_macd_dead,
            _exit_macd_golden,
            _exit_sma_dead,
            _exit_sma_golden,
            _exit_yield_curve_recovery,
        )
        df = pd.DataFrame({"macd": [1.0, -0.5], "macd_signal": [0.5, 0.5]})
        assert _exit_macd_golden(df, 1) is True
        assert _exit_macd_golden(df, 0) is False
        df = pd.DataFrame({"macd": [-1.0, 0.5], "macd_signal": [-0.5, -0.5]})
        assert _exit_macd_dead(df, 1) is True
        df = pd.DataFrame({"sma_50": [200, 150], "sma_200": [190, 180]})
        assert _exit_sma_golden(df, 1) is True
        df = pd.DataFrame({"sma_50": [150, 200], "sma_200": [180, 180]})
        assert _exit_sma_dead(df, 1) is True
        df = pd.DataFrame({"macro_yield_spread": [0.5, -0.1]})
        assert _exit_yield_curve_recovery(df, 1) is True
        df2 = pd.DataFrame({"close": [100]})
        assert _exit_yield_curve_recovery(df2, 0) is False

    def test_backtest_signals_with_data(self, db_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        _seed_prices(db_path, "AAPL", days=60)
        _seed_portfolio(db_path, [("AAPL", 150.0, 10)])
        results = backtest_signals(ticker="AAPL", signals=["rsi_oversold", "gap_up"], db_path=db_path)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2025-01-01", 100, "2025-01-20", 110, 10.0, 20, True),
            SignalResult("rsi_oversold", "AAPL", "2025-02-01", 110, "2025-02-20", 105, -4.5, 20, False),
            SignalResult("rsi_oversold", "TSLA", "2025-01-10", 200, "2025-01-30", 220, 10.0, 20, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0
        total_cards = [s for s in scorecards if s.ticker is None]
        assert len(total_cards) >= 1

    def test_generate_scorecard_empty(self):
        from nuri.quant.validation.signal_backtest import generate_scorecard
        assert generate_scorecard([]) == []

    def test_print_scorecard(self, capsys):
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "데이터가 없습니다" in captured.out
        sc = [SignalScorecard("rsi_oversold", None, 10, 0.6, 5.0, 4.0, 15.0, -3.0, 2.0, 15.0)]
        print_scorecard(sc)

    def test_detect_signal_entries_unknown(self):
        from nuri.quant.validation.signal_backtest import detect_signal_entries
        df = pd.DataFrame({"close": [100, 101]})
        assert detect_signal_entries(df, "nonexistent_signal") == []

    def test_compute_exit_hold_days(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": list(range(30))})
        assert compute_exit(df, 5, "rsi_oversold") == 25
        assert compute_exit(df, 15, "rsi_oversold") is None

    def test_compute_exit_signal_based(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({
            "close": list(range(10)),
            "macd": [1, 1, 1, 0.5, 0.3, -0.1, -0.5, -1, -1, -1],
            "macd_signal": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        })
        result = compute_exit(df, 1, "macd_golden")
        assert result == 5

    def test_public_api_functions_exist(self):
        from nuri.quant.validation.signal_backtest import (
            compute_exit,
            compute_indicators,
            detect_signal_entries,
            merge_data_signals,
            merge_macro_data,
        )
        assert compute_indicators is not None
        assert detect_signal_entries is not None
        assert compute_exit is not None
        assert merge_macro_data is not None
        assert merge_data_signals is not None


class TestMacroSignalDetectors:
    """(from test_coverage_round19.py)."""

    def _make_df(self, n=30):
        return pd.DataFrame({"date": pd.date_range("2025-01-01", periods=n),
                             "close": np.linspace(100, 110, n),
                             "open": np.linspace(99, 109, n),
                             "volume": [1000000] * n})

    def test_vix_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        df["macro_vix"] = 32.0
        df.loc[26:, "macro_vix"] = 24.0
        assert _entry_vix_reversal(df, 26) is True

    def test_vix_reversal_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        df["macro_vix"] = 20.0
        assert _entry_vix_reversal(df, 10) is False

    def test_vix_reversal_missing_column(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        assert _entry_vix_reversal(df, 10) is False

    def test_pcr_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        df["macro_pcr"] = 0.9
        df.loc[5:10, "macro_pcr"] = 1.3
        df.loc[22:, "macro_pcr"] = 0.7
        assert _entry_pcr_reversal(df, 25) is True

    def test_pcr_reversal_no_peak(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        df["macro_pcr"] = 0.7
        assert _entry_pcr_reversal(df, 25) is False

    def test_yield_curve_recovery_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [-0.5, -0.4, -0.3, -0.2, -0.1, 0.05, 0.1, 0.2, 0.3, 0.4]
        assert _entry_yield_curve_recovery(df, 5) is True

    def test_yield_curve_recovery_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [0.5] * 10
        assert _entry_yield_curve_recovery(df, 5) is False


class TestDataSignalDetectors:
    """(from test_coverage_round19.py)."""

    def test_insider_cluster_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_insider_cluster
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100] * 10,
            "insider_buy_count_10d": [0, 1, 2, 2, 3, 4, 4, 3, 2, 1],
        })
        assert _entry_insider_cluster(df, 4) is True

    def test_short_squeeze_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_short_squeeze
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "short_interest": [12.0] * 10,
        })
        assert _entry_short_squeeze(df, 5) is True


class TestComputeExit_R19:
    """(from test_coverage_round19.py)."""

    def test_hold_days_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(50)})
        assert compute_exit(df, 5, "rsi_oversold") == 25

    def test_hold_days_exit_out_of_range(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(10)})
        assert compute_exit(df, 5, "rsi_oversold") is None

    def test_signal_exit_function(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(20), "macd": [0.5] * 10 + [-0.5] * 10, "macd_signal": [0.0] * 20})
        assert compute_exit(df, 0, "macd_golden") == 10

    def test_yield_curve_recovery_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(20), "macro_yield_spread": [0.5] * 10 + [-0.5] * 10})
        assert compute_exit(df, 0, "yield_curve_recovery") == 10


class TestMergeDataSignals_R19:
    """(from test_coverage_round19.py)."""

    def test_merge_with_insider_trades(self, tmp_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-01", "Tim Cook", "P-Purchase", 1000, 190000.0),
            )
        dates = pd.date_range("2025-02-25", periods=10, freq="B")
        df = pd.DataFrame({"date": dates, "close": [190.0] * 10})
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_empty_db(self, tmp_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=5), "close": [100] * 5})
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns


class TestMergeMacroData_R19:
    """(from test_coverage_round19.py)."""

    def test_merge_macro(self, rich_db):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        df = pd.DataFrame({"date": dates, "close": np.linspace(100, 110, 20)})
        result = merge_macro_data(df, db_path=rich_db)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_no_date_col(self):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100, 101]})
        result = merge_macro_data(df)
        assert "macro_vix" not in result.columns


class TestSignalBacktestDeep:
    """(from test_coverage_round8.py)."""

    def test_compute_indicators(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            result = compute_indicators(df)
            assert "rsi_14" in result.columns
            assert "macd" in result.columns

    def test_detect_signal_entries(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "rsi_oversold")
            assert isinstance(entries, list)

    def test_compute_exit(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_exit, compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "rsi_oversold")
            if entries:
                exit_idx = compute_exit(df, entries[0], "rsi_oversold")
                assert exit_idx is None or isinstance(exit_idx, int)


class TestSignalBacktestMore:
    """(from test_coverage_round12.py)."""

    def test_macd_signal(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "macd_golden")
            assert isinstance(entries, list)

    def test_bb_bounce_signal(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "bb_bounce")
            assert isinstance(entries, list)

    def test_volume_spike(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "volume_spike")
            assert isinstance(entries, list)

    def test_sma_golden(self, rich_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import compute_indicators, detect_signal_entries
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if len(df) > 50:
            df = compute_indicators(df)
            entries = detect_signal_entries(df, "sma_golden")
            assert isinstance(entries, list)


class TestSignalBacktestRun:
    """(from test_coverage_round13.py)."""

    def test_backtest_signals(self, rich_db):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals()
        assert isinstance(results, list)


class TestSignalBacktestHelpers:
    """(from test_coverage_final.py)."""

    def test_signal_definitions(self):
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert isinstance(SIGNAL_DEFINITIONS, dict)
        assert len(SIGNAL_DEFINITIONS) > 0

    def test_backtest_signals_callable(self):
        from nuri.quant.validation.signal_backtest import backtest_signals
        assert callable(backtest_signals)
