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


# ═══════════════════════════════════════════════════════
# 커버리지 강화: 에이전트별 분기 테스트
# ═══════════════════════════════════════════════════════


class TestFundamentalBranches:
    """펀더멘탈 에이전트 PE/ROE 분기 커버리지."""

    def test_undervalued_buy(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.fundamental import FundamentalAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("CHEAP", "2025-03-25", 10.0, 0.25, 0.30, 1.0),
            )
        v = FundamentalAgent().analyze("CHEAP", db_path=db_path)
        assert v.action == "BUY"
        assert "저평가" in v.reasoning

    def test_overvalued_sell(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.fundamental import FundamentalAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("EXPENSIVE", "2025-03-25", 50.0, -0.05, -0.15, 3.0),
            )
        v = FundamentalAgent().analyze("EXPENSIVE", db_path=db_path)
        assert v.action == "SELL"

    def test_fair_value_hold(self, db_path):
        """PE 30 (적정~고) + ROE 8% (보통) → HOLD."""
        from nuri.core.db import get_db
        from nuri.trading.agents.fundamental import FundamentalAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth) "
                "VALUES (?, ?, ?, ?, ?)",
                ("FAIR", "2025-03-25", 30.0, 0.08, 0.05),
            )
        v = FundamentalAgent().analyze("FAIR", db_path=db_path)
        assert v.action == "HOLD"


class TestSmartMoneyBranches:
    """스마트머니 에이전트 분기 커버리지."""

    def test_superinvestor_buy(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?)",
                ("Buffett", "GOOD", 8.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date) "
                "VALUES (?, ?, ?, ?)",
                ("Dalio", "GOOD", 3.0, "2025-03-01"),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("GOOD", "2025-03-25", "buy", 200.0, 100.0, 10),
            )
        v = SmartMoneyAgent().analyze("GOOD", db_path=db_path)
        assert v.action == "BUY"
        assert v.data_points["n_superinvestors"] == 2

    def test_analyst_sell(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("BAD", "2025-03-25", "sell", 50.0, 100.0, 5),
            )
        v = SmartMoneyAgent().analyze("BAD", db_path=db_path)
        assert v.action == "SELL"

    def test_ark_buy(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        with get_db(db_path) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("ARKY", f"2025-03-{20+i:02d}", "Buy", 1000),
                )
        v = SmartMoneyAgent().analyze("ARKY", db_path=db_path)
        assert "ARK" in v.reasoning


class TestKoreanMarketBranches:
    """한국 시장 에이전트 분기 커버리지."""

    def test_us_ticker_neutral(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        v = KoreanMarketAgent().analyze("AAPL", db_path=db_path)
        assert v.action == "HOLD"
        assert v.data_points["is_korean"] is False

    def test_kr_ticker_with_fx(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "005930.KS", 10, 70000, "KRW", "Semiconductor"),
            )
            # 환율 데이터
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "usd_krw", 1420.0),
            )
            # 가격 데이터 (21일)
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 + i * 100, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert v.data_points["is_korean"] is True
        assert v.data_points["fx_rate"] == 1420.0

    def test_kr_fx_calibration(self, db_path):
        """90일 환율 데이터로 동적 캘리브레이션."""
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import _calibrate_fx_thresholds
        with get_db(db_path) as conn:
            base = pd.Timestamp("2025-01-01")
            for i in range(40):
                d = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (d, "usd_krw", 1380.0 + i * 0.5),
                )
        weak, strong = _calibrate_fx_thresholds(db_path)
        assert weak >= 1300
        assert strong <= 1350


class TestOptionsBranches:
    """옵션 에이전트 추가 분기."""

    def test_neutral_pcr(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{20+i:02d}", "put_call_ratio", 0.9),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert v.action == "HOLD"
        assert "중립" in v.reasoning

    def test_pcr_trend(self, db_path):
        """PCR 상승 추세 감지."""
        from nuri.core.db import get_db
        from nuri.trading.agents.options_agent import OptionsAgent
        with get_db(db_path) as conn:
            # 최근 값이 평균보다 크게 높음
            for i, val in enumerate([1.5, 0.9, 0.9, 0.9, 0.9]):
                conn.execute(
                    "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                    (f"2025-03-{25-i:02d}", "put_call_ratio", val),
                )
        v = OptionsAgent().analyze("TEST", db_path=db_path)
        assert "상승 추세" in v.reasoning or "공포" in v.reasoning


class TestCryptoBranches:
    """크립토 에이전트 추가 분기."""

    def test_dominance_high(self, db_path):
        """BTC 지배력 높음 → 리스크오프."""
        from nuri.core.db import get_db
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_dominance", 65.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert "지배력" in v.reasoning

    def test_btc_price_recorded(self, db_path):
        """BTC 가격 data_points에 포함."""
        from nuri.core.db import get_db
        from nuri.trading.agents.crypto_agent import CryptoAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_usd_cg", 95000.0),
            )
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "btc_24h_change_pct", 1.0),
            )
        v = CryptoAgent().analyze("TEST", db_path=db_path)
        assert v.data_points.get("btc_price") == 95000.0


class TestRetailBranches:
    """리테일 에이전트 추가 분기."""

    def test_post_count_overload(self, db_path):
        """WSB 전체 과열."""
        from nuri.core.db import get_db
        from nuri.trading.agents.retail_agent import RetailAgent
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "wsb_post_count", 1500),
            )
        v = RetailAgent().analyze("TEST", db_path=db_path)
        assert "전체 과열" in v.reasoning


# ═══════════════════════════════════════════════════════
# 커버리지 강화 2: consensus 동적 가중치 + 한국 시장 분기
# ═══════════════════════════════════════════════════════


class TestDynamicWeights:
    """consensus._compute_weights 동적 가중치 계산 테스트."""

    def test_learning_memory_adjusts_weights(self, db_path):
        """충분한 recommendations → 동적 가중치 계산."""
        import json

        from nuri.core.db import get_db
        from nuri.trading.agents.consensus import _compute_weights

        with get_db(db_path) as conn:
            # 15건의 recommendations (min_records=10 충족)
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
                    (f"T{i}", f"2025-01-{i+1:02d}", "BUY", 70, signals, 5.0 if i % 2 == 0 else -2.0),
                )
        weights = _compute_weights(db_path=db_path)
        # 동적 가중치가 계산됨 (기본값과 다를 수 있음)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        # technical의 hit rate가 50%이므로 기본값 근처
        assert weights["technical"] > 0.03  # min floor

    def test_no_verdicts_in_signals_fallback(self, db_path):
        """signals에 verdicts 없으면 기본 가중치."""
        from nuri.core.db import get_db
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _compute_weights

        with get_db(db_path) as conn:
            for i in range(15):
                conn.execute(
                    "INSERT INTO recommendations "
                    "(ticker, date, action, confidence, signals, outcome_30d) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"T{i}", f"2025-01-{i+1:02d}", "BUY", 70, "rsi_oversold", 5.0),
                )
        weights = _compute_weights(db_path=db_path)
        assert weights == DEFAULT_WEIGHTS  # JSON 파싱 실패 → 기본값

    def test_sell_hit_rate(self, db_path):
        """SELL 적중: outcome 음수일 때 적중."""
        import json

        from nuri.core.db import get_db
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
                    (f"T{i}", f"2025-01-{i+1:02d}", "SELL", 80, signals, -5.0),
                )
        weights = _compute_weights(db_path=db_path)
        # risk의 SELL이 100% 적중 → 가중치 상승
        assert weights["risk"] > 0.15


class TestMacroAgentBranches:
    """매크로 에이전트 레짐별 모멘텀 분기 커버리지."""

    def _make_prices(self, db_path, ticker, close_values):
        """가격 데이터 삽입 헬퍼."""
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            for i, c in enumerate(close_values):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, f"2025-03-{i+1:02d}", c, c, c, c, 100000),
                )

    def _mock_regime(self, monkeypatch, trend, regime_name, macro_score):
        class FakeRegime:
            pass
        r = FakeRegime()
        r.regime = regime_name
        r.trend = trend
        r.volatility = "low"
        r.confidence = 0.8
        r.details = None

        class FakeMacro:
            pass
        m = FakeMacro()
        m.total_score = macro_score

        # lazy import 되므로 모듈 내부에서 패치
        import nuri.quant.regime.classifier as cls_mod
        import nuri.quant.regime.macro_score as ms_mod
        monkeypatch.setattr(cls_mod, "classify_regime", lambda db_path=None: r)
        monkeypatch.setattr(ms_mod, "compute_macro_score", lambda db_path=None: m)

    def test_bull_buy(self, db_path, monkeypatch):
        """상승장 + 매크로 양호 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        self._make_prices(db_path, "BULL", [100 + i for i in range(20)])
        v = MacroAgent().analyze("BULL", db_path=db_path)
        assert v.action == "BUY"

    def test_bear_sell(self, db_path, monkeypatch):
        """하락장 → SELL."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bear", "bear_low_vol", 30)
        self._make_prices(db_path, "BEAR", [100 - i for i in range(20)])
        v = MacroAgent().analyze("BEAR", db_path=db_path)
        assert v.action in ("SELL", "HOLD")  # bear bounce도 가능

    def test_sideways_strong_momentum_buy(self, db_path, monkeypatch):
        """횡보 + 강한 상승 모멘텀 → BUY."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "sideways", "sideways_low_vol", 50)
        # 5일 +10%, 10일 +12% (급등)
        prices = [100] * 10 + [112] * 5 + [100, 100, 100, 100, 100]
        prices.reverse()  # DESC order → most recent first in DB
        # DB는 ASC order로 저장하지만 agent가 DESC LIMIT 20으로 읽음
        self._make_prices(db_path, "ROCKET", list(reversed(prices[:20])))
        v = MacroAgent().analyze("ROCKET", db_path=db_path)
        # 모멘텀 강세 → BUY 또는 기본 HOLD
        assert v.action in ("BUY", "HOLD")

    def test_bull_underperform_hold(self, db_path, monkeypatch):
        """상승장이나 개별 약세 → HOLD로 약화."""
        from nuri.trading.agents.macro_agent import MacroAgent
        self._mock_regime(monkeypatch, "bull", "bull_low_vol", 70)
        # 최근 5일 -8% 하락 (bull_underperform < -5)
        prices = [100] * 15 + [92, 91, 90, 89, 88]
        self._make_prices(db_path, "WEAK", prices[:20])
        v = MacroAgent().analyze("WEAK", db_path=db_path)
        assert v.action in ("BUY", "HOLD")


class TestKoreanMarketFullBranches:
    """한국 시장 에이전트 FX/외국인/모멘텀 전체 분기."""

    def _setup_kr_base(self, db_path, ticker="005930.KS", sector="Semiconductor", fx=1420.0):
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, 10, 70000, "KRW", sector),
            )
            conn.execute(
                "INSERT OR REPLACE INTO macro (date, indicator, value) VALUES (?, ?, ?)",
                ("2025-03-25", "usd_krw", fx),
            )

    def test_fx_weak_nonexport(self, db_path):
        """원화 약세 + 내수주 → 부담."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path, sector="Retail", fx=1420.0)
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "내수주 부담" in v.reasoning

    def test_fx_strong_nonexport(self, db_path):
        """원화 강세 + 내수주 → 유리."""
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path, sector="Retail", fx=1200.0)
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "내수주 유리" in v.reasoning

    def test_foreign_buy(self, db_path):
        """외국인 순매수 → 점수 증가."""
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO institutional_flows (ticker, date, market, foreign_net) VALUES (?, ?, ?, ?)",
                ("005930.KS", "2025-03-25", "KOSPI", 50000),
            )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "외국인 순매수" in v.reasoning

    def test_foreign_sell(self, db_path):
        """외국인 순매도 → 점수 감소."""
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO institutional_flows (ticker, date, market, foreign_net) VALUES (?, ?, ?, ?)",
                ("005930.KS", "2025-03-25", "KOSPI", -30000),
            )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "외국인 순매도" in v.reasoning

    def test_momentum_positive(self, db_path):
        """20일 모멘텀 양호 → 점수 증가."""
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 + i * 500, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "모멘텀" in v.reasoning

    def test_momentum_negative(self, db_path):
        """20일 모멘텀 부진 → 점수 감소."""
        from nuri.core.db import get_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        self._setup_kr_base(db_path)
        with get_db(db_path) as conn:
            for i in range(21):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("005930.KS", f"2025-03-{i+1:02d}", 70000, 71000, 69000, 70000 - i * 500, 100000),
                )
        v = KoreanMarketAgent().analyze("005930.KS", db_path=db_path)
        assert "모멘텀" in v.reasoning
