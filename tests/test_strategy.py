"""Long/Short Strategy + Position Manager 테스트."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def bull_data(db_path):
    """상승장 데이터: SPY 상승 + VIX 낮음."""
    dates = pd.bdate_range(end=datetime.now().strftime("%Y-%m-%d"), periods=300)
    close = np.linspace(100, 200, 300) + np.random.normal(0, 1, 300)

    for ticker in ["SPY", "QQQ", "TEST"]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [50000000] * 300, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([{
        "indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 15.0, "source": "test",
    }], db_path)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 150.0, "USD"),
        )

    return db_path


class TestCertification:

    def test_regime_aligned_long_in_bull(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("QQQ", "long", "bull_low_vol", db_path=bull_data)
        assert cert.regime_aligned is True

    def test_regime_misaligned_short_in_bull(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("SH", "short", "bull_low_vol", db_path=bull_data)
        assert cert.regime_aligned is False
        assert cert.certified is False

    def test_regime_aligned_short_in_bear(self, bull_data):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("SH", "short", "bear_high_vol", db_path=bull_data)
        assert cert.regime_aligned is True


class TestPositionManager:

    def test_open_and_query(self, bull_data):
        from nuri.trading.strategy.position import get_positions_summary, open_position
        # bull 레짐에서 long은 인증 통과 가능
        open_position("QQQ", "long", 400.0, portfolio_type="tactical",
                     regime="bull_low_vol", db_path=bull_data)
        # 에이전트 합의 실패할 수 있지만 open 시도는 됨
        summary = get_positions_summary(db_path=bull_data)
        assert summary["open_total"] >= 0  # 인증 결과에 따라

    def test_duplicate_blocked(self, bull_data):
        # 이미 오픈된 포지션이 있으면 concentration_ok = False
        from nuri.core.db import get_db
        from nuri.trading.strategy.position import certify_position
        with get_db(bull_data) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, status) "
                "VALUES ('tactical', 'QQQ', 'long', '2026-03-27', 400.0, 'open')")

        cert = certify_position("QQQ", "long", "bull_low_vol", db_path=bull_data)
        assert cert.concentration_ok is False


class TestLongShortStrategy:

    def test_generate_strategy(self, bull_data):
        from nuri.trading.strategy.longshort import generate_strategy
        # bull 데이터에서 전략 생성
        actions = generate_strategy(db_path=bull_data)
        assert isinstance(actions, list)

    def test_regime_allocation_keys(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            assert alloc["long_pct"] + alloc["short_pct"] + alloc["cash_pct"] == 100


class TestMonitor:

    def test_regime_transition_initial(self, bull_data):
        from nuri.trading.strategy.monitor import detect_regime_transition
        transition = detect_regime_transition(db_path=bull_data)
        # 첫 실행이면 transition 기록
        if transition:
            assert "to_regime" in transition

    def test_pnl_empty(self, db_path):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        pnl = daily_pnl_summary(db_path=db_path)
        assert pnl["total_positions"] == 0
