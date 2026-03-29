"""투자 규칙 자동화 테스트 — 익절, 트레일링 스톱, 포트폴리오 MDD."""
import pytest

from nuri.core.db import get_db, init_db, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_portfolio(db_path, ticker, avg_price, qty=10, account="test"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
            (account, ticker, qty, avg_price),
        )


def _insert_price(db_path, ticker, close, high=None, date="2026-03-28"):
    if high is None:
        high = close * 1.02
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, date, close * 0.99, high, close * 0.98, close, 1000000),
        )


# ═══════════════════════════════════════════════════════
# DB 마이그레이션 테스트
# ═══════════════════════════════════════════════════════


class TestMigrations:
    def test_positions_has_target_columns(self, db_path):
        """positions 테이블에 target_1_price, target_2_price, high_water_mark 컬럼 존재."""
        rows = query("PRAGMA table_info(positions)", db_path=db_path)
        cols = [r["name"] for r in rows]
        assert "target_1_price" in cols
        assert "target_2_price" in cols
        assert "high_water_mark" in cols

    def test_migration_versions(self, db_path):
        """마이그레이션 v8-v10 적용 확인."""
        rows = query("SELECT version FROM schema_version ORDER BY version", db_path=db_path)
        versions = [r["version"] for r in rows]
        assert 8 in versions
        assert 9 in versions
        assert 10 in versions


# ═══════════════════════════════════════════════════════
# 익절 감지 테스트
# ═══════════════════════════════════════════════════════


class TestTakeProfitSignals:
    def test_no_holdings(self, db_path):
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        assert check_take_profit_signals(db_path=db_path) == []

    def test_target_1_hit(self, db_path):
        """진입가 $100, 현재가 $125 → 성장주 +25% → 1차 익절(+20%) 도달."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 125.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        s = signals[0]
        assert s["ticker"] == "AAPL"
        assert s["level"] == "target_1"
        assert s["sell_pct"] == 50  # 1차 익절 50% 매도

    def test_target_2_hit(self, db_path):
        """진입가 $100, 현재가 $145 → 성장주 +45% → 2차 익절(+40%) 도달."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 145.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_2"
        assert signals[0]["sell_pct"] == 25  # 2차 익절 25% 매도

    def test_no_signal_below_target(self, db_path):
        """진입가 $100, 현재가 $110 → +10% → 목표 미달."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 110.0)

        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 0

    def test_target_2_takes_priority(self, db_path):
        """2차 익절 도달 시 target_2가 반환 (target_1이 아님)."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 150.0)  # +50% → target_2(+40%) 초과

        signals = check_take_profit_signals(db_path=db_path)
        assert signals[0]["level"] == "target_2"

    def test_multiple_tickers(self, db_path):
        """여러 종목 중 익절 도달한 것만 반환."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_portfolio(db_path, "MSFT", 100.0)
        _insert_price(db_path, "AAPL", 125.0)  # +25% → target_1
        _insert_price(db_path, "MSFT", 105.0)  # +5% → 미달

        signals = check_take_profit_signals(db_path=db_path)
        tickers = [s["ticker"] for s in signals]
        assert "AAPL" in tickers
        assert "MSFT" not in tickers


# ═══════════════════════════════════════════════════════
# 트레일링 스톱 테스트
# ═══════════════════════════════════════════════════════


class TestTrailingStopSignals:
    def test_no_holdings(self, db_path):
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        assert check_trailing_stop_signals(db_path=db_path) == []

    def test_triggered_when_drop_exceeds_threshold(self, db_path):
        """진입가 $100, 고점 $200, 현재 $160 → -20% → growth -15% 임계값 초과."""
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        # 고점 $200
        _insert_price(db_path, "AAPL", 160.0, high=200.0)

        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1
        s = signals[0]
        assert s["ticker"] == "AAPL"
        assert s["status"] == "TRIGGERED"
        assert s["drop_pct"] <= -15  # -20% < -15% 임계값

    def test_safe_when_within_threshold(self, db_path):
        """진입가 $100, 고점 $120, 현재 $110 → -8.3% → 임계값 -15% 이내."""
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 110.0, high=120.0)

        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) == 0

    def test_hwm_uses_max_of_entry_and_high(self, db_path):
        """HWM은 진입가와 최고가 중 큰 값."""
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        _insert_portfolio(db_path, "AAPL", 200.0)
        _insert_price(db_path, "AAPL", 160.0, high=150.0)  # 고점 < 진입가

        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1
        # HWM = max(200, 150) = 200, drop = (160-200)/200 = -20%
        assert signals[0]["high_water_mark"] == 200.0


# ═══════════════════════════════════════════════════════
# 포트폴리오 MDD 테스트
# ═══════════════════════════════════════════════════════


class TestPortfolioMDD:
    def test_no_violation_when_profitable(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 110.0)

        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_violation_at_minus_10(self, db_path):
        """PnL -15% → MDD 한도(-10%) 초과."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _insert_portfolio(db_path, "AAPL", 100.0, qty=10)
        _insert_price(db_path, "AAPL", 85.0)  # -15%

        result = check_portfolio_mdd(db_path=db_path)
        assert result is not None
        assert result["severity"] == "critical"
        assert result["pnl_pct"] < -10

    def test_no_violation_at_minus_5(self, db_path):
        """PnL -5% → MDD 한도(-10%) 이내."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _insert_portfolio(db_path, "AAPL", 100.0)
        _insert_price(db_path, "AAPL", 95.0)

        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_empty_portfolio(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        assert check_portfolio_mdd(db_path=db_path) is None


# ═══════════════════════════════════════════════════════
# 통합 테스트
# ═══════════════════════════════════════════════════════


class TestIntegration:
    def test_calculate_targets_uses_rules(self, db_path):
        """calculate_targets가 rules.yaml 값을 사용하는지 확인."""
        from nuri.trading.recommend.price_targets import calculate_targets
        _insert_price(db_path, "AAPL", 100.0)

        result = calculate_targets("AAPL", entry_price=100.0, stock_type="growth", db_path=db_path)
        assert result["target_1"] == 120.0   # +20%
        assert result["target_2"] == 140.0   # +40%
        assert result["stop_loss"] == 93.0   # -7%

    def test_value_stock_targets(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        _insert_price(db_path, "LLY", 100.0)

        result = calculate_targets("LLY", entry_price=100.0, stock_type="value", db_path=db_path)
        assert result["target_1"] == 115.0   # +15%
        assert result["target_2"] == 130.0   # +30%
        assert result["stop_loss"] == 90.0   # -10%

    def test_swing_stock_targets(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        _insert_price(db_path, "SWNG", 100.0)

        result = calculate_targets("SWNG", entry_price=100.0, stock_type="swing", db_path=db_path)
        assert result["target_1"] == 105.0   # +5%
        assert result["target_2"] == 110.0   # +10%
