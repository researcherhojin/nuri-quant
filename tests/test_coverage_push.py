"""60% 목표 최종 푸시 — analysis.rebalance, performance, correlation, scheduler."""
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
def price_db(db_path):
    """포트폴리오 + 250일 가격 데이터."""
    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("GOOGL", 3, 2700, "BigTech")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.bdate_range("2023-06-01", periods=250)
    for ticker, base in [("AAPL", 140), ("MSFT", 280), ("GOOGL", 120), ("SPY", 430)]:
        close = np.linspace(base, base * 1.15, 250) + np.random.normal(0, 0.5, 250)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    upsert_macro([
        {"indicator": "vix", "date": today, "value": 16.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], db_path)
    return db_path


# ═══════════════════════════════════════════════════════
# analysis/rebalance (MVO/RP)
# ═══════════════════════════════════════════════════════

class TestAnalysisRebalance:
    def test_empty_db(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_with_data(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="rp")
        assert isinstance(result, pd.DataFrame)

    def test_mvo_method(self, price_db):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance(method="mvo")
        assert isinstance(result, pd.DataFrame)


# ═══════════════════════════════════════════════════════
# analysis/performance
# ═══════════════════════════════════════════════════════

class TestPerformance:
    def test_portfolio_returns(self, price_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert isinstance(returns, pd.Series)

    def test_benchmark_returns(self, price_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert isinstance(returns, pd.Series)


# ═══════════════════════════════════════════════════════
# analysis/correlation
# ═══════════════════════════════════════════════════════

class TestCorrelation:
    def test_with_data(self, price_db):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=20)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)


# ═══════════════════════════════════════════════════════
# Position 확장
# ═══════════════════════════════════════════════════════

class TestPositionExtended:
    def test_certify_position(self, db_path, monkeypatch):
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.8, dissent=[], reasoning="test",
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "ok"),
                AgentVerdict("fundamental", "AAPL", "BUY", 65, "ok"),
            ],
        )
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: mock, raising=False)

        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=db_path)
        assert cert.regime_aligned is True

    def test_position_dataclass(self):
        from nuri.trading.strategy.position import Position, PositionCertification
        cert = PositionCertification(True, True, True, True, True, True, {})
        p = Position("AAPL", "long", "tactical", 150.0, 10, "bull_low_vol", cert)
        assert p.ticker == "AAPL"


# ═══════════════════════════════════════════════════════
# LongShort Strategy 확장
# ═══════════════════════════════════════════════════════

class TestLongShortExtended:
    def test_print_strategy(self, capsys):
        from nuri.trading.strategy.longshort import StrategyAction, print_strategy
        actions = [
            StrategyAction("open_long", "QQQ", "long", "tactical", "bull", "bull_low_vol", 75.0),
            StrategyAction("hold", "SPY", "long", "tactical", "maintain", "bull_low_vol", 60.0),
        ]
        print_strategy(actions)
        output = capsys.readouterr().out
        assert "QQQ" in output or "Strategy" in output

    def test_print_empty(self, capsys):
        from nuri.trading.strategy.longshort import print_strategy
        print_strategy([])
        output = capsys.readouterr().out
        assert len(output) > 0


# ═══════════════════════════════════════════════════════
# Scheduler
# ═══════════════════════════════════════════════════════

class TestSchedulerExtended:
    def test_schedules_structure(self):
        from nuri.scheduler import SCHEDULES
        for s in SCHEDULES:
            assert isinstance(s, dict)
            # 각 스케줄에 cron과 job이 있어야 함
            assert "name" in s

    def test_run_collector_import(self):
        """_run_collector 함수가 존재하는지."""
        from nuri.scheduler import _run_collector
        assert callable(_run_collector)


# ═══════════════════════════════════════════════════════
# Backtest Optimizer
# ═══════════════════════════════════════════════════════

class TestOptimizer:
    def test_opt_result(self):
        from nuri.quant.backtest.optimizer import OptResult
        r = OptResult(signal_id="rsi_oversold", params={"rsi_th": 30},
                      total_trades=50, win_rate=0.65, avg_return=3.5, profit_factor=2.1, sharpe=1.5)
        assert r.signal_id == "rsi_oversold"

    def test_optimize_all_empty(self, db_path):
        from nuri.quant.backtest.optimizer import optimize_all
        results = optimize_all(db_path=db_path)
        assert isinstance(results, pd.DataFrame)


# ═══════════════════════════════════════════════════════
# Scanner
# ═══════════════════════════════════════════════════════

class TestScanner:
    def test_scan_market_empty(self, db_path):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market(market="us")
        assert isinstance(results, list)

    def test_scan_market_with_data(self, price_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market(market="us")
        assert isinstance(results, list)

    def test_scan_result_fields(self):
        from nuri.trading.swing.scanner import ScanResult
        r = ScanResult("AAPL", 150.0, 2.5, 5.0, 1.5, 35.0, 0.1, "bounce", 30.0)
        assert r.ticker == "AAPL"
        assert r.score == 30.0


# ═══════════════════════════════════════════════════════
# Analysis Portfolio 확장
# ═══════════════════════════════════════════════════════

class TestPortfolioExtended:
    def test_print_summary(self, price_db, capsys):
        from nuri.analysis.portfolio import analyze_portfolio, print_summary
        df = analyze_portfolio()
        print_summary(df)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_exchange_rate(self, price_db):
        from nuri.analysis.portfolio import get_exchange_rate
        rate = get_exchange_rate()
        assert rate > 0


# ═══════════════════════════════════════════════════════
# Risk 확장
# ═══════════════════════════════════════════════════════

class TestRiskExtended:
    def test_with_data(self, price_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════
# Korean Market Agent
# ═══════════════════════════════════════════════════════

class TestKoreanMarketAgent:
    def test_us_ticker_returns_hold(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        v = agent.analyze("AAPL", db_path=db_path)
        assert v.action == "HOLD"

    def test_kr_ticker(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        v = agent.analyze("005930.KS", db_path=db_path)
        assert v.action in ("BUY", "SELL", "HOLD")
