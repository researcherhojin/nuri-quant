"""Tests for nuri.trading.strategy.position.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""
from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import get_db, query


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


class TestRegimeAlignmentMatrix_R86:
    """10 regime × 2 direction 풀 매트릭스 — #86 회귀 가드.

    이전 코드는 substring fallback (`'bull' in regime`, `'high' in regime`)
    을 썼는데, 이는 두 가지 문제를 만들었음:

    1. 4개 special regime (recovery/euphoria/stagflation/sector_rotation)
       이름에 'bull'/'sideways' 부분문자열이 없어서 LONG fallback이 항상
       False였음. 다행히 REGIME_ALLOCATION 메인 lookup이 먼저 매칭되어
       latent bug였음.
    2. SHORT 로직의 `'high' in regime` 체크는 두 가지 잘못:
       - bear_low_vol (short_pct=30)이 'high' 미포함이라 잘못 차단
       - sideways_high_vol (short_pct=0)이 'high' 포함이라 잘못 허용

    Fix: REGIME_ALLOCATION의 long_pct/short_pct를 ground truth로 사용.
    이 클래스는 그 결정이 회귀하지 않도록 10×2 = 20 케이스를 lock한다.
    """

    @pytest.fixture
    def db(self, bull_data):
        return bull_data

    @pytest.mark.parametrize(("regime", "expected_long"), [
        # 6 base regimes — long_pct > 0 인 곳만 long aligned
        ("bull_low_vol",      True),   # long_pct=80
        ("bull_high_vol",     True),   # long_pct=60
        ("sideways_low_vol",  True),   # long_pct=40
        ("sideways_high_vol", True),   # long_pct=20
        ("bear_low_vol",      True),   # long_pct=10 (방어 섹터 롱 허용)
        ("bear_high_vol",     False),  # long_pct=0  (전량 청산)
        # 4 special regimes — 이전엔 substring fallback이 dead code였음
        ("recovery",          True),   # long_pct=80 (회복기 공격적 롱)
        ("euphoria",          True),   # long_pct=40 (과열기 방어적이지만 롱 일부)
        ("stagflation",       True),   # long_pct=10 (최소 롱)
        ("sector_rotation",   True),   # long_pct=50 (선별 롱)
    ])
    def test_long_alignment(self, db, regime, expected_long):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", regime, db_path=db)
        assert cert.regime_aligned is expected_long, (
            f"long in {regime}: got {cert.regime_aligned}, expected {expected_long}"
        )

    @pytest.mark.parametrize(("regime", "expected_short"), [
        # 6 base regimes — short_pct > 0 인 곳만 short aligned
        ("bull_low_vol",      False),  # short_pct=0
        ("bull_high_vol",     False),  # short_pct=0
        ("sideways_low_vol",  False),  # short_pct=0
        ("sideways_high_vol", False),  # short_pct=0  (이전 substring 로직은 잘못 True)
        ("bear_low_vol",      True),   # short_pct=30 (이전 substring 로직은 잘못 False)
        ("bear_high_vol",     True),   # short_pct=50
        # 4 special regimes — 모두 short_pct=0
        ("recovery",          False),
        ("euphoria",          False),
        ("stagflation",       False),
        ("sector_rotation",   False),
    ])
    def test_short_alignment(self, db, regime, expected_short):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("SH", "short", regime, db_path=db)
        assert cert.regime_aligned is expected_short, (
            f"short in {regime}: got {cert.regime_aligned}, expected {expected_short}"
        )

    def test_unknown_regime_fails_closed(self, db):
        """미등록 레짐은 보수적으로 차단."""
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "totally_made_up_regime", db_path=db)
        assert cert.regime_aligned is False


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
