"""최종 커버리지 보충 — consensus print, monitor, pairs, mean_reversion, analysis modules."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def market_db(db_path):
    """시장 데이터 (포트폴리오 + 300일 가격)."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.bdate_range(end=today, periods=300)
    for ticker, base in [("SPY", 430), ("AAPL", 140), ("MSFT", 280)]:
        close = np.linspace(base, base * 1.15, 300) + np.random.normal(0, 0.5, 300)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 16.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 60.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path


# ═══════════════════════════════════════════════════════
# Consensus print_consensus
# ═══════════════════════════════════════════════════════

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
        results = [ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=68.0,
            agreement_rate=0.80, verdicts=verdicts,
            dissent=["risk(HOLD, 50): 중립"],
            reasoning="consensus",
        )]
        print_consensus(results)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "BUY" in output
        assert "Dissent" in output

    def test_analyze_portfolio_empty(self, db_path):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio(db_path=db_path)
        assert results == []


# ═══════════════════════════════════════════════════════
# Mean Reversion
# ═══════════════════════════════════════════════════════

class TestMeanReversion:
    def test_import(self):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        assert callable(scan_mean_reversion)

    def test_empty_db(self, db_path):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=db_path)
        assert isinstance(results, list)

    def test_with_data(self, market_db):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        results = scan_mean_reversion(db_path=market_db)
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════
# Pairs Trading
# ═══════════════════════════════════════════════════════

class TestPairsTrading:
    def test_find_pairs(self):
        from nuri.trading.strategy.pairs import find_pairs
        assert callable(find_pairs)

    def test_find_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=db_path)
        assert isinstance(results, list)

    def test_find_pairs_with_data(self, market_db):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=market_db)
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════
# Strategy Monitor
# ═══════════════════════════════════════════════════════

class TestStrategyMonitor:
    def test_detect_regime_transition(self, db_path):
        from nuri.trading.strategy.monitor import detect_regime_transition
        result = detect_regime_transition(db_path=db_path)
        assert result is None or isinstance(result, dict)

    def test_daily_pnl_summary(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        result = daily_pnl_summary(db_path=db_path)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════
# Analysis modules 보충
# ═══════════════════════════════════════════════════════

class TestPortfolioAnalysis:
    def test_analyze_empty(self, db_path):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)

    def test_analyze_with_data(self, market_db):
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        assert isinstance(df, pd.DataFrame)


class TestRiskAnalysis:
    def test_analyze_empty(self, db_path):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


class TestSectorAnalysis:
    def test_analyze_empty(self, db_path):
        from nuri.analysis.sector import analyze_sector
        result = analyze_sector()
        assert isinstance(result, tuple)


# ═══════════════════════════════════════════════════════
# Candidates 보충
# ═══════════════════════════════════════════════════════

class TestCandidatesExtended:
    def test_candidate_dataclass(self):
        from nuri.trading.recommend.candidates import Candidate
        c = Candidate("AAPL", "rsi_oversold", "2026-03-28", "BUY", 75.0, 0.65, 2.1, True, 155.0, "test")
        assert c.ticker == "AAPL"
        assert c.direction == "BUY"
        assert c.confidence == 75.0

    def test_screen_with_data(self, market_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10, db_path=market_db)
        assert isinstance(candidates, list)


# ═══════════════════════════════════════════════════════
# Auth API
# ═══════════════════════════════════════════════════════

class TestAuthAPI:
    def test_create_token(self):
        from nuri.api.auth import create_token
        token = create_token("test_user")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_decode_token(self):
        from nuri.api.auth import create_token, decode_token
        token = create_token("test_user")
        payload = decode_token(token)
        assert payload is not None
        assert payload.get("sub") == "test_user"

    def test_decode_invalid_token(self):
        from nuri.api.auth import decode_token
        payload = decode_token("invalid.token.here")
        assert payload is None

    def test_hash_password(self):
        from nuri.api.auth import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True
        assert verify_password("wrong", hashed) is False


# ═══════════════════════════════════════════════════════
# Broker 확장
# ═══════════════════════════════════════════════════════

class TestBrokerPosition:
    def test_position_dataclass(self):
        from nuri.trading.execution.broker import Position
        p = Position("AAPL", 10, 150.0, 155.0, 3.3)
        assert p.ticker == "AAPL"
        assert p.pnl_pct == 3.3


# ═══════════════════════════════════════════════════════
# Analyst Backtest
# ═══════════════════════════════════════════════════════

class TestAnalystBacktest:
    def test_validate_estimates(self, db_path):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates(db_path=db_path)
        assert isinstance(results, list)

    def test_estimate_result_class(self):
        from nuri.quant.validation.analyst_backtest import EstimateResult
        r = EstimateResult(
            ticker="AAPL", estimate_date="2026-01-01", recommendation="Buy",
            target_mean=200.0, price_at_estimate=180.0, actual_price=195.0,
            actual_date="2026-04-01", target_gap_pct=11.1, actual_return_pct=8.3,
            target_hit=False,
        )
        assert r.target_hit is False
        assert r.ticker == "AAPL"


# ═══════════════════════════════════════════════════════
# Discord Bot
# ═══════════════════════════════════════════════════════

class TestDiscordBot:
    def test_send_webhook_no_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.discord_bot import send_webhook
        result = send_webhook({"title": "test"})
        assert result is False

    def test_send_text_no_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.discord_bot import send_webhook_text
        result = send_webhook_text("test message")
        assert result is False
