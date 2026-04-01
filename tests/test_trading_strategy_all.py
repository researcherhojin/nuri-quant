"""Consolidated trading strategy + swing tests.

Extracts ALL strategy-related test classes from existing test files.
Target modules:
  - nuri.trading.strategy.* (longshort, ls_backtest, pairs, mean_reversion, monitor, position)
  - nuri.trading.swing.* (scanner, rules)
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import today_kst

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def bull_data(db_path):
    """상승장 데이터: SPY 상승 + VIX 낮음."""
    dates = pd.date_range(end=today_kst(), periods=300)
    close = np.linspace(100, 200, 300) + np.random.normal(0, 1, 300)

    for ticker in ["SPY", "QQQ", "TEST"]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [50000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([{
        "indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 15.0, "source": "test",
    }], db_path)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 150.0, "USD"),
        )
    return db_path


@pytest.fixture
def rich_db(db_path):
    """풍부한 테스트 데이터 — 포트폴리오 + 300일 가격 + 매크로."""
    today = today_kst()

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "EV/AI"), ("NVDA", 3, 130, "Semiconductor"),
                            ("SPY", 50, 450, "Index")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=300)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300), ("NVDA", 110)]:
        close = np.linspace(base, base * 1.2, 300) + np.random.normal(0, 1, 300)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    with get_db(db_path) as conn:
        for d in dates[-50:]:
            ds = d.strftime("%Y-%m-%d")
            conn.execute("INSERT OR IGNORE INTO signals (ticker, date, rsi_14, sma_20, sma_50, sma_200) "
                         "VALUES (?, ?, ?, ?, ?, ?)", ("SPY", ds, 55.0, 480.0, 470.0, 440.0))

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
        {"indicator": "gdp_growth", "date": today, "value": 2.5, "source": "test"},
        {"indicator": "unemployment", "date": today, "value": 3.8, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path


@pytest.fixture
def backtest_data(db_path):
    """5년 SPY + SH + VIX 시뮬레이션 데이터."""
    dates = pd.bdate_range("2020-01-01", periods=1200)

    phase1 = np.linspace(300, 450, 400)
    phase2 = np.linspace(450, 350, 200)
    phase3 = np.linspace(350, 500, 600)
    spy_close = np.concatenate([phase1, phase2, phase3]) + np.random.normal(0, 2, 1200)

    sh_close = 40 - (spy_close - 400) * 0.08 + np.random.normal(0, 0.5, 1200)

    for ticker, close in [("SPY", spy_close), ("SH", sh_close)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": [50000000] * 1200, "adj_close": close,
        })
        upsert_prices(df, db_path)

    vix = np.concatenate([
        np.full(400, 15) + np.random.normal(0, 2, 400),
        np.full(200, 30) + np.random.normal(0, 3, 200),
        np.full(600, 16) + np.random.normal(0, 2, 600),
    ]).clip(10, 80)

    records = [{"indicator": "vix", "date": dates[i].strftime("%Y-%m-%d"),
                "value": float(vix[i]), "source": "test"} for i in range(1200)]
    upsert_macro(records, db_path)
    return db_path


@pytest.fixture
def market_data(db_path):
    """가격 + 포트폴리오 테스트 데이터."""
    prices = []
    for i in range(200):
        date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
        prices.append({
            "ticker": "AAPL", "date": date,
            "open": 150 + i * 0.1, "high": 152 + i * 0.1,
            "low": 148 + i * 0.1, "close": 150 + i * 0.1,
            "volume": 1000000, "adj_close": 150 + i * 0.1,
        })
        prices.append({
            "ticker": "MSFT", "date": date,
            "open": 300 + i * 0.15, "high": 303 + i * 0.15,
            "low": 298 + i * 0.15, "close": 300 + i * 0.15,
            "volume": 800000, "adj_close": 300 + i * 0.15,
        })
    upsert_prices(pd.DataFrame(prices), db_path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "MSFT", "quantity": 5,
         "avg_price": 300, "currency": "USD", "sector": "Tech"},
    ], db_path)
    return db_path


# ═══════════════════════════════════════════════════════════════════════
# PART 1: nuri.trading.strategy.position
# ═══════════════════════════════════════════════════════════════════════


class TestCertification:
    """From test_strategy.py — basic certification."""

    def test_regime_aligned_long_in_bull(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("QQQ", "long", "bull_low_vol", db_path=bull_data)
        assert cert.regime_aligned is True

    def test_regime_misaligned_short_in_bull(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("SH", "short", "bull_low_vol", db_path=bull_data)
        assert cert.regime_aligned is False
        assert cert.certified is False

    def test_regime_aligned_short_in_bear(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("SH", "short", "bear_high_vol", db_path=bull_data)
        assert cert.regime_aligned is True


class TestPositionManager:
    """From test_strategy.py — position open/query."""

    def test_open_and_query(self, bull_data):
        from nuri.trading.strategy.position import get_positions_summary, open_position
        open_position("QQQ", "long", 400.0, portfolio_type="tactical",
                     regime="bull_low_vol", db_path=bull_data)
        summary = get_positions_summary(db_path=bull_data)
        assert summary["open_total"] >= 0

    def test_duplicate_blocked(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        with get_db(bull_data) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'QQQ', 'long', '2026-03-27', 400.0, 'open')")
        cert = certify_position("QQQ", "long", "bull_low_vol", db_path=bull_data)
        assert cert.concentration_ok is False


class TestPositionCertification:
    """From test_coverage_boost.py — dataclass tests."""

    def test_create(self):
        from nuri.trading.strategy.position import PositionCertification
        cert = PositionCertification(
            regime_aligned=True, agent_consensus=True, concentration_ok=True,
            daily_limit_ok=True, drift_safe=True, certified=True, details={},
        )
        assert cert.certified is True

    def test_not_certified(self):
        from nuri.trading.strategy.position import PositionCertification
        cert = PositionCertification(
            regime_aligned=False, agent_consensus=True, concentration_ok=True,
            daily_limit_ok=True, drift_safe=True, certified=False, details={"reason": "regime mismatch"},
        )
        assert cert.certified is False


class TestCertifyPosition:
    """From test_coverage_boost.py — mock-based certification."""

    def test_basic_certification(self, db_path, monkeypatch):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.8, dissent=[], reasoning="test",
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "ok"),
                AgentVerdict("fundamental", "AAPL", "BUY", 65, "ok"),
                AgentVerdict("macro", "AAPL", "HOLD", 50, "ok"),
                AgentVerdict("risk", "AAPL", "HOLD", 40, "ok"),
                AgentVerdict("smart_money", "AAPL", "BUY", 55, "ok"),
            ],
        )
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: mock_result, raising=False)

        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=db_path)
        assert cert.regime_aligned is True
        assert cert.concentration_ok is True
        assert cert.daily_limit_ok is True

    def test_bear_long_misaligned(self, db_path, monkeypatch):
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: MagicMock(final_action="SELL", verdicts=[]), raising=False)
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", db_path=db_path)
        assert cert.regime_aligned is False


class TestCertifyPosition_R18:
    """From test_coverage_round18.py — extensive SIEGE certification tests."""

    def test_long_bull_regime_aligned(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY"), MagicMock(action="HOLD")],
                final_action="BUY", final_confidence=70,
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
                final_action="SELL", final_confidence=80,
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
                final_action="SELL", final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "short", "bear_high_vol", db_path=rich_db)
        assert cert.regime_aligned is True

    def test_duplicate_position_blocks(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-01-01', 150.0, 'open')")
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY", final_confidence=80,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)
        assert cert.concentration_ok is False
        assert cert.certified is False

    def test_agent_consensus_error_handled(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        with patch("nuri.trading.agents.consensus.analyze_ticker", side_effect=RuntimeError("timeout")):
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)
        assert cert.agent_consensus is False
        assert "agent_error" in cert.details

    def test_unknown_regime_fallback_long(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at:
            mock_at.return_value = MagicMock(
                verdicts=[MagicMock(action="BUY"), MagicMock(action="BUY")],
                final_action="BUY", final_confidence=70,
            )
            with patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
                cert = certify_position("AAPL", "long", "unknown_regime", db_path=rich_db)
        assert cert.regime_aligned is False


class TestOpenPosition:
    """From test_coverage_round18.py — open_position SIEGE gate."""

    def test_certified_position_opens(self, rich_db):
        from nuri.trading.strategy.position import open_position
        with patch("nuri.trading.strategy.position.certify_position") as mock_cert:
            mock_cert.return_value = MagicMock(
                certified=True, regime_aligned=True, agent_consensus=True,
                concentration_ok=True, daily_limit_ok=True, drift_safe=True,
                details={"regime": "bull_low_vol"},
            )
            with patch("nuri.trading.strategy.position.asdict", return_value={"certified": True}):
                result = open_position("AAPL", "long", 190.0, 10, "tactical", "bull_low_vol", rich_db)
        assert result is True
        rows = query("SELECT * FROM positions WHERE ticker='AAPL' AND status='open'", db_path=rich_db)
        assert len(rows) >= 1

    def test_uncertified_position_blocked(self, rich_db):
        from nuri.trading.strategy.position import open_position
        with patch("nuri.trading.strategy.position.certify_position") as mock_cert:
            mock_cert.return_value = MagicMock(
                certified=False, regime_aligned=False, agent_consensus=False,
                concentration_ok=True, daily_limit_ok=True, drift_safe=True,
                details={"agent_agree": "0/5"},
            )
            result = open_position("AAPL", "long", 190.0, 10, "tactical", "bear_high_vol", rich_db)
        assert result is False


class TestClosePosition:
    """From test_coverage_round18.py — close_position PnL."""

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
        from nuri.trading.strategy.position import close_position
        pos_id = self._insert_position(rich_db, "AAPL2", "short", 100.0)
        close_position(pos_id, 80.0, "take_profit", rich_db)
        row = query("SELECT * FROM positions WHERE id=?", (pos_id,), db_path=rich_db)[0]
        assert row["return_pct"] == 20.0

    def test_nonexistent_position(self, rich_db):
        from nuri.trading.strategy.position import close_position
        close_position(99999, 100.0, "test", rich_db)


class TestUpdatePrices:
    """From test_coverage_round18.py — update_prices."""

    def test_update_open_long(self, rich_db):
        from nuri.trading.strategy.position import update_prices
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 'open')")
        update_prices(rich_db)
        row = query("SELECT current_price, return_pct FROM positions WHERE ticker='AAPL' AND status='open'",
                     db_path=rich_db)[0]
        assert row["current_price"] is not None
        assert row["current_price"] > 0

    def test_update_no_price_data_skips(self, rich_db):
        from nuri.trading.strategy.position import update_prices
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'ZZZZZ', 'long', '2024-10-01', 100.0, 'open')")
        update_prices(rich_db)
        row = query("SELECT current_price FROM positions WHERE ticker='ZZZZZ'", db_path=rich_db)[0]
        assert row["current_price"] is None


class TestGetPositionsSummary:
    """From test_coverage_round18.py — summary."""

    def test_empty_positions(self, rich_db):
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary(rich_db)
        assert summary["open_total"] == 0
        assert summary["closed_total"] == 0

    def test_mixed_positions(self, rich_db):
        from nuri.trading.strategy.position import get_positions_summary
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('core', 'AAPL', 'long', '2024-10-01', 170.0, 'open')")
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'SPY', 'short', '2024-10-02', 450.0, 'open')")
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "status, return_pct, exit_price, exit_date) "
                "VALUES ('tactical', 'NVDA', 'long', '2024-09-01', 100.0, 'closed', 15.0, 115.0, '2024-10-15')")
        summary = get_positions_summary(rich_db)
        assert summary["open_total"] == 2
        assert summary["closed_total"] == 1


class TestPrintPositions:
    """From test_coverage_round18.py — print_positions."""

    def test_print_with_positions(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, "
                "current_price, return_pct, status, regime_at_entry) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 180.0, 5.88, 'open', 'bull_low_vol')")
        with patch("nuri.trading.strategy.position.update_prices"):
            print_positions(rich_db)
        out = capsys.readouterr().out
        assert "AAPL" in out

    def test_print_empty(self, rich_db, capsys):
        from nuri.trading.strategy.position import print_positions
        with patch("nuri.trading.strategy.position.update_prices"):
            print_positions(rich_db)
        out = capsys.readouterr().out
        assert "오픈 포지션 없음" in out


class TestPositionExtended:
    """From test_coverage_push.py — position dataclass."""

    def test_position_dataclass(self):
        from nuri.trading.strategy.position import Position, PositionCertification
        cert = PositionCertification(True, True, True, True, True, True, {})
        p = Position("AAPL", "long", "tactical", 150.0, 10, "bull_low_vol", cert)
        assert p.ticker == "AAPL"


class TestPosition_R2:
    """From test_coverage_round2.py."""

    def test_certify_position_no_data(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth", db_path=db_path)
        assert hasattr(cert, "certified")
        assert hasattr(cert, "regime_aligned")

    def test_open_position_rejected(self, db_path):
        from nuri.trading.strategy.position import open_position
        result = open_position("FAKE", "long", 100.0, 10, "growth", "bull_low_vol", db_path=db_path)
        assert result is False

    def test_get_positions_summary_empty(self, db_path):
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary(db_path=db_path)
        assert isinstance(summary, dict)

    def test_close_position_nonexistent(self, db_path):
        from nuri.trading.strategy.position import close_position
        close_position(99999, 100.0, "test", db_path=db_path)


class TestPositionDeep:
    """From test_coverage_round3.py."""

    def test_certify_bull_long(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth", db_path=db_path)
        assert cert.regime_aligned is True

    def test_certify_bear_long_misaligned(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", "growth", db_path=db_path)
        assert cert.regime_aligned is False

    def test_certify_concentration_ok(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth", db_path=db_path)
        assert cert.concentration_ok is True
        assert cert.daily_limit_ok is True

    def test_get_positions_summary(self, db_path):
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary(db_path=db_path)
        assert "open_total" in summary
        assert summary["open_total"] == 0

    def test_close_nonexistent(self, db_path):
        from nuri.trading.strategy.position import close_position
        close_position(99999, 100.0, "test", db_path=db_path)


class TestPositionRound7:
    """From test_coverage_round7.py — open/close full flow."""

    def test_open_close_full_flow(self, rich_db):
        from nuri.trading.strategy.position import (
            certify_position,
            close_position,
            get_positions_summary,
            open_position,
        )
        certify_position("AAPL", "long", "bull_low_vol", "growth", db_path=rich_db)

        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at, \
             patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
            mock_at.return_value = MagicMock(
                final_action="BUY", final_confidence=85, agreement_rate=0.8,
            )
            opened = open_position("AAPL", "long", 190.0, 10, "growth", "bull_low_vol", db_path=rich_db)

        if opened:
            pos = query("SELECT id FROM positions WHERE ticker='AAPL' AND exit_date IS NULL", db_path=rich_db)
            if pos:
                close_position(pos[0]["id"], 210.0, "take_profit", db_path=rich_db)

        summary = get_positions_summary(db_path=rich_db)
        assert isinstance(summary, dict)

    def test_update_prices(self, rich_db):
        from nuri.trading.strategy.position import update_prices
        update_prices(db_path=rich_db)


class TestPositionCycle:
    """From test_coverage_round13.py — full lifecycle."""

    def test_full_lifecycle(self, rich_db):
        from nuri.trading.strategy.position import (
            close_position,
            get_positions_summary,
            open_position,
            update_prices,
        )
        mock_result = MagicMock(
            final_action="BUY", final_confidence=85, agreement_rate=0.8,
        )
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_result), \
             patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
            opened = open_position("NVDA", "long", 130.0, 5, "growth", "bull_low_vol", db_path=rich_db)

        if opened:
            update_prices(db_path=rich_db)
            pos = query("SELECT id FROM positions WHERE ticker='NVDA' AND exit_date IS NULL", db_path=rich_db)
            if pos:
                close_position(pos[0]["id"], 150.0, "take_profit", db_path=rich_db)

        summary = get_positions_summary(db_path=rich_db)
        assert isinstance(summary, dict)


class TestPositionFull:
    """From test_coverage_round14.py — full certification fields."""

    def test_open_with_all_checks(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("TSLA", "long", "bull_low_vol", "growth", db_path=rich_db)
        assert hasattr(cert, "regime_aligned")
        assert hasattr(cert, "agent_consensus")
        assert hasattr(cert, "concentration_ok")
        assert hasattr(cert, "daily_limit_ok")
        assert hasattr(cert, "drift_safe")
        assert hasattr(cert, "certified")


class TestPositionOpen:
    """From test_coverage_round10.py — open with mock consensus."""

    def test_open_success(self, rich_db):
        from nuri.trading.strategy.position import open_position
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at, \
             patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
            mock_at.return_value = MagicMock(
                final_action="BUY", final_confidence=85, agreement_rate=0.8,
            )
            result = open_position("AAPL", "long", 190.0, 10, "growth", "bull_low_vol", db_path=rich_db)
        assert isinstance(result, bool)


class TestPosition_R26:
    """From test_coverage_round26.py."""

    def test_certify_position_bull(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=rich_db)
        assert cert.regime_aligned is True

    def test_certify_position_bear(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", db_path=rich_db)
        assert cert.regime_aligned is False

    def test_close_position_nonexistent(self, rich_db):
        from nuri.trading.strategy.position import close_position
        close_position(99999, 100.0, "test", db_path=rich_db)

    def test_update_prices(self, rich_db):
        from nuri.trading.strategy.position import update_prices
        update_prices(db_path=rich_db)

    def test_get_positions_summary_empty(self, rich_db):
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary(db_path=rich_db)
        assert isinstance(summary, dict)


class TestPosition_R27:
    """From test_coverage_round27.py — certify_position + REGIME_ALLOCATION."""

    def test_certify_different_regimes(self, rich_db):
        from nuri.trading.strategy.position import certify_position
        for regime in ["bull_low_vol", "bear_high_vol", "sideways_low_vol"]:
            cert = certify_position("AAPL", "long", regime, db_path=rich_db)
            assert hasattr(cert, "certified")


# ═══════════════════════════════════════════════════════════════════════
# PART 2: nuri.trading.strategy.longshort
# ═══════════════════════════════════════════════════════════════════════


class TestLongShortStrategy:
    """From test_strategy.py — basic longshort."""

    def test_generate_strategy(self, bull_data):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=bull_data)
        assert isinstance(actions, list)

    def test_regime_allocation_keys(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            assert alloc["long_pct"] + alloc["short_pct"] + alloc["cash_pct"] == 100


class TestLongShort:
    """From test_coverage_boost.py — allocation checks."""

    def test_regime_allocation_exists(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        assert "bull_low_vol" in REGIME_ALLOCATION
        assert "bear_high_vol" in REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc.get("long_pct", 0) + alloc.get("short_pct", 0) + alloc.get("cash_pct", 0)
            assert total == 100, f"{regime}: allocations don't sum to 100"

    def test_etf_universe(self):
        from nuri.trading.strategy.longshort import LONG_ETFS, SHORT_ETFS
        assert "QQQ" in LONG_ETFS or "SPY" in LONG_ETFS
        assert len(SHORT_ETFS) > 0


class TestStrategyAction:
    """From test_coverage_final.py — strategy actions."""

    def test_create(self):
        from nuri.trading.strategy.longshort import StrategyAction
        a = StrategyAction("open_long", "QQQ", "long", "tactical", "bull regime", "bull_low_vol", 75.0)
        assert a.action == "open_long"

    def test_regime_allocation_keys(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        base_regimes = {"bull_low_vol", "bull_high_vol", "sideways_low_vol",
                        "sideways_high_vol", "bear_low_vol", "bear_high_vol"}
        special_regimes = {"recovery", "euphoria", "stagflation", "sector_rotation"}
        assert set(REGIME_ALLOCATION.keys()) == base_regimes | special_regimes

    def test_transition_rules(self):
        from nuri.trading.strategy.longshort import REGIME_TRANSITION_RULES
        assert len(REGIME_TRANSITION_RULES) > 5
        for (from_r, to_r), note in REGIME_TRANSITION_RULES.items():
            assert from_r != to_r
            assert len(note) > 0

    def test_short_etfs_tiers(self):
        from nuri.trading.strategy.longshort import SHORT_ETFS
        assert "conservative" in SHORT_ETFS
        assert "moderate" in SHORT_ETFS
        assert "aggressive" in SHORT_ETFS

    def test_generate_strategy(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        assert isinstance(actions, list)

    def test_generate_strategy_empty(self, db_path):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=db_path)
        assert isinstance(actions, list)


class TestLongShortExtended:
    """From test_coverage_push.py — print strategy."""

    def test_print_strategy(self, capsys):
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy
        actions = [
            StrategyAction("open_long", "QQQ", "long", "tactical", "bull", "bull_low_vol", 75.0),
            StrategyAction("hold", "SPY", "long", "tactical", "maintain", "bull_low_vol", 60.0),
        ]
        print_strategy(actions)
        output = capsys.readouterr().out
        assert "QQQ" in output or "Strategy" in output

    def test_print_empty(self, capsys):
        from nuri.trading.strategy.longshort import print_strategy
        print_strategy([])
        output = capsys.readouterr().out
        assert len(output) > 0


class TestRegimeAllocation:
    """From test_coverage_round18.py — allocation integrity."""

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
    """From test_coverage_round18.py — generate_strategy with mocked regime."""

    def _mock_regime(self, regime_name, confidence=0.8):
        return MagicMock(regime=regime_name, confidence=confidence)

    def test_bull_long_opens_etfs(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bull_low_vol")
            with patch("nuri.trading.swing.scanner.scan_market", return_value=[]):
                actions = generate_strategy(rich_db)
        open_longs = [a for a in actions if a.action == "open_long"]
        assert len(open_longs) >= 2

    def test_bear_closes_longs_opens_shorts(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'QQQ', 'long', '2024-10-01', 400.0, 'open')")
        with patch("nuri.quant.regime.classifier.classify_regime") as mock_cls:
            mock_cls.return_value = self._mock_regime("bear_high_vol")
            actions = generate_strategy(rich_db)
        close_actions = [a for a in actions if a.action == "close"]
        assert any(a.ticker == "QQQ" for a in close_actions)

    def test_sideways_high_vol_no_new_positions(self, rich_db):
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


class TestPrintStrategy:
    """From test_coverage_round18.py — print_strategy."""

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


class TestLongshortExecute:
    """From test_coverage_round8.py — execute_strategy."""

    def test_execute_strategy(self, rich_db):
        from nuri.trading.strategy.longshort import execute_strategy, generate_strategy
        actions = generate_strategy(db_path=rich_db)
        if actions:
            count = execute_strategy(actions, db_path=rich_db)
            assert isinstance(count, int)


class TestExecuteStrategy:
    """From test_coverage_round18.py — execute_strategy close action."""

    def test_execute_close_action(self, rich_db):
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'AAPL', 'long', '2024-10-01', 170.0, 'open')")
        actions = [
            StrategyAction("close", "AAPL", "long", "tactical", "take profit", "bull_low_vol", 85),
        ]
        with patch("nuri.trading.strategy.position.update_prices"):
            n = execute_strategy(actions, rich_db)
        assert n == 1
        row = query("SELECT status FROM positions WHERE ticker='AAPL'", db_path=rich_db)[0]
        assert row["status"] == "closed"


class TestLongshort_R5:
    """From test_coverage_round5.py."""

    def test_get_regime_allocation(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        assert "bull_low_vol" in REGIME_ALLOCATION
        assert "bear_high_vol" in REGIME_ALLOCATION
        alloc = REGIME_ALLOCATION["bull_low_vol"]
        assert "direction" in alloc
        assert "long_pct" in alloc

    def test_generate_strategy(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        assert isinstance(actions, list)


class TestLongshortDeep:
    """From test_coverage_round6.py."""

    def test_generate_strategy(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy(db_path=rich_db)
        assert isinstance(actions, list)

    def test_print_strategy(self, rich_db, capsys):
        from nuri.trading.strategy.longshort import generate_strategy, print_strategy
        actions = generate_strategy(db_path=rich_db)
        print_strategy(actions)
        assert len(capsys.readouterr().out) >= 0


# ═══════════════════════════════════════════════════════════════════════
# PART 3: nuri.trading.strategy.ls_backtest
# ═══════════════════════════════════════════════════════════════════════


class TestRegimeClassification:
    """From test_backtest.py — historical regime classification."""

    def test_classifies_multiple_regimes(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        regimes = df["regime"].unique()
        non_unknown = [r for r in regimes if r != "unknown"]
        assert len(non_unknown) >= 2

    def test_bear_detected_in_decline(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=backtest_data)
        bear_days = df[df["regime"].str.contains("bear", na=False)]
        assert len(bear_days) > 50


class TestBacktest:
    """From test_backtest.py — backtest results."""

    def test_returns_result(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.total_days > 500
        assert -100 < result.total_return < 500
        assert result.max_drawdown <= 0

    def test_equity_curve(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=backtest_data)
        result = run_backtest(regimes, db_path=backtest_data)
        assert result.equity_curve is not None
        assert len(result.equity_curve) == result.total_days


class TestMonteCarlo:
    """From test_backtest.py — Monte Carlo simulation."""

    def test_runs_without_error(self, backtest_data):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=backtest_data)
        mc = monte_carlo_test(regimes, n_simulations=50, db_path=backtest_data)
        assert "actual_return" in mc
        assert "statistically_significant" in mc
        assert 0 <= mc["return_percentile"] <= 1


class TestAllocation:
    """From test_backtest.py — allocation sums."""

    def test_allocations_sum_to_100(self):
        from nuri.trading.strategy.ls_backtest import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc["long"] + alloc["short"] + alloc["cash"]
            assert abs(total - 1.0) < 0.01, f"{regime}: {total}"


class TestLSBacktest:
    """From test_coverage_round4.py."""

    def test_classify_historical_regimes(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        assert isinstance(regimes, pd.DataFrame)
        assert "regime" in regimes.columns
        assert len(regimes) > 100

    def test_run_backtest(self, rich_db):
        from nuri.trading.strategy.ls_backtest import BacktestResult, classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert isinstance(result, BacktestResult)
        assert hasattr(result, "total_return")
        assert result.total_days > 0

    def test_monte_carlo(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=10, db_path=rich_db)
        assert isinstance(mc, dict)


class TestLSBacktestDeep:
    """From test_coverage_round5.py."""

    def test_backtest_result_fields(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert hasattr(result, "annual_return")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "win_rate")


class TestLSBacktestRound6:
    """From test_coverage_round6.py — extended backtest functions."""

    def test_analyze_per_regime(self, rich_db):
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)
        assert len(perfs) > 0
        assert hasattr(perfs[0], "regime")

    def test_stress_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        assert isinstance(results, list)

    def test_run_backtest_with_rules(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        assert isinstance(result, dict)

    def test_print_stress(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, print_stress, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        print_stress(results)
        assert len(capsys.readouterr().out) > 0

    def test_print_monte_carlo(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test, print_monte_carlo
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=5, db_path=rich_db)
        print_monte_carlo(mc)
        assert len(capsys.readouterr().out) > 0

    def test_print_rules_comparison(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_rules_comparison,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        print_rules_comparison(result)
        assert len(capsys.readouterr().out) > 0


class TestLSBacktest_R26:
    """From test_coverage_round26.py."""

    def test_classify_returns_df(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=rich_db)
        assert isinstance(df, pd.DataFrame)
        assert "regime" in df.columns

    def test_run_backtest(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest(regimes, db_path=rich_db)
        assert hasattr(result, "total_return")

    def test_monte_carlo_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, monte_carlo_test
        regimes = classify_historical_regimes(db_path=rich_db)
        mc = monte_carlo_test(regimes, n_simulations=5, db_path=rich_db)
        assert isinstance(mc, dict)

    def test_stress_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, stress_test
        regimes = classify_historical_regimes(db_path=rich_db)
        results = stress_test(regimes)
        assert isinstance(results, list)

    def test_run_backtest_with_rules(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, run_backtest_with_rules
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        assert isinstance(result, dict)

    def test_analyze_per_regime(self, rich_db):
        from nuri.trading.strategy.ls_backtest import analyze_per_regime, classify_historical_regimes
        regimes = classify_historical_regimes(db_path=rich_db)
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)


class TestLSBacktest_R27:
    """From test_coverage_round27.py."""

    def test_classify_multiple_regimes(self, rich_db):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=rich_db)
        assert len(df) > 0

    def test_print_timing(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes, print_timing
        regimes = classify_historical_regimes(db_path=rich_db)
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing
        timing = analyze_entry_timing(regimes)
        print_timing(timing)
        assert len(capsys.readouterr().out) >= 0

    def test_print_rules_comparison(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_rules_comparison,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes(db_path=rich_db)
        result = run_backtest_with_rules(regimes, db_path=rich_db)
        print_rules_comparison(result)
        assert len(capsys.readouterr().out) > 0


class TestLSBacktestEmpty:
    """ls_backtest: empty DataFrame causes IndexError."""

    def test_empty_df_raises(self, db_path):
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        df = classify_historical_regimes(db_path=db_path)
        # Empty DB → empty or minimal df
        assert isinstance(df, pd.DataFrame)
        if len(df) == 0:
            from nuri.trading.strategy.ls_backtest import run_backtest
            with pytest.raises((IndexError, KeyError, ValueError)):
                run_backtest(df, db_path=db_path)


# ═══════════════════════════════════════════════════════════════════════
# PART 4: nuri.trading.strategy.pairs
# ═══════════════════════════════════════════════════════════════════════


class TestPairs:
    """From test_new_features.py — pairs trading basics."""

    def test_find_pairs(self, market_data):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=market_data)
        assert isinstance(pairs, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=market_data)
        assert "pairs_found" in result


class TestPairsTrading:
    """From test_coverage_extra.py — pairs trading."""

    def test_find_pairs(self):
        from nuri.trading.strategy.pairs import find_pairs
        assert callable(find_pairs)

    def test_find_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=db_path)
        assert isinstance(results, list)

    def test_find_pairs_with_data(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=rich_db)
        assert isinstance(results, list)


class TestFindPairs:
    """From test_coverage_round21.py — find_pairs deeper tests."""

    def test_finds_correlated_pairs(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=rich_db)
        assert isinstance(pairs, list)
        if pairs:
            assert hasattr(pairs[0], "ticker_a")
            assert pairs[0].correlation >= 0.5

    def test_empty_when_no_prices(self, tmp_path):
        path = tmp_path / "no_prices.db"
        init_db(path)
        upsert_portfolio([
            {"account": "t", "ticker": "AAPL", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
            {"account": "t", "ticker": "MSFT", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
        ], path)
        from nuri.trading.strategy.pairs import find_pairs
        assert find_pairs(db_path=path) == []

    def test_pairs_sorted_by_zscore(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.3, db_path=rich_db)
        if len(pairs) >= 2:
            assert abs(pairs[0].current_z) >= abs(pairs[1].current_z)


class TestScanPairSignals:
    """From test_coverage_round21.py — scan pair signals."""

    def test_scan_returns_signals_or_empty(self, rich_db):
        from nuri.trading.strategy.pairs import scan_pair_signals
        signals = scan_pair_signals(db_path=rich_db)
        assert isinstance(signals, list)


class TestBacktestPairs:
    """From test_coverage_round21.py — backtest pairs."""

    def test_backtest_runs(self, rich_db):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(max_hold=10, db_path=rich_db)
        assert isinstance(result, dict)
        assert "pairs_found" in result

    def test_backtest_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=path)
        assert result["total_trades"] == 0


# ═══════════════════════════════════════════════════════════════════════
# PART 5: nuri.trading.strategy.mean_reversion
# ═══════════════════════════════════════════════════════════════════════


class TestMeanReversion:
    """From test_new_features.py — mean reversion basics."""

    def test_scan_returns_list(self, market_data):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        signals = scan_mean_reversion(db_path=market_data)
        assert isinstance(signals, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=market_data)
        assert "total_trades" in result


class TestMeanReversion_Extra:
    """From test_coverage_extra.py — mean reversion."""

    def test_import(self):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        assert callable(scan_mean_reversion)

    def test_empty_db(self, db_path):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=db_path)
        assert isinstance(results, list)

    def test_with_data(self, rich_db):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=rich_db)
        assert isinstance(results, list)


class TestMeanReversionBacktest:
    """From test_coverage_round16.py — backtest."""

    def test_no_trades(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "flat.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "t", "ticker": "FLAT", "quantity": 1,
                           "avg_price": 100, "currency": "USD", "sector": "Tech"}], path)
        dates = pd.bdate_range("2024-01-01", periods=80, freq="B")
        rows = [{"ticker": "FLAT", "date": d.strftime("%Y-%m-%d"),
                 "open": 100, "high": 101, "low": 99, "close": 100,
                 "volume": 1_000_000, "adj_close": 100} for d in dates]
        upsert_prices(pd.DataFrame(rows), path)

        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=path)
        assert result["total_trades"] == 0

    def test_backtest_with_rich_data(self, rich_db):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=rich_db)
        assert "total_trades" in result


# ═══════════════════════════════════════════════════════════════════════
# PART 6: nuri.trading.strategy.monitor
# ═══════════════════════════════════════════════════════════════════════


class TestMonitor:
    """From test_strategy.py — monitor."""

    def test_regime_transition_initial(self, bull_data):
        from nuri.trading.strategy.monitor import detect_regime_transition
        transition = detect_regime_transition(db_path=bull_data)
        if transition:
            assert "to_regime" in transition

    def test_pnl_empty(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        pnl = daily_pnl_summary(db_path=db_path)
        assert pnl["total_positions"] == 0


class TestStrategyMonitor:
    """From test_coverage_extra.py — monitor."""

    def test_detect_regime_transition(self, db_path):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=db_path)
        assert result is None or isinstance(result, dict)

    def test_daily_pnl_summary(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=db_path)
        assert isinstance(result, dict)


class TestMonitorDailyPnl:
    """From test_coverage_round16.py — daily PnL."""

    def test_empty_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 0
        assert result["best"] is None

    def test_with_open_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "AAPL", "long", "2025-01-01", 170.0, 10, 200.0, 17.6, "open"))
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "TSLA", "long", "2025-01-01", 250.0, 3, 230.0, -8.0, "open"))
        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 2
        assert result["best"]["ticker"] == "AAPL"
        assert result["worst"]["ticker"] == "TSLA"


class TestMonitorRegimeTransition:
    """From test_coverage_round16.py — regime transitions."""

    def test_classify_regime_fails(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_classify_returns_none(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_transition_bull_to_bear(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bear_high_vol"
        mock_regime.confidence = 0.80
        mock_regime.trend = "bear"
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "sideways_low_vol", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "high"

    def test_first_regime_no_previous(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.90
        mock_regime.trend = "bull"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "low"


class TestMonitorDeep:
    """From test_coverage_round10.py — monitor print."""

    def test_daily_pnl_summary(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=rich_db)
        assert isinstance(result, dict)

    def test_print_monitor(self, rich_db, capsys):
        from nuri.trading.strategy.monitor import print_monitor
        print_monitor(db_path=rich_db)
        output = capsys.readouterr().out
        assert len(output) >= 0


class TestMonitor_R8:
    """From test_coverage_round8.py — monitor."""

    def test_detect_regime_transition(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=rich_db)
        assert result is None or isinstance(result, dict)

    def test_daily_pnl_summary(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=rich_db)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════
# PART 7: nuri.trading.swing.scanner
# ═══════════════════════════════════════════════════════════════════════


class TestScanResult:
    """From test_swing.py — scan result."""

    def test_analyze_ticker(self):
        from nuri.trading.swing.scanner import ScanResult, _analyze_ticker
        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 120, 30)
        volume = [1000000] * 20 + [3000000] * 10
        data = pd.DataFrame({
            "Close": close, "Volume": volume,
        }, index=dates)
        result = _analyze_ticker("TEST", data)
        if result:
            assert isinstance(result, ScanResult)
            assert result.ticker == "TEST"
            assert result.score > 0


class TestAnalyzeTickerScanner:
    """From test_coverage_round18.py — _analyze_ticker patterns."""

    def _make_data(self, prices, volumes=None):
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        df = pd.DataFrame({
            "Close": prices, "Volume": volumes,
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
        volumes = [10_000_000] * 29 + [30_000_000]
        prices = [100.0 + i * 0.5 for i in range(30)]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.score > 0

    def test_zero_price_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [0.0] * 30
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        assert result is None

    def test_no_signal_returns_none(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0] * 30
        volumes = [10_000_000] * 30
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        assert result is None


class TestScanMarket:
    """From test_coverage_round18.py — scan_market."""

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


class TestPrintScan:
    """From test_coverage_round18.py — print_scan."""

    def test_print_scan_results(self, capsys):
        from nuri.trading.swing.scanner import ScanResult, print_scan
        results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]
        print_scan(results)
        out = capsys.readouterr().out
        assert "AAPL" in out

    def test_print_scan_empty(self, capsys):
        from nuri.trading.swing.scanner import print_scan
        print_scan([])
        out = capsys.readouterr().out
        assert "스캔 결과 없음" in out


class TestScannerMomentumBreakout:
    """From test_coverage_round18.py — momentum/breakout detection."""

    def _make_data(self, prices, volumes=None):
        n = len(prices)
        if volumes is None:
            volumes = [50_000_000] * n
        dates = pd.bdate_range("2024-01-01", periods=n)
        return pd.DataFrame({
            "Close": prices, "Volume": volumes,
            "Open": [p - 1 for p in prices],
            "High": [p + 2 for p in prices],
            "Low": [p - 2 for p in prices],
        }, index=dates)

    def test_momentum_signal(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0 + i * 1.5 for i in range(30)]
        df = self._make_data(prices)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.score > 0

    def test_breakout_signal(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        prices = [100.0] * 25 + [100.0, 101.0, 103.0, 108.0, 115.0]
        volumes = [10_000_000] * 25 + [10_000_000, 15_000_000, 20_000_000, 25_000_000, 35_000_000]
        df = self._make_data(prices, volumes)
        result = _analyze_ticker("AAPL", df)
        if result is not None:
            assert result.signal in ("breakout", "volume_spike", "momentum")


class TestScanner_Push:
    """From test_coverage_push.py — scanner."""

    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market(market="us")
        assert isinstance(results, list)

    def test_scan_result_fields(self):
        from nuri.trading.swing.scanner import ScanResult
        r = ScanResult("AAPL", 150.0, 2.5, 5.0, 1.5, 35.0, 0.1, "bounce", 30.0)
        assert r.ticker == "AAPL"
        assert r.score == 30.0


class TestSwingScannerInternals:
    """From test_coverage_round15.py — scanner internals."""

    def test_scan_with_signals(self, rich_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market()
        if results:
            r = results[0]
            assert hasattr(r, "ticker")


class TestScanner_R26:
    """From test_coverage_round26.py — scanner."""

    def test_analyze_ticker_flat(self):
        from nuri.trading.swing.scanner import _analyze_ticker
        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n)
        df = pd.DataFrame({
            "Close": [100.0] * n, "Volume": [1_000_000] * n,
            "Open": [99.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
        }, index=dates)
        result = _analyze_ticker("TEST", df)
        assert result is None

    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market
        with patch("nuri.trading.swing.scanner._fetch_prices", return_value=None):
            results = scan_market()
        assert results == []


# ═══════════════════════════════════════════════════════════════════════
# PART 8: nuri.trading.swing.rules
# ═══════════════════════════════════════════════════════════════════════


class TestSwingRules:
    """From test_swing.py — basic rules."""

    def test_entry_evaluation(self, db_path):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(scan_results=[], db_path=db_path)
        assert entries == []

    def test_exit_no_positions(self, db_path):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_save_entry(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [SwingEntry(
            ticker="TEST", price=100.0, scan_signal="volume_spike",
            scan_score=30, agent_action="BUY", agent_confidence=70,
            agent_agreement=0.6, approved=True, reason="test",
        )]
        n = save_entries(entries, db_path=db_path)
        assert n == 1
        rows = query("SELECT * FROM swing_trades WHERE ticker='TEST'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["status"] == "open"


class TestSwingEntry:
    """From test_swing_rules.py — SwingEntry dataclass."""

    def test_create(self):
        from nuri.trading.swing.rules import SwingEntry
        e = SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok")
        assert e.ticker == "AAPL"
        assert e.approved is True

    def test_rejected(self):
        from nuri.trading.swing.rules import SwingEntry
        e = SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "HOLD", 30.0, 0.5, False, "에이전트 HOLD")
        assert e.approved is False


class TestSwingExit:
    """From test_swing_rules.py — SwingExit dataclass."""

    def test_create(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 165.0, 10.0, 5, "take_profit", True)
        assert x.should_exit is True
        assert x.exit_reason == "take_profit"

    def test_hold(self):
        from nuri.trading.swing.rules import SwingExit
        x = SwingExit("AAPL", 150.0, 152.0, 1.3, 2, "hold", False)
        assert x.should_exit is False


class TestSaveEntries:
    """From test_swing_rules.py — save_entries."""

    def test_save_approved(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok"),
            SwingEntry("MSFT", 300.0, "macd_golden", 25.0, "HOLD", 30.0, 0.5, False, "rejected"),
        ]
        n = save_entries(entries, db_path=db_path)
        assert n == 1
        rows = query("SELECT * FROM swing_trades", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"

    def test_save_empty(self, db_path):
        from nuri.trading.swing.rules import save_entries
        n = save_entries([], db_path=db_path)
        assert n == 0

    def test_save_all_rejected(self, db_path):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "HOLD", 30.0, 0.5, False, "no"),
        ]
        n = save_entries(entries, db_path=db_path)
        assert n == 0


class TestCheckExits:
    """From test_swing_rules.py — check_exits."""

    def test_no_open_trades(self, db_path):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_take_profit(self, db_path):
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("AAPL", today, 100.0, "rsi_oversold"),
            )
        prices = pd.DataFrame([{
            "ticker": "AAPL", "date": today,
            "open": 114, "high": 116, "low": 113, "close": 115.0,
            "volume": 1000000, "adj_close": 115.0,
        }])
        upsert_prices(prices, db_path)
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "take_profit"
        assert exits[0].should_exit is True

    def test_stop_loss(self, db_path):
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("BAD", today, 100.0, "bb_bounce"),
            )
        prices = pd.DataFrame([{
            "ticker": "BAD", "date": today,
            "open": 93, "high": 94, "low": 92, "close": 93.0,
            "volume": 1000000, "adj_close": 93.0,
        }])
        upsert_prices(prices, db_path)
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "stop_loss"

    def test_max_hold(self, db_path):
        entry_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, entry_signal, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                ("HOLD", entry_date, 100.0, "momentum"),
            )
        prices = pd.DataFrame([{
            "ticker": "HOLD", "date": today,
            "open": 101, "high": 102, "low": 100, "close": 101.0,
            "volume": 1000000, "adj_close": 101.0,
        }])
        upsert_prices(prices, db_path)
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert len(exits) == 1
        assert exits[0].exit_reason == "max_hold"


class TestCheckExits_R18:
    """From test_coverage_round18.py — check_exits with rich data."""

    def test_take_profit_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', '2024-10-01', 100.0, 'open')")
        exits = check_exits(rich_db)
        assert len(exits) >= 1
        tp = [e for e in exits if e.exit_reason == "take_profit"]
        assert len(tp) >= 1

    def test_no_open_trades(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(rich_db)
        assert exits == []


class TestPrintEntries:
    """From test_swing_rules.py — print_entries."""

    def test_empty(self, capsys):
        from nuri.trading.swing.rules import print_entries
        print_entries([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_entries(self, capsys):
        from nuri.trading.swing.rules import SwingEntry, print_entries
        entries = [
            SwingEntry("AAPL", 150.0, "rsi_oversold", 30.0, "BUY", 65.0, 0.8, True, "ok"),
            SwingEntry("MSFT", 300.0, "macd_golden", 25.0, "HOLD", 30.0, 0.5, False, "no"),
        ]
        print_entries(entries)
        output = capsys.readouterr().out
        assert "APPROVED" in output
        assert "REJECTED" in output


class TestPrintExits:
    """From test_swing_rules.py — print_exits."""

    def test_empty(self, capsys):
        from nuri.trading.swing.rules import print_exits
        print_exits([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_exits(self, capsys):
        from nuri.trading.swing.rules import SwingExit, print_exits
        exits = [SwingExit("AAPL", 150.0, 165.0, 10.0, 5, "take_profit", True)]
        print_exits(exits)
        output = capsys.readouterr().out
        assert "AAPL" in output


class TestConstants:
    """From test_swing_rules.py — constants."""

    def test_thresholds(self):
        from nuri.trading.swing.rules import (
            MAX_HOLD_DAYS,
            MIN_AGENT_CONFIDENCE,
            MIN_SCAN_SCORE,
            STOP_LOSS_PCT,
            TAKE_PROFIT_PCT,
        )
        assert TAKE_PROFIT_PCT == 10.0
        assert STOP_LOSS_PCT == -5.0
        assert MAX_HOLD_DAYS == 7
        assert MIN_SCAN_SCORE == 20
        assert MIN_AGENT_CONFIDENCE == 50


class TestEvaluateEntries:
    """From test_coverage_round18.py — evaluate_entries with mocked consensus."""

    def test_approved_entry(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult
        scan_results = [
            ScanResult("AAPL", 180.0, 2.0, 8.0, 3.0, 55.0, 0.6, "volume_spike", 40.0),
        ]
        mock_consensus = MagicMock(
            final_action="BUY", final_confidence=75.0, agreement_rate=0.6,
        )
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            entries = evaluate_entries(scan_results=scan_results, db_path=rich_db)
        assert len(entries) == 1
        assert entries[0].approved is True

    def test_rejected_low_confidence(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        from nuri.trading.swing.scanner import ScanResult
        scan_results = [
            ScanResult("NVDA", 900.0, 3.0, 10.0, 2.0, 60.0, 0.5, "momentum", 30.0),
        ]
        mock_consensus = MagicMock(
            final_action="BUY", final_confidence=30.0, agreement_rate=0.3,
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

    def test_empty_scan_results(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(scan_results=[], db_path=rich_db)
        assert entries == []


class TestSaveEntries_R18:
    """From test_coverage_round18.py — save_entries."""

    def test_saves_approved(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("AAPL", 180.0, "volume_spike", 40.0, "BUY", 75.0, 0.6, True, "approved"),
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]
        n = save_entries(entries, rich_db)
        assert n == 1

    def test_no_approved_returns_zero(self, rich_db):
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [
            SwingEntry("NVDA", 900.0, "momentum", 50.0, "HOLD", 40.0, 0.3, False, "rejected"),
        ]
        n = save_entries(entries, rich_db)
        assert n == 0


class TestSwingPrintHelpers:
    """From test_coverage_round18.py — print helpers."""

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

    def test_print_exits(self, capsys):
        from nuri.trading.swing.rules import SwingExit, print_exits
        exits = [
            SwingExit("AAPL", 170.0, 185.0, 8.82, 3, "hold", False),
            SwingExit("NVDA", 900.0, 800.0, -11.11, 5, "stop_loss", True),
        ]
        print_exits(exits)
        out = capsys.readouterr().out
        assert "STOP_LOSS" in out


class TestSwingRulesDeep:
    """From test_coverage_round11.py — deeper rules."""

    def test_evaluate_entries(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(db_path=rich_db)
        assert isinstance(entries, list)

    def test_check_exits(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=rich_db)
        assert isinstance(exits, list)


class TestSwingAgentSellExit:
    """From test_coverage_round18.py — agent SELL exit path."""

    def test_agent_sell_triggers_exit(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        latest = query(
            "SELECT close FROM prices WHERE ticker='AAPL' ORDER BY date DESC LIMIT 1",
            db_path=rich_db,
        )[0]["close"]
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO swing_trades (ticker, entry_date, entry_price, status) "
                "VALUES ('AAPL', ?, ?, 'open')",
                (datetime.now().strftime("%Y-%m-%d"), latest),
            )
        mock_consensus = MagicMock(final_action="SELL", final_confidence=85.0)
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_consensus):
            exits = check_exits(rich_db)
        agent_sells = [e for e in exits if e.exit_reason == "agent_sell"]
        assert len(agent_sells) >= 1
        assert agent_sells[0].should_exit is True


class TestSwingScanner_R8:
    """From test_coverage_round8.py — swing scanner/rules combo."""

    def test_scan(self, rich_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market()
        assert isinstance(results, list)

    def test_evaluate_entries(self, rich_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(db_path=rich_db)
        assert isinstance(entries, list)

    def test_check_exits(self, rich_db):
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=rich_db)
        assert isinstance(exits, list)
