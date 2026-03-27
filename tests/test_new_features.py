"""신규 기능 테스트 — 한국 에이전트, 전략, 옵티마이저, 브로커."""
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def market_data(db_path):
    """가격 + 포트폴리오 테스트 데이터."""
    prices = []
    for i in range(200):
        date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
        prices.append({
            "ticker": "AAPL", "date": date,
            "open": 150 + i * 0.1, "high": 152 + i * 0.1,
            "low": 148 + i * 0.1, "close": 150 + i * 0.1,
            "volume": 1000000, "adj_close": 150 + i * 0.1,
        })
        prices.append({
            "ticker": "MSFT", "date": date,
            "open": 300 + i * 0.15, "high": 303 + i * 0.15,
            "low": 298 + i * 0.15, "close": 300 + i * 0.15,
            "volume": 800000, "adj_close": 300 + i * 0.15,
        })
    upsert_prices(pd.DataFrame(prices), db_path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "MSFT", "quantity": 5,
         "avg_price": 300, "currency": "USD", "sector": "Tech"},
    ], db_path)
    return db_path


class TestKoreanAgent:
    def test_us_ticker_neutral(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        agent = KoreanMarketAgent()
        verdict = agent.analyze("AAPL", db_path=db_path)
        assert verdict.action == "HOLD"
        assert verdict.data_points["is_korean"] is False

    def test_kr_ticker(self, db_path):
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        upsert_portfolio([{
            "account": "test", "ticker": "005930.KS",
            "quantity": 4, "avg_price": 200500,
            "currency": "KRW", "sector": "Semiconductor",
        }], db_path)
        agent = KoreanMarketAgent()
        verdict = agent.analyze("005930.KS", db_path=db_path)
        assert verdict.data_points["is_korean"] is True
        assert verdict.action in ("BUY", "SELL", "HOLD")


class TestMeanReversion:
    def test_scan_returns_list(self, market_data):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        signals = scan_mean_reversion(db_path=market_data)
        assert isinstance(signals, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=market_data)
        assert "total_trades" in result


class TestPairs:
    def test_find_pairs(self, market_data):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=market_data)
        assert isinstance(pairs, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=market_data)
        assert "pairs_found" in result


class TestOptimizer:
    def test_optimize_signal(self, market_data):
        from nuri.quant.backtest.optimizer import optimize_signal
        results = optimize_signal("rsi_oversold", db_path=market_data)
        assert isinstance(results, list)


class TestBroker:
    def test_dry_run(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker.get_account_value() == 100_000.0

        order = broker.submit_order("AAPL", "buy", 1)
        assert order.status == "dry_run"

    def test_factory_fallback(self):
        """Alpaca 키 없으면 DryRun으로 폴백."""
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=False)
        # 키 없으면 DryRunBroker
        assert broker.get_account_value() >= 0
