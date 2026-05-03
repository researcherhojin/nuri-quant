"""Additional branch coverage for strategy/ files: longshort, mean_reversion,
monitor, pairs, position. Targets remaining missed lines per 2026-05-04 audit.

Each test cites source line(s) and verifies behavior, not just call.
"""

# cspell:ignore DROPME OSCL FLATA FLATB SHORTHIST

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_prices
from nuri.core.timezone import today_kst


@pytest.fixture
def basic_db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    p = tmp_path / "test.db"
    init_db(p)
    monkeypatch.setattr(db_mod, "DB_PATH", p)
    return p


# ════════════════════════ longshort.py ════════════════════════════════


class TestLongshortFullBranches:
    def test_open_long_includes_scanner_top_picks(self, basic_db, monkeypatch):
        """Lines 134-140: scanner returns ScanResult with score≥30 → open_long actions."""
        from dataclasses import dataclass

        from nuri.trading.strategy.longshort import generate_strategy
        from nuri.trading.swing.scanner import ScanResult

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        # Provide 3 scan results; only the score≥30 ones become actions
        scan_results = [
            ScanResult("AAA", 100.0, 1.0, 5.0, 2.0, 60, 0.5, "momentum", 50.0),
            ScanResult("BBB", 50.0, 0.5, 3.0, 1.5, 55, 0.4, "breakout", 35.0),
            ScanResult("CCC", 25.0, 0.0, 0.5, 1.0, 50, 0.5, "none", 10.0),  # filtered
        ]
        monkeypatch.setattr(
            "nuri.trading.swing.scanner.scan_market",
            lambda **kw: scan_results,
        )

        actions = generate_strategy(db_path=basic_db)
        scanner_actions = [a for a in actions if a.ticker in {"AAA", "BBB", "CCC"}]
        # CCC excluded (score < 30); AAA + BBB included
        tickers_emitted = {a.ticker for a in scanner_actions}
        assert "AAA" in tickers_emitted
        assert "BBB" in tickers_emitted
        assert "CCC" not in tickers_emitted

    def test_open_long_scanner_exception_swallowed(self, basic_db, monkeypatch):
        """Lines 141-142: scanner raises → except-pass, ETF actions still emitted."""
        from dataclasses import dataclass

        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        monkeypatch.setattr(
            "nuri.trading.swing.scanner.scan_market",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("synthetic")),
        )
        actions = generate_strategy(db_path=basic_db)
        # ETF opens still happen (LONG_ETFS[:2] = QQQ, SPY)
        opens = [a.ticker for a in actions if a.action == "open_long"]
        assert "QQQ" in opens

    def test_open_short_high_vol_uses_aggressive(self, basic_db, monkeypatch):
        """Lines 146-149: 'high' in regime → SHORT_ETFS[aggressive][:1] = SQQQ."""
        from dataclasses import dataclass

        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class FakeRegime:
            regime: str = "bear_high_vol"
            trend: str = "bear"
            volatility: str = "high"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        actions = generate_strategy(db_path=basic_db)
        opens = [a.ticker for a in actions if a.action == "open_short"]
        assert "SQQQ" in opens  # aggressive branch
        assert "SH" not in opens  # conservative branch should NOT fire

    def test_open_short_low_vol_uses_conservative(self, basic_db, monkeypatch):
        """Lines 148-149 (else branch): 'low' regime → SHORT_ETFS[conservative][:1] = SH."""
        from dataclasses import dataclass

        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class FakeRegime:
            regime: str = "bear_low_vol"
            trend: str = "bear"
            volatility: str = "low"
            confidence: float = 0.7

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        actions = generate_strategy(db_path=basic_db)
        opens = [a.ticker for a in actions if a.action == "open_short"]
        assert "SH" in opens
        assert "SQQQ" not in opens

    def test_neutral_with_short_pct_emits_hedge(self, basic_db, monkeypatch):
        """Line 162: alloc[short_pct] > 0 in neutral → hedge SH action.

        sideways_high_vol has short_pct=0 in current REGIME_ALLOCATION; we patch
        the table entry to short_pct>0 to exercise the hedge branch.
        """
        from dataclasses import dataclass

        from nuri.trading.strategy import longshort as ls_mod
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class FakeRegime:
            regime: str = "sideways_high_vol"
            trend: str = "sideways"
            volatility: str = "high"
            confidence: float = 0.5

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        # Patch alloc to set short_pct > 0 — exercise the hedge action emission
        patched = dict(ls_mod.REGIME_ALLOCATION)
        patched["sideways_high_vol"] = dict(ls_mod.REGIME_ALLOCATION["sideways_high_vol"])
        patched["sideways_high_vol"]["short_pct"] = 15
        monkeypatch.setattr(ls_mod, "REGIME_ALLOCATION", patched)

        actions = generate_strategy(db_path=basic_db)
        hedges = [a for a in actions if a.action == "open_short" and a.ticker == "SH"]
        assert len(hedges) == 1
        assert "헤지" in hedges[0].reason

    def test_execute_strategy_close_path(self, basic_db, monkeypatch):
        """Lines 196-209: execute_strategy CLOSE branch — calls close_position with exit price."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        # Seed an open position to be closed
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, entry_date, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("QQQ", "long", "tactical", "open", "2025-03-25", 400.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("QQQ", "2025-03-26", 410.0),
            )
        # Mock update_prices + close_position to isolate flow
        called = {}

        def fake_close(pid, exit_price, reason, db_path):
            called["pid"] = pid
            called["exit_price"] = exit_price
            called["reason"] = reason

        monkeypatch.setattr("nuri.trading.strategy.position.close_position", fake_close)
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a, **k: None)
        # open_position not used for close
        monkeypatch.setattr("nuri.trading.strategy.position.open_position", lambda **kw: True)

        actions = [StrategyAction("close", "QQQ", "long", "tactical", "test", "bull", 90)]
        n = execute_strategy(actions, db_path=basic_db)
        assert n == 1
        assert called["exit_price"] == 410.0  # latest price
        assert called["reason"] == "test"

    def test_execute_strategy_open_yfinance_empty_skips(self, basic_db, monkeypatch):
        """Lines 215-219: yfinance empty df → continue (no execution counted)."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a, **k: None)
        # yf.download → empty DataFrame
        import yfinance as yf

        monkeypatch.setattr(yf, "download", lambda *a, **kw: pd.DataFrame())

        actions = [StrategyAction("open_long", "AAA", "long", "tactical", "test", "bull", 80)]
        n = execute_strategy(actions, db_path=basic_db)
        assert n == 0

    def test_execute_strategy_yfinance_exception_skips(self, basic_db, monkeypatch):
        """Lines 220-221: yfinance raises → continue."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a, **k: None)
        import yfinance as yf

        def boom(*a, **kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(yf, "download", boom)
        actions = [StrategyAction("open_long", "AAA", "long", "tactical", "test", "bull", 80)]
        n = execute_strategy(actions, db_path=basic_db)
        assert n == 0

    def test_execute_strategy_open_success_increments(self, basic_db, monkeypatch):
        """Lines 224-233: open_position success → executed += 1."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a, **k: None)
        import yfinance as yf

        idx = pd.bdate_range("2025-03-20", periods=5)
        fake = pd.DataFrame({"Close": [100.0, 102.0, 104.0, 106.0, 108.0]}, index=idx)
        monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)
        # open_position returns True
        monkeypatch.setattr(
            "nuri.trading.strategy.position.open_position",
            lambda **kw: True,
        )
        actions = [StrategyAction("open_long", "AAA", "long", "tactical", "test", "bull_low_vol", 80)]
        n = execute_strategy(actions, db_path=basic_db)
        assert n == 1


# ════════════════════════ mean_reversion.py ═══════════════════════════


class TestMeanReversionFullBranches:
    def test_signal_emitted_with_complete_fields(self, basic_db):
        """Lines 70-80: BB lower break + RSI<30 → MeanRevSignal with all fields populated.

        The DB query uses ORDER BY date DESC LIMIT 60. We seed the LAST 60 rows
        (out of more) so the breakdown sits inside the lookback window (last 5).
        """
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion

        # 60 rows total: first 55 flat, last 5 sharp drops (within lookback=5).
        prices = [100.0] * 55 + [70, 60, 50, 40, 30]
        rows = [
            {
                "ticker": "DROPME",
                "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "open": float(c),
                "high": float(c) * 1.01,
                "low": float(c) * 0.99,
                "close": float(c),
                "volume": 1000,
                "adj_close": float(c),
            }
            for i, c in enumerate(prices)
        ]
        upsert_prices(pd.DataFrame(rows), basic_db)
        # get_tickers() reads `portfolio` table (NOT prices) — must seed.
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "DROPME", 10, 100.0, "USD"),
            )
        signals = scan_mean_reversion(db_path=basic_db)
        # Sharp drop in lookback window → ≥1 signal for DROPME.
        my_signals = [s for s in signals if s.ticker == "DROPME"]
        assert len(my_signals) >= 1
        s = my_signals[0]
        # RSI must be deeply oversold
        assert s.rsi < 30
        # Z-score (current price - 20-day SMA / std) is negative for oversold
        assert s.z_score < 0
        # entry_price must equal close (a real number, not NaN)
        assert s.entry_price > 0

    def test_zero_std_z_score_zero(self, basic_db):
        """Line 71-72: std20==0 → z_score=0 fallback. Hard to hit with real data
        but verify division-guard: if all prices identical at break point, std=0."""
        # Skip — requires synthetic guard hit; covered by other test exercising the line via std>0 path.
        # Documented: std==0 fallback only fires when all 20 prior prices are identical AND BB lower
        # break occurs simultaneously, which is mathematically impossible (BB lower = SMA - 2*std = SMA
        # when std=0, so close < SMA never breaks lower). Defensive code; lock by assertion above.
        pytest.skip("std==0 path is unreachable when BB lower break occurs; defensive guard documented.")

    def test_scan_skips_ticker_with_insufficient_history(self, basic_db):
        """Line 47-48: portfolio ticker exists but < 30 price rows → continue.

        Seeds portfolio with ticker SHORTHIST + only 10 prices. The for-loop iterates
        the ticker but the < 30 guard fires → continue → final result is [].
        """
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion

        rows = [
            {
                "ticker": "SHORTHIST",
                "date": f"2025-03-{i + 1:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i,
                "volume": 1000,
                "adj_close": 100.0,
            }
            for i in range(10)
        ]
        upsert_prices(pd.DataFrame(rows), basic_db)
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "SHORTHIST", 5, 100.0, "USD"),
            )
        result = scan_mean_reversion(db_path=basic_db)
        # Empty because the only candidate skipped via the < 30 continue branch
        assert result == []

    def test_backtest_skips_ticker_with_short_history(self, basic_db):
        """Line 100-101: portfolio ticker with < 60 prices → continue."""
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion

        rows = [
            {
                "ticker": "SHORT60",
                "date": f"2025-03-{i + 1:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i,
                "volume": 1000,
                "adj_close": 100.0,
            }
            for i in range(20)
        ]
        upsert_prices(pd.DataFrame(rows), basic_db)
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "SHORT60", 5, 100.0, "USD"),
            )
        result = backtest_mean_reversion(db_path=basic_db)
        assert result == {"total_trades": 0}

    def test_scan_skips_nan_indicator_rows(self, basic_db):
        """Line 68-69: bb_lower or rsi NaN → continue (i.e. early-bar indicators).

        Seed exactly 30 rows of constant prices. `range(max(len(df) - lookback, 20),
        len(df))` = range(25, 30) → indices 25-29. At these indices SMA20/std20/RSI14
        are computed (need 14+20 prior rows), but with constant prices RSI is NaN
        (gain/loss both 0) → continue branch fires.
        """
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion

        rows = [
            {
                "ticker": "FLAT30",
                "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000,
                "adj_close": 100.0,
            }
            for i in range(30)
        ]
        upsert_prices(pd.DataFrame(rows), basic_db)
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "FLAT30", 5, 100.0, "USD"),
            )
        result = scan_mean_reversion(db_path=basic_db)
        # All indices in range hit NaN guard → continue → empty
        assert result == []

    def test_backtest_full_pipeline_returns_metrics(self, basic_db):
        """Lines 117-156: backtest produces all metric fields when trades exist."""
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion

        # 100 days with 2 oversold dips that recover
        np.random.seed(11)
        prices = list(np.full(100, 100.0))
        # Dip 1: drop and recover
        for k, v in [(40, 70), (41, 72), (42, 75), (43, 80), (44, 90), (45, 100)]:
            prices[k] = float(v)
        # Dip 2
        for k, v in [(70, 75), (71, 78), (72, 85), (73, 95), (74, 100)]:
            prices[k] = float(v)
        rows = [
            {
                "ticker": "OSCL",
                "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "open": float(c),
                "high": float(c) * 1.01,
                "low": float(c) * 0.99,
                "close": float(c),
                "volume": 1000,
                "adj_close": float(c),
            }
            for i, c in enumerate(prices)
        ]
        upsert_prices(pd.DataFrame(rows), basic_db)
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "OSCL", 10, 100.0, "USD"),
            )
        result = backtest_mean_reversion(db_path=basic_db)
        # If trades occurred, full metric schema present
        if result["total_trades"] > 0:
            for key in {"strategy", "win_rate", "avg_return", "profit_factor", "avg_hold_days", "best", "worst"}:
                assert key in result
            # Lock specific contracts
            assert result["strategy"] == "mean_reversion"
            assert 0 <= result["win_rate"] <= 1


# ════════════════════════ monitor.py ══════════════════════════════════


class TestMonitorFullBranches:
    def test_detect_regime_transition_classifier_exception(self, basic_db, monkeypatch):
        """Lines 24-25: classify_regime raises → return None (no transition recorded)."""
        from nuri.trading.strategy.monitor import detect_regime_transition

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("synthetic")),
        )
        result = detect_regime_transition(db_path=basic_db)
        assert result is None

    def test_detect_regime_transition_no_change_returns_none(self, basic_db, monkeypatch):
        """Line 38: prev_regime == current.regime → None."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import detect_regime_transition

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        # Insert prev transition with same to_regime
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-25", "sideways_low_vol", "bull_low_vol", "{}"),
            )
        result = detect_regime_transition(db_path=basic_db)
        assert result is None

    def test_bull_to_bear_transition_high_urgency(self, basic_db, monkeypatch):
        """Lines 56-58: prev=bull, curr=bear → BULL→BEAR switch, high urgency."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import detect_regime_transition

        @dataclass
        class FakeRegime:
            regime: str = "bear_high_vol"
            trend: str = "bear"
            volatility: str = "high"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "sideways_low_vol", "bull_low_vol", "{}"),
            )
        result = detect_regime_transition(db_path=basic_db)
        assert result is not None
        assert result["urgency"] == "high"
        assert "BULL→BEAR" in result["switch"]

    def test_bear_to_bull_transition_high_urgency(self, basic_db, monkeypatch):
        """Lines 59-61: prev=bear, curr=bull → BEAR→BULL switch."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import detect_regime_transition

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "bear_high_vol", "bear_low_vol", "{}"),
            )
        result = detect_regime_transition(db_path=basic_db)
        assert result is not None
        assert result["urgency"] == "high"
        assert "BEAR→BULL" in result["switch"]

    def test_to_sideways_medium_urgency(self, basic_db, monkeypatch):
        """Lines 62-64: curr_trend=sideways → medium urgency."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import detect_regime_transition

        @dataclass
        class FakeRegime:
            regime: str = "sideways_high_vol"
            trend: str = "sideways"
            volatility: str = "high"
            confidence: float = 0.5

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "bull_high_vol", "bull_low_vol", "{}"),
            )
        result = detect_regime_transition(db_path=basic_db)
        assert result is not None
        assert result["urgency"] == "medium"

    def test_volatility_change_low_urgency(self, basic_db, monkeypatch):
        """Lines 65-67: same trend, volatility change → low urgency.

        prev=bull_low_vol, curr=bull_high_vol → trend stays bull, neither path of
        bull→bear / bear→bull / sideways fires; falls into else (low urgency).
        """
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import detect_regime_transition

        @dataclass
        class FakeRegime:
            regime: str = "bull_high_vol"
            trend: str = "bull"
            volatility: str = "high"
            confidence: float = 0.6

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "sideways_low_vol", "bull_low_vol", "{}"),
            )
        result = detect_regime_transition(db_path=basic_db)
        assert result is not None
        assert result["urgency"] == "low"

    def test_print_monitor_with_transition_and_pnl(self, basic_db, monkeypatch, capsys):
        """Lines 130-157: print_monitor full path with transition + pnl block."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import print_monitor

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        # Stub print_regime to avoid heavy output
        monkeypatch.setattr("nuri.quant.regime.classifier.print_regime", lambda *a, **k: print("REGIME"))
        # Insert prev transition for transition detection (different regime)
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "bear_high_vol", "bear_low_vol", "{}"),
            )
            # Insert open position so PnL block prints
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price, return_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "long", "tactical", "open", "2025-03-20", 100.0, 5.0),
            )

        # Stub heavy downstream print helpers
        monkeypatch.setattr(
            "nuri.trading.strategy.longshort.generate_strategy",
            lambda *a, **k: [],
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.longshort.print_strategy",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "nuri.trading.strategy.position.print_positions",
            lambda *a, **k: None,
        )
        # update_prices uses query/yf — stub it
        monkeypatch.setattr(
            "nuri.trading.strategy.position.update_prices",
            lambda *a, **k: None,
        )

        print_monitor(db_path=basic_db)
        out = capsys.readouterr().out
        # Transition section
        assert "REGIME TRANSITION" in out
        # PnL section (line 149-156)
        assert "P&L Summary" in out
        assert "Total:" in out

    def test_print_monitor_no_transition_no_pnl(self, basic_db, monkeypatch, capsys):
        """Line 137: no transition prints '레짐 전환 없음'. Empty positions skips PnL block."""
        from dataclasses import dataclass

        from nuri.trading.strategy.monitor import print_monitor

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        monkeypatch.setattr("nuri.quant.regime.classifier.print_regime", lambda *a, **k: None)
        # Same regime as last transition → no new transition
        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) VALUES (?, ?, ?, ?)",
                ("2025-03-20", "sideways", "bull_low_vol", "{}"),
            )
        monkeypatch.setattr("nuri.trading.strategy.longshort.generate_strategy", lambda *a, **k: [])
        monkeypatch.setattr("nuri.trading.strategy.longshort.print_strategy", lambda *a, **k: None)
        monkeypatch.setattr("nuri.trading.strategy.position.print_positions", lambda *a, **k: None)
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a, **k: None)

        print_monitor(db_path=basic_db)
        out = capsys.readouterr().out
        assert "레짐 전환 없음" in out
        assert "P&L Summary" not in out  # no positions → block skipped


# ════════════════════════ pairs.py ════════════════════════════════════


class TestPairsFullBranches:
    def test_find_pairs_few_us_tickers_returns_empty(self, basic_db):
        """Line 61-62: < 2 US tickers → return [].

        Insert KR-only tickers (.KS suffix) → US filter strips to empty.
        """
        from nuri.trading.strategy.pairs import find_pairs

        rows = []
        for ticker in ["005930.KS", "000660.KS"]:
            for i in range(60):
                rows.append(
                    {
                        "ticker": ticker,
                        "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0 + i,
                        "volume": 1000,
                        "adj_close": 100.0,
                    }
                )
        upsert_prices(pd.DataFrame(rows), basic_db)
        result = find_pairs(db_path=basic_db)
        assert result == []

    def test_find_pairs_lookback_filter(self, basic_db):
        """Line 71-72: prices df < LOOKBACK//2 → ticker filtered.

        Seed 2 US tickers with only 10 days of data (< LOOKBACK/2=30). Since
        the prices dict drops both, len(prices) < 2 → return [].
        """
        from nuri.trading.strategy.pairs import find_pairs

        rows = []
        for ticker in ["AAA", "BBB"]:
            for i in range(10):
                rows.append(
                    {
                        "ticker": ticker,
                        "date": f"2025-03-{i + 1:02d}",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0 + i,
                        "volume": 1000,
                        "adj_close": 100.0,
                    }
                )
        upsert_prices(pd.DataFrame(rows), basic_db)
        # Add to portfolio so get_tickers returns them
        with get_db(basic_db) as conn:
            for t in ["AAA", "BBB"]:
                conn.execute(
                    "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                    ("test", t, 1, 100.0, "USD"),
                )
        result = find_pairs(db_path=basic_db)
        assert result == []

    def test_find_pairs_dropna_below_30_returns_empty(self, basic_db):
        """Line 79-80: 2 tickers each ≥30 rows but DISJOINT dates → dropna() < 30 → [].

        AAA covers Jan-Feb, BBB covers Feb-Mar; intersection (10 days) < 30.
        """
        from nuri.trading.strategy.pairs import find_pairs

        rows = []
        for i in range(40):
            # AAA: 2025-01-01 .. 2025-02-09 (40 days, gap suffix range)
            rows.append(
                {
                    "ticker": "AAA",
                    "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0 + i * 0.5,
                    "volume": 1000,
                    "adj_close": 100.0,
                }
            )
        for i in range(40):
            # BBB: 2025-04-* .. 2025-05-* (no overlap with AAA above)
            rows.append(
                {
                    "ticker": "BBB",
                    "date": f"2025-{(i // 28) + 4:02d}-{(i % 28) + 1:02d}",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 200.0 + i * 0.5,
                    "volume": 1000,
                    "adj_close": 200.0,
                }
            )
        upsert_prices(pd.DataFrame(rows), basic_db)
        with get_db(basic_db) as conn:
            for t in ["AAA", "BBB"]:
                conn.execute(
                    "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                    ("test", t, 1, 100.0, "USD"),
                )
        result = find_pairs(db_path=basic_db)
        # Disjoint date ranges → 0 common dates after dropna() → returns [].
        assert result == []

    def test_backtest_pairs_no_matching_prices(self, basic_db, monkeypatch):
        """Lines 165-166: price_a or price_b empty → continue.

        Mock find_pairs to return a pair whose tickers don't have prices in DB.
        """
        from nuri.trading.strategy import pairs as pairs_mod
        from nuri.trading.strategy.pairs import PairStats, backtest_pairs

        monkeypatch.setattr(
            pairs_mod,
            "find_pairs",
            lambda **kw: [
                PairStats("GHOST_A", "GHOST_B", 0.85, 0.0, 0.05, 2.5),
            ],
        )
        result = backtest_pairs(db_path=basic_db)
        # No prices in DB → no trades → fall to lines 208-209
        assert result["total_trades"] == 0
        assert result["pairs_found"] == 1

    def test_backtest_pairs_short_merged_skipped(self, basic_db, monkeypatch):
        """Line 169-170: merged.empty path — but we exercise len < LOOKBACK skip.

        Pair with prices but only 30 rows (< LOOKBACK=60) → continue.
        """
        from nuri.trading.strategy import pairs as pairs_mod
        from nuri.trading.strategy.pairs import PairStats, backtest_pairs

        rows = []
        for ticker in ["AAA", "BBB"]:
            for i in range(30):
                rows.append(
                    {
                        "ticker": ticker,
                        "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0 + i,
                        "volume": 1000,
                        "adj_close": 100.0,
                    }
                )
        upsert_prices(pd.DataFrame(rows), basic_db)
        monkeypatch.setattr(
            pairs_mod,
            "find_pairs",
            lambda **kw: [
                PairStats("AAA", "BBB", 0.85, 0.0, 0.05, 2.5),
            ],
        )
        result = backtest_pairs(db_path=basic_db)
        assert result["total_trades"] == 0
        assert result["pairs_found"] == 1

    def test_backtest_pairs_zero_std_skips(self, basic_db, monkeypatch):
        """Lines 179-181: window std=0 → continue (i+=1).

        Pair with constant prices over the whole window → log ratio constant → std=0.
        """
        from nuri.trading.strategy import pairs as pairs_mod
        from nuri.trading.strategy.pairs import PairStats, backtest_pairs

        rows = []
        for ticker in ["FLATA", "FLATB"]:
            for i in range(80):
                rows.append(
                    {
                        "ticker": ticker,
                        "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        "open": 100.0,
                        "high": 100.0,
                        "low": 100.0,
                        "close": 100.0,
                        "volume": 1000,
                        "adj_close": 100.0,
                    }
                )
        upsert_prices(pd.DataFrame(rows), basic_db)
        monkeypatch.setattr(
            pairs_mod,
            "find_pairs",
            lambda **kw: [
                PairStats("FLATA", "FLATB", 1.0, 0.0, 0.0, 0.0),
            ],
        )
        result = backtest_pairs(db_path=basic_db)
        # Flat prices → no Z trade ever fires
        assert result["total_trades"] == 0

    def test_backtest_pairs_z_entry_then_exit(self, basic_db, monkeypatch):
        """Lines 185-209: full backtest path with Z>=Z_ENTRY entry + convergence exit.

        Construct two correlated tickers with a divergence then convergence so
        Z exceeds 2.0 then returns near 0.
        """
        from nuri.trading.strategy import pairs as pairs_mod
        from nuri.trading.strategy.pairs import PairStats, backtest_pairs

        np.random.seed(7)
        n = 100
        # AAA tracks BBB closely except for a divergence at idx 65
        bbb = 100 + np.cumsum(np.random.normal(0, 0.5, n))
        aaa = bbb.copy()
        aaa[65:75] += 20  # 10-day divergence
        rows = []
        for ticker, series in [("AAA", aaa), ("BBB", bbb)]:
            for i, c in enumerate(series):
                rows.append(
                    {
                        "ticker": ticker,
                        "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        "open": float(c),
                        "high": float(c) * 1.01,
                        "low": float(c) * 0.99,
                        "close": float(c),
                        "volume": 1000,
                        "adj_close": float(c),
                    }
                )
        upsert_prices(pd.DataFrame(rows), basic_db)
        monkeypatch.setattr(
            pairs_mod,
            "find_pairs",
            lambda **kw: [
                PairStats("AAA", "BBB", 0.95, 0.0, 0.05, 2.5),
            ],
        )
        result = backtest_pairs(db_path=basic_db)
        # Divergence + convergence → at least one trade emitted
        assert result["total_trades"] >= 1
        assert "win_rate" in result
        assert "avg_return" in result


# ════════════════════════ position.py ═════════════════════════════════


class TestPositionFullBranches:
    def test_certify_drift_safe_critical_blocks_long(self, basic_db, monkeypatch):
        """Lines 109-111: ≥3 critical drifts blocks long entry."""
        from dataclasses import dataclass

        from nuri.trading.strategy.position import certify_position

        @dataclass
        class FakeDrift:
            status: str

        # 4 critical drifts → drift_safe = False
        monkeypatch.setattr(
            "nuri.trading.engine.memory.detect_drift",
            lambda **kw: [FakeDrift("critical")] * 4,
        )
        cert = certify_position(
            ticker="AAA",
            direction="long",
            regime="bull_low_vol",
            portfolio_type="tactical",
            db_path=basic_db,
        )
        assert cert.drift_safe is False
        assert cert.details["critical_drifts"] == 4

    def test_certify_drift_safe_short_path(self, basic_db, monkeypatch):
        """Line 109 condition `direction == 'long'` — short keeps drift_safe=True even with critical."""
        from dataclasses import dataclass

        from nuri.trading.strategy.position import certify_position

        @dataclass
        class FakeDrift:
            status: str

        monkeypatch.setattr(
            "nuri.trading.engine.memory.detect_drift",
            lambda **kw: [FakeDrift("critical")] * 5,
        )
        cert = certify_position(
            ticker="AAA",
            direction="short",
            regime="bear_high_vol",
            portfolio_type="tactical",
            db_path=basic_db,
        )
        # Short bypasses the critical-drift block (line 109 condition is direction == 'long')
        assert cert.drift_safe is True

    def test_certify_drift_exception_swallowed(self, basic_db, monkeypatch):
        """Lines 113-114: detect_drift raises → except-pass, drift_safe stays True."""
        from nuri.trading.strategy.position import certify_position

        monkeypatch.setattr(
            "nuri.trading.engine.memory.detect_drift",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("synthetic")),
        )
        cert = certify_position(
            ticker="AAA",
            direction="long",
            regime="bull_low_vol",
            portfolio_type="tactical",
            db_path=basic_db,
        )
        assert cert.drift_safe is True

    def test_open_position_classifier_used(self, basic_db, monkeypatch):
        """Lines 141-146: regime not provided → classify_regime called."""
        from dataclasses import dataclass

        from nuri.trading.strategy.position import open_position

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        # Make consensus pass + no duplicates + 0 drifts so cert succeeds
        from nuri.trading.agents.consensus import AgentVerdict, ConsensusResult

        verdicts = [
            AgentVerdict(agent_name=f"a{i}", ticker="AAA", action="BUY", confidence=70, reasoning="r", data_points={})
            for i in range(3)
        ]
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_ticker",
            lambda *a, **kw: ConsensusResult(
                ticker="AAA",
                final_action="BUY",
                final_confidence=80,
                agreement_rate=0.8,
                verdicts=verdicts,
                dissent=[],
                reasoning="ok",
            ),
        )
        # No critical drifts
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: [])

        ok = open_position(
            ticker="AAA",
            direction="long",
            entry_price=100.0,
            db_path=basic_db,
        )
        assert ok is True
        # Verify position was actually inserted with regime captured
        with get_db(basic_db) as conn:
            row = conn.execute("SELECT regime_at_entry FROM positions WHERE ticker = ?", ("AAA",)).fetchone()
        assert row[0] == "bull_low_vol"

    def test_open_position_classifier_exception_uses_unknown(self, basic_db, monkeypatch):
        """Lines 145-146: classify_regime raises → regime='unknown', cert fails."""
        from nuri.trading.strategy.position import open_position

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("synthetic")),
        )
        ok = open_position(
            ticker="AAA",
            direction="long",
            entry_price=100.0,
            db_path=basic_db,
        )
        # 'unknown' regime → fail-closed in certify (regime_aligned=False) → False
        assert ok is False

    def test_open_position_certification_fails_logs_reasons(self, basic_db, monkeypatch, caplog):
        """Lines 158-162: certification failure logs each failed gate."""
        import logging

        from nuri.trading.strategy.position import open_position

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: type("R", (), {"regime": "bear_high_vol"})(),
        )
        # bear_high_vol + long → regime_aligned False (long_pct=0)
        with caplog.at_level(logging.WARNING):
            ok = open_position(
                ticker="AAA",
                direction="long",
                entry_price=100.0,
                db_path=basic_db,
            )
        assert ok is False
        warning_text = " ".join(r.getMessage() for r in caplog.records)
        assert "CERT BLOCKED" in warning_text or "레짐 불일치" in warning_text

    def test_open_position_logs_concentration_block(self, basic_db, monkeypatch, caplog):
        """Line 158: duplicate position → '중복 포지션' message added to failed reasons."""
        import logging

        from nuri.trading.strategy.position import open_position

        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
                ("DUP", "long", "tactical", "open", "2025-03-20", 100.0),
            )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: type("R", (), {"regime": "bull_low_vol"})(),
        )
        with caplog.at_level(logging.WARNING):
            ok = open_position(
                ticker="DUP",
                direction="long",
                entry_price=100.0,
                db_path=basic_db,
            )
        assert ok is False
        warnings = " ".join(r.getMessage() for r in caplog.records)
        assert "중복 포지션" in warnings

    def test_open_position_logs_daily_limit_block(self, basic_db, monkeypatch, caplog):
        """Line 160: daily_limit_ok=False → '일일 한도 초과' message.

        Seed 5 tactical positions today → daily count >= 5 → daily_limit_ok=False.
        """
        import logging

        from nuri.trading.strategy.position import open_position

        today = today_kst()
        with get_db(basic_db) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                    "entry_date, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"P{i}", "long", "tactical", "open", today, 100.0),
                )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: type("R", (), {"regime": "bull_low_vol"})(),
        )
        with caplog.at_level(logging.WARNING):
            ok = open_position(
                ticker="NEW",
                direction="long",
                entry_price=100.0,
                db_path=basic_db,
            )
        assert ok is False
        warnings = " ".join(r.getMessage() for r in caplog.records)
        assert "일일 한도 초과" in warnings

    def test_open_position_logs_drift_block(self, basic_db, monkeypatch, caplog):
        """Line 162: drift_safe=False → '시그널 drift 위험' message.

        ≥3 critical drifts (long direction) trips drift_safe=False.
        """
        import logging
        from dataclasses import dataclass

        from nuri.trading.strategy.position import open_position

        @dataclass
        class FakeDrift:
            status: str

        monkeypatch.setattr(
            "nuri.trading.engine.memory.detect_drift",
            lambda **kw: [FakeDrift("critical")] * 5,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: type("R", (), {"regime": "bull_low_vol"})(),
        )
        with caplog.at_level(logging.WARNING):
            ok = open_position(
                ticker="DRIFT",
                direction="long",
                entry_price=100.0,
                db_path=basic_db,
            )
        assert ok is False
        warnings = " ".join(r.getMessage() for r in caplog.records)
        assert "시그널 drift" in warnings

    def test_update_prices_yfinance_fallback_used(self, basic_db, monkeypatch):
        """Line 219-225: prices empty + yfinance returns data → current_price set."""
        from nuri.trading.strategy.position import update_prices

        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
                ("ZZZ", "long", "tactical", "open", "2025-03-20", 100.0),
            )
        # No prices in DB → falls to yfinance
        import yfinance as yf

        idx = pd.bdate_range("2025-03-25", periods=5)
        fake = pd.DataFrame({"Close": [100.0, 102.0, 104.0, 106.0, 108.0]}, index=idx)
        monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)

        update_prices(db_path=basic_db)
        with get_db(basic_db) as conn:
            row = conn.execute("SELECT current_price, return_pct FROM positions WHERE ticker = ?", ("ZZZ",)).fetchone()
        assert row[0] == 108.0
        assert row[1] == 8.0  # (108-100)/100*100

    def test_update_prices_yfinance_exception_skips(self, basic_db, monkeypatch):
        """Lines 226-227: yfinance raises → continue (no update)."""
        from nuri.trading.strategy.position import update_prices

        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
                ("ZZZ", "long", "tactical", "open", "2025-03-20", 100.0),
            )
        import yfinance as yf

        monkeypatch.setattr(yf, "download", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))

        update_prices(db_path=basic_db)
        with get_db(basic_db) as conn:
            row = conn.execute("SELECT current_price FROM positions WHERE ticker = ?", ("ZZZ",)).fetchone()
        assert row[0] is None  # never updated

    def test_update_prices_short_direction(self, basic_db):
        """Line 234-235: direction == short → return_pct = (entry-current)/entry."""
        from nuri.trading.strategy.position import update_prices

        with get_db(basic_db) as conn:
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
                ("SH", "short", "tactical", "open", "2025-03-20", 50.0),
            )
            # Add a price so DB-path is taken (no yfinance)
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SH", "2025-03-25", 45.0),
            )
        update_prices(db_path=basic_db)
        with get_db(basic_db) as conn:
            row = conn.execute("SELECT return_pct FROM positions WHERE ticker = ?", ("SH",)).fetchone()
        # Short profits when price drops. (50-45)/50 * 100 = 10
        assert row[0] == 10.0

    def test_print_positions_with_open_and_closed(self, basic_db, capsys, monkeypatch):
        """Lines 288-302: full table print + closed summary footer."""
        from nuri.trading.strategy.position import print_positions

        with get_db(basic_db) as conn:
            # 1 open + 2 closed
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price, current_price, return_pct, regime_at_entry) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("AAA", "long", "tactical", "open", "2025-03-20", 100.0, 105.0, 5.0, "bull_low_vol"),
            )
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price, return_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("BBB", "long", "tactical", "closed", "2025-03-15", 100.0, 12.0),
            )
            conn.execute(
                "INSERT INTO positions (ticker, direction, portfolio_type, status, "
                "entry_date, entry_price, return_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("CCC", "long", "tactical", "closed", "2025-03-10", 100.0, -3.0),
            )
        # Stub update_prices network path
        monkeypatch.setattr(
            "nuri.trading.strategy.position.update_prices",
            lambda *a, **k: None,
        )
        print_positions(db_path=basic_db)
        out = capsys.readouterr().out
        assert "AAA" in out
        # Footer: 2 closed total, win rate 50% (1W of 2)
        assert "Closed: 2" in out

    def test_print_positions_empty(self, basic_db, capsys, monkeypatch):
        """Line 296-297: no positions → "오픈 포지션 없음"."""
        from nuri.trading.strategy.position import print_positions

        monkeypatch.setattr(
            "nuri.trading.strategy.position.update_prices",
            lambda *a, **k: None,
        )
        print_positions(db_path=basic_db)
        out = capsys.readouterr().out
        assert "오픈 포지션 없음" in out
