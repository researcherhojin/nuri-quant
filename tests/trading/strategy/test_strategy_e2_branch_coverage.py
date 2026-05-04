"""Bucket E2 branch coverage — strategy/longshort, mean_reversion, strategic_allocation.

Targets specific missed lines from coverage audit 2026-05-04.
Each test = behavioral lock. Refactored CLI mains tested via main(argv).
"""
# cspell:ignore SPYY siege longshort

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    p = tmp_path / "test.db"
    init_db(p)
    monkeypatch.setattr(db_mod, "DB_PATH", p)
    return p


# ════════════════════════ longshort.py main(argv) ═════════════════════


class TestLongshortMainCLI:
    """`__main__` block (lines 271-286) refactored to main(argv) — testable."""

    def test_main_no_actions_prints_strategy(self, db_path, monkeypatch, capsys):
        """No-args: generate_strategy + print_strategy, execute branch skipped."""
        from nuri.trading.strategy import longshort as ls

        called = {"generate": False, "print": False, "execute": False}

        def fake_gen():
            called["generate"] = True
            return []

        def fake_print(actions):
            called["print"] = True

        def fake_exec(actions):
            called["execute"] = True
            return 0

        monkeypatch.setattr(ls, "generate_strategy", fake_gen)
        monkeypatch.setattr(ls, "print_strategy", fake_print)
        monkeypatch.setattr(ls, "execute_strategy", fake_exec)
        monkeypatch.setattr(ls, "init_db", lambda: None)

        rc = ls.main([])
        assert rc == 0
        assert called["generate"] is True
        assert called["print"] is True
        assert called["execute"] is False  # no --execute flag

    def test_main_execute_flag_with_actions_invokes_executor(self, db_path, monkeypatch):
        """--execute + actions present → execute_strategy + print_positions."""
        from nuri.trading.strategy import longshort as ls

        called = {"execute": False, "print_pos": False}
        fake_actions = [
            ls.StrategyAction(
                action="open_long", ticker="QQQ", direction="long",
                portfolio_type="tactical", reason="r", regime="bull_low_vol", confidence=80,
            )
        ]

        monkeypatch.setattr(ls, "init_db", lambda: None)
        monkeypatch.setattr(ls, "generate_strategy", lambda: fake_actions)
        monkeypatch.setattr(ls, "print_strategy", lambda actions: None)

        def fake_exec(actions):
            called["execute"] = True
            return 1

        monkeypatch.setattr(ls, "execute_strategy", fake_exec)

        # patch print_positions used in --execute branch
        import nuri.trading.strategy.position as pos_mod

        def fake_pp():
            called["print_pos"] = True

        monkeypatch.setattr(pos_mod, "print_positions", fake_pp)

        rc = ls.main(["--execute"])
        assert rc == 0
        assert called["execute"] is True
        assert called["print_pos"] is True

    def test_main_execute_flag_no_actions_skips_executor(self, db_path, monkeypatch):
        """--execute but actions empty → execute_strategy NOT invoked."""
        from nuri.trading.strategy import longshort as ls

        called = {"execute": False}
        monkeypatch.setattr(ls, "init_db", lambda: None)
        monkeypatch.setattr(ls, "generate_strategy", lambda: [])
        monkeypatch.setattr(ls, "print_strategy", lambda actions: None)

        def fake_exec(actions):
            called["execute"] = True
            return 0

        monkeypatch.setattr(ls, "execute_strategy", fake_exec)
        rc = ls.main(["--execute"])
        assert rc == 0
        # `args.execute and actions` short-circuits — execute NOT called
        assert called["execute"] is False


# ════════════════════════ mean_reversion.py main() ═════════════════════


class TestMeanReversionMainCLI:
    """`__main__` (lines 160-171) refactored to main() — testable."""

    def test_main_invokes_scan_and_backtest(self, monkeypatch, capsys):
        """main() prints scan results + backtest report."""
        from nuri.trading.strategy import mean_reversion as mr

        called = {"scan": False, "bt": False}

        def fake_scan():
            called["scan"] = True
            return []

        def fake_bt():
            called["bt"] = True
            return {"strategy": "mean_reversion", "total_trades": 0}

        monkeypatch.setattr(mr, "scan_mean_reversion", fake_scan)
        monkeypatch.setattr(mr, "backtest_mean_reversion", fake_bt)

        rc = mr.main()
        assert rc == 0
        assert called["scan"] is True
        assert called["bt"] is True

        captured = capsys.readouterr()
        # 두 헤더 모두 출력 — 분기 진입 lock
        assert "Mean-Reversion Scan" in captured.out
        assert "Mean-Reversion Backtest" in captured.out

    def test_main_prints_signal_loop(self, monkeypatch, capsys):
        """signals 가 있으면 ticker/RSI/Z line emit (signals[:10] loop)."""
        from nuri.trading.strategy import mean_reversion as mr

        sig = mr.MeanRevSignal(
            ticker="AAPL", date="2025-03-25", entry_price=170.0,
            bb_lower=168.0, rsi=25.0, z_score=-2.5, expected_target=175.0,
        )
        monkeypatch.setattr(mr, "scan_mean_reversion", lambda: [sig])
        monkeypatch.setattr(
            mr, "backtest_mean_reversion",
            lambda: {"strategy": "mean_reversion", "total_trades": 0},
        )
        rc = mr.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "AAPL" in out


# ════════════════════════ strategic_allocation.py ═════════════════════


class TestStrategicAllocationDriftEdges:
    def test_non_numeric_quantity_skipped(self, db_path):
        """Lines 51-52: non-numeric quantity/avg_price → ValueError → continue."""
        from nuri.trading.strategy.strategic_allocation import compute_current_allocation

        # quantity is a string non-convertible value
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "BAD", "not_a_number", 100.0, "Technology"),
            )
            # Add one valid row so we don't hit the `total_value <= 0` branch
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "AAPL", 10, 150.0, "Technology"),
            )
        result = compute_current_allocation(db_path=db_path)
        # Bad row skipped, only AAPL counted → 100% us_equity
        assert result.get("us_equity", 0) == 100.0

    def test_zero_value_position_skipped(self, db_path):
        """Lines 53-54 (value <= 0 skip) and effectively non-zero AAPL classifies."""
        from nuri.trading.strategy.strategic_allocation import compute_current_allocation

        with get_db(db_path) as conn:
            # quantity 0 → value 0 → skip
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "ZERO", 0, 100.0, "Technology"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "AAPL", 5, 200.0, "Technology"),
            )
        result = compute_current_allocation(db_path=db_path)
        # ZERO skipped. AAPL accounts for 100%
        assert result.get("us_equity", 0) == 100.0

    def test_total_value_zero_returns_empty(self, db_path):
        """Line 60: 모든 row skip 되어 total_value <= 0 → {}.

        ValueError 가 발생하는 텍스트 quantity 와 0 quantity 만 사용 — NaN 회피.
        """
        from nuri.trading.strategy.strategic_allocation import compute_current_allocation

        with get_db(db_path) as conn:
            # 텍스트 quantity → ValueError → continue
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "BAD1", "abc", 100.0, "Technology"),
            )
            # quantity = 0 → value <= 0 → continue
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "BAD2", 0, 100.0, "Technology"),
            )
        result = compute_current_allocation(db_path=db_path)
        assert result == {}

    def test_no_asset_class_rules_returns_empty(self, db_path, monkeypatch):
        """Line 44: rules_cfg empty → return {} (asset_class_rules 없음)."""
        from nuri.trading.strategy import strategic_allocation as sa

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "AAPL", 10, 150.0, "Technology"),
            )
        # Remove asset_class_rules
        fake_rules = {"siege_gates": {}}
        monkeypatch.setattr(sa, "RULES", fake_rules)
        result = sa.compute_current_allocation(db_path=db_path)
        assert result == {}
