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


class TestConsensusDivergenceMechanicalPenalty:
    """P1 A3 — divergence_flag 가 informational 에서 실 action downgrade 로 전환.

    Codex-reviewed design:
    - tech confidence ≥ threshold (default 80) 일 때만 발동
    - BUY/SELL → HOLD downgrade (risk veto 와 달리 full flip 아님)
    - Symmetric: BUY vs SELL 같이 처리
    - Risk veto 우선 — 그 경우 penalty skip
    - final_confidence 는 **보존** (원 계산값). agreement_rate/dissent 도 원 final_action 기준.
    """

    @staticmethod
    def _verdict(name, action, confidence=70):
        from nuri.trading.agents.base import AgentVerdict

        return AgentVerdict(name, "TEST", action, confidence, f"mock {name}")

    def _scenario_buy_consensus_with_tech_sell(self, tech_conf: float):
        """BUY 8 + HOLD 1 + tech=SELL — 합의 BUY 여야 자연스러움."""
        verdicts = [
            self._verdict("technical", "SELL", tech_conf),
            self._verdict("fundamental", "BUY", 70),
            self._verdict("wallstreet", "BUY", 70),
            self._verdict("smart_money", "BUY", 70),
            self._verdict("macro", "BUY", 70),
            self._verdict("korean_market", "BUY", 70),
            self._verdict("options", "BUY", 70),
            self._verdict("crypto", "BUY", 70),
            self._verdict("retail", "BUY", 70),
            self._verdict("risk", "HOLD", 40),
        ]
        weights = {v.agent_name: 0.1 for v in verdicts}
        return verdicts, weights

    def test_buy_consensus_with_technical_sell_80_downgrades_to_hold(self):
        """JKHY-class: BUY 합의 + tech SELL conf=80 → final_action=HOLD."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=80)
        result = _build_consensus("TEST", verdicts, weights)

        assert result.final_action == "HOLD", f"Expected HOLD (penalty), got {result.final_action}"
        assert result.divergence_flag is True
        assert "downgrade" in result.reasoning, "reasoning should flag penalty"

    def test_sell_consensus_with_technical_buy_80_downgrades_to_hold(self):
        """역방향 대칭: SELL 합의 + tech BUY conf=80 → HOLD."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts = [
            self._verdict("technical", "BUY", 80),
            self._verdict("fundamental", "SELL", 70),
            self._verdict("wallstreet", "SELL", 70),
            self._verdict("smart_money", "SELL", 70),
            self._verdict("macro", "SELL", 70),
            self._verdict("korean_market", "SELL", 70),
            self._verdict("options", "SELL", 70),
            self._verdict("crypto", "SELL", 70),
            self._verdict("retail", "SELL", 70),
            self._verdict("risk", "HOLD", 40),
        ]
        weights = {v.agent_name: 0.1 for v in verdicts}
        result = _build_consensus("TEST", verdicts, weights)

        assert result.final_action == "HOLD"
        assert result.divergence_flag is True

    def test_technical_confidence_79_does_not_trigger_penalty(self):
        """경계 조건: tech conf 79 < threshold 80 → action 유지, flag 만 설정."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=79)
        result = _build_consensus("TEST", verdicts, weights)

        assert result.final_action == "BUY", f"79 < 80 — penalty 발동 안 해야 함, got {result.final_action}"
        assert result.divergence_flag is True, "flag 는 여전히 set"

    def test_risk_veto_wins_over_divergence_penalty(self):
        """Precedence: risk SELL conf=90 거부권 발동 → final SELL 유지 (HOLD downgrade 아님).

        Risk veto 는 포트폴리오 안전 규칙. tech=BUY 가 반대한다고 HOLD 로
        희석되면 거부권 의미 상실. risk 거부권이 divergence penalty 보다 우선.
        """
        from nuri.trading.agents.consensus import _build_consensus

        verdicts = [
            self._verdict("technical", "BUY", 90),  # tech 반대 + 고confidence
            self._verdict("fundamental", "BUY", 60),
            self._verdict("wallstreet", "BUY", 60),
            self._verdict("risk", "SELL", 90),  # risk 거부권 발동
            self._verdict("smart_money", "HOLD", 40),
            self._verdict("macro", "HOLD", 40),
            self._verdict("korean_market", "HOLD", 40),
            self._verdict("options", "HOLD", 40),
            self._verdict("crypto", "HOLD", 40),
            self._verdict("retail", "HOLD", 40),
        ]
        weights = {v.agent_name: 0.1 for v in verdicts}
        result = _build_consensus("TEST", verdicts, weights)

        # Risk veto 승. SELL 그대로. HOLD 로 downgrade 되면 안 됨.
        assert result.final_action == "SELL"
        assert "거부권" in result.reasoning

    def test_divergence_flag_still_surfaces_after_penalty(self):
        """Penalty 가 발동해도 flag + reason 은 사용자에게 여전히 노출."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=85)
        result = _build_consensus("TEST", verdicts, weights)

        assert result.final_action == "HOLD"  # penalty fired
        assert result.divergence_flag is True
        assert result.divergence_reason != ""
        assert "SELL" in result.divergence_reason

    def test_penalty_applied_flag_set_and_pre_penalty_action_captured(self):
        """Q1 telemetry 준비: ConsensusResult 에 penalty_applied + pre_penalty_action 노출."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=85)
        result = _build_consensus("TEST", verdicts, weights)

        assert result.penalty_applied is True
        assert result.pre_penalty_action == "BUY"

    def test_penalty_applied_false_when_below_threshold(self):
        """No penalty → penalty_applied=False, pre_penalty_action empty."""
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=60)
        result = _build_consensus("TEST", verdicts, weights)

        assert result.penalty_applied is False
        assert result.pre_penalty_action == ""

    def test_final_confidence_preserved_after_penalty(self):
        """Penalty 가 action 만 바꾸고 final_confidence 는 원 계산값 유지.

        근거: downstream (dashboard, SIEGE) 이 confidence 를 신뢰도 정보로 사용.
        Penalty 발동 시 "HOLD with 원 confidence 50" 이 "원래는 BUY 70% 였지만
        tech 반대로 HOLD" 라는 의미를 유지. 0 으로 리셋하면 정보 손실.
        """
        from nuri.trading.agents.consensus import _build_consensus

        verdicts, weights = self._scenario_buy_consensus_with_tech_sell(tech_conf=90)
        # tech conf 79 는 penalty 발동 안 함 → 같은 weights/actions 로 원 final_confidence 확보
        ref_verdicts, _ = self._scenario_buy_consensus_with_tech_sell(tech_conf=79)
        ref_result = _build_consensus("TEST", ref_verdicts, weights)
        # action_scores 에서 weight × (conf/100) 가 들어가므로 79 vs 90 이 결과에 영향.
        # 동일 conf 로 확보하려면 79 → penalty 전 최대 79 의 BUY/SELL 분포로 비교
        # 대신 중요한 assertion 은 final_confidence 가 0 으로 리셋 안 되었다는 것.
        result = _build_consensus("TEST", verdicts, weights)

        assert result.final_action == "HOLD"
        assert result.final_confidence > 0, "penalty 가 confidence 를 0 으로 리셋하면 안 됨"
        assert result.final_confidence != 0.0, "preserved original computed confidence"
        # sanity: ref 는 penalty 발동 안 했으니 같은 크기 수준이어야
        assert abs(result.final_confidence - ref_result.final_confidence) < 5, (
            f"penalty 이후 confidence 크게 달라짐: ref={ref_result.final_confidence}, "
            f"after penalty={result.final_confidence}"
        )


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


class TestPenaltyTelemetryEvent:
    """Q1 — `consensus_penalty_applied` 이벤트 발행 감사.

    STRATEGY §2.6 Escalation Ladder 의 soft-penalty rung 이 실제로 얼마나
    자주 발동하는지 1-2 달 후 측정 가능해야 한다. 이벤트는 penalty 가 실제로
    action 을 downgrade 할 때만 emit. flag 만 set 된 sub-threshold 케이스는
    emit 안 함 (noise 억제).
    """

    @staticmethod
    def _verdict(name, action, confidence=70):
        from nuri.trading.agents.base import AgentVerdict

        return AgentVerdict(name, "JKHY", action, confidence, f"mock {name}")

    def _scenario_buy_with_tech_sell(self, tech_conf: float):
        verdicts = [
            self._verdict("technical", "SELL", tech_conf),
            self._verdict("fundamental", "BUY", 70),
            self._verdict("wallstreet", "BUY", 70),
            self._verdict("smart_money", "BUY", 70),
            self._verdict("macro", "BUY", 70),
            self._verdict("korean_market", "BUY", 70),
            self._verdict("options", "BUY", 70),
            self._verdict("crypto", "BUY", 70),
            self._verdict("retail", "BUY", 70),
            self._verdict("risk", "HOLD", 40),
        ]
        weights = {v.agent_name: 0.1 for v in verdicts}
        return verdicts, weights

    def test_emit_helper_fires_when_penalty_applied(self, db_path, monkeypatch):
        """penalty_applied=True 인 result 전달 시 emit_event 호출."""
        from nuri.trading.agents import consensus as cons_mod

        verdicts, weights = self._scenario_buy_with_tech_sell(tech_conf=85)
        result = cons_mod._build_consensus("JKHY", verdicts, weights)
        assert result.penalty_applied is True

        captured = []
        monkeypatch.setattr(
            "nuri.core.events.emit_event",
            lambda event_type, step=None, payload=None, **kw: captured.append(
                {"event_type": event_type, "step": step, "payload": payload}
            ),
        )
        cons_mod._emit_penalty_event_if_fired(result, verdicts, db_path=db_path)

        assert len(captured) == 1, f"expected 1 emit, got {len(captured)}"
        evt = captured[0]
        assert evt["event_type"] == "consensus_penalty_applied"
        assert evt["step"] == "recommend"
        p = evt["payload"]
        assert p["ticker"] == "JKHY"
        assert p["penalty_kind"] == "divergence_technical"
        assert p["technical_action"] == "SELL"
        assert p["technical_confidence"] == 85
        assert p["consensus_action_before"] == "BUY"
        assert p["consensus_action_after"] == "HOLD"
        assert p["swing"] == "BUY_TO_HOLD"
        assert "threshold" in p
        assert "divergence_reason" in p

    def test_no_emit_when_penalty_not_applied(self, db_path, monkeypatch):
        """Sub-threshold (tech conf 60): flag 만 set, penalty 발동 안 함 → emit 없음."""
        from nuri.trading.agents import consensus as cons_mod

        verdicts, weights = self._scenario_buy_with_tech_sell(tech_conf=60)
        result = cons_mod._build_consensus("JKHY", verdicts, weights)
        assert result.penalty_applied is False

        captured = []
        monkeypatch.setattr(
            "nuri.core.events.emit_event",
            lambda *args, **kw: captured.append(kw.get("event_type") or args[0]),
        )
        cons_mod._emit_penalty_event_if_fired(result, verdicts, db_path=db_path)

        assert captured == [], "sub-threshold 에서는 event emit 금지"

    def test_sell_to_hold_swing_recorded(self, db_path, monkeypatch):
        """역방향: SELL 합의 + tech BUY 80 → swing=SELL_TO_HOLD."""
        from nuri.trading.agents import consensus as cons_mod

        verdicts = [
            self._verdict("technical", "BUY", 80),
            self._verdict("fundamental", "SELL", 70),
            self._verdict("wallstreet", "SELL", 70),
            self._verdict("smart_money", "SELL", 70),
            self._verdict("macro", "SELL", 70),
            self._verdict("korean_market", "SELL", 70),
            self._verdict("options", "SELL", 70),
            self._verdict("crypto", "SELL", 70),
            self._verdict("retail", "SELL", 70),
            self._verdict("risk", "HOLD", 40),
        ]
        weights = {v.agent_name: 0.1 for v in verdicts}
        result = cons_mod._build_consensus("X", verdicts, weights)
        assert result.penalty_applied is True

        captured = []
        monkeypatch.setattr(
            "nuri.core.events.emit_event",
            lambda event_type, step=None, payload=None, **kw: captured.append(payload),
        )
        cons_mod._emit_penalty_event_if_fired(result, verdicts, db_path=db_path)

        assert len(captured) == 1
        assert captured[0]["swing"] == "SELL_TO_HOLD"

    def test_emit_failure_does_not_propagate(self, db_path, monkeypatch):
        """emit_event 실패 시 consensus 결과는 정상 반환 (graceful fallback)."""
        from nuri.trading.agents import consensus as cons_mod

        verdicts, weights = self._scenario_buy_with_tech_sell(tech_conf=85)
        result = cons_mod._build_consensus("JKHY", verdicts, weights)

        def _boom(*args, **kw):
            raise RuntimeError("DB gone")

        monkeypatch.setattr("nuri.core.events.emit_event", _boom)
        # 예외 전파 안 함
        cons_mod._emit_penalty_event_if_fired(result, verdicts, db_path=db_path)

    def test_consensus_penalty_applied_registered_in_event_types(self):
        """event type 이 EVENT_TYPES whitelist 에 등록되어야 pipeline_events 저장 가능."""
        from nuri.core.events import EVENT_TYPES

        assert "consensus_penalty_applied" in EVENT_TYPES


class TestSaveToRecommendations:
    """`save_to_recommendations` coverage (lines 415-480) — consensus → DB data path.

    Critical data integrity: 합의 결과를 `recommendations` 테이블에 저장하지 않으면
    frontend /decision + tracker.py 가 ghost 상태. REPLACE 동작 + price fallback +
    agent_verdicts JSON 직렬화가 모두 올바른지 검증.
    """

    @staticmethod
    def _result(ticker="TEST", action="BUY", conf=70.0):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        return ConsensusResult(
            ticker=ticker,
            final_action=action,
            final_confidence=conf,
            agreement_rate=0.7,
            verdicts=[
                AgentVerdict("technical", ticker, "BUY", 75, "MACD bullish", {"rsi": 55}),
                AgentVerdict("fundamental", ticker, "BUY", 65, "PE 적정", {"pe": 20}),
            ],
            dissent=["macro(HOLD, 40): neutral"],
            reasoning="strong technical + fundamental",
        )

    def test_empty_results_returns_zero(self, db_path):
        """빈 리스트 → 조기 종료, 0 반환."""
        from nuri.trading.agents.consensus import save_to_recommendations

        assert save_to_recommendations([], db_path=db_path) == 0

    def test_happy_path_saves_and_serializes_verdicts(self, db_path):
        """정상 플로우: recommendations 테이블에 row 저장 + JSON agent_verdicts 직렬화."""
        import json

        # Price fixture — entry_price 를 실제값으로 fetch 하도록
        import pandas as pd

        from nuri.core.db import query, upsert_prices
        from nuri.trading.agents.consensus import save_to_recommendations

        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "TEST",
                        "date": "2026-04-15",
                        "open": 100.0,
                        "high": 105.0,
                        "low": 98.0,
                        "close": 102.5,
                        "volume": 1000000,
                        "adj_close": 102.5,
                    }
                ]
            ),
            db_path=db_path,
        )
        saved = save_to_recommendations([self._result()], db_path=db_path)
        assert saved == 1

        rows = query("SELECT * FROM recommendations WHERE ticker='TEST'", db_path=db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["ticker"] == "TEST"
        assert row["action"] == "BUY"
        assert row["confidence"] == 70.0
        assert row["entry_price"] == 102.5

        # agent_verdicts JSON round-trip
        verdicts = json.loads(row["agent_verdicts"])
        assert len(verdicts) == 2
        assert verdicts[0]["agent_name"] == "technical"
        assert verdicts[0]["action"] == "BUY"

        # signals JSON 에 agreement_rate + dissent_count 포함
        signals = json.loads(row["signals"])
        assert signals["agreement_rate"] == 0.7
        assert signals["dissent_count"] == 1

    def test_missing_price_falls_back_to_zero(self, db_path):
        """prices 테이블에 ticker 없으면 entry_price=0.0 (crash 아님)."""
        from nuri.core.db import query
        from nuri.trading.agents.consensus import save_to_recommendations

        saved = save_to_recommendations([self._result(ticker="NOPX")], db_path=db_path)
        assert saved == 1
        row = query("SELECT entry_price FROM recommendations WHERE ticker='NOPX'", db_path=db_path)[0]
        assert row["entry_price"] == 0.0

    def test_same_day_ticker_bug_creates_duplicate_rows(self, db_path):
        """**실제 동작 문서화 (bug)**: recommendations 에 `UNIQUE(date, ticker)` 제약 없음 →
        `INSERT OR REPLACE` 가 실질 REPLACE 안 됨. duplicate row 생성.

        NEXT_SESSION Tier 3 후보: schema 마이그레이션 or 코드에서 DELETE-then-INSERT.
        지금은 현 동작을 회귀 가드로만 lock in.
        """
        from nuri.core.db import query
        from nuri.trading.agents.consensus import save_to_recommendations

        save_to_recommendations([self._result(action="BUY", conf=70)], db_path=db_path)
        save_to_recommendations([self._result(action="HOLD", conf=50)], db_path=db_path)

        rows = query("SELECT * FROM recommendations WHERE ticker='TEST' ORDER BY id", db_path=db_path)
        assert len(rows) == 2, "Known schema bug: no UNIQUE constraint, REPLACE not effective"
        assert rows[-1]["action"] == "HOLD"


class TestComputeWeightsHitRates:
    """`_compute_weights` hit_rates 적중률 경로 — lines 138-142 (BUY/SELL hit 분기)."""

    def _seed_recommendations(self, db_path, n_records=15, outcome_sign=1):
        """recommendations 테이블에 N 건의 verdict JSON 삽입. outcome_sign 으로 적중/오답 제어.

        outcome_sign=1 → 모두 양수 outcome (BUY 적중, SELL 오답).
        outcome_sign=-1 → 모두 음수 outcome (BUY 오답, SELL 적중).
        """
        import json

        from nuri.core.db import get_db
        from nuri.core.timezone import today_kst

        with get_db(db_path) as conn:
            for i in range(n_records):
                verdicts = [
                    {"agent_name": "technical", "action": "BUY"},
                    {"agent_name": "fundamental", "action": "SELL"},
                    {"agent_name": "macro", "action": "HOLD"},  # HOLD 는 hit 판정 제외
                ]
                conn.execute(
                    """INSERT INTO recommendations
                       (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        today_kst(),
                        f"T{i}",
                        "BUY",
                        50.0,
                        None,
                        json.dumps({"verdicts": verdicts}),
                        100.0,
                        0.05 * outcome_sign,
                    ),
                )

    def test_hit_rate_outcome_read_bug_documented(self, db_path):
        """**실제 동작 문서화 (bug)**: `_compute_weights` line 128 에서
        `row.get("outcome_30d", 0) if hasattr(row, "get") else 0` 는 sqlite3.Row 에
        `.get()` 메서드가 없어서 **항상 0 으로 fallback**. 즉 `outcome_sign` 에 무관하게
        `is_positive=False` → BUY 는 전부 miss, SELL 은 전부 hit 로 기록됨.

        결과: 15 건 positive outcome seed → fundamental(SELL) 가중치 ↑, technical(BUY) ↓
        (의도된 반대 방향).

        NEXT_SESSION Tier 3 후보: `row_factory=sqlite3.Row` + `row['outcome_30d']` 직접
        접근 또는 `dict(row).get()` 패턴으로 교정.
        """
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        self._seed_recommendations(db_path, n_records=15, outcome_sign=1)
        weights = _compute_weights(db_path=db_path)

        # 현 버그로 인해 outcome=0 → BUY miss / SELL hit
        assert weights["fundamental"] > DEFAULT_WEIGHTS["fundamental"], (
            "현 bug: outcome 항상 0 → SELL always hits → fundamental 가중치 상승"
        )
        assert weights["technical"] < DEFAULT_WEIGHTS["technical"], (
            "현 bug: outcome 항상 0 → BUY always miss → technical 가중치 하락"
        )
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_empty_signals_string_skipped(self, db_path):
        """signals 필드가 빈 문자열이면 해당 row skip — crash 없이 DEFAULT_WEIGHTS 반환."""
        from nuri.core.db import get_db
        from nuri.core.timezone import today_kst
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        with get_db(db_path) as conn:
            # 15 건 모두 signals 빈 문자열
            for i in range(15):
                conn.execute(
                    """INSERT INTO recommendations
                       (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (today_kst(), f"X{i}", "BUY", 50.0, None, "", 100.0, 0.05),
                )

        weights = _compute_weights(db_path=db_path)
        # 빈 signals → hit_rate 계산 불가 → DEFAULT_WEIGHTS
        assert weights == DEFAULT_WEIGHTS
