"""멀티 에이전트 합의 엔진 확장 테스트."""
import pytest

from nuri.core.db import init_db
from nuri.trading.agents.base import AgentVerdict


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# ConsensusResult
# ═══════════════════════════════════════════════════════

class TestConsensusResult:
    def test_create(self):
        from nuri.trading.agents.consensus import ConsensusResult
        result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=75.0,
            agreement_rate=0.85, verdicts=[], dissent=[], reasoning="test",
        )
        assert result.final_action == "BUY"
        assert result.agreement_rate == 0.85


# ═══════════════════════════════════════════════════════
# 가중치 계산
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 합의 로직 유닛 테스트
# ═══════════════════════════════════════════════════════

class TestConsensusLogic:
    def test_all_agents_loaded(self):
        from nuri.trading.agents.consensus import ALL_AGENTS
        assert len(ALL_AGENTS) == 10

    def test_default_weights_keys(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS
        expected = {"technical", "fundamental", "macro", "risk", "smart_money",
                    "wallstreet", "korean_market", "options", "crypto", "retail"}
        assert set(DEFAULT_WEIGHTS.keys()) == expected

    def test_risk_weight_highest(self):
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS
        assert DEFAULT_WEIGHTS["risk"] == max(DEFAULT_WEIGHTS.values())


# ═══════════════════════════════════════════════════════
# 합의 통합 (analyze_ticker 호출)
# ═══════════════════════════════════════════════════════

class TestAnalyzeTicker:
    def test_analyze_returns_consensus(self, db_path, monkeypatch):
        """모든 에이전트를 mock하여 합의 결과 확인."""
        from nuri.trading.agents import consensus as cons_mod

        # 모든 에이전트를 단순 mock으로 교체
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
            MockAgent("risk", "SELL", 85),  # 거부권 행사
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

        class MockAgent:
            def __init__(self, name):
                self.name = name

            def analyze(self, ticker, db_path=None):
                return AgentVerdict(self.name, ticker, "SELL", 70, "mock")

        mock_agents = [MockAgent(n) for n in [
            "technical", "fundamental", "macro", "risk", "smart_money",
            "wallstreet", "korean_market", "options", "crypto", "retail",
        ]]
        monkeypatch.setattr(cons_mod, "ALL_AGENTS", mock_agents)

        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("BEAR", db_path=db_path)
        assert result.final_action == "SELL"
        assert result.agreement_rate == 1.0
