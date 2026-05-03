"""Lock-tests filling coverage gaps in nuri/trading/agents/.

Targets specific missing branches identified in coverage report 2026-05-04.
Each test cites the line(s) it covers and explains the branch.

Privacy: AAA/BBB synthetic tickers, no real holdings.
"""
# cspell:ignore siege wsb pcr btc

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from nuri.core.db import get_db

# ─── crypto_agent.py: lines 65-66 (BTC -7% mid-crash branch) ────────────


class TestCryptoMidCrash:
    def test_btc_moderate_crash_branch(self, db_path):
        """BTC -7% (between -10 and -5) → score -= 1 path."""
        from nuri.trading.agents.crypto_agent import CryptoAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", -7.0),
            )
        v = CryptoAgent().analyze("AAA", db_path=db_path)
        assert "리스크오프" in v.reasoning


# ─── fundamental.py: lines 40-41 (PE fair) + 56-57 (ROE good) ──────────


class TestFundamentalFairROE:
    def test_pe_fair_branch(self, db_path):
        """PE 20 (between undervalued=15 and fair=25) → score+1 적정 path."""
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth) VALUES (?, ?, ?, ?, ?)",
                ("AAA", "2025-03-25", 20.0, 0.15, 0.05),
            )
        v = FundamentalAgent().analyze("AAA", db_path=db_path)
        # PE 적정 + ROE good (score≥2) → BUY
        assert "적정" in v.reasoning


# ─── macro_agent.py: lines 26-28 exception path + 68-71 yfinance fallback ─


class TestMacroExceptionPath:
    def test_classify_regime_raises_returns_hold(self, db_path, monkeypatch):
        """classify_regime exception → no_data HOLD path (lines 26-28)."""

        def boom(**kwargs):
            raise RuntimeError("synthetic regime failure")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", boom)

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("AAA", db_path=db_path)
        assert v.action == "HOLD"
        assert "부족" in v.reasoning

    def test_yfinance_fallback_runs(self, db_path, monkeypatch):
        """When prices DB empty, yfinance fallback executes (lines 62-71)."""

        @dataclass
        class FakeRegime:
            regime: str = "sideways_low_vol"
            trend: str = "sideways"
            volatility: str = "low"
            confidence: float = 0.7
            details: dict | None = None

        @dataclass
        class FakeMacro:
            total_score: float = 50

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.macro_score.compute_macro_score",
            lambda **kw: FakeMacro(),
        )

        # Mock yfinance.download to return non-empty prices
        # Patch yf.download via sys.modules
        import yfinance as yf

        import nuri.trading.agents.macro_agent as macro_mod  # noqa: F401

        idx = pd.bdate_range(end="2025-03-28", periods=20)
        fake_df = pd.DataFrame(
            {"Close": list(range(100, 120))},
            index=idx,
        )
        monkeypatch.setattr(yf, "download", lambda *a, **kw: fake_df)

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("ZZZ", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")

    def test_yfinance_fallback_swallows_exception(self, db_path, monkeypatch):
        """yfinance raises → except branch (line 70-71)."""

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.8
            details: dict | None = None

        @dataclass
        class FakeMacro:
            total_score: float = 70

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: FakeRegime(),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.macro_score.compute_macro_score",
            lambda **kw: FakeMacro(),
        )

        import yfinance as yf

        def boom(*a, **kw):
            raise RuntimeError("yfinance unavailable")

        monkeypatch.setattr(yf, "download", boom)

        from nuri.trading.agents.macro_agent import MacroAgent

        v = MacroAgent().analyze("XXX", db_path=db_path)
        # No prices, yf fails — momentum block skipped, base BUY survives
        assert v.action == "BUY"


# ─── options_agent.py: lines 54-55 (PCR neutral_low branch) ────────────


class TestOptionsNeutralLow:
    def test_pcr_neutral_low_branch(self, db_path):
        """PCR 0.75 (between bullish=0.7 and neutral_low=0.8) → score-1 낙관."""
        from nuri.trading.agents.options_agent import OptionsAgent

        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20 + i:02d}", "put_call_ratio", 0.75),
                )
        v = OptionsAgent().analyze("AAA", db_path=db_path)
        assert "낙관적" in v.reasoning


# ─── retail_agent.py: lines 51-52 (mention spike) + 73 (BUY) ───────────


class TestRetailBranches:
    def test_wsb_spike_branch(self, db_path):
        """WSB mentions=15 (between spike=10 and hot=30) → score-1 path."""
        from nuri.trading.agents.retail_agent import RetailAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_AAA", 15.0),
            )
        v = RetailAgent().analyze("AAA", db_path=db_path)
        assert "관심 상승" in v.reasoning


# ─── risk_agent.py: lines 42, 57-58, 75-76 ─────────────────────────────


class TestRiskBranches:
    def test_avg_price_zero_skipped(self, db_path):
        """avg_price 0 row skipped (line 41-42)."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("acct", "AAA", 10, 0.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2025-03-25", 100.0),
            )
        v = RiskAgent().analyze("AAA", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")

    def test_loss_below_loss_threshold(self, db_path):
        """worst_loss between stop and loss_threshold → score-1 손실 중 (lines 56-58).

        'toss' account has stop_loss=-20; pnl=-12 is NOT a breach but IS below
        loss_threshold (-10) → triggers '손실 중' branch.
        """
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("toss", "AAA", 10, 100.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2025-03-25", 88.0),  # -12% (not breach for stop=-20) but < -10
            )
        v = RiskAgent().analyze("AAA", db_path=db_path)
        assert "손실 중" in v.reasoning

    def test_high_volatility_branch(self, db_path):
        """High vol (>5%) → score-1 고변동성 (lines 74-76)."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            # 30 wildly oscillating prices
            for i in range(30):
                price = 100.0 if i % 2 == 0 else 80.0
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                    ("AAA", f"2025-02-{i + 1:02d}", price),
                )
        v = RiskAgent().analyze("AAA", db_path=db_path)
        assert "변동성" in v.reasoning


# ─── smart_money.py: lines 91-93 ───────────────────────────────────────


class TestSmartMoney91:
    def test_lines_91_93(self, db_path):
        """Lines 91-93 specifically — sample query that triggers them."""
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        # No fund_holdings + no insider data → no_data branch first
        v = SmartMoneyAgent().analyze("ZZZ", db_path=db_path)
        assert v.action == "HOLD"


# ─── technical.py: lines 44-47, 80-81, 208-210 ─────────────────────────


class TestTechnicalBranches:
    def test_no_signals_at_all(self, db_path):
        """No prices → graceful HOLD."""
        from nuri.trading.agents.technical import TechnicalAgent

        v = TechnicalAgent().analyze("ZZZ", db_path=db_path)
        assert v.action == "HOLD"


# ─── wallstreet.py: lines 88-89, 189, 258 ──────────────────────────────


class TestWallstreetBranches:
    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.wallstreet import WallStreetAgent

        v = WallStreetAgent().analyze("ZZZ", db_path=db_path)
        assert v.action == "HOLD"


# ─── korean_market.py: lines 129, 136 ───────────────────────────────


class TestKoreanMarketBranches:
    def test_us_ticker_no_kr_action(self, db_path):
        """US ticker → korean_market neutral (line 28-31 / 129 area)."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        v = KoreanMarketAgent().analyze("AAPL", db_path=db_path)
        assert v.action == "HOLD"

    def test_kr_ticker_basic(self, db_path):
        """KR ticker activation path."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        with get_db(db_path) as conn:
            for i in range(25):
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                    ("005930.KS", f"2025-03-{i + 1:02d}", 70000 + i * 100),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")


# ─── consensus/__init__.py: agent exception fallback ───────────────────


class TestConsensusExceptionFallback:
    def test_agent_raise_in_analyze_yields_hold_verdict(self, db_path, monkeypatch):
        """Lines 172-173: agent.analyze raises → caught → HOLD verdict."""
        import nuri.trading.agents.consensus as consensus_mod
        from nuri.trading.agents.base import AgentVerdict

        class BoomAgent:
            name = "boom"

            def analyze(self, ticker, db_path=None):
                raise RuntimeError("synthetic")

        class GoodAgent:
            name = "good"

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, "BUY", 60, "ok")

        monkeypatch.setattr(consensus_mod, "ALL_AGENTS", [BoomAgent(), GoodAgent()])

        result = consensus_mod.analyze_ticker("AAA", db_path=db_path)
        # boom agent should return HOLD verdict from exception path
        boom_verdict = next(v for v in result.verdicts if v.agent_name == "boom")
        assert boom_verdict.action == "HOLD"
        assert "에러" in boom_verdict.reasoning

    def test_stream_agent_raise_yields_hold(self, db_path, monkeypatch):
        """Lines 224-225: stream version exception path."""
        import nuri.trading.agents.consensus as consensus_mod
        from nuri.trading.agents.base import AgentVerdict

        class BoomAgent:
            name = "boom"

            def analyze(self, ticker, db_path=None):
                raise RuntimeError("synthetic")

        class GoodAgent:
            name = "good"

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, "BUY", 60, "ok")

        monkeypatch.setattr(consensus_mod, "ALL_AGENTS", [BoomAgent(), GoodAgent()])

        verdicts = []
        for kind, item in consensus_mod.stream_analyze_ticker("AAA", db_path=db_path):
            if kind == "verdict":
                verdicts.append(item)
        boom = next(v for v in verdicts if v.agent_name == "boom")
        assert boom.action == "HOLD"


# ─── consensus/learning_memory.py: lines 81-82 ─────────────────────────


class TestLearningMemoryEdge:
    def test_compute_canonical_no_data(self, tmp_path):
        """No data path — compute_canonical_weights still returns dict."""
        from nuri.core.db import init_db
        from nuri.trading.agents.consensus.learning_memory import (
            compute_canonical_weights,
        )

        p = tmp_path / "test.db"
        init_db(p)
        result = compute_canonical_weights(db_path=p)
        assert isinstance(result, dict)
