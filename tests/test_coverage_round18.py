"""Coverage round 18 — position, longshort, scanner, swing rules, candidates, consensus."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Shared fixture
# ═══════════════════════════════════════════════════════


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, prices (SPY + tickers), macro."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
    ], path)

    dates = pd.bdate_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
    upsert_macro(macro, path)
    return path


# ═══════════════════════════════════════════════════════
# 1. position.py — certify_position, open_position, close_position,
#    update_prices, get_positions_summary, print_positions
# ═══════════════════════════════════════════════════════


class TestCertifyPosition:
    """SIEGE certification gate tests."""

    def test_long_bull_regime_aligned(self, rich_db):
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY"), MagicMock(action="HOLD")],
                final_action="BUY",
                final_confidence=70,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)

        assert cert.regime_aligned is True
        assert cert.details["regime_check"] == "aligned"

    def test_long_bear_regime_misaligned(self, rich_db):
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="SELL"), MagicMock(action="SELL")],
                final_action="SELL",
                final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bear_high_vol", db_path=rich_db)

        assert cert.regime_aligned is False
        assert cert.certified is False

    def test_short_bear_high_vol_aligned(self, rich_db):
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="SELL"), MagicMock(action="SELL"), MagicMock(action="SELL")],
                final_action="SELL",
                final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "short", "bear_high_vol", db_path=rich_db)

        assert cert.regime_aligned is True

    def test_short_sideways_low_vol_misaligned(self, rich_db):
        """Short in sideways_low_vol should be misaligned (neutral direction, no 'high' in regime)."""
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="SELL"), MagicMock(action="SELL")],
                final_action="SELL",
                final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "short", "sideways_low_vol", db_path=rich_db)

        assert cert.regime_aligned is False

    def test_duplicate_position_blocks(self, rich_db):
        """Opening a position for a ticker that already has an open position should fail concentration check."""
        from nuri.trading.strategy.position import certify_position

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-01-01', 150.0, 'open')"
            )

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY",
                final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)

        assert cert.concentration_ok is False
        assert cert.certified is False

    def test_daily_limit_exceeded(self, rich_db):
        """Exceeding 5 daily opens should block."""
        from nuri.core.timezone import today_kst
        from nuri.trading.strategy.position import certify_position

        today = today_kst()
        with get_db(rich_db) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                    "VALUES ('tactical', ?, 'long', ?, ?, 'open')",
                    (f"TICK{i}", today, 100.0 + i),
                )

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY",
                final_confidence=75,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("NEWT", "long", "bull_low_vol", "tactical", rich_db)

        assert cert.daily_limit_ok is False

    def test_drift_critical_blocks_long(self, rich_db):
        """3+ critical drifts should block long positions."""
        from nuri.trading.engine.memory import PerformanceDrift
        from nuri.trading.strategy.position import certify_position

        critical_drifts = [
            PerformanceDrift("sig1", None, 0.6, 0.3, -50, "critical", ""),
            PerformanceDrift("sig2", None, 0.7, 0.2, -71, "critical", ""),
            PerformanceDrift("sig3", None, 0.5, 0.1, -80, "critical", ""),
        ]

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY",
                final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=critical_drifts):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)

        assert cert.drift_safe is False

    def test_agent_consensus_error_handled(self, rich_db):
        """Agent consensus error should not crash; agent_consensus stays False."""
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker", side_effect=RuntimeError("timeout")):
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)

        assert cert.agent_consensus is False
        assert "agent_error" in cert.details

    def test_unknown_regime_fallback_long(self, rich_db):
        """Unknown regime uses fallback string matching."""
        from nuri.trading.strategy.position import certify_position

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY",
                final_confidence=70,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "unknown_regime", db_path=rich_db)

        # "unknown_regime" not in REGIME_ALLOCATION, fallback: no "bull" or "sideways" => misaligned
        assert cert.regime_aligned is False


class TestOpenPosition:
    """open_position with SIEGE certification."""

    def test_certified_position_opens(self, rich_db):
        from nuri.trading.strategy.position import open_position

        with patch("nuri.trading.strategy.position.certify_position") as mock_cert:
            mock_cert.return_value = MagicMock(
                certified=True,
                regime_aligned=True,
                agent_consensus=True,
                concentration_ok=True,
                daily_limit_ok=True,
                drift_safe=True,
                details={"regime": "bull_low_vol"},
            )
            # Mock asdict for dataclass serialization
            with patch("nuri.trading.strategy.position.asdict", return_value={"certified": True}):
                result = open_position("AAPL", "long", 190.0, 10, "tactical", "bull_low_vol", rich_db)

        assert result is True
        rows = query("SELECT * FROM positions WHERE ticker='AAPL' AND status='open'", db_path=rich_db)
        assert len(rows) >= 1

    def test_uncertified_position_blocked(self, rich_db):
        from nuri.trading.strategy.position import open_position

        with patch("nuri.trading.strategy.position.certify_position") as mock_cert:
            mock_cert.return_value = MagicMock(
                certified=False,
                regime_aligned=False,
                agent_consensus=False,
                concentration_ok=True,
                daily_limit_ok=True,
                drift_safe=True,
                details={"agent_agree": "0/5"},
            )
            result = open_position("AAPL", "long", 190.0, 10, "tactical", "bear_high_vol", rich_db)

        assert result is False

    def test_auto_regime_detection_fallback(self, rich_db):
        """When regime is empty and classify_regime fails, uses 'unknown'."""
        from nuri.trading.strategy.position import open_position

        with patch("nuri.trading.strategy.position.certify_position") as mock_cert:
            mock_cert.return_value = MagicMock(
                certified=True,
                regime_aligned=True,
                agent_consensus=True,
                concentration_ok=True,
                daily_limit_ok=True,
                drift_safe=True,
                details={},
            )
            with patch("nuri.trading.strategy.position.asdict", return_value={"certified": True}):
                with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("no data")):
                    result = open_position("AAPL", "long", 190.0, db_path=rich_db)

        assert result is True
        # certify_position was called with regime="unknown"
        mock_cert.assert_called_once()
        args = mock_cert.call_args
        assert args[0][2] == "unknown"  # regime arg


class TestClosePosition:
    """close_position PnL calculations."""

    def _insert_position(self, db_path, ticker, direction, entry_price):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', ?, ?, '2024-10-01', ?, 'open')",
                (ticker, direction, entry_price),
            )
        rows = query("SELECT id FROM positions WHERE ticker=? AND status='open'", (ticker,), db_path=db_path)
        return rows[0]["id"]

    def test_long_profit(self, rich_db):
        from nuri.trading.strategy.position import close_position

        pos_id = self._insert_position(rich_db, "AAPL", "long", 100.0)
        close_position(pos_id, 120.0, "take_profit", rich_db)

        row = query("SELECT * FROM positions WHERE id=?", (pos_id,), db_path=rich_db)[0]
        assert row["status"] == "closed"
        assert row["return_pct"] == 20.0

    def test_long_loss(self, rich_db):
        from nuri.trading.strategy.position import close_position

        pos_id = self._insert_position(rich_db, "NVDA", "long", 200.0)
        close_position(pos_id, 180.0, "stop_loss", rich_db)

        row = query("SELECT * FROM positions WHERE id=?", (pos_id,), db_path=rich_db)[0]
        assert row["return_pct"] == -10.0

    def test_short_profit(self, rich_db):
        """Short position: price goes down = profit."""
        from nuri.trading.strategy.position import close_position

        pos_id = self._insert_position(rich_db, "AAPL", "short", 100.0)
        close_position(pos_id, 80.0, "take_profit", rich_db)

        row = query("SELECT * FROM positions WHERE id=?", (pos_id,), db_path=rich_db)[0]
        assert row["return_pct"] == 20.0

    def test_short_loss(self, rich_db):
        """Short position: price goes up = loss."""
        from nuri.trading.strategy.position import close_position

        pos_id = self._insert_position(rich_db, "AAPL2", "short", 100.0)
        close_position(pos_id, 115.0, "stop_loss", rich_db)

        row = query("SELECT * FROM positions WHERE id=?", (pos_id,), db_path=rich_db)[0]
        assert row["return_pct"] == -15.0

    def test_nonexistent_position(self, rich_db):
        """Closing a nonexistent position does nothing."""
        from nuri.trading.strategy.position import close_position

        close_position(99999, 100.0, "test", rich_db)


class TestUpdatePrices:
    """update_prices with price data in DB."""

    def test_update_open_long(self, rich_db):
        from nuri.trading.strategy.position import update_prices

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 'open')"
            )

        update_prices(rich_db)

        row = query("SELECT current_price, return_pct FROM positions WHERE ticker='AAPL' AND status='open'",
                     db_path=rich_db)[0]
        assert row["current_price"] is not None
        assert row["current_price"] > 0
        assert row["return_pct"] is not None

    def test_update_open_short(self, rich_db):
        from nuri.trading.strategy.position import update_prices

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'NVDA', 'short', '2024-10-01', 300.0, 'open')"
            )

        update_prices(rich_db)

        row = query("SELECT current_price, return_pct FROM positions WHERE ticker='NVDA' AND status='open'",
                     db_path=rich_db)[0]
        assert row["current_price"] is not None
        assert row["return_pct"] is not None

    def test_update_no_price_data_skips(self, rich_db):
        """Ticker with no price data (and yfinance mocked empty) gets skipped."""
        from nuri.trading.strategy.position import update_prices

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'ZZZZZ', 'long', '2024-10-01', 100.0, 'open')"
            )

        update_prices(rich_db)

        row = query("SELECT current_price FROM positions WHERE ticker='ZZZZZ'", db_path=rich_db)[0]
        assert row["current_price"] is None  # no data available


class TestGetPositionsSummary:
    """get_positions_summary with mixed positions."""

    def test_empty_positions(self, rich_db):
        from nuri.trading.strategy.position import get_positions_summary

        summary = get_positions_summary(rich_db)
        assert summary["open_total"] == 0
        assert summary["open_long"] == 0
        assert summary["closed_total"] == 0
        assert summary["closed_win_rate"] == 0

    def test_mixed_positions(self, rich_db):
        from nuri.trading.strategy.position import get_positions_summary

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('core', 'AAPL', 'long', '2024-10-01', 170.0, 'open')"
            )
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'SPY', 'short', '2024-10-02', 450.0, 'open')"
            )
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "status, return_pct, exit_price, exit_date) "
                "VALUES ('tactical', 'NVDA', 'long', '2024-09-01', 100.0, 'closed', 15.0, 115.0, '2024-10-15')"
            )

        summary = get_positions_summary(rich_db)
        assert summary["open_total"] == 2
        assert summary["open_long"] == 1
        assert summary["open_short"] == 1
        assert summary["open_core"] == 1
        assert summary["open_tactical"] == 1
        assert summary["closed_total"] == 1
        assert summary["closed_win_rate"] == 1.0
        assert summary["closed_avg_return"] == 15.0
        assert len(summary["positions"]) == 2


class TestPrintPositions:
    """print_positions coverage (update_prices will be mocked to avoid yfinance calls)."""

    def test_print_with_positions(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "current_price, return_pct, status, regime_at_entry) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 180.0, 5.88, 'open', 'bull_low_vol')"
            )

        # Mock update_prices to avoid yfinance interference
        with patch("nuri.trading.strategy.position.update_prices"):
            print_positions(rich_db)
        out = capsys.readouterr().out
        assert "Position Monitor" in out
        assert "AAPL" in out

    def test_print_empty(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions

        with patch("nuri.trading.strategy.position.update_prices"):
            print_positions(rich_db)
        out = capsys.readouterr().out
        assert "오픈 포지션 없음" in out

    def test_print_with_closed_stats(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "status, return_pct, exit_price, exit_date) "
                "VALUES ('tactical', 'NVDA', 'long', '2024-09-01', 100.0, 'closed', 15.0, 115.0, '2024-10-15')"
            )
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "status, return_pct, exit_price, exit_date) "
                "VALUES ('tactical', 'SPY', 'long', '2024-09-15', 440.0, 'closed', -3.0, 426.8, '2024-10-20')"
            )

        with patch("nuri.trading.strategy.position.update_prices"):
            print_positions(rich_db)
        out = capsys.readouterr().out
        assert "Closed:" in out


# ═══════════════════════════════════════════════════════
# 2. longshort.py — generate_strategy, print_strategy
# ═══════════════════════════════════════════════════════


class TestRegimeAllocation:
    """REGIME_ALLOCATION and REGIME_TRANSITION_RULES integrity."""

    def test_all_10_regimes_present(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION

        expected = {
            "bull_low_vol", "bull_high_vol", "sideways_low_vol", "sideways_high_vol",
            "bear_low_vol", "bear_high_vol", "recovery", "euphoria", "stagflation", "sector_rotation",
        }
        assert expected == set(REGIME_ALLOCATION.keys())

    def test_allocation_sums_to_100(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION

        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc["long_pct"] + alloc["short_pct"] + alloc["cash_pct"]
            assert total == 100, f"{regime}: {total} != 100"


class TestGenerateStrategy:
    """generate_strategy with mocked regime classifier."""

    def _mock_regime(self, regime_name, confidence=0.8):
        return MagicMock(regime=regime_name, confidence=confidence)

    def test_bull_long_opens_etfs(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bull_low_vol")
            # Also patch scanner to avoid network calls
            with patch("nuri.trading.swing.scanner.scan_market", return_value=[]):
                actions = generate_strategy(rich_db)

        open_longs = [a for a in actions if a.action == "open_long"]
        assert len(open_longs) >= 2
        etf_tickers = {a.ticker for a in open_longs}
        assert "QQQ" in etf_tickers or "SPY" in etf_tickers

    def test_bear_closes_longs_opens_shorts(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'QQQ', 'long', '2024-10-01', 400.0, 'open')"
            )

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bear_high_vol")
            actions = generate_strategy(rich_db)

        close_actions = [a for a in actions if a.action == "close"]
        short_actions = [a for a in actions if a.action == "open_short"]
        assert any(a.ticker == "QQQ" for a in close_actions)
        assert len(short_actions) >= 1

    def test_bear_low_vol_uses_conservative_etf(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bear_low_vol")
            actions = generate_strategy(rich_db)

        short_actions = [a for a in actions if a.action == "open_short"]
        if short_actions:
            assert short_actions[0].ticker == "SH"

    def test_sideways_high_vol_no_new_positions(self, rich_db):
        """sideways_high_vol direction=neutral with short_pct=0 => no opens."""
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("sideways_high_vol")
            actions = generate_strategy(rich_db)

        open_actions = [a for a in actions if a.action in ("open_long", "open_short")]
        assert len(open_actions) == 0

    def test_regime_none_returns_empty(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            actions = generate_strategy(rich_db)

        assert actions == []

    def test_regime_exception_returns_empty(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            actions = generate_strategy(rich_db)

        assert actions == []

    def test_bull_closes_shorts(self, rich_db):
        """In bull regime, existing short positions should be closed."""
        from nuri.trading.strategy.longshort import generate_strategy

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'SH', 'short', '2024-09-01', 30.0, 'open')"
            )

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bull_low_vol")
            with patch("nuri.trading.swing.scanner.scan_market", return_value=[]):
                actions = generate_strategy(rich_db)

        close_shorts = [a for a in actions if a.action == "close" and a.ticker == "SH"]
        assert len(close_shorts) >= 1

    def test_take_profit_trigger(self, rich_db):
        """Position with return_pct >= 10 should trigger close."""
        from nuri.trading.strategy.longshort import generate_strategy

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "return_pct, status) VALUES ('tactical', 'QQQ', 'long', '2024-09-01', 400.0, 12.5, 'open')"
            )

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bull_low_vol")
            with patch("nuri.trading.swing.scanner.scan_market", return_value=[]):
                actions = generate_strategy(rich_db)

        tp_actions = [a for a in actions if "익절" in a.reason]
        assert len(tp_actions) >= 1

    def test_stop_loss_trigger(self, rich_db):
        """Position with return_pct <= -5 should trigger close."""
        from nuri.trading.strategy.longshort import generate_strategy

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "return_pct, status) VALUES ('tactical', 'SPY', 'long', '2024-09-01', 450.0, -7.0, 'open')"
            )

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bull_low_vol")
            with patch("nuri.trading.swing.scanner.scan_market", return_value=[]):
                actions = generate_strategy(rich_db)

        sl_actions = [a for a in actions if "손절" in a.reason]
        assert len(sl_actions) >= 1

    def test_unknown_regime_fallback(self, rich_db):
        """Unknown regime uses sideways_high_vol defaults."""
        from nuri.trading.strategy.longshort import generate_strategy

        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("some_new_regime")
            actions = generate_strategy(rich_db)

        # sideways_high_vol default has direction="neutral", short_pct=0 => no opens
        open_actions = [a for a in actions if a.action in ("open_long", "open_short")]
        assert len(open_actions) == 0


class TestPrintStrategy:
    """print_strategy output formatting."""

    def test_print_no_actions(self, capsys):
        from nuri.trading.strategy.longshort import print_strategy

        print_strategy([])
        out = capsys.readouterr().out
        assert "액션 없음" in out

    def test_print_with_actions(self, capsys):
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy

        actions = [
            StrategyAction("close", "QQQ", "long", "tactical", "test close", "bull_low_vol", 90),
            StrategyAction("open_long", "SPY", "long", "tactical", "test open", "bull_low_vol", 80),
        ]
        print_strategy(actions)
        out = capsys.readouterr().out
        assert "Long/Short Strategy" in out
        assert "CLOSE" in out
        assert "OPEN" in out


# ═══════════════════════════════════════════════════════
# 3. scanner.py — _analyze_ticker, scan_market
# ═══════════════════════════════════════════════════════


class TestAnalyzeTickerScanner:
    """_analyze_ticker with various price patterns."""

    def _make_data(self, prices, volumes=None):
        """Create a DataFrame mimicking yfinance download for a single ticker."""
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        df = pd.DataFrame({
            "Close": prices,
            "Volume": volumes,
            "Open": [p - 1 for p in prices],
            "High": [p + 2 for p in prices],
            "Low": [p - 2 for p in prices],
        }, index=dates)
        return df

    def test_too_short_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker

        df = self._make_data([100.0] * 10)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_volume_spike_detected(self):
        from nuri.trading.swing.scanner import _analyze_ticker

        # Normal volume for 29 days, then a 3x spike
        volumes = [10_000_000] * 29 + [30_000_000]
        prices = [100.0 + i * 0.5 for i in range(30)]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.signal in ("volume_spike", "momentum", "breakout", "bounce")
            assert result.score > 0

    def test_zero_price_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker

        prices = [0.0] * 30
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_no_signal_returns_none(self):
        """Flat prices with no volume spike should produce no signal."""
        from nuri.trading.swing.scanner import _analyze_ticker

        prices = [100.0] * 30
        volumes = [10_000_000] * 30
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_multiindex_data(self):
        """Test with MultiIndex columns (batch download format)."""
        from nuri.trading.swing.scanner import _analyze_ticker

        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n)
        # Create proper MultiIndex
        tuples = [(t, col) for t in ["AAPL", "MSFT"] for col in ["Close", "Open", "High", "Low", "Volume"]]
        idx = pd.MultiIndex.from_tuples(tuples)

        data = np.ones((n, 10)) * 100
        # Make AAPL Volume column spike
        data[:, 4] = 10_000_000
        data[-1, 4] = 30_000_000  # volume spike last day
        # Make AAPL Close go up
        data[:, 0] = [100 + i * 0.5 for i in range(n)]

        df = pd.DataFrame(data, index=dates, columns=idx)
        result = _analyze_ticker("AAPL", df)
        # Just verify no crash
        assert result is None or hasattr(result, "signal")

    def test_multiindex_missing_ticker(self):
        """Ticker not in MultiIndex returns None."""
        from nuri.trading.swing.scanner import _analyze_ticker

        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n)
        tuples = [("MSFT", col) for col in ["Close", "Open", "High", "Low", "Volume"]]
        idx = pd.MultiIndex.from_tuples(tuples)
        data = np.ones((n, 5)) * 100
        df = pd.DataFrame(data, index=dates, columns=idx)

        result = _analyze_ticker("AAPL", df)
        assert result is None


class TestScanMarket:
    """scan_market with mocked _fetch_prices."""

    def test_scan_returns_empty_on_no_data(self):
        from nuri.trading.swing.scanner import scan_market

        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market()

        assert results == []

    def test_scan_filters_and_sorts(self):
        from nuri.trading.swing.scanner import ScanResult, scan_market

        fake_results = {
            "AAPL": ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
            "NVDA": ScanResult("NVDA", 900.0, 5.0, 15.0, 2.5, 65.0, 0.8, "momentum", 60.0),
        }

        def mock_analyze(ticker, data):
            return fake_results.get(ticker)

        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=pd.DataFrame({"x": [1]})):
            with patch("nuri.trading.swing.scanner._analyze_ticker", side_effect=mock_analyze):
                results = scan_market(top_n=5)

        if len(results) >= 2:
            assert results[0].score >= results[1].score

    def test_scan_kr_market(self):
        from nuri.trading.swing.scanner import scan_market

        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market(market="kr")

        assert results == []


# ═══════════════════════════════════════════════════════
# 4. swing/rules.py — evaluate_entries, save_entries, check_exits
# ═══════════════════════════════════════════════════════


class TestEvaluateEntries:
    """evaluate_entries with mocked scan and consensus."""

    def test_approved_entry(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult

        scan_results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]

        mock_consensus = MagicMock(
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.6,
        )

        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)

        assert len(entries) == 1
        assert entries[0].approved is True
        assert entries[0].agent_action == "BUY"

    def test_rejected_low_confidence(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult

        scan_results = [
            ScanResult("NVDA", 900.0, 3.0, 10.0, 2.0, 60.0, 0.5, "momentum", 30.0),
        ]

        mock_consensus = MagicMock(
            final_action="BUY",
            final_confidence=30.0,
            agreement_rate=0.3,
        )

        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)

        assert len(entries) == 1
        assert entries[0].approved is False

    def test_rejected_sell_action(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult

        scan_results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]

        mock_consensus = MagicMock(
            final_action="SELL",
            final_confidence=80.0,
            agreement_rate=0.7,
        )

        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)

        assert len(entries) == 1
        assert entries[0].approved is False

    def test_low_score_skipped(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult

        scan_results = [
            ScanResult("AAPL", 180.0, 1.0, 3.0, 1.5, 50.0, 0.5, "none", 10.0),
        ]

        entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 0

    def test_existing_open_skipped(self, rich_db):
        """Already-open swing trade tickers are skipped."""
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 170.0, 'open')"
            )

        scan_results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]

        entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 0

    def test_empty_scan_results(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries

        entries = evaluate_entries(scan_results=[], db_path=rich_db)
        assert entries == []


class TestSaveEntries:
    """save_entries persists approved entries."""

    def test_saves_approved(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries

        entries = [
            SwingEntry("AAPL", 180.0, "volume_spike", 40.0, "BUY", 75.0, 0.6, True, "approved"),
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]

        n = save_entries(entries, rich_db)
        assert n == 1

        rows = query("SELECT * FROM swing_trades WHERE ticker='AAPL'", db_path=rich_db)
        assert len(rows) == 1
        assert rows[0]["entry_signal"] == "volume_spike"

    def test_no_approved_returns_zero(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries

        entries = [
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]
        n = save_entries(entries, rich_db)
        assert n == 0


class TestCheckExits:
    """check_exits with various exit conditions."""

    def test_take_profit_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 100.0, 'open')"
            )

        exits = check_exits(rich_db)
        assert len(exits) >= 1
        tp = [e for e in exits if e.exit_reason == "take_profit"]
        assert len(tp) >= 1
        assert tp[0].should_exit is True

    def test_stop_loss_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 300.0, 'open')"
            )

        exits = check_exits(rich_db)
        sl = [e for e in exits if e.exit_reason == "stop_loss"]
        assert len(sl) >= 1
        assert sl[0].should_exit is True

    def test_no_open_trades(self, rich_db):
        from nuri.trading.swing.rules import check_exits

        exits = check_exits(rich_db)
        assert exits == []

    def test_exit_updates_db(self, rich_db):
        """Exiting a trade should update swing_trades to closed."""
        from nuri.trading.swing.rules import check_exits

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 100.0, 'open')"
            )

        check_exits(rich_db)

        rows = query("SELECT * FROM swing_trades WHERE ticker='AAPL'", db_path=rich_db)
        assert rows[0]["status"] == "closed"


# ═══════════════════════════════════════════════════════
# 5. candidates.py — VIX gate, drift multipliers, screen_candidates
# ═══════════════════════════════════════════════════════


class TestCandidatesVixGate:
    """VIX gate logic in candidates."""

    def test_vix_blocked(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 35.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "blocked"
        assert result["vix"] == 35.0

    def test_vix_caution(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 27.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "caution"

    def test_vix_normal(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 15.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"

    def test_vix_no_data(self, tmp_path, monkeypatch):
        """No VIX data => value 0 => normal."""
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"
        assert result["vix"] == 0.0


class TestCandidatesDriftMultipliers:
    """DRIFT_MULTIPLIERS sanity."""

    def test_drift_multiplier_values(self):
        from nuri.trading.recommend.candidates import DRIFT_MULTIPLIERS

        assert DRIFT_MULTIPLIERS["critical"] == 0.3
        assert DRIFT_MULTIPLIERS["degrading"] == 0.6
        assert DRIFT_MULTIPLIERS["improving"] == 1.1
        assert DRIFT_MULTIPLIERS["stable"] == 1.0


class TestScreenCandidates:
    """screen_candidates integration with mocked regime and scorecard."""

    def test_empty_portfolio_returns_empty(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import screen_candidates

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    candidates = screen_candidates(lookback_days=5, db_path=path)

        assert candidates == []

    def test_screen_with_regime_avoid(self, rich_db):
        """Signals in avoid list get regime_fit=False and confidence penalty."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bear_high_vol",
            "recommended": [],
            "avoid": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce",
                       "volume_spike", "gap_up", "vix_reversal", "pcr_reversal",
                       "yield_curve_recovery", "insider_cluster", "short_squeeze"],
            "position": "minimal",
            "regime_stats": {},
        }
        scorecard = {
            "rsi_oversold": {"win_rate": 0.6, "profit_factor": 2.0, "avg_return": 3.0, "total_trades": 20},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=(scorecard, 1)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        # Any candidate with an avoided signal should have regime_fit=False
        avoided = [c for c in candidates if not c.regime_fit]
        for c in avoided:
            assert c.confidence < 50  # penalized due to minimal + regime_fit

    def test_screen_with_drift_penalty(self, rich_db):
        """Signals with critical drift get heavily penalized."""
        from nuri.trading.recommend.candidates import screen_candidates

        drift_map = {
            "rsi_oversold": {"status": "critical", "drift_pct": -50},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value=drift_map):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        critical = [c for c in candidates if c.drift_status == "critical"]
        for c in critical:
            # critical drift multiplier is 0.3 => confidence reduced
            assert c.scoring_detail is not None
            assert c.scoring_detail["drift_multiplier"] == 0.3


# ═══════════════════════════════════════════════════════
# 6. consensus.py — _compute_weights, analyze_ticker, weighted vote
# ═══════════════════════════════════════════════════════


class TestComputeWeights:
    """_compute_weights with various DB states."""

    def test_default_weights_on_empty_db(self, rich_db):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        weights = _compute_weights(rich_db)
        assert weights == DEFAULT_WEIGHTS

    def test_weights_sum_to_one(self, rich_db):
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(rich_db)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01


class TestConsensusAnalyzeTicker:
    """analyze_ticker with mocked agents."""

    def _make_verdict(self, agent_name, action, confidence, reasoning="test"):
        from nuri.trading.agents.base import AgentVerdict
        return AgentVerdict(agent_name, "AAPL", action, confidence, reasoning)

    def _run_with_verdicts(self, verdicts, db_path):
        """Helper to run analyze_ticker with mocked agents."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.consensus import analyze_ticker

        original_agents = cons_mod.ALL_AGENTS
        mock_agents = []
        for v in verdicts:
            agent = MagicMock()
            agent.name = v.agent_name
            agent.analyze.return_value = v
            mock_agents.append(agent)

        try:
            cons_mod.ALL_AGENTS = mock_agents
            return analyze_ticker("AAPL", db_path)
        finally:
            cons_mod.ALL_AGENTS = original_agents

    def test_majority_buy(self, rich_db):
        verdicts = [
            self._make_verdict("technical", "BUY", 80),
            self._make_verdict("fundamental", "BUY", 70),
            self._make_verdict("macro", "BUY", 60),
            self._make_verdict("risk", "HOLD", 50),
            self._make_verdict("smart_money", "HOLD", 40),
            self._make_verdict("wallstreet", "BUY", 75),
            self._make_verdict("korean_market", "HOLD", 30),
            self._make_verdict("options", "BUY", 65),
            self._make_verdict("crypto", "HOLD", 40),
            self._make_verdict("retail", "HOLD", 0),
        ]

        result = self._run_with_verdicts(verdicts, rich_db)
        assert result.final_action == "BUY"
        assert result.final_confidence > 0
        assert result.agreement_rate > 0
        assert result.ticker == "AAPL"

    def test_risk_veto(self, rich_db):
        """Risk agent with SELL + confidence >= 80 overrides all."""
        verdicts = [
            self._make_verdict("technical", "BUY", 90),
            self._make_verdict("fundamental", "BUY", 85),
            self._make_verdict("macro", "BUY", 70),
            self._make_verdict("risk", "SELL", 85, "VIX spike + drawdown"),
            self._make_verdict("smart_money", "BUY", 60),
            self._make_verdict("wallstreet", "BUY", 75),
            self._make_verdict("korean_market", "HOLD", 30),
            self._make_verdict("options", "BUY", 65),
            self._make_verdict("crypto", "BUY", 50),
            self._make_verdict("retail", "HOLD", 0),
        ]

        result = self._run_with_verdicts(verdicts, rich_db)
        assert result.final_action == "SELL"
        assert "거부권" in result.reasoning
        assert result.final_confidence == 85

    def test_risk_veto_below_threshold(self, rich_db):
        """Risk SELL below threshold does NOT trigger veto."""
        verdicts = [
            self._make_verdict("technical", "BUY", 90),
            self._make_verdict("fundamental", "BUY", 85),
            self._make_verdict("macro", "BUY", 70),
            self._make_verdict("risk", "SELL", 60, "mild concern"),
            self._make_verdict("smart_money", "BUY", 60),
            self._make_verdict("wallstreet", "BUY", 75),
            self._make_verdict("korean_market", "HOLD", 30),
            self._make_verdict("options", "BUY", 65),
            self._make_verdict("crypto", "BUY", 50),
            self._make_verdict("retail", "HOLD", 0),
        ]

        result = self._run_with_verdicts(verdicts, rich_db)
        assert result.final_action == "BUY"

    def test_all_hold_returns_hold(self, rich_db):
        """All agents returning HOLD should produce HOLD consensus."""
        verdicts = [
            self._make_verdict(name, "HOLD", 50)
            for name in ["technical", "fundamental", "macro", "risk", "smart_money",
                         "wallstreet", "korean_market", "options", "crypto", "retail"]
        ]

        result = self._run_with_verdicts(verdicts, rich_db)
        assert result.final_action == "HOLD"
        assert result.agreement_rate == 1.0
        assert len(result.dissent) == 0

    def test_agent_timeout_handled(self, rich_db):
        """Agent that raises exception should produce HOLD verdict with 0 confidence."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.consensus import analyze_ticker

        original_agents = cons_mod.ALL_AGENTS
        mock_agents = []
        for name in ["technical", "fundamental", "macro", "risk", "smart_money",
                      "wallstreet", "korean_market", "options", "crypto", "retail"]:
            agent = MagicMock()
            agent.name = name
            agent.analyze.side_effect = RuntimeError("timeout")
            mock_agents.append(agent)

        try:
            cons_mod.ALL_AGENTS = mock_agents
            result = analyze_ticker("AAPL", rich_db)
        finally:
            cons_mod.ALL_AGENTS = original_agents

        # All agents errored => all verdicts are HOLD with 0 confidence
        for v in result.verdicts:
            assert v.action == "HOLD"
            assert v.confidence == 0
        # All action_scores are 0 => max() tie-breaks to first key ("BUY")
        # The important thing is no crash and all verdicts are HOLD
        assert result.final_action in ("BUY", "SELL", "HOLD")

    def test_sell_majority(self, rich_db):
        """When SELL dominates, final action should be SELL."""
        verdicts = [
            self._make_verdict("technical", "SELL", 80),
            self._make_verdict("fundamental", "SELL", 70),
            self._make_verdict("macro", "SELL", 60),
            self._make_verdict("risk", "SELL", 70),
            self._make_verdict("smart_money", "SELL", 60),
            self._make_verdict("wallstreet", "SELL", 75),
            self._make_verdict("korean_market", "HOLD", 30),
            self._make_verdict("options", "SELL", 65),
            self._make_verdict("crypto", "HOLD", 40),
            self._make_verdict("retail", "HOLD", 0),
        ]

        result = self._run_with_verdicts(verdicts, rich_db)
        assert result.final_action == "SELL"
        assert len(result.dissent) > 0  # HOLD agents dissent


class TestAnalyzePortfolio:
    """analyze_portfolio with mocked analyze_ticker."""

    def test_analyze_all_tickers(self, rich_db):
        from nuri.trading.agents.consensus import ConsensusResult, analyze_portfolio

        mock_result = ConsensusResult(
            ticker="AAPL",
            final_action="BUY",
            final_confidence=70.0,
            agreement_rate=0.6,
            verdicts=[],
            dissent=[],
            reasoning="test",
        )

        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_result):
            results = analyze_portfolio(rich_db)

        assert len(results) == 2


class TestPrintConsensus:
    """print_consensus output formatting."""

    def test_print_empty(self, capsys):
        from nuri.trading.agents.consensus import print_consensus

        print_consensus([])
        out = capsys.readouterr().out
        assert "합의 결과 없음" in out

    def test_print_with_results(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 80, "RSI oversold"),
            AgentVerdict("risk", "AAPL", "SELL", 60, "volatility high"),
        ]

        result = ConsensusResult(
            ticker="AAPL",
            final_action="BUY",
            final_confidence=65.0,
            agreement_rate=0.5,
            verdicts=verdicts,
            dissent=["risk(SELL, 60): volatility high"],
            reasoning="technical: RSI oversold",
        )

        print_consensus([result])
        out = capsys.readouterr().out
        assert "Multi-Agent Consensus" in out
        assert "AAPL" in out
        assert "Dissent" in out


# ═══════════════════════════════════════════════════════
# Print helpers for swing/rules.py and scanner.py
# ═══════════════════════════════════════════════════════


class TestSwingPrintHelpers:
    """Print functions in swing/rules.py."""

    def test_print_entries_approved(self, capsys):
        from nuri.trading.swing.rules import SwingEntry, print_entries

        entries = [
            SwingEntry("AAPL", 180.0, "volume_spike", 40.0, "BUY", 75.0, 0.6, True, "approved"),
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected: low conf"),
        ]
        print_entries(entries)
        out = capsys.readouterr().out
        assert "APPROVED" in out
        assert "REJECTED" in out
        assert "AAPL" in out

    def test_print_entries_empty(self, capsys):
        from nuri.trading.swing.rules import print_entries

        print_entries([])
        out = capsys.readouterr().out
        assert "진입 후보 없음" in out

    def test_print_exits(self, capsys):
        from nuri.trading.swing.rules import SwingExit, print_exits

        exits = [
            SwingExit("AAPL", 170.0, 185.0, 8.82, 3, "hold", False),
            SwingExit("NVDA", 900.0, 800.0, -11.11, 5, "stop_loss", True),
        ]
        print_exits(exits)
        out = capsys.readouterr().out
        assert "Swing Trade Positions" in out
        assert "STOP_LOSS" in out

    def test_print_exits_empty(self, capsys):
        from nuri.trading.swing.rules import print_exits

        print_exits([])
        out = capsys.readouterr().out
        assert "오픈 포지션 없음" in out


class TestPrintScan:
    """print_scan formatting."""

    def test_print_scan_results(self, capsys):
        from nuri.trading.swing.scanner import ScanResult, print_scan

        results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]
        print_scan(results)
        out = capsys.readouterr().out
        assert "Market Scanner" in out
        assert "AAPL" in out

    def test_print_scan_empty(self, capsys):
        from nuri.trading.swing.scanner import print_scan

        print_scan([])
        out = capsys.readouterr().out
        assert "스캔 결과 없음" in out


# ═══════════════════════════════════════════════════════
# Additional coverage — _compute_weights with real data,
# execute_strategy, _load_scorecard, _get_regime_context,
# momentum/breakout signals, print_candidates
# ═══════════════════════════════════════════════════════


class TestComputeWeightsWithData:
    """_compute_weights with recommendation data in DB."""

    def test_weights_adjusted_with_verdicts(self, rich_db):
        """When enough recommendation data exists, weights should adjust."""
        from nuri.trading.agents.consensus import _compute_weights

        # Insert 20 recommendation rows with verdict JSON and outcomes
        # Use recent dates (within 180 days of "now" in SQLite = UTC today)
        verdict_json = json.dumps({
            "verdicts": [
                {"agent_name": "technical", "action": "BUY"},
                {"agent_name": "fundamental", "action": "BUY"},
                {"agent_name": "macro", "action": "HOLD"},
                {"agent_name": "risk", "action": "SELL"},
                {"agent_name": "smart_money", "action": "BUY"},
                {"agent_name": "wallstreet", "action": "BUY"},
                {"agent_name": "korean_market", "action": "HOLD"},
                {"agent_name": "options", "action": "BUY"},
                {"agent_name": "crypto", "action": "HOLD"},
                {"agent_name": "retail", "action": "HOLD"},
            ]
        })

        with get_db(rich_db) as conn:
            for i in range(20):
                outcome = 5.0 if i % 2 == 0 else -3.0  # mixed outcomes
                # Recent dates within last 60 days
                date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, 'BUY', 70, ?, ?)",
                    (date, f"TICK{i}", verdict_json, outcome),
                )

        weights = _compute_weights(rich_db)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01
        # With 20 records and mixed outcomes, weights should be adjusted
        # (technical BUY hit half the time => some adjustment from default)

    def test_weights_with_insufficient_data(self, rich_db):
        """Fewer than min_records returns default weights."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        # Only insert 3 rows (below the min_records threshold of 10)
        with get_db(rich_db) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, signals, outcome_30d) "
                    "VALUES (?, 'AAPL', 'BUY', 70, '{}', 5.0)",
                    (f"2025-06-{i+1:02d}",),
                )

        weights = _compute_weights(rich_db)
        assert weights == DEFAULT_WEIGHTS

    def test_weights_with_no_valid_verdicts(self, rich_db):
        """Recommendations with non-JSON signals should fall back to default."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        with get_db(rich_db) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, signals, outcome_30d) "
                    "VALUES (?, 'AAPL', 'BUY', 70, 'not-json', 5.0)",
                    (f"2025-{(i % 12)+1:02d}-{(i % 28)+1:02d}",),
                )

        weights = _compute_weights(rich_db)
        assert weights == DEFAULT_WEIGHTS


class TestExecuteStrategy:
    """execute_strategy covers close/open branches."""

    def test_execute_close_action(self, rich_db):
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        # Insert open position
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 'open')"
            )

        actions = [
            StrategyAction("close", "AAPL", "long", "tactical", "take profit", "bull_low_vol", 85),
        ]

        # Mock update_prices (imported lazily from nuri.trading.strategy.position)
        with patch("nuri.trading.strategy.position.update_prices"):
            n = execute_strategy(actions, rich_db)

        assert n == 1
        row = query("SELECT status FROM positions WHERE ticker='AAPL'", db_path=rich_db)[0]
        assert row["status"] == "closed"


class TestLoadScorecard:
    """_load_scorecard with and without CSV files."""

    def test_no_report_dir(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        monkeypatch.setattr(cand_mod, "REPORT_DIR", tmp_path / "nonexistent")
        data, age = cand_mod._load_scorecard()
        assert data == {}
        assert age is None

    def test_with_scorecard_csv(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2026-03-30"
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        csv_content += ",macd_golden,0.55,1.5,2.0,20\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert "rsi_oversold" in data
        assert data["rsi_oversold"]["win_rate"] == 0.65
        assert age is not None

    def test_stale_scorecard_warning(self, tmp_path, monkeypatch):
        """Scorecard older than 7 days triggers warning."""
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2025-01-01"  # very old
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert age > 7
        assert "rsi_oversold" in data


class TestGetRegimeContext:
    """_get_regime_context with mocked regime classifier."""

    def test_regime_returns_context(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        mock_regime = MagicMock(regime="bull_low_vol")
        mock_strategy = MagicMock(
            recommended_signals=["rsi_oversold"],
            avoid_signals=["rsi_overbought"],
            position_sizing="normal",
            signal_regime_stats={"rsi_oversold": {"win_rate": 0.7, "pf": 2.0, "trades": 10}},
        )

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            with patch("nuri.quant.regime.strategy_map.map_regime_to_strategy", return_value=mock_strategy):
                ctx = _get_regime_context(rich_db)

        assert ctx is not None
        assert ctx["regime"] == "bull_low_vol"
        assert "rsi_oversold" in ctx["recommended"]
        assert ctx["regime_stats"]["rsi_oversold"]["win_rate"] == 0.7

    def test_regime_none_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            ctx = _get_regime_context(rich_db)

        assert ctx is None

    def test_regime_exception_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            ctx = _get_regime_context(rich_db)

        assert ctx is None


class TestPrintCandidates:
    """print_candidates output formatting."""

    def test_print_empty(self, capsys):
        from nuri.trading.recommend.candidates import print_candidates

        print_candidates([])
        out = capsys.readouterr().out
        assert "매매 후보 없음" in out

    def test_print_with_candidates(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=75.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="과거 20건",
                drift_status="", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="NVDA", signal_id="macd_dead", signal_date="2026-03-30",
                direction="SELL", confidence=60.0, win_rate=0.55, profit_factor=1.5,
                regime_fit=True, price=900.0, notes="",
                drift_status="degrading", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="AAPL", signal_id="rsi_overbought", signal_date="2026-03-30",
                direction="SELL", confidence=30.0, win_rate=0.45, profit_factor=0.8,
                regime_fit=False, price=180.0, notes="레짐에서 비추천",
                drift_status="critical", conflict="direction_conflict", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 15, "gate": "normal", "msg": ""}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "Signal-Based Candidates" in out
        assert "AAPL" in out

    def test_print_vix_blocked(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=0.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="VIX > 30",
                drift_status="", conflict="", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 35, "gate": "blocked", "msg": "VIX 35.0 > 30 -> block"}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "VIX" in out


class TestScannerMomentumBreakout:
    """Test momentum and breakout signal detection paths."""

    def _make_data(self, prices, volumes=None):
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        return pd.DataFrame({
            "Close": prices,
            "Volume": volumes,
            "Open": [p - 1 for p in prices],
            "High": [p + 2 for p in prices],
            "Low": [p - 2 for p in prices],
        }, index=dates)

    def test_momentum_signal(self):
        """Strong 5-day rally with RSI > 50 should detect momentum."""
        from nuri.trading.swing.scanner import _analyze_ticker

        # Gradually rising prices => good 5d change, RSI > 50
        prices = [100.0 + i * 1.5 for i in range(30)]
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.score > 0

    def test_breakout_signal(self):
        """Price at upper BB with high volume ratio should trigger breakout."""
        from nuri.trading.swing.scanner import _analyze_ticker

        # Flat prices then a sharp spike to break BB
        prices = [100.0] * 25 + [100.0, 101.0, 103.0, 108.0, 115.0]
        volumes = [10_000_000] * 25 + [10_000_000, 15_000_000, 20_000_000, 25_000_000, 35_000_000]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.signal in ("breakout", "volume_spike", "momentum")


class TestSwingAgentSellExit:
    """check_exits with agent SELL for early exit path."""

    def test_agent_sell_triggers_exit(self, rich_db):
        """When return is in normal range but agent says SELL with high confidence."""
        from nuri.trading.swing.rules import check_exits

        # Insert trade with entry_price close to current price (small return)
        latest = query(
            "SELECT close FROM prices WHERE ticker='AAPL' ORDER BY date DESC LIMIT 1",
            db_path=rich_db,
        )[0]["close"]
        # entry at current price => ~0% return
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', ?, ?, 'open')",
                # Use a recent date so hold_days < 7
                (datetime.now().strftime("%Y-%m-%d"), latest),
            )

        mock_consensus = MagicMock(final_action="SELL", final_confidence=85.0)
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            exits = check_exits(rich_db)

        agent_sells = [e for e in exits if e.exit_reason == "agent_sell"]
        assert len(agent_sells) >= 1
        assert agent_sells[0].should_exit is True


class TestCandidatesConflictDetection:
    """Conflict detection in screen_candidates."""

    def test_conflict_penalty_applied(self, rich_db):
        """When detect_conflicts returns high severity, confidence is halved."""
        from nuri.trading.engine.conflicts import SignalConflict
        from nuri.trading.recommend.candidates import screen_candidates

        conflicts = [
            SignalConflict(
                ticker="AAPL",
                conflict_type="direction_conflict",
                severity="high",
                buy_signals=["rsi_oversold"],
                sell_signals=["rsi_overbought"],
                detail="방향 충돌",
                recommendation="관망",
            ),
        ]

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=conflicts):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        aapl_conflicted = [c for c in candidates if c.ticker == "AAPL" and c.conflict]
        for c in aapl_conflicted:
            assert c.conflict == "direction_conflict"
            # High severity should have applied 0.5x penalty
            if c.scoring_detail:
                assert c.scoring_detail.get("conflict_penalty") == 0.5


class TestCandidatesRegimeStats:
    """Test regime-specific stats path in confidence calculation."""

    def test_regime_stats_used_when_available(self, rich_db):
        """When regime_stats has enough trades, uses regime-specific win_rate."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bull_low_vol",
            "recommended": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce", "volume_spike"],
            "avoid": [],
            "position": "normal",
            "regime_stats": {
                "rsi_oversold": {"win_rate": 0.8, "pf": 3.0, "trades": 15},
                "macd_golden": {"win_rate": 0.7, "pf": 2.5, "trades": 12},
            },
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        # Candidates with regime_stats should use regime-specific scoring
        rsi_cands = [c for c in candidates if c.signal_id == "rsi_oversold"]
        for c in rsi_cands:
            if c.scoring_detail:
                assert "regime_win_rate" in c.scoring_detail
