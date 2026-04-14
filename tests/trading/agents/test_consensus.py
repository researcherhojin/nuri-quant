"""Tests for consensus agent — split from test_trading_agents_all.py."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestConsensus:
    def test_consensus_returns_result(self, agent_data):
        from nuri.trading.agents.consensus import analyze_ticker

        r = analyze_ticker("TEST", db_path=agent_data)
        assert r.ticker == "TEST"
        assert r.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= r.final_confidence <= 100
        assert 0 <= r.agreement_rate <= 1
        assert len(r.verdicts) == 10

    def test_risk_veto(self, db_path):
        """리스크 에이전트 거부권: 손절 돌파 → 전체 SELL."""
        from nuri.trading.agents.consensus import analyze_ticker

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "VETO", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2024-01-01", periods=250)
        close = np.concatenate([np.linspace(100, 120, 200), np.linspace(120, 60, 50)])
        df = pd.DataFrame(
            {
                "ticker": "VETO",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": [100000] * 250,
                "adj_close": close,
            }
        )
        upsert_prices(df, db_path)

        r = analyze_ticker("VETO", db_path=db_path)
        assert r.final_action == "SELL"

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.consensus import analyze_ticker

        r = analyze_ticker("NODATA", db_path=db_path)
        assert r.final_action == "HOLD"

    def test_dynamic_weights_fallback(self, db_path):
        """데이터 부족 시 DEFAULT_WEIGHTS 반환."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_dynamic_weights_sum_to_one(self, db_path):
        """가중치 합은 항상 1.0."""
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01


class TestDynamicWeights:
    """consensus._compute_weights 동적 가중치 계산 테스트."""

    def test_learning_memory_adjusts_weights(self, db_path):
        """충분한 recommendations → 동적 가중치 계산."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = [
                    {"agent_name": "technical", "action": "BUY", "confidence": 70},
                    {"agent_name": "fundamental", "action": "BUY", "confidence": 60},
                    {"agent_name": "risk", "action": "HOLD", "confidence": 50},
                ]
                signals = json.dumps({"verdicts": verdicts})
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i + 1:02d}", "BUY", 70, signals, 5.0 if i % 2 == 0 else -2.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert weights["technical"] > 0.03

    def test_no_verdicts_in_signals_fallback(self, db_path):
        """signals에 verdicts 없으면 기본 가중치."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i + 1:02d}", "BUY", 70, "rsi_oversold", 5.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_sell_hit_rate(self, db_path):
        """SELL 적중: outcome 음수일 때 적중."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = [
                    {"agent_name": "risk", "action": "SELL", "confidence": 80},
                ]
                signals = json.dumps({"verdicts": verdicts})
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i + 1:02d}", "SELL", 80, signals, -5.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert weights["risk"] > 0.15


class TestConsensusResult:
    def test_create(self):
        from nuri.trading.agents.consensus import ConsensusResult

        result = ConsensusResult(
            ticker="AAPL",
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.85,
            verdicts=[],
            dissent=[],
            reasoning="test",
        )
        assert result.final_action == "BUY"
        assert result.agreement_rate == 0.85

    def test_divergence_fields_default_false(self):
        """신규 divergence 필드가 기본값(False, '') 이어야 한다 (회귀 가드)."""
        from nuri.trading.agents.consensus import ConsensusResult

        result = ConsensusResult(
            ticker="AAPL",
            final_action="HOLD",
            final_confidence=50.0,
            agreement_rate=0.5,
            verdicts=[],
            dissent=[],
            reasoning="x",
        )
        assert result.divergence_flag is False
        assert result.divergence_reason == ""


class TestConsensusDivergence:
    """#5.10 JKHY 방지 — TechnicalAgent 가 합의에 정면 반대하면 flag surface."""

    @staticmethod
    def _verdicts(spec: dict[str, str]) -> list:
        """spec = {'technical': 'SELL', 'fundamental': 'BUY', ...} → AgentVerdict 리스트."""
        from nuri.trading.agents.base import AgentVerdict

        return [AgentVerdict(name, "TEST", action, 70, f"mock {name}") for name, action in spec.items()]

    @staticmethod
    def _even_weights(names) -> dict:
        w = 1.0 / len(names)
        return {n: w for n in names}

    def test_buy_consensus_with_technical_sell_sets_flag(self):
        """JKHY-class: 합의 BUY + technical SELL → divergence_flag=True."""
        from nuri.trading.agents.consensus import _build_consensus

        # 8 BUY + 1 SELL (technical) + 1 HOLD → BUY 우세, technical 반대
        spec = {
            "technical": "SELL",
            "fundamental": "BUY",
            "wallstreet": "BUY",
            "smart_money": "BUY",
            "macro": "BUY",
            "korean_market": "BUY",
            "options": "BUY",
            "crypto": "BUY",
            "retail": "BUY",
            "risk": "HOLD",
        }
        verdicts = self._verdicts(spec)
        weights = self._even_weights(spec.keys())
        result = _build_consensus("TEST", verdicts, weights)
        assert result.final_action == "BUY", f"sanity: expected BUY, got {result.final_action}"
        assert result.divergence_flag is True
        assert "TechnicalAgent" in result.divergence_reason
        assert "SELL" in result.divergence_reason

    def test_sell_consensus_with_technical_buy_sets_flag(self):
        """역방향: 합의 SELL + technical BUY → flag=True."""
        from nuri.trading.agents.consensus import _build_consensus

        spec = {
            "technical": "BUY",
            "fundamental": "SELL",
            "wallstreet": "SELL",
            "smart_money": "SELL",
            "macro": "SELL",
            "korean_market": "SELL",
            "options": "SELL",
            "crypto": "SELL",
            "retail": "SELL",
            "risk": "HOLD",
        }
        verdicts = self._verdicts(spec)
        weights = self._even_weights(spec.keys())
        result = _build_consensus("TEST", verdicts, weights)
        assert result.final_action == "SELL", f"sanity: expected SELL, got {result.final_action}"
        assert result.divergence_flag is True
        assert "BUY" in result.divergence_reason

    def test_buy_consensus_with_technical_hold_no_flag(self):
        """TechnicalAgent HOLD 는 "약한 반대" — flag 하지 않는다 (noise 억제)."""
        from nuri.trading.agents.consensus import _build_consensus

        spec = {
            "technical": "HOLD",
            "fundamental": "BUY",
            "wallstreet": "BUY",
            "smart_money": "BUY",
            "macro": "BUY",
            "korean_market": "BUY",
            "options": "BUY",
            "crypto": "BUY",
            "retail": "BUY",
            "risk": "HOLD",
        }
        verdicts = self._verdicts(spec)
        weights = self._even_weights(spec.keys())
        result = _build_consensus("TEST", verdicts, weights)
        assert result.final_action == "BUY"
        assert result.divergence_flag is False
        assert result.divergence_reason == ""

    def test_buy_consensus_with_technical_buy_no_flag(self):
        """동조 — TechnicalAgent 가 합의와 같은 방향이면 flag 없음."""
        from nuri.trading.agents.consensus import _build_consensus

        spec = {
            name: "BUY"
            for name in [
                "technical",
                "fundamental",
                "wallstreet",
                "smart_money",
                "macro",
                "risk",
                "korean_market",
                "options",
                "crypto",
                "retail",
            ]
        }
        verdicts = self._verdicts(spec)
        weights = self._even_weights(spec.keys())
        result = _build_consensus("TEST", verdicts, weights)
        assert result.final_action == "BUY"
        assert result.divergence_flag is False

    def test_hold_consensus_with_technical_sell_no_flag(self):
        """합의 HOLD 는 flag 대상 아님 — BUY/SELL 둘 다 아니니 대립 구도 성립 안 함."""
        from nuri.trading.agents.consensus import _build_consensus

        spec = {
            "technical": "SELL",
            "fundamental": "HOLD",
            "wallstreet": "HOLD",
            "smart_money": "HOLD",
            "macro": "HOLD",
            "risk": "HOLD",
            "korean_market": "HOLD",
            "options": "HOLD",
            "crypto": "HOLD",
            "retail": "HOLD",
        }
        verdicts = self._verdicts(spec)
        weights = self._even_weights(spec.keys())
        result = _build_consensus("TEST", verdicts, weights)
        assert result.final_action == "HOLD"
        assert result.divergence_flag is False


class TestComputeWeights:
    def test_default_weights(self, db_path):
        """추천 데이터 부족 시 기본 가중치."""
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS

    def test_weights_sum_to_one(self, db_path):
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01


class TestConsensusLogic:
    def test_all_agents_loaded(self):
        from nuri.trading.agents.consensus import ALL_AGENTS

        assert len(ALL_AGENTS) == 10

    def test_default_weights_keys(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS

        expected = {
            "technical",
            "fundamental",
            "macro",
            "risk",
            "smart_money",
            "wallstreet",
            "korean_market",
            "options",
            "crypto",
            "retail",
        }
        assert set(DEFAULT_WEIGHTS.keys()) == expected

    def test_risk_weight_highest(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS

        assert DEFAULT_WEIGHTS["risk"] == max(DEFAULT_WEIGHTS.values())


class TestAnalyzeTicker:
    def test_analyze_returns_consensus(self, db_path, monkeypatch):
        """모든 에이전트를 mock하여 합의 결과 확인."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, confidence):
                self.name = name
                self._action = action
                self._confidence = confidence

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._action, self._confidence, "mock")

        mock_agents = [
            MockAgent("technical", "BUY", 70),
            MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "BUY", 60),
            MockAgent("risk", "HOLD", 50),
            MockAgent("smart_money", "BUY", 55),
            MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
            MockAgent("options", "HOLD", 40),
            MockAgent("crypto", "BUY", 50),
            MockAgent("retail", "HOLD", 0),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker

        result = analyze_ticker("AAPL", db_path=db_path)

        assert result.ticker == "AAPL"
        assert result.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= result.final_confidence <= 100
        assert 0 <= result.agreement_rate <= 1
        assert len(result.verdicts) == 10

    def test_risk_veto(self, db_path, monkeypatch):
        """Risk 에이전트 거부권: SELL + confidence >= 80 → 전체 SELL."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, confidence):
                self.name = name
                self._action = action
                self._confidence = confidence

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._action, self._confidence, "mock")

        mock_agents = [
            MockAgent("technical", "BUY", 70),
            MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "BUY", 60),
            MockAgent("risk", "SELL", 85),
            MockAgent("smart_money", "BUY", 55),
            MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
            MockAgent("options", "HOLD", 40),
            MockAgent("crypto", "BUY", 50),
            MockAgent("retail", "HOLD", 0),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker

        result = analyze_ticker("DANGER", db_path=db_path)
        assert result.final_action == "SELL"

    def test_all_sell(self, db_path, monkeypatch):
        """전원 SELL → SELL."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name):
                self.name = name

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, "SELL", 70, "mock")

        mock_agents = [
            MockAgent(n)
            for n in [
                "technical",
                "fundamental",
                "macro",
                "risk",
                "smart_money",
                "wallstreet",
                "korean_market",
                "options",
                "crypto",
                "retail",
            ]
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker

        result = analyze_ticker("BEAR", db_path=db_path)
        assert result.final_action == "SELL"
        assert result.agreement_rate == 1.0


class TestConsensusDeep:
    def test_analyze_ticker(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker

        result = analyze_ticker("AAPL")
        assert hasattr(result, "final_action")
        assert hasattr(result, "final_confidence")
        assert hasattr(result, "agreement_rate")

    def test_analyze_portfolio(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio

        results = analyze_portfolio()
        assert isinstance(results, list)
        assert len(results) > 0


class TestConsensusInternals:
    def test_consensus_result_structure(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker

        result = analyze_ticker("AAPL")
        assert hasattr(result, "verdicts")
        assert isinstance(result.verdicts, list)
        assert len(result.verdicts) >= 5

    def test_consensus_all_tickers(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio

        results = analyze_portfolio(db_path=rich_db)
        tickers = [r.ticker for r in results]
        # rich_db seeds AAPL, MSFT, SPY, TSLA
        assert "AAPL" in tickers


class TestConsensusSave:
    def test_save_to_db(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker

        analyze_ticker("AAPL")
        from nuri.core.db import query

        recs = query("SELECT * FROM recommendations WHERE ticker='AAPL'")
        assert isinstance(recs, list)


class TestConsensus_R23:
    """Cover lines 108, 112, 127-128, 138, 178-183, 289-292, 320-321, 326-341."""

    def test_compute_weights_no_data(self, db_path):
        """No recommendation data → default weights."""
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert abs(weights["technical"] - 0.16) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """With enough data → adjusted weights."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts = json.dumps(
                    {
                        "verdicts": [
                            {"agent_name": "technical", "action": "BUY"},
                            {"agent_name": "fundamental", "action": "BUY"},
                        ]
                    }
                )
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-01-{i + 1:02d}", f"T{i}", "BUY", 70, "bull", verdicts, 100.0, 5.0 + i),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_non_json_signals(self, db_path):
        """Signals field that isn't the expected JSON format."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"2026-02-{i + 1:02d}", f"T{i}", "BUY", 70, "bull", '["rsi_oversold"]', 100.0, 3.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert "technical" in weights

    def test_analyze_ticker_with_timeout(self, db_path, monkeypatch):
        """Agent timeout handling."""
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
        monkeypatch.setattr(
            "nuri.trading.agents.consensus._compute_weights", lambda db_path=None: {"technical": 0.5, "slow_agent": 0.5}
        )
        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.ticker == "AAPL"
        assert result.final_action in ("BUY", "SELL", "HOLD")

    def test_print_consensus_with_targets(self, capsys, db_path, monkeypatch):
        """Print consensus with price targets."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [
            ConsensusResult(
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
            )
        ]
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.calculate_targets",
            lambda *a, **kw: {"ticker": "AAPL", "error": "no data"},
        )
        monkeypatch.setattr("nuri.trading.recommend.price_targets.format_target_tree", lambda t: "AAPL target tree")
        monkeypatch.setattr(
            "nuri.collectors.external.get_external", lambda *a: (_ for _ in ()).throw(ImportError("no module"))
        )
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
        """Print consensus with external data."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        results = [
            ConsensusResult(
                ticker="AAPL",
                final_action="HOLD",
                final_confidence=50.0,
                agreement_rate=0.6,
                verdicts=[AgentVerdict("technical", "AAPL", "HOLD", 50, "neutral")],
                dissent=[],
                reasoning="neutral",
            )
        ]
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.calculate_targets",
            lambda *a, **kw: (_ for _ in ()).throw(Exception("fail")),
        )
        monkeypatch.setattr(
            "nuri.collectors.external.get_external",
            lambda ticker: [
                {"data_type": "consensus", "value": "Strong Buy", "source": "tipranks", "numeric_value": None},
                {"data_type": "superinvestor_count", "value": "5", "source": "dataroma", "numeric_value": 5},
                {"data_type": "target_price", "value": "$200", "source": "tipranks", "numeric_value": 200},
            ],
        )
        print_consensus(results)
        captured = capsys.readouterr()
        assert "External Data" in captured.out


class TestAdditionalEdgeCases_R23:
    """Extra tests to hit remaining uncovered lines (agent-related only)."""

    def test_wallstreet_cached_ratings_upgrades(self, db_path):
        """WallStreet _check_cached with ratings data."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO analyst_ratings (ticker, date, firm, action, target_price) VALUES (?, ?, ?, ?, ?)",
                    ("TSLA", f"2026-03-{20 + i}", f"Firm{i}", "upgrade", 300 + i * 10),
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
                    ("TSLA", f"2026-03-{10 + i}", f"Insider{i}", "sale", 1000, 100000),
                )
        result = agent._check_cached("TSLA", db_path)
        assert result is not None
        assert result.action == "SELL"

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
        monkeypatch.setattr(
            "nuri.trading.agents.consensus._compute_weights", lambda db_path=None: {"technical": 0.5, "risk": 0.5}
        )
        result = analyze_ticker("AAPL", db_path=db_path)
        assert result.final_action == "SELL"
        assert "거부권" in result.reasoning

    def test_wallstreet_insider_net_buy(self, db_path, monkeypatch):
        """Insider net buy signal."""
        from nuri.trading.agents.wallstreet import WallStreetAgent

        agent = WallStreetAgent()
        monkeypatch.setattr(agent, "_check_cached", lambda *a, **kw: None)
        ins_data = pd.DataFrame({"Text": ["Purchase of"] * 5 + ["Sale of"] * 1})

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
        rec_data = pd.DataFrame(
            {
                "strongBuy": [8],
                "buy": [5],
                "hold": [2],
                "sell": [0],
                "strongSell": [0],
            }
        )

        class MockTicker:
            upgrades_downgrades = None
            earnings_history = None
            insider_transactions = None
            recommendations = rec_data

        import yfinance

        monkeypatch.setattr(yfinance, "Ticker", lambda t: MockTicker())
        v = agent.analyze("TEST", db_path=db_path)
        assert "매수" in v.reasoning


class TestConsensus_R27:
    """Tests for nuri/trading/agents/consensus.py."""

    def test_compute_weights_default(self, db_path):
        """Default weights when no recommendation data."""
        from nuri.trading.agents.consensus import _compute_weights

        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_compute_weights_with_data(self, db_path):
        """Weights adjusted with learning memory data."""
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                verdicts_data = {
                    "verdicts": [
                        {"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"},
                        {"agent_name": "risk", "action": "HOLD", "confidence": 50, "reasoning": "test"},
                    ]
                }
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations (date, ticker, action, confidence, regime, signals, "
                    "entry_price, outcome_30d) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        f"2024-{(i % 12) + 1:02d}-{15 + i}",
                        f"AAPL{i}",
                        "BUY",
                        70,
                        "bull",
                        json.dumps(verdicts_data),
                        150,
                        5.0 if i % 2 == 0 else -2.0,
                    ),
                )
        weights = _compute_weights(db_path=db_path)
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_print_consensus_empty(self, capsys):
        """print_consensus with empty results."""
        from nuri.trading.agents.consensus import print_consensus

        print_consensus([])
        captured = capsys.readouterr()
        assert "합의 결과 없음" in captured.out

    def test_print_consensus_with_results(self, capsys):
        """print_consensus with mock results."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI bullish"),
            AgentVerdict("risk", "AAPL", "HOLD", 50, "moderate risk"),
        ]
        results = [
            ConsensusResult(
                ticker="AAPL",
                final_action="BUY",
                final_confidence=65,
                agreement_rate=0.7,
                verdicts=verdicts,
                dissent=["risk(HOLD, 50): moderate risk"],
                reasoning="technical: RSI bullish",
            )
        ]
        print_consensus(results)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out


class TestPrintConsensus:
    def test_empty(self, capsys):
        from nuri.trading.agents.consensus import print_consensus

        print_consensus([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_results(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI ok"),
            AgentVerdict("fundamental", "AAPL", "BUY", 65, "PE low"),
            AgentVerdict("macro", "AAPL", "BUY", 60, "bull"),
            AgentVerdict("risk", "AAPL", "HOLD", 50, "중립"),
            AgentVerdict("smart_money", "AAPL", "BUY", 55, "13F"),
        ]
        results = [
            ConsensusResult(
                ticker="AAPL",
                final_action="BUY",
                final_confidence=68.0,
                agreement_rate=0.80,
                verdicts=verdicts,
                dissent=["risk(HOLD, 50): 중립"],
                reasoning="consensus",
            )
        ]
        print_consensus(results)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "BUY" in output
        assert "Dissent" in output

    def test_analyze_portfolio_empty(self, db_path):
        from nuri.trading.agents.consensus import analyze_portfolio

        results = analyze_portfolio(db_path=db_path)
        assert results == []


class TestConsensusPrint:
    def test_print_consensus(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        result = ConsensusResult(
            ticker="AAPL",
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.85,
            dissent=["risk"],
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "RSI 매수"),
                AgentVerdict("risk", "AAPL", "SELL", 80, "과집중"),
            ],
            reasoning="test consensus",
        )
        print(f"Action: {result.final_action}, Confidence: {result.final_confidence}")
        output = capsys.readouterr().out
        assert "BUY" in output


class TestConsensusFull:
    def test_print_with_all_agents(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "AAPL", "BUY", 70, "RSI 과매도 반등"),
            AgentVerdict("fundamental", "AAPL", "BUY", 65, "PE 적정, ROE 높음"),
            AgentVerdict("macro", "AAPL", "HOLD", 45, "횡보 레짐"),
            AgentVerdict("risk", "AAPL", "HOLD", 40, "집중도 정상"),
            AgentVerdict("smart_money", "AAPL", "BUY", 60, "13F 보유 3명"),
            AgentVerdict("wallstreet", "AAPL", "BUY", 55, "업그레이드 2건"),
            AgentVerdict("korean_market", "AAPL", "HOLD", 30, "US 종목"),
        ]
        results = [
            ConsensusResult(
                ticker="AAPL",
                final_action="BUY",
                final_confidence=68.0,
                agreement_rate=0.57,
                verdicts=verdicts,
                dissent=[
                    "macro(HOLD, 45): 횡보 레짐",
                    "risk(HOLD, 40): 집중도 정상",
                    "korean_market(HOLD, 30): US 종목",
                ],
                reasoning="technical + fundamental + smart_money",
            ),
            ConsensusResult(
                ticker="TSLA",
                final_action="SELL",
                final_confidence=72.0,
                agreement_rate=0.71,
                verdicts=[
                    AgentVerdict("technical", "TSLA", "SELL", 75, "데드크로스"),
                    AgentVerdict("fundamental", "TSLA", "SELL", 60, "PE 327"),
                    AgentVerdict("macro", "TSLA", "SELL", 55, "bear regime"),
                    AgentVerdict("risk", "TSLA", "SELL", 85, "손절선 초과"),
                    AgentVerdict("smart_money", "TSLA", "HOLD", 40, "보유 유지"),
                ],
                dissent=["smart_money(HOLD, 40): 보유 유지"],
                reasoning="risk veto",
            ),
        ]
        print_consensus(results)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "TSLA" in output
        assert "Multi-Agent" in output

    def test_analyze_ticker_with_populated_db(self, db_path, monkeypatch):
        """에이전트 mock으로 analyze_ticker 전체 경로 커버."""
        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class MockAgent:
            def __init__(self, name, action, conf):
                self.name = name
                self._a = action
                self._c = conf

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, self._a, self._c, "mock reason")

        agents = [
            MockAgent("technical", "BUY", 70),
            MockAgent("fundamental", "BUY", 65),
            MockAgent("macro", "HOLD", 50),
            MockAgent("risk", "HOLD", 45),
            MockAgent("smart_money", "BUY", 55),
            MockAgent("wallstreet", "BUY", 60),
            MockAgent("korean_market", "HOLD", 30),
        ]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", agents)
        result = cons_mod.analyze_ticker("AAPL", db_path=db_path)
        assert result.final_action == "BUY"
        assert len(result.verdicts) == 7
        assert len(result.dissent) > 0


# ═══════════════════════════════════════════════════════
# Consensus verbose 모드
# ═══════════════════════════════════════════════════════


class TestConsensusVerbose:
    def test_print_consensus_verbose_keyword_only(self, capsys):
        """verbose는 keyword-only — 위치 인자로 못 전달."""
        from nuri.trading.agents.consensus import print_consensus

        with pytest.raises(TypeError):
            print_consensus([], True)  # positional bool intentionally — verbose is keyword-only

    def test_print_consensus_no_verbose_for_multi(self, capsys):
        """여러 종목 + verbose=False → supporting reasoning 출력 안 함."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "TSLA", "BUY", 100, "MACD>Signal; 추세강세(+84)"),
            AgentVerdict("risk", "TSLA", "BUY", 80, "수익 양호"),
        ]
        r1 = ConsensusResult("TSLA", "BUY", 90, 1.0, verdicts, [], "tech: foo")
        r2 = ConsensusResult("NVDA", "BUY", 85, 1.0, verdicts, [], "tech: bar")
        print_consensus([r1, r2], verbose=False)
        out = capsys.readouterr().out
        assert "▸" not in out  # supporters 출력 마커 없어야 함

    def test_print_consensus_verbose_shows_supporters(self, capsys):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "TSLA", "BUY", 100, "MACD>Signal; 추세강세(+84)"),
            AgentVerdict("risk", "TSLA", "BUY", 80, "수익 양호"),
        ]
        r = ConsensusResult("TSLA", "BUY", 90, 1.0, verdicts, [], "tech: foo")
        print_consensus([r], verbose=True)
        out = capsys.readouterr().out
        assert "▸" in out
        assert "supporters" in out
        assert "MACD>Signal" in out  # technical reasoning 포함
        assert "추세강세" in out

    def test_print_consensus_single_ticker_auto_verbose(self, capsys):
        """단일 종목은 verbose=False여도 자동으로 supporting 출력."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, print_consensus

        verdicts = [
            AgentVerdict("technical", "TSLA", "BUY", 100, "test reasoning"),
        ]
        r = ConsensusResult("TSLA", "BUY", 90, 1.0, verdicts, [], "tech: foo")
        print_consensus([r], verbose=False)
        out = capsys.readouterr().out
        assert "▸" in out
        assert "test reasoning" in out


class TestConsensusTimeout_R130:
    """Regression: #130 — consensus.py 15s timeout crashes Phase E pipeline.

    Before the fix, `as_completed(timeout=N)` raised TimeoutError on the
    iterator itself, escaping the inner `except` clause and crashing the
    entire `analyze_ticker` call (and thus the `make full-scan` pipeline).

    Fix: catch the iterator-level TimeoutError, emit HOLD/0/타임아웃 verdicts
    for unfinished futures, and shut down the executor with cancel_futures=True
    so the function returns promptly instead of waiting for slow agents.
    """

    def _patch_short_timeout(self, monkeypatch, seconds: float = 0.3):
        """consensus가 짧은 timeout을 사용하도록 AGENT_CONFIG 패치."""
        from nuri.trading.agents import consensus as cons_mod

        new_config = dict(cons_mod.AGENT_CONFIG)
        new_consensus = dict(new_config.get("consensus", {}))
        new_consensus["agent_timeout_sec"] = seconds
        new_config["consensus"] = new_consensus
        monkeypatch.setattr(cons_mod, "AGENT_CONFIG", new_config)

    def test_analyze_ticker_returns_when_one_agent_hangs(self, db_path, monkeypatch):
        """한 에이전트가 timeout을 초과해도 analyze_ticker가 반환한다."""
        import time as _time

        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class HangingAgent:
            name = "hanging"

            def analyze(self, ticker, db_path=None):
                _time.sleep(5.0)  # timeout 0.3s보다 훨씬 길게
                return AgentVerdict("hanging", ticker, "BUY", 90, "completed")

        class FastAgent:
            name = "technical"

            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 70, "fast result")

        monkeypatch.setattr(cons_mod, "ALL_AGENTS", [FastAgent(), HangingAgent()])
        monkeypatch.setattr(
            cons_mod,
            "_compute_weights",
            lambda db_path=None: {"technical": 0.5, "hanging": 0.5},
        )
        self._patch_short_timeout(monkeypatch, 0.3)

        # 회귀 전: TimeoutError 발생 → 함수가 죽었음
        # 회귀 후: 0.3s 후 반환, hanging은 타임아웃 verdict
        start = _time.monotonic()
        result = cons_mod.analyze_ticker("AAPL", db_path=db_path)
        elapsed = _time.monotonic() - start

        assert elapsed < 3.0, f"analyze_ticker가 {elapsed:.1f}s 걸림 — timeout 후 즉시 반환해야 함"
        assert result.ticker == "AAPL"

        verdicts_by_name = {v.agent_name: v for v in result.verdicts}
        assert "technical" in verdicts_by_name
        assert verdicts_by_name["technical"].action == "BUY"
        assert verdicts_by_name["technical"].confidence == 70

        assert "hanging" in verdicts_by_name
        timeout_verdict = verdicts_by_name["hanging"]
        assert timeout_verdict.action == "HOLD"
        assert timeout_verdict.confidence == 0
        assert "타임아웃" in timeout_verdict.reasoning

    def test_stream_analyze_ticker_yields_timeout_verdicts(self, db_path, monkeypatch):
        """스트리밍 변형도 동일하게 timeout 시 fallback verdict yield."""
        import time as _time

        from nuri.trading.agents import consensus as cons_mod
        from nuri.trading.agents.base import AgentVerdict

        class HangingAgent:
            name = "hanging"

            def analyze(self, ticker, db_path=None):
                _time.sleep(5.0)
                return AgentVerdict("hanging", ticker, "BUY", 90, "completed")

        class FastAgent:
            name = "technical"

            def analyze(self, ticker, db_path=None):
                return AgentVerdict("technical", ticker, "BUY", 70, "fast result")

        monkeypatch.setattr(cons_mod, "ALL_AGENTS", [FastAgent(), HangingAgent()])
        monkeypatch.setattr(
            cons_mod,
            "_compute_weights",
            lambda db_path=None: {"technical": 0.5, "hanging": 0.5},
        )
        self._patch_short_timeout(monkeypatch, 0.3)

        start = _time.monotonic()
        events = list(cons_mod.stream_analyze_ticker("AAPL", db_path=db_path))
        elapsed = _time.monotonic() - start

        assert elapsed < 3.0, f"stream_analyze_ticker가 {elapsed:.1f}s 걸림"

        verdict_events = [e for e in events if e[0] == "verdict"]
        consensus_events = [e for e in events if e[0] == "consensus"]
        assert len(verdict_events) == 2
        assert len(consensus_events) == 1

        verdicts_by_name = {e[1].agent_name: e[1] for e in verdict_events}
        assert verdicts_by_name["hanging"].action == "HOLD"
        assert verdicts_by_name["hanging"].confidence == 0
        assert "타임아웃" in verdicts_by_name["hanging"].reasoning
        assert verdicts_by_name["technical"].action == "BUY"

    def test_default_timeout_is_60_seconds(self):
        """기본 timeout이 60초 — 회귀 가드 (15초로 되돌리기 방지)."""
        from nuri.core.agent_config import AGENT_CONFIG

        timeout = AGENT_CONFIG.get("consensus", {}).get("agent_timeout_sec")
        assert timeout == 60, f"agent_timeout_sec이 {timeout} — 60이어야 함 (#130)"
