"""멀티 에이전트 합의 시스템 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def agent_data(db_path):
    """에이전트 테스트용 데이터 (포트폴리오 + 가격)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    dates = pd.bdate_range("2024-01-01", periods=250)
    close = np.linspace(40, 80, 250) + np.random.normal(0, 1, 250)
    df = pd.DataFrame({
        "ticker": "TEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [1000000] * 250, "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


class TestTechnicalAgent:
    def test_returns_verdict(self, agent_data):
        from nuri.trading.agents.technical import TechnicalAgent
        v = TechnicalAgent().analyze("TEST", db_path=agent_data)
        assert v.agent_name == "technical"
        assert v.action in ("BUY", "SELL", "HOLD")
        assert 0 <= v.confidence <= 100

    def test_no_data(self, db_path):
        from nuri.trading.agents.technical import TechnicalAgent
        v = TechnicalAgent().analyze("NONE", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0


class TestFundamentalAgent:
    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent
        v = FundamentalAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


class TestRiskAgent:
    def test_stop_loss_detected(self, db_path):
        """손절선 돌파 시 SELL + 높은 confidence."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "CRASH", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 70, 30)
        df = pd.DataFrame({
            "ticker": "CRASH", "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close, "high": close, "low": close, "close": close,
            "volume": [100] * 30, "adj_close": close,
        })
        upsert_prices(df, db_path)

        v = RiskAgent().analyze("CRASH", db_path=db_path)
        assert v.action == "SELL"
        assert v.confidence >= 80
        assert "손절선" in v.reasoning


class TestConsensus:
    def test_consensus_returns_result(self, agent_data):
        from nuri.trading.agents.consensus import analyze_ticker
        r = analyze_ticker("TEST", db_path=agent_data)
        assert r.ticker == "TEST"
        assert r.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= r.final_confidence <= 100
        assert 0 <= r.agreement_rate <= 1
        assert len(r.verdicts) == 10  # 10 agents (7 base + options + crypto + retail)

    def test_risk_veto(self, db_path):
        """리스크 에이전트 거부권: 손절 돌파 → 전체 SELL."""
        from nuri.trading.agents.consensus import analyze_ticker

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "VETO", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2024-01-01", periods=250)
        close = np.concatenate([np.linspace(100, 120, 200), np.linspace(120, 60, 50)])
        df = pd.DataFrame({
            "ticker": "VETO", "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [100000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

        r = analyze_ticker("VETO", db_path=db_path)
        # 기술적으로 하락 + 리스크 손절 → SELL이어야 함
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


class TestAgentConfig:
    """config/agents.yaml 로더 테스트."""

    def test_config_loads(self):
        from nuri.core.agent_config import AGENT_CONFIG
        assert isinstance(AGENT_CONFIG, dict)
        assert "technical" in AGENT_CONFIG
        assert "fundamental" in AGENT_CONFIG
        assert "consensus" in AGENT_CONFIG

    def test_config_has_all_agents(self):
        from nuri.core.agent_config import AGENT_CONFIG
        for name in ["technical", "fundamental", "macro", "risk", "smart_money",
                      "wallstreet", "korean_market", "options", "crypto", "retail"]:
            assert name in AGENT_CONFIG, f"{name} missing from agents.yaml"

    def test_confidence_normalization_config(self):
        from nuri.core.agent_config import AGENT_CONFIG
        cn = AGENT_CONFIG.get("confidence_normalization", {})
        assert cn.get("enabled") is True
        scales = cn.get("scales", {})
        assert "technical" in scales
        assert scales["technical"]["raw_max"] == 90


class TestOptionsAgent:
    """옵션 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_high_pcr_returns_buy(self, db_path):
        """PCR 1.3 (극도 공포) → 역발상 BUY."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 1.3),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "BUY"
        assert v.confidence > 0

    def test_low_pcr_returns_sell(self, db_path):
        """PCR 0.5 (과도한 낙관) → 경계 SELL."""
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 0.5),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"
        assert v.confidence > 0


class TestCryptoAgent:
    """크립토 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.crypto_agent import CryptoAgent
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_btc_rally_returns_buy(self, db_path):
        """BTC +12% → 리스크온 BUY."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 12.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "BUY"

    def test_btc_crash_returns_sell(self, db_path):
        """BTC -12% → 리스크오프 SELL."""
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", -12.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"


class TestRetailAgent:
    """리테일 에이전트 테스트."""

    def test_no_data_returns_hold(self, db_path):
        from nuri.trading.agents.retail_agent import RetailAgent
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0

    def test_wsb_spike_returns_sell(self, db_path):
        """WSB 50건 과열 → 역발상 SELL."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 50),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_post_count", 1500),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "SELL"

    def test_moderate_mentions_returns_buy_or_hold(self, db_path):
        """WSB 3건 적정 관심 → BUY 또는 HOLD."""
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 3),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action in ("BUY", "HOLD")


class TestNormalizeConfidence:
    """confidence 정규화 테스트."""

    def test_normalization_enabled(self):
        from nuri.trading.agents.technical import TechnicalAgent
        agent = TechnicalAgent()
        # Technical: raw_max=90 → raw 90 → normalized 100
        assert agent.normalize_confidence(90) == 100.0
        # Technical: raw 0 → normalized 0
        assert agent.normalize_confidence(0) == 0.0
        # Technical: raw 45 → normalized 50
        assert agent.normalize_confidence(45) == 50.0

    def test_korean_market_identity(self):
        """Korean market (0-100 → 0-100) 변환 없음."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        assert agent.normalize_confidence(50) == 50.0
        assert agent.normalize_confidence(100) == 100.0

    def test_clamp_bounds(self):
        """범위 밖 값은 0-100으로 클램핑."""
        from nuri.trading.agents.fundamental import FundamentalAgent
        agent = FundamentalAgent()
        # Fundamental raw_max=80 → raw 100 would be > 100 normalized
        assert agent.normalize_confidence(100) == 100.0
        assert agent.normalize_confidence(-10) == 0.0

    def test_disabled_normalization(self, monkeypatch):
        """정규화 비활성화 시 원본 반환."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": False, "scales": {"technical": {"raw_min": 0, "raw_max": 90}}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(45) == 45  # raw 그대로

    def test_agent_missing_from_scales(self, monkeypatch):
        """scales에 에이전트 없으면 원본 반환."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": True, "scales": {}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(70) == 70  # fallback

    def test_zero_range_returns_raw(self, monkeypatch):
        """raw_min == raw_max 시 원본 반환 (0 나누기 방지)."""
        from nuri.trading.agents import base as base_mod
        from nuri.trading.agents.technical import TechnicalAgent

        monkeypatch.setattr(base_mod, "_load_norm_config",
                            lambda: {"enabled": True, "scales": {"technical": {"raw_min": 50, "raw_max": 50}}})
        agent = TechnicalAgent()
        assert agent.normalize_confidence(50) == 50


class TestAgentConfigFallback:
    """config 로더 폴백 테스트."""

    def test_missing_config_returns_empty(self, tmp_path, monkeypatch):
        """agents.yaml 없으면 빈 dict 반환."""
        import nuri.core.agent_config as acfg
        monkeypatch.setattr(acfg, "_CONFIG_PATH", tmp_path / "nonexistent.yaml")
        result = acfg._load_config()
        assert result == {}

    def test_partial_config_ok(self):
        """에이전트 config 일부만 있어도 .get() 기본값으로 동작."""
        from nuri.core.agent_config import AGENT_CONFIG
        # 존재하지 않는 에이전트 → 빈 dict
        cfg = AGENT_CONFIG.get("nonexistent_agent", {})
        assert cfg == {}
        # 존재하지 않는 키 → 기본값
        val = cfg.get("some_threshold", 42)
        assert val == 42


class TestNewAgentNullData:
    """새 에이전트 NULL 데이터 처리 테스트."""

    def test_options_null_pcr_value(self, db_path):
        """PCR 값이 NULL인 경우 graceful HOLD."""
        from nuri.core.db import get_db
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "put_call_ratio", None),
            )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_crypto_null_change_value(self, db_path):
        """BTC 변화율이 NULL인 경우 graceful HOLD."""
        from nuri.core.db import get_db
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", None),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"

    def test_retail_null_mentions(self, db_path):
        """WSB 언급 값이 NULL인 경우 graceful HOLD."""
        from nuri.core.db import get_db
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", None),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"


class TestNewAgentDataPoints:
    """새 에이전트 data_points 검증."""

    def test_options_data_points(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 1.0),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert "pcr_avg" in v.data_points
        assert "pcr_latest" in v.data_points
        assert "lookback_count" in v.data_points

    def test_crypto_data_points(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 5.0),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_dominance", 55.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert "btc_24h_change" in v.data_points
        assert "btc_dominance" in v.data_points

    def test_retail_data_points(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_mention_TEST", 5),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert "wsb_mentions" in v.data_points
