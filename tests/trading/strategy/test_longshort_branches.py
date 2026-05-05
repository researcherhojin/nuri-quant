"""longshort.py branch coverage — Issue #616 Phase 3-D2.

| line | branch | trigger |
|---|---|---|
| 314→306 | `if pos:` False (close 시 포지션 부재) | actions 에 close 인데 DB 에 매칭 포지션 없음 |
| 325→306 | `elif a.action in ('open_long','open_short')` False | action 이 close/open_* 외 |
| 347→306 | `if success:` False (open_position 실패) | open_position → False |
| 378→384 | `if opens:` False (close 만 있는 actions) | print_strategy with close-only |
"""

from __future__ import annotations

from unittest.mock import patch

from nuri.trading.strategy.longshort import StrategyAction, execute_strategy, print_strategy


def _action(act: str = "close", ticker: str = "AAA", direction: str = "long") -> StrategyAction:
    return StrategyAction(act, ticker, direction, "tactical", "test", "bull_low_vol", 80)


class TestExecuteStrategyClosePathNoPosition:
    def test_close_action_no_matching_position_skipped(self, tmp_path, monkeypatch):
        """314→306: close action 인데 DB 에 포지션 없음 → close_position 미호출 → next iter."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        p = tmp_path / "no_pos.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)

        # update_prices / close_position / open_position 호출 차단
        with (
            patch("nuri.trading.strategy.position.update_prices") as up_prices,
            patch("nuri.trading.strategy.position.close_position") as cp,
            patch("nuri.trading.strategy.position.open_position"),
        ):
            executed = execute_strategy([_action("close")], db_path=p)

        assert executed == 0
        cp.assert_not_called()
        up_prices.assert_called_once()


class TestExecuteStrategyUnknownAction:
    def test_unknown_action_falls_through(self, tmp_path, monkeypatch):
        """325→306: action='hold' 등 close/open_* 외 → if/elif 모두 False → next iter."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        p = tmp_path / "unknown.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)

        unknown = StrategyAction("hold", "AAA", "long", "tactical", "wait", "bull_low_vol", 50)

        with (
            patch("nuri.trading.strategy.position.update_prices"),
            patch("nuri.trading.strategy.position.close_position") as cp,
            patch("nuri.trading.strategy.position.open_position") as op,
        ):
            executed = execute_strategy([unknown], db_path=p)

        assert executed == 0
        cp.assert_not_called()
        op.assert_not_called()


class TestExecuteStrategyOpenFailure:
    def test_open_position_returns_false_no_increment(self, tmp_path, monkeypatch):
        """347→306: open_position → False (SIEGE reject 등) → executed 증가 없음."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        p = tmp_path / "open_fail.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)

        # yfinance.download mock — 정상 가격 반환
        import pandas as pd

        fake_df = pd.DataFrame({"Close": [100.0, 102.0, 105.0, 107.0, 110.0]})

        class _FakeYf:
            @staticmethod
            def download(*a, **kw):
                return fake_df

        import sys

        monkeypatch.setitem(sys.modules, "yfinance", _FakeYf)

        with (
            patch("nuri.trading.strategy.position.update_prices"),
            patch("nuri.trading.strategy.position.close_position"),
            patch("nuri.trading.strategy.position.open_position", return_value=False) as op,
        ):
            executed = execute_strategy([_action("open_long")], db_path=p)

        assert executed == 0
        op.assert_called_once()


class TestPrintStrategyClosesOnly:
    def test_close_only_skips_opens_section(self, capsys):
        """378→384: opens=[] 빈 리스트 → if False → OPEN section skip → final print()."""
        actions = [_action("close", "AAA"), _action("close", "BBB")]
        print_strategy(actions)
        captured = capsys.readouterr().out
        assert "CLOSE" in captured
        assert "OPEN" not in captured  # opens section 미렌더
