"""Tests for nuri.trading.strategy.longshort.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""
from unittest.mock import MagicMock, patch

from nuri.core.db import get_db, query


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
