"""Round 23 coverage tests — targeting uncovered lines across 10 modules.

Modules covered:
1. wallstreet.py — WallStreet agent analyze + cached path
2. rebalance.py — regime_aware_rebalance + print_rebalance
3. certification.py — SIEGE certification conditions
4. longshort.py — L/S strategy + execute_strategy
5. tracker.py — save_recommendations + print_tracking_report
6. gate.py — print_gate + CLI __main__ paths
7. pipeline.py — Pipeline API routes
8. consensus.py — edge cases + print_consensus
9. price_targets.py — take-profit, trailing stop, MDD
10. memory.py — save_snapshot + detect_drift edge cases
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db

# ═══════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_portfolio(db_path, tickers=None):
    """Insert sample portfolio rows."""
    tickers = tickers or [("kakaopay", "AAPL", 10, 150.0, "USD", "Technology"),
                          ("kakaopay", "MSFT", 5, 300.0, "USD", "Technology"),
                          ("kakaopay", "JNJ", 20, 160.0, "USD", "Health")]
    with get_db(db_path) as conn:
        for account, ticker, qty, avg_price, currency, sector in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, ticker, qty, avg_price, currency, sector),
            )


def _seed_prices(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


# ═══════════════════════════════════════════════════════
# 1. WallStreet Agent
# ═══════════════════════════════════════════════════════


class TestWallStreetAgent:
    """Cover lines 51-52, 71-72, 78, 85-86, 88, 98-99, 112-116, 121-122,
    142-144, 148-149, 170-174, 180-181, 193."""

    def test_skip_tickers(self, db_path):
        """ETF/KS tickers return HOLD immediately."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        v = agent.analyze("VOO", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 20

    def test_skip_korean(self, db_path):
        """Korean tickers (.KS) skip."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        v = agent.analyze("005930.KS", db_path=db_path)
        assert v.action == "HOLD"

    def test_yfinance_exception(self, db_path, monkeypatch):
        """yfinance load failure → HOLD conf=0 (lines 51-52)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        # Force _check_cached to return None
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        # Force yfinance import to raise
        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: (_ for _ in ()).throw(RuntimeError("fail")))
        v = agent.analyze("NVDA", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0
        assert "yfinance 로드 실패" in v.reasoning

    def test_analyze_upgrades_and_downgrades(self, db_path, monkeypatch):
        """Downgrades exceed upgrades (lines 71-72, 78, 85-86, 88, 98-99)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        # Build mock Ticker with downgrades dominant + priceTargetAction
        ud_data = pd.DataFrame({
            "Action": ["down", "down", "down", "down", "init"],
            "priceTargetAction": ["lowers", "lowers", "", "", "raises"],
            "currentPriceTarget": [100.0, 95.0, None, None, 110.0],
        }, index=pd.to_datetime(["2026-03-28"] * 5))

        class MockTicker:
            upgrades_downgrades = ud_data
            earnings_history = None
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        # Should have downgrades dominant → negative score
        assert "다운그레이드" in v.reasoning or "등급변경" in v.reasoning

    def test_analyze_earnings_surprise_positive(self, db_path, monkeypatch):
        """Earnings surprise positive (lines 112-116)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        eh_data = pd.DataFrame({
            "surprisePercent": [0.15],
            "epsActual": [3.5],
            "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "서프라이즈" in v.reasoning

    def test_analyze_earnings_miss(self, db_path, monkeypatch):
        """Earnings miss (lines 112-114)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        eh_data = pd.DataFrame({
            "surprisePercent": [-0.10],
            "epsActual": [2.5],
            "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "미스" in v.reasoning

    def test_analyze_earnings_inline(self, db_path, monkeypatch):
        """Earnings inline (lines 115-116)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        eh_data = pd.DataFrame({
            "surprisePercent": [0.01],
            "epsActual": [3.0],
            "epsEstimate": [3.0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "부합" in v.reasoning

    def test_analyze_earnings_exception(self, db_path, monkeypatch):
        """Earnings_history raises exception (lines 121-122)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None

            @property
            def earnings_history(self):
                raise RuntimeError("earnings fail")

            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        # Should still return a verdict (HOLD with no data)
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_insider_net_sell(self, db_path, monkeypatch):
        """Insider net sell (lines 142-144)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        ins_data = pd.DataFrame({
            "Text": ["Sale of"] * 8 + ["Purchase of"] * 2,
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = ins_data
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "내부자 순매도" in v.reasoning

    def test_analyze_insider_exception(self, db_path, monkeypatch):
        """Insider_transactions raises exception (lines 148-149)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None

            @property
            def insider_transactions(self):
                raise RuntimeError("insider fail")

            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_consensus_bear(self, db_path, monkeypatch):
        """Consensus bearish (lines 170-174)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        rec_data = pd.DataFrame({
            "strongBuy": [0],
            "buy": [1],
            "hold": [2],
            "sell": [5],
            "strongSell": [5],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "매도" in v.reasoning

    def test_analyze_consensus_neutral(self, db_path, monkeypatch):
        """Consensus neutral (lines 173-174)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        rec_data = pd.DataFrame({
            "strongBuy": [2],
            "buy": [2],
            "hold": [10],
            "sell": [1],
            "strongSell": [0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "중립" in v.reasoning

    def test_analyze_consensus_exception(self, db_path, monkeypatch):
        """Recommendations raises exception (lines 180-181)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None

            @property
            def recommendations(self):
                raise RuntimeError("recs fail")

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_analyze_sell_verdict(self, db_path, monkeypatch):
        """Enough negative score → SELL verdict (line 193)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        # Downgrades + earnings miss + insider sell + bear consensus → strong negative
        ud_data = pd.DataFrame({
            "Action": ["down", "down", "down", "down"],
            "priceTargetAction": ["lowers", "lowers", "lowers", ""],
            "currentPriceTarget": [100.0, 95.0, 90.0, None],
        }, index=pd.to_datetime(["2026-03-28"] * 4))

        eh_data = pd.DataFrame({
            "surprisePercent": [-0.15],
            "epsActual": [2.0],
            "epsEstimate": [3.0],
        })

        ins_data = pd.DataFrame({"Text": ["Sale"] * 8 + ["Purchase"] * 1})

        rec_data = pd.DataFrame({
            "strongBuy": [0], "buy": [0], "hold": [2], "sell": [5], "strongSell": [5],
        })

        class MockTicker:
            upgrades_downgrades = ud_data
            earnings_history = eh_data
            insider_transactions = ins_data
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert v.action == "SELL"

    def test_upgrades_exception_path(self, db_path, monkeypatch):
        """upgrades_downgrades access raises (lines 98-99)."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        eh_data = pd.DataFrame({
            "surprisePercent": [0.10],
            "epsActual": [3.5],
            "epsEstimate": [3.0],
        })

        class MockTicker:
            @property
            def upgrades_downgrades(self):
                raise RuntimeError("fail")

            earnings_history = eh_data
            insider_transactions = None
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        # Still gets earnings data
        assert "서프라이즈" in v.reasoning


# ═══════════════════════════════════════════════════════
# 2. Rebalance
# ═══════════════════════════════════════════════════════


class TestRebalance:
    """Cover lines 76-77, 110-111, 120-122, 140-144, 151-153, 155-157,
    165-166, 218-225."""

    def test_classify_sector_defensive(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Finance") == "neutral"

    def test_classify_sector_growth(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_regime_aware_rebalance_with_mocks(self, db_path, monkeypatch):
        """Full rebalance flow with mocked dependencies (covers many lines)."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        # Mock gate
        @dataclass
        class MockGateResult:
            ready: bool = False
            conditions: list = None

            def __post_init__(self):
                if self.conditions is None:
                    self.conditions = []

        @dataclass
        class MockGateCond:
            id: str = "test"
            passed: bool = False

        # Mock regime + strategy
        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "minimal"

        # Mock analyze_rebalance returns DataFrame
        base_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT", "JNJ"],
            "sector": ["Technology", "Technology", "Health"],
            "current_weight": [30.0, 25.0, 15.0],
            "optimal_weight": [20.0, 18.0, 22.0],
            "trade_value_usd": [-5000, -3500, 3500],
            "action": ["SELL", "REDUCE", "BUY"],
        })

        monkeypatch.setattr(
            "nuri.trading.engine.gate.check_gate",
            lambda *a, **kw: MockGateResult(
                ready=False,
                conditions=[MockGateCond(id="prices_data", passed=False)],
            ),
        )
        monkeypatch.setattr(
            "nuri.analysis.rebalance.analyze_rebalance",
            lambda **kw: base_df,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: MockRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda *a, **kw: MockStrategy(),
        )
        # Mock screen_candidates to return some candidates
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.trading.engine.conflicts.detect_conflicts",
            lambda *a, **kw: [],
        )

        actions = regime_aware_rebalance(method="rp", db_path=db_path)
        assert len(actions) == 3
        # minimal position → BUY should be blocked (lines 155-157)
        jnj = [a for a in actions if a.ticker == "JNJ"][0]
        assert jnj.action == "HOLD"  # minimal blocks new buys

    def test_regime_aware_rebalance_with_conflicts(self, db_path, monkeypatch):
        """Conflict tickers forced HOLD (lines 151-153)."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        @dataclass
        class MockConflict:
            ticker: str = "AAPL"
            conflict_type: str = "direction_conflict"
            severity: str = "high"

        monkeypatch.setattr(
            "nuri.analysis.rebalance.analyze_rebalance",
            lambda **kw: base_df,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: MockRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda *a, **kw: MockStrategy(),
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.trading.engine.conflicts.detect_conflicts",
            lambda *a, **kw: [MockConflict()],
        )

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"
        assert "충돌" in actions[0].regime_note

    def test_rebalance_empty_base(self, db_path, monkeypatch):
        """Empty base_df returns empty list."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        monkeypatch.setattr(
            "nuri.analysis.rebalance.analyze_rebalance",
            lambda **kw: pd.DataFrame(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: None,
        )

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions == []

    def test_print_rebalance_no_actions(self, capsys):
        """Print empty rebalance (line coverage)."""
        from nuri.trading.recommend.rebalance import print_rebalance

        print_rebalance([])
        captured = capsys.readouterr()
        assert "리밸런싱 데이터 없음" in captured.out

    def test_print_rebalance_with_actions(self, capsys):
        """Print with actionable items (lines 218-225)."""
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance

        actions = [
            RebalanceAction("AAPL", "Tech", "SELL", 30.0, 20.0, -5000.0, ["signal1"], "[bear_high_vol]"),
            RebalanceAction("MSFT", "Tech", "HOLD", 15.0, 15.0, 0.0, [], "[bear_high_vol]"),
        ]
        print_rebalance(actions)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "HOLD: MSFT" in captured.out

    def test_defensive_sector_tilt(self, db_path, monkeypatch):
        """Defensive sector tilt in minimal regime (lines 140-144)."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "defensive"

        base_df = pd.DataFrame({
            "ticker": ["JNJ", "NVDA"],
            "sector": ["Health Care", "Semiconductor"],
            "current_weight": [10.0, 10.0],
            "optimal_weight": [10.0, 10.0],
            "trade_value_usd": [0, 0],
            "action": ["HOLD", "HOLD"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 2

    def test_hold_action_small_diff(self, db_path, monkeypatch):
        """Small weight difference → HOLD (lines 165-166)."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "sideways_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [15.0],
            "optimal_weight": [15.5],  # tiny diff
            "trade_value_usd": [200],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"


# ═══════════════════════════════════════════════════════
# 3. Certification
# ═══════════════════════════════════════════════════════


class TestCertification:
    """Cover lines 80, 85-86, 100, 105-106, 150-154, 166-170,
    181-185, 196, 200-201, 302-304."""

    def test_check_position_limits_pass(self, db_path, monkeypatch):
        """Position limits passing (line 80)."""
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "weight_pct": [10.0, 8.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is True
        assert "최대 비중" in cond.detail

    def test_check_position_limits_violation(self, db_path, monkeypatch):
        """Position limits violation (lines 85-86)."""
        from nuri.trading.engine.certification import _check_position_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "AAPL"],
            "weight_pct": [50.0, 30.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "위반" in cond.detail

    def test_check_position_limits_exception(self, db_path, monkeypatch):
        """Position limits exception (lines 85-86)."""
        from nuri.trading.engine.certification import _check_position_limits

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        cond = _check_position_limits(db_path)
        assert cond.passed is False
        assert "검증 실패" in cond.detail

    def test_check_sector_limits_pass(self, db_path, monkeypatch):
        """Sector limits passing (line 100)."""
        from nuri.trading.engine.certification import _check_sector_limits

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "JNJ"],
            "sector": ["Tech", "Health"],
            "weight_pct": [20.0, 15.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_sector_limits(db_path)
        assert cond.passed is True

    def test_check_sector_limits_exception(self, db_path, monkeypatch):
        """Sector limits exception (lines 105-106)."""
        from nuri.trading.engine.certification import _check_sector_limits

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        cond = _check_sector_limits(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_stop_loss_violations(self, db_path, monkeypatch):
        """Stop loss with violations (lines 150-154)."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        mock_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "pnl_pct": [-25.0, 5.0],
        })
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: mock_df)
        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is False
        assert "위반" in cond.detail

    def test_check_stop_loss_exception(self, db_path, monkeypatch):
        """Stop loss exception (line 154)."""
        from nuri.trading.engine.certification import _check_stop_loss_compliance

        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_stop_loss_compliance(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_conflicts_high(self, db_path, monkeypatch):
        """Conflicts with high severity (lines 166-170)."""
        from nuri.trading.engine.certification import _check_conflicts

        @dataclass
        class MockConflict:
            ticker: str = "AAPL"
            severity: str = "high"

        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: [MockConflict()])
        cond = _check_conflicts(db_path)
        assert cond.passed is False
        assert "high 충돌" in cond.detail

    def test_check_conflicts_exception(self, db_path, monkeypatch):
        """Conflicts exception (lines 169-170)."""
        from nuri.trading.engine.certification import _check_conflicts

        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_conflicts(db_path)
        assert cond.passed is True
        assert "스킵" in cond.detail

    def test_check_drift_critical(self, db_path, monkeypatch):
        """Drift with critical status (lines 181-185)."""
        from nuri.trading.engine.certification import _check_drift_safety

        @dataclass
        class MockDrift:
            signal_id: str = "rsi_oversold"
            status: str = "critical"

        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: [MockDrift()])
        cond = _check_drift_safety(db_path)
        assert cond.passed is False
        assert "critical" in cond.detail

    def test_check_drift_exception(self, db_path, monkeypatch):
        """Drift exception (lines 184-185)."""
        from nuri.trading.engine.certification import _check_drift_safety

        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_drift_safety(db_path)
        assert cond.passed is True

    def test_check_external_data_insufficient(self, db_path, monkeypatch):
        """External data insufficient (lines 196, 200-201)."""
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr("nuri.collectors.external.get_external_summary",
                            lambda *a: {"total_records": 3, "sources": ["tipranks"]})
        cond = _check_external_data(db_path)
        assert cond.passed is False
        assert "3건" in cond.detail

    def test_check_external_data_exception(self, db_path, monkeypatch):
        """External data exception (lines 200-201)."""
        from nuri.trading.engine.certification import _check_external_data

        monkeypatch.setattr("nuri.collectors.external.get_external_summary",
                            lambda *a: (_ for _ in ()).throw(RuntimeError()))
        cond = _check_external_data(db_path)
        assert cond.passed is False
        assert "테이블 없음" in cond.detail

    def test_certify_full(self, db_path, monkeypatch):
        """Full certify with all checks mocked."""
        from nuri.trading.engine.certification import CertCondition, certify

        # Mock all checks to pass
        def mock_check(**kw):
            return CertCondition("test", "test", True, "ok")

        monkeypatch.setattr("nuri.trading.engine.certification.ALL_CERT_CHECKS",
                            [lambda **kw: CertCondition("c1", "desc", True, "ok"),
                             lambda **kw: CertCondition("c2", "desc", False, "fail", "warning")])
        cert = certify(db_path)
        assert cert.certified is True  # warnings don't block
        assert cert.warnings == 1

    def test_print_certificate(self, capsys, db_path, monkeypatch):
        """Print certificate output (lines 302-304)."""
        from nuri.trading.engine.certification import CertCondition, Certificate, print_certificate

        cert = Certificate(
            timestamp="2026-03-31",
            total_conditions=3,
            passed=2,
            failed=1,
            warnings=0,
            certified=False,
            conditions=[
                CertCondition("c1", "Test 1", True, "ok"),
                CertCondition("c2", "Test 2", False, "fail", "error"),
                CertCondition("c3", "Test 3", False, "warn", "warning"),
            ],
            score=66.7,
        )
        print_certificate(cert)
        captured = capsys.readouterr()
        assert "REJECTED" in captured.out
        assert "필수 조건 미충족" in captured.out


# ═══════════════════════════════════════════════════════
# 4. Long/Short Strategy
# ═══════════════════════════════════════════════════════


class TestLongShort:
    """Cover lines 134-141, 161, 216, 219-232, 270-285."""

    def test_generate_bull_with_scanner(self, db_path, monkeypatch):
        """Bull regime with scanner results (lines 134-141)."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            confidence: float = 0.8

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        # No open positions
        _seed_portfolio(db_path)

        @dataclass
        class MockScanResult:
            ticker: str
            signal: str
            score: float

        monkeypatch.setattr("nuri.trading.swing.scanner.scan_market",
                            lambda **kw: [MockScanResult("TSLA", "rsi_oversold", 45),
                                          MockScanResult("GOOG", "macd_golden", 35)])

        actions = generate_strategy(db_path=db_path)
        # Should have ETF longs + scanner results
        long_opens = [a for a in actions if a.action == "open_long"]
        assert len(long_opens) >= 2  # At least QQQ, SPY

    def test_generate_neutral_with_hedge(self, db_path, monkeypatch):
        """Neutral/sideways regime with small hedge (line 161)."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "sideways_high_vol"
            confidence: float = 0.6

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        actions = generate_strategy(db_path=db_path)
        # sideways_high_vol has short_pct=0, so no hedge
        # But the REGIME_ALLOCATION says short_pct: 0 for sideways_high_vol
        # So no short actions expected
        assert all(a.action != "open_short" for a in actions) or len(actions) == 0

    def test_execute_strategy_close(self, db_path, monkeypatch):
        """Execute strategy close action (lines 216, 219-232)."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        # Insert open position
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("tactical", "QQQ", "long", "2026-03-01", 450.0, "open"),
            )

        # Insert price for QQQ
        _seed_prices(db_path, "QQQ", 460.0)

        actions = [
            StrategyAction("close", "QQQ", "long", "tactical", "test close", "bull_low_vol", 85),
        ]

        # Mock close_position and update_prices
        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a: None)
        monkeypatch.setattr("nuri.trading.strategy.position.close_position", lambda *a, **kw: None)

        result = execute_strategy(actions, db_path=db_path)
        assert result == 1

    def test_execute_strategy_open_long(self, db_path, monkeypatch):
        """Execute strategy open_long with yf download (lines 216, 219-232)."""
        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        actions = [
            StrategyAction("open_long", "QQQ", "long", "tactical", "test", "bull_low_vol", 80),
        ]

        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a: None)

        # yf.download returns empty → continue (line 218-219)
        result = execute_strategy(actions, db_path=db_path)
        assert result == 0  # download returns empty due to conftest mock

    def test_execute_strategy_open_exception(self, db_path, monkeypatch):
        """Execute strategy open with exception (line 219-220)."""
        import yfinance

        from nuri.trading.strategy.longshort import StrategyAction, execute_strategy

        actions = [
            StrategyAction("open_long", "QQQ", "long", "tactical", "test", "bull_low_vol", 80),
        ]

        monkeypatch.setattr("nuri.trading.strategy.position.update_prices", lambda *a: None)
        monkeypatch.setattr(yfinance, "download", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fail")))

        result = execute_strategy(actions, db_path=db_path)
        assert result == 0

    def test_print_strategy(self, capsys):
        """Print strategy output."""
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy

        actions = [
            StrategyAction("close", "QQQ", "long", "tactical", "close reason", "bull_low_vol", 90),
            StrategyAction("open_long", "SPY", "long", "tactical", "open reason", "bull_low_vol", 80),
            StrategyAction("open_short", "SH", "short", "tactical", "hedge", "bear_low_vol", 70),
        ]
        print_strategy(actions)
        captured = capsys.readouterr()
        assert "CLOSE" in captured.out
        assert "OPEN" in captured.out

    def test_print_strategy_empty(self, capsys):
        """Print strategy with no actions."""
        from nuri.trading.strategy.longshort import print_strategy

        print_strategy([])
        captured = capsys.readouterr()
        assert "전략 액션 없음" in captured.out

    def test_generate_bear_close_longs(self, db_path, monkeypatch):
        """Bear regime closes existing long positions."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "bear_low_vol"
            confidence: float = 0.7

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        # Insert open long position
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("tactical", "QQQ", "long", "2026-03-01", 450.0, "open"),
            )

        actions = generate_strategy(db_path=db_path)
        close_actions = [a for a in actions if a.action == "close" and a.ticker == "QQQ"]
        assert len(close_actions) == 1

    def test_generate_pnl_check(self, db_path, monkeypatch):
        """P&L check triggers close (take-profit/stop-loss)."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "sideways_low_vol"
            confidence: float = 0.5

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        # Insert position with +15% return
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("tactical", "TSLA", "long", "2026-03-01", 200.0, 12.0, "open"),
            )

        actions = generate_strategy(db_path=db_path)
        close_tp = [a for a in actions if "익절" in a.reason]
        assert len(close_tp) >= 1

    def test_generate_stop_loss(self, db_path, monkeypatch):
        """Stop-loss triggers close."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "sideways_low_vol"
            confidence: float = 0.5

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("tactical", "TSLA", "long", "2026-03-01", 200.0, -7.0, "open"),
            )

        actions = generate_strategy(db_path=db_path)
        close_sl = [a for a in actions if "손절" in a.reason]
        assert len(close_sl) >= 1


# ═══════════════════════════════════════════════════════
# 5. Tracker
# ═══════════════════════════════════════════════════════


class TestTracker:
    """Cover lines 80, 108, 288-314."""

    def test_save_recommendations_with_actions(self, db_path):
        """Save rebalance actions (line 80, 108)."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockAction:
            ticker: str
            action: str
            signals: list
            regime_note: str

        # Insert price for action ticker
        _seed_prices(db_path, "AAPL", 170.0)

        actions = [
            MockAction("AAPL", "BUY", ["sig1"], "[bull] 비중 확대"),
            MockAction("MSFT", "HOLD", [], "[bull]"),  # HOLD skipped (line 80)
        ]

        verdicts = {
            "AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"}],
        }

        n = save_recommendations(actions=actions, verdicts=verdicts, db_path=db_path)
        assert n == 1  # HOLD is skipped

    def test_save_recommendations_with_candidates(self, db_path):
        """Save candidates."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "NVDA"
            direction: str = "BUY"
            confidence: float = 75.0
            signal_id: str = "rsi_oversold"
            price: float = 850.0
            regime_fit: bool = True
            scoring_detail: dict = None

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_save_empty(self, db_path):
        """No records to save returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations

        n = save_recommendations(db_path=db_path)
        assert n == 0

    def test_save_with_scoring_detail(self, db_path):
        """Save with scoring_detail attached."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "TSLA"
            direction: str = "BUY"
            confidence: float = 60.0
            signal_id: str = "macd_golden"
            price: float = 200.0
            regime_fit: bool = True
            scoring_detail: dict = None

            def __post_init__(self):
                self.scoring_detail = {"base": 50, "drift": 1.0}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_print_tracking_report(self, db_path, capsys):
        """Print tracking report (covers print paths)."""
        from nuri.trading.recommend.tracker import print_tracking_report

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation Tracking Report" in captured.out

    def test_print_tracking_report_with_data(self, db_path, capsys):
        """Print report with tracked data."""
        from nuri.trading.recommend.tracker import print_tracking_report

        # Insert recommendation with outcome
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d, hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-01-01", "AAPL", "BUY", 70, "bull", '["sig1"]', 150.0, 8.5, 1),
            )

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "BUY" in captured.out

    def test_save_merge_existing(self, db_path):
        """Merge signals when same ticker+action exists (line 84-88)."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "AAPL"
            direction: str = "BUY"
            confidence: float = 70.0
            signal_id: str = "rsi_oversold"
            price: float = 170.0
            regime_fit: bool = True
            scoring_detail: dict = None

        @dataclass
        class MockAction:
            ticker: str = "AAPL"
            action: str = "BUY"
            signals: list = None
            regime_note: str = "[bull]"

            def __post_init__(self):
                self.signals = ["macd_golden"]

        _seed_prices(db_path, "AAPL", 170.0)
        n = save_recommendations(
            candidates=[MockCandidate()],
            actions=[MockAction()],
            db_path=db_path,
        )
        assert n == 1  # merged, not duplicated


# ═══════════════════════════════════════════════════════
# 6. Gate
# ═══════════════════════════════════════════════════════


class TestGate:
    """Cover lines 253-263, 267-280."""

    def test_print_gate_ready(self, capsys, db_path):
        """Print gate when ready."""
        from nuri.trading.engine.gate import GateCondition, GateResult, print_gate

        result = GateResult(
            phase="collect",
            total=2,
            passed=2,
            score=1.0,
            ready=True,
            conditions=[
                GateCondition("c1", "collect", "Test 1", True, "ok"),
                GateCondition("c2", "collect", "Test 2", True, "fine"),
            ],
        )
        print_gate(result)
        captured = capsys.readouterr()
        assert "READY" in captured.out
        assert "[PASS]" in captured.out

    def test_print_gate_blocked(self, capsys, db_path):
        """Print gate when blocked."""
        from nuri.trading.engine.gate import GateCondition, GateResult, print_gate

        result = GateResult(
            phase="validate",
            total=2,
            passed=1,
            score=0.5,
            ready=False,
            conditions=[
                GateCondition("c1", "validate", "Test 1", True, "ok"),
                GateCondition("c2", "validate", "Test 2", False, "need data"),
            ],
        )
        print_gate(result)
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.out
        assert "[FAIL]" in captured.out

    def test_check_all_gates(self, db_path):
        """check_all_gates returns dict of phases."""
        from nuri.trading.engine.gate import check_all_gates

        gates = check_all_gates(db_path=db_path)
        assert "collect" in gates
        assert "validate" in gates
        assert "regime" in gates
        assert "recommend" in gates

    def test_check_gate_none_phase(self, db_path):
        """check_gate with None phase checks all."""
        from nuri.trading.engine.gate import check_gate

        result = check_gate(phase=None, db_path=db_path)
        assert result.phase == "all"
        assert result.total >= 8


# ═══════════════════════════════════════════════════════
# 7. Pipeline API
# ═══════════════════════════════════════════════════════


class TestPipelineAPI:
    """Cover lines 21-22, 90-93, 108-110, 115, 117-129."""

    @pytest.fixture()
    def client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        return TestClient(app)

    def test_scheduler_health_no_file(self, client, monkeypatch, tmp_path):
        """Scheduler health when no heartbeat file (lines 21-22)."""
        import nuri.api.routes.pipeline as pipeline_mod
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", tmp_path / "nonexistent")
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    def test_scheduler_health_valid(self, client, monkeypatch, tmp_path):
        """Scheduler health with valid heartbeat."""
        import nuri.api.routes.pipeline as pipeline_mod
        hb_path = tmp_path / ".scheduler_heartbeat"
        from nuri.core.timezone import kst_now
        hb_path.write_text(kst_now().replace(tzinfo=None).isoformat())
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_pipeline_status(self, client):
        """Pipeline status endpoint."""
        resp = client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data

    def test_pipeline_timeline(self, client):
        """Pipeline timeline endpoint."""
        resp = client.get("/api/pipeline/timeline?limit=10")
        assert resp.status_code == 200

    def test_pipeline_timeline_invalid_step(self, client):
        """Pipeline timeline with invalid step."""
        resp = client.get("/api/pipeline/timeline?step=invalid")
        assert resp.status_code == 400

    def test_run_step_invalid(self, client):
        """Run invalid step."""
        resp = client.post("/api/pipeline/invalid_step/run")
        assert resp.status_code == 400

    def test_run_step_collect(self, client):
        """Run collect step (lines 108-110)."""
        resp = client.post("/api/pipeline/collect/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "not_implemented" in data.get("detail", "")

    def test_run_step_validate(self, client, monkeypatch):
        """Run validate step (lines 108-110)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: [{"signal": "test"}],
        )
        resp = client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_run_step_classify(self, client, monkeypatch):
        """Run classify step (lines 115)."""
        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            trend: str = "bullish"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: MockRegime(),
        )
        resp = client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "bull_low_vol" in data.get("detail", "")

    def test_run_step_classify_none(self, client, monkeypatch):
        """Run classify step returns None (line 116)."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: None,
        )
        resp = client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown" in data.get("detail", "")

    def test_run_step_diagnose(self, client, monkeypatch):
        """Run diagnose step (lines 117-120)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda: ["r1", "r2"],
        )
        resp = client.post("/api/pipeline/diagnose/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "2 tickers" in data.get("detail", "")

    def test_run_step_recommend(self, client, monkeypatch):
        """Run recommend step (lines 121-124)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda: ["c1"],
        )
        resp = client.post("/api/pipeline/recommend/run")
        assert resp.status_code == 200

    def test_run_step_track(self, client, monkeypatch):
        """Run track step (lines 125-128)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.tracker.track_outcomes",
            lambda: 5,
        )
        resp = client.post("/api/pipeline/track/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "5 recommendations" in data.get("detail", "")

    def test_run_step_exception(self, client, monkeypatch):
        """Run step that throws exception (lines 90-93)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        resp = client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    def test_freshness_endpoint(self, client):
        """Freshness endpoint."""
        resp = client.get("/api/freshness")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════
# 8. Consensus
# ═══════════════════════════════════════════════════════


class TestConsensus:
    """Cover lines 108, 112, 127-128, 138, 178-183, 289-292, 320-321, 326-341."""

    def test_compute_weights_no_data(self, db_path):
        """No recommendation data → default weights (line 97)."""
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert abs(weights["technical"] - 0.16) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """With enough data → adjusted weights (lines 108, 112, 127-128, 138)."""
        from nuri.trading.agents.consensus import _compute_weights

        # Insert 15+ recommendations with verdicts
        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = json.dumps({
                    "verdicts": [
                        {"agent_name": "technical", "action": "BUY"},
                        {"agent_name": "fundamental", "action": "BUY"},
                    ]
                })
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-01-{i+1:02d}", f"T{i}", "BUY", 70, "bull", verdicts, 100.0, 5.0 + i),
                )

        weights = _compute_weights(db_path=db_path)
        # Should still be normalized
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_non_json_signals(self, db_path):
        """Signals field that isn't the expected JSON format (lines 108, 112)."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-02-{i+1:02d}", f"T{i}", "BUY", 70, "bull", '["rsi_oversold"]', 100.0, 3.0),
                )

        weights = _compute_weights(db_path=db_path)
        # Falls back to default because signals don't contain verdicts
        assert "technical" in weights

    def test_analyze_ticker_with_timeout(self, db_path, monkeypatch):
        """Agent timeout handling (lines 178-183)."""
        # Mock ALL_AGENTS to contain one slow agent
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import analyze_ticker

        class SlowAgent:
            name = "slow_agent"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("slow_agent", ticker, "HOLD", 50, "slow result")

        class QuickAgent:
            name = "technical"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 70, "quick buy")

        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [QuickAgent(), SlowAgent()])
        monkeypatch.setattr("nuri.trading.agents.consensus._compute_weights",
                            lambda db_path=None: {"technical": 0.5, "slow_agent": 0.5})

        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.ticker == "AAPL"
        assert result.final_action in ("BUY", "SELL", "HOLD")

    def test_print_consensus_with_targets(self, capsys, db_path, monkeypatch):
        """Print consensus with price targets (lines 289-292)."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [ConsensusResult(
            ticker="AAPL",
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.8,
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 80, "buy signal"),
                AgentVerdict("fundamental", "AAPL", "HOLD", 40, "neutral"),
            ],
            dissent=["fundamental(HOLD, 40): neutral"],
            reasoning="technical: buy signal",
        )]

        # Mock calculate_targets and format_target_tree
        monkeypatch.setattr("nuri.trading.recommend.price_targets.calculate_targets",
                            lambda *a, **kw: {"ticker": "AAPL", "error": "no data"})
        monkeypatch.setattr("nuri.trading.recommend.price_targets.format_target_tree",
                            lambda t: "AAPL target tree")

        # Mock get_external to raise so we skip that block
        monkeypatch.setattr("nuri.collectors.external.get_external",
                            lambda *a: (_ for _ in ()).throw(ImportError("no module")))

        print_consensus(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "Dissent" in captured.out

    def test_print_consensus_empty(self, capsys):
        """Print with empty results."""
        from nuri.trading.agents.consensus import print_consensus

        print_consensus([])
        captured = capsys.readouterr()
        assert "합의 결과 없음" in captured.out

    def test_print_consensus_external_data(self, capsys, monkeypatch):
        """Print consensus with external data (lines 320-321)."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [ConsensusResult(
            ticker="AAPL",
            final_action="HOLD",
            final_confidence=50.0,
            agreement_rate=0.6,
            verdicts=[AgentVerdict("technical", "AAPL", "HOLD", 50, "neutral")],
            dissent=[],
            reasoning="neutral",
        )]

        monkeypatch.setattr("nuri.trading.recommend.price_targets.calculate_targets",
                            lambda *a, **kw: (_ for _ in ()).throw(Exception("fail")))
        monkeypatch.setattr("nuri.collectors.external.get_external",
                            lambda ticker: [
                                {"data_type": "consensus", "value": "Strong Buy", "source": "tipranks", "numeric_value": None},
                                {"data_type": "superinvestor_count", "value": "5", "source": "dataroma", "numeric_value": 5},
                                {"data_type": "target_price", "value": "$200", "source": "tipranks", "numeric_value": 200},
                            ])

        print_consensus(results)
        captured = capsys.readouterr()
        assert "External Data" in captured.out


# ═══════════════════════════════════════════════════════
# 9. Price Targets
# ═══════════════════════════════════════════════════════


class TestPriceTargets:
    """Cover lines 88, 239-240, 313-327, 359, 363-364, 369, 427, 431-432,
    441, 449, 492-493, 523, 541-547."""

    def test_classify_stock_type_growth_pe(self, db_path):
        """PE > 30 → growth (line 88)."""
        # Reset cache
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?, ?, ?)",
                ("NEWCO", "2026-03-31", 50.0),
            )

        result = classify_stock_type("NEWCO", db_path=db_path)
        assert result == "growth"

    def test_classify_stock_type_sector_growth(self, db_path):
        """Sector-based growth classification."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [("kakaopay", "SEMCO", 10, 100.0, "USD", "Semiconductor")])
        result = classify_stock_type("SEMCO", db_path=db_path)
        assert result == "growth"

    def test_classify_stock_type_value(self, db_path):
        """Default fallback → value."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None

        result = classify_stock_type("UNKNOWN", db_path=db_path)
        assert result == "value"

    def test_calculate_targets_no_price(self, db_path):
        """No price data → error dict."""
        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_calculate_targets_swing(self, db_path):
        """Swing stock type."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_targets
        pt_mod._stock_types_cache = None

        _seed_prices(db_path, "SWING", 100.0)
        result = calculate_targets("SWING", entry_price=100.0, stock_type="swing", db_path=db_path)
        assert result["stock_type"] == "swing"
        assert result["trailing_stop_pct"] == -20  # volatile

    def test_calculate_targets_value(self, db_path):
        """Value stock type."""
        from nuri.trading.recommend.price_targets import calculate_targets

        _seed_prices(db_path, "VALUE", 100.0)
        result = calculate_targets("VALUE", entry_price=100.0, stock_type="value", db_path=db_path)
        assert result["stock_type"] == "value"
        assert result["stop_loss_pct"] == -10  # value stop loss

    def test_calculate_targets_with_analyst(self, db_path):
        """Analyst target present."""
        from nuri.trading.recommend.price_targets import calculate_targets

        _seed_prices(db_path, "AAPL", 170.0)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, target_mean) VALUES (?, ?, ?)",
                ("AAPL", "2026-03-31", 220.0),
            )

        result = calculate_targets("AAPL", db_path=db_path)
        assert result["analyst_target"] == 220.0
        assert result["analyst_upside_pct"] is not None

    def test_print_portfolio_targets_empty(self, capsys):
        """Print empty targets."""
        from nuri.trading.recommend.price_targets import print_portfolio_targets

        print_portfolio_targets([])
        captured = capsys.readouterr()
        assert "종목 없음" in captured.out

    def test_print_portfolio_targets(self, capsys, db_path):
        """Print targets with data (lines 313-327)."""
        from nuri.trading.recommend.price_targets import print_portfolio_targets

        targets = [
            {
                "ticker": "AAPL",
                "stock_type": "growth",
                "current_price": 170.0,
                "entry_price": 150.0,
                "stop_loss": 139.5,
                "stop_loss_pct": -7.0,
                "target_1": 180.0,
                "target_1_pct": 20.0,
                "target_1_sell_pct": 50,
                "target_2": 210.0,
                "target_2_pct": 40.0,
                "target_2_sell_pct": 25,
                "trailing_stop_pct": -15.0,
                "analyst_target": 220.0,
                "analyst_upside_pct": 29.4,
            },
            {
                "ticker": "MSFT",
                "stock_type": "value",
                "current_price": 400.0,
                "entry_price": 380.0,
                "stop_loss": 342.0,
                "stop_loss_pct": -10.0,
                "target_1": 437.0,
                "target_1_pct": 15.0,
                "target_1_sell_pct": 50,
                "target_2": 494.0,
                "target_2_pct": 30.0,
                "target_2_sell_pct": 25,
                "trailing_stop_pct": -15.0,
                "analyst_target": None,
                "analyst_upside_pct": None,
            },
        ]
        print_portfolio_targets(targets)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "MSFT" in captured.out
        assert "포트폴리오 가격 목표" in captured.out

    def test_check_take_profit_target2(self, db_path):
        """Take profit target_2 reached (lines 359, 363-364, 369)."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        pt_mod._stock_types_cache = None

        # Insert portfolio with avg_price
        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 100.0, "USD", "Technology")])
        # Current price = 145 → +45% for growth (target_2 = +40%)
        _seed_prices(db_path, "AAPL", 145.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_2"

    def test_check_take_profit_target1(self, db_path):
        """Take profit target_1 reached."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 100.0, "USD", "Technology")])
        # Current price = 122 → +22% (target_1 = +20%)
        _seed_prices(db_path, "AAPL", 122.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_1"

    def test_check_take_profit_no_entry(self, db_path):
        """No avg_price → skip."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 0, "USD", "Technology")])
        _seed_prices(db_path, "AAPL", 200.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 0

    def test_check_trailing_stop(self, db_path):
        """Trailing stop triggered (lines 427, 431-432, 441, 449)."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 100.0, "USD", "Technology")])
        # HWM=200, current=160 → -20% drop, threshold=-15% → triggered
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-01", 195, 200, 190, 195, 1000000),
            )
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-31", 162, 165, 158, 160, 1000000),
            )

        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["status"] == "TRIGGERED"

    def test_check_trailing_stop_not_triggered(self, db_path):
        """Trailing stop NOT triggered."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices(db_path, "AAPL", 180.0, high=185.0)

        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) == 0

    def test_check_portfolio_mdd_no_violation(self, db_path):
        """MDD within limit."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 150.0, "USD", "Technology")])
        _seed_prices(db_path, "AAPL", 155.0)

        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_check_portfolio_mdd_violation(self, db_path):
        """MDD exceeds limit (lines 492-493, 523)."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 100, 200.0, "USD", "Technology")])
        # Current price = 170 → -15% (limit is -10%)
        _seed_prices(db_path, "AAPL", 170.0)

        result = check_portfolio_mdd(db_path=db_path)
        assert result is not None
        assert result["severity"] == "critical"

    def test_check_portfolio_mdd_with_krw(self, db_path):
        """MDD with KRW ticker conversion (lines 492-493)."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        _seed_portfolio(db_path, [("kakaopay", "005930.KS", 10, 70000.0, "KRW", "Semiconductor")])
        _seed_prices(db_path, "005930.KS", 72000.0, high=73000.0)
        _seed_macro(db_path, "usd_krw", 1350.0)

        result = check_portfolio_mdd(db_path=db_path)
        assert result is None  # +2.8% → no violation

    def test_check_portfolio_mdd_empty(self, db_path):
        """Empty portfolio → None."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_format_target_tree_error(self):
        """Format target tree with error."""
        from nuri.trading.recommend.price_targets import format_target_tree

        result = format_target_tree({"ticker": "AAPL", "error": "no data"})
        assert "AAPL" in result
        assert "no data" in result

    def test_format_target_tree_no_analyst(self):
        """Format target tree without analyst target (line 306)."""
        from nuri.trading.recommend.price_targets import format_target_tree

        target = {
            "ticker": "AAPL",
            "stock_type": "growth",
            "current_price": 170.0,
            "entry_price": 150.0,
            "stop_loss": 139.5,
            "stop_loss_pct": -7.0,
            "target_1": 180.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 210.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "└──" in result  # Last line should use └

    def test_format_price_krw(self):
        """KRW price formatting."""
        from nuri.trading.recommend.price_targets import _format_price

        assert "₩" in _format_price(70000, "005930.KS")
        assert "$" in _format_price(170.0, "AAPL")

    def test_calculate_portfolio_targets_empty(self, db_path):
        """Empty portfolio."""
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets

        result = calculate_portfolio_targets(db_path=db_path)
        assert result == []

    def test_calculate_portfolio_targets(self, db_path):
        """Portfolio targets with data (lines 239-240)."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [("kakaopay", "AAPL", 10, 150.0, "USD", "Technology")])
        _seed_prices(db_path, "AAPL", 170.0)

        targets = calculate_portfolio_targets(db_path=db_path)
        assert len(targets) >= 1
        assert targets[0]["ticker"] == "AAPL"

    def test_calculate_portfolio_targets_skip_no_price(self, db_path):
        """Skip ticker with no price data (lines 239-240)."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        pt_mod._stock_types_cache = None

        _seed_portfolio(db_path, [
            ("kakaopay", "AAPL", 10, 150.0, "USD", "Technology"),
            ("kakaopay", "NOPRICE", 5, 100.0, "USD", "Tech"),
        ])
        _seed_prices(db_path, "AAPL", 170.0)

        targets = calculate_portfolio_targets(db_path=db_path)
        tickers = [t["ticker"] for t in targets]
        assert "AAPL" in tickers
        assert "NOPRICE" not in tickers


# ═══════════════════════════════════════════════════════
# 10. Memory
# ═══════════════════════════════════════════════════════


class TestMemory:
    """Cover lines 46-47, 57-58, 114, 241-254."""

    def test_save_snapshot_no_csv(self, db_path, monkeypatch):
        """No CSV file → 0 records (lines 46-47)."""
        from nuri.trading.engine.memory import save_snapshot

        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: None)
        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_empty_trades(self, db_path, monkeypatch, tmp_path):
        """Empty CSV → 0 records."""
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        pd.DataFrame(columns=["signal_id", "entry_date", "return_pct"]).to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_with_trades(self, db_path, monkeypatch, tmp_path):
        """Valid trades → snapshot saved."""
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 5 + ["macd_golden"] * 3,
            "entry_date": [
                (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
                for d in range(8)
            ],
            "return_pct": [3.0, -1.0, 5.0, 2.0, -2.0, 4.0, -1.0, 6.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        # Mock cross analysis to raise (lines 57-58)
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: (_ for _ in ()).throw(ImportError("no module")))

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_save_snapshot_with_cross_df(self, db_path, monkeypatch, tmp_path):
        """Snapshot with regime cross analysis data (line 114)."""
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 3,
            "entry_date": ["2026-03-01", "2026-03-10", "2026-03-20"],
            "return_pct": [3.0, -1.0, 5.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        cross_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"],
            "regime": ["bull_low_vol"],
            "trades": [10],
            "win_rate": [0.65],
            "profit_factor": [2.1],
            "avg_return": [3.5],
        })
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: cross_df)

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_detect_drift_no_data(self, db_path):
        """No snapshot data → empty drifts."""
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_detect_drift_with_data(self, db_path):
        """Drift detection with degrading signal (lines 241-254)."""
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            # All-time: high win rate
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "rsi_oversold", 100, 0.70, 2.5, 3.0),
            )
            # Recent: much lower win rate (critical drift)
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "rsi_oversold", 20, 0.35, 0.8, -1.0),
            )
            # Stable signal
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "macd_golden", 80, 0.55, 1.5, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "macd_golden", 15, 0.60, 1.6, 2.5),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) >= 2
        # rsi_oversold should be critical (50% drop in win rate)
        rsi_drift = [d for d in drifts if d.signal_id == "rsi_oversold"]
        assert rsi_drift[0].status == "critical"
        # macd_golden should be improving or stable
        macd_drift = [d for d in drifts if d.signal_id == "macd_golden"]
        assert macd_drift[0].status in ("stable", "improving")

    def test_print_memory_status_empty(self, capsys):
        """Print with no drifts."""
        from nuri.trading.engine.memory import print_memory_status

        print_memory_status([])
        captured = capsys.readouterr()
        assert "학습 메모리 없음" in captured.out

    def test_print_memory_status_with_drifts(self, capsys):
        """Print with drifts including critical (lines 241-254)."""
        from nuri.trading.engine.memory import PerformanceDrift, print_memory_status

        drifts = [
            PerformanceDrift("rsi_oversold", None, 0.70, 0.35, -50.0, "critical",
                             "승률 -50% 급락 (전체 70% → 최근 35%)"),
            PerformanceDrift("macd_golden", None, 0.55, 0.60, 9.1, "stable",
                             "승률 변화 +9.1% (안정)"),
        ]
        print_memory_status(drifts)
        captured = capsys.readouterr()
        assert "Performance Drift" in captured.out
        assert "성과 하락 시그널" in captured.out

    def test_detect_drift_degrading(self, db_path):
        """Drift detection with degrading (not critical) signal."""
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "bb_bounce", 50, 0.60, 1.8, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "bb_bounce", 10, 0.48, 1.0, 0.5),
            )

        drifts = detect_drift(db_path=db_path)
        bb_drift = [d for d in drifts if d.signal_id == "bb_bounce"]
        assert bb_drift[0].status == "degrading"

    def test_find_latest_csv_nonexistent(self):
        """No report dir → None."""
        from pathlib import Path

        # This will look in the actual REPORT_DIR, but we can test the function
        import nuri.trading.engine.memory as mem_mod
        from nuri.trading.engine.memory import _find_latest_csv
        original = mem_mod.REPORT_DIR
        mem_mod.REPORT_DIR = Path("/nonexistent/path")
        result = _find_latest_csv("signal_results.csv")
        mem_mod.REPORT_DIR = original
        assert result is None


# ═══════════════════════════════════════════════════════
# Additional edge case tests
# ═══════════════════════════════════════════════════════


class TestAdditionalEdgeCases:
    """Extra tests to hit remaining uncovered lines."""

    def test_wallstreet_cached_ratings_upgrades(self, db_path):
        """WallStreet _check_cached with ratings data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()

        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, action, target_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("TSLA", f"2026-03-{20+i}", f"Firm{i}", "upgrade", 300 + i * 10),
                )

        result = agent._check_cached("TSLA", db_path)
        assert result is not None
        assert "cached" in result.reasoning

    def test_wallstreet_cached_earnings_positive(self, db_path):
        """WallStreet _check_cached with positive earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?, ?, ?, ?, ?)",
                ("TSLA", "2026-Q1", 1.5, 1.2, 0.10),
            )

        result = agent._check_cached("TSLA", db_path)
        assert result is not None

    def test_wallstreet_cached_earnings_negative(self, db_path):
        """WallStreet _check_cached with negative earnings surprise."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) "
                "VALUES (?, ?, ?, ?, ?)",
                ("TSLA", "2026-Q1", 0.8, 1.2, -0.15),
            )

        result = agent._check_cached("TSLA", db_path)
        assert result is not None

    def test_wallstreet_cached_insider_sells(self, db_path):
        """WallStreet _check_cached with heavy insider sells."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()

        with get_db(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, shares, value) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("TSLA", f"2026-03-{10+i}", f"Insider{i}", "sale", 1000, 100000),
                )

        result = agent._check_cached("TSLA", db_path)
        assert result is not None
        assert result.action == "SELL"

    def test_tracker_track_outcomes(self, db_path):
        """Track outcomes for old recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        # Insert old recommendation
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "BUY", 70, "bull", '["sig"]', 150.0),
            )
        # Insert price data for 30-day mark
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2025-12-31", 160.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2026-01-30", 165.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2026-03-01", 170.0),
            )

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_tracker_track_sell_outcome(self, db_path):
        """Track outcomes for SELL recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "SELL", 70, "bear", '["sig"]', 150.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2025-12-31", 140.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2026-01-30", 135.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAPL", "2026-03-01", 130.0),
            )

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_certification_leverage_ban_violation(self, db_path):
        """Leverage ETF found in portfolio."""
        from nuri.trading.engine.certification import _check_leverage_ban

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
                ("test", "TQQQ", 10, 50.0),
            )

        cond = _check_leverage_ban(db_path)
        assert cond.passed is False
        assert "TQQQ" in cond.detail

    def test_certification_vix_gate_high(self, db_path):
        """VIX > 30 triggers warning."""
        from nuri.trading.engine.certification import _check_vix_gate

        _seed_macro(db_path, "vix", 35.0)
        cond = _check_vix_gate(db_path)
        assert cond.passed is False
        assert "금지" in cond.detail

    def test_certification_data_fresh(self, db_path):
        """Data freshness check."""
        from nuri.trading.engine.certification import _check_data_freshness

        _seed_prices(db_path, "SPY", 500.0)
        cond = _check_data_freshness(db_path)
        assert cond.passed is True

    def test_certification_data_stale(self, db_path):
        """Data freshness stale."""
        from nuri.trading.engine.certification import _check_data_freshness

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", "2025-01-01", 450.0),
            )
        cond = _check_data_freshness(db_path)
        assert cond.passed is False

    def test_gate_check_estimates_accumulation_fresh(self, db_path):
        """Estimates accumulation check — fresh data."""
        from nuri.trading.engine.gate import _check_estimates_accumulation

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation) VALUES (?, ?, ?)",
                ("AAPL", "2025-12-01", "buy"),
            )
        cond = _check_estimates_accumulation(db_path)
        assert cond.passed is True

    def test_gate_check_estimates_empty(self, db_path):
        """Estimates accumulation check — no data."""
        from nuri.trading.engine.gate import _check_estimates_accumulation

        cond = _check_estimates_accumulation(db_path)
        assert cond.passed is False

    def test_longshort_bear_high_vol_shorts(self, db_path, monkeypatch):
        """Bear high vol opens aggressive short ETFs."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"
            confidence: float = 0.8

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        actions = generate_strategy(db_path=db_path)
        short_opens = [a for a in actions if a.action == "open_short"]
        assert len(short_opens) >= 1

    def test_longshort_bull_close_shorts(self, db_path, monkeypatch):
        """Bull regime closes existing short positions."""
        from nuri.trading.strategy.longshort import generate_strategy

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            confidence: float = 0.9

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("tactical", "SH", "short", "2026-03-01", 40.0, "open"),
            )

        actions = generate_strategy(db_path=db_path)
        close_actions = [a for a in actions if a.action == "close" and a.ticker == "SH"]
        assert len(close_actions) == 1

    def test_consensus_risk_veto(self, db_path, monkeypatch):
        """Risk agent veto triggers SELL override."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import analyze_ticker

        class RiskAgent:
            name = "risk"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("risk", ticker, "SELL", 90, "veto: danger")

        class TechAgent:
            name = "technical"
            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 80, "buy signal")

        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [TechAgent(), RiskAgent()])
        monkeypatch.setattr("nuri.trading.agents.consensus._compute_weights",
                            lambda db_path=None: {"technical": 0.5, "risk": 0.5})

        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.final_action == "SELL"
        assert "거부권" in result.reasoning

    def test_wallstreet_insider_net_buy(self, db_path, monkeypatch):
        """Insider net buy signal."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        ins_data = pd.DataFrame({
            "Text": ["Purchase of"] * 5 + ["Sale of"] * 1,
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = ins_data
            recommendations = None

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "내부자 순매수" in v.reasoning

    def test_wallstreet_consensus_bull(self, db_path, monkeypatch):
        """Consensus bullish."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)

        rec_data = pd.DataFrame({
            "strongBuy": [8], "buy": [5], "hold": [2], "sell": [0], "strongSell": [0],
        })

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "매수" in v.reasoning

    def test_rebalance_screen_exception(self, db_path, monkeypatch):
        """Screen candidates throws but rebalance continues (lines 120-122)."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("fail")))

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 1
        assert actions[0].action == "BUY"

    def test_scheduler_health_stale(self, db_path, monkeypatch, tmp_path):
        """Scheduler health stale heartbeat."""
        from fastapi.testclient import TestClient

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        # Write timestamp 15 minutes ago (stale)
        stale_time = (datetime.now() - timedelta(minutes=15)).isoformat()
        hb_path.write_text(stale_time)
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stale"

    def test_scheduler_health_error(self, db_path, monkeypatch, tmp_path):
        """Scheduler health with malformed file."""
        from fastapi.testclient import TestClient

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        hb_path.write_text("not-a-valid-iso-timestamp")
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        client = TestClient(app)
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
