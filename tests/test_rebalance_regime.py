"""E-2 레짐 적응 리밸런싱 테스트."""
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# 섹터 분류
# ═══════════════════════════════════════════════════════

class TestClassifySector:
    def test_defensive_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Real Estate") == "defensive"
        assert _classify_sector("Pharma") == "defensive"
        assert _classify_sector("Defense") == "defensive"

    def test_growth_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("Software") == "growth"

    def test_neutral(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"

    def test_case_insensitive(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("TECHNOLOGY") == "growth"
        assert _classify_sector("health care") == "defensive"


# ═══════════════════════════════════════════════════════
# RebalanceAction 데이터 클래스
# ═══════════════════════════════════════════════════════

class TestRebalanceAction:
    def test_create(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="AAPL", sector="Technology", action="BUY",
            current_weight=5.0, target_weight=10.0, trade_value=5000,
            signals=["rsi_oversold(BUY)"], regime_note="[bull_strong]",
        )
        assert a.action == "BUY"
        assert a.trade_value == 5000

    def test_hold_action(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="MSFT", sector="Software", action="HOLD",
            current_weight=10.0, target_weight=10.0, trade_value=0,
            signals=[], regime_note="[bull_strong]",
        )
        assert a.action == "HOLD"


# ═══════════════════════════════════════════════════════
# CASH_TARGETS
# ═══════════════════════════════════════════════════════

class TestCashTargets:
    def test_values(self):
        from nuri.trading.recommend.rebalance import CASH_TARGETS
        assert CASH_TARGETS["aggressive"] == 0.0
        assert CASH_TARGETS["minimal"] == 0.40
        assert CASH_TARGETS["defensive"] == 0.20
        assert CASH_TARGETS["normal"] == 0.05


# ═══════════════════════════════════════════════════════
# print_rebalance
# ═══════════════════════════════════════════════════════

class TestPrintRebalance:
    def test_empty(self, capsys):
        from nuri.trading.recommend.rebalance import print_rebalance
        print_rebalance([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_actions(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "BUY", 5.0, 10.0, 5000, ["rsi(BUY)"], "[bull_strong]"),
            RebalanceAction("MSFT", "Software", "HOLD", 10.0, 10.0, 0, [], "[bull_strong]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "Rebalancing" in output

    def test_all_hold(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "HOLD", 10.0, 10.0, 0, [], "[bull]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "불필요" in output
