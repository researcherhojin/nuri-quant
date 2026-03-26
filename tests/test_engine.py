"""SIEGE-inspired engine 테스트: gate, conflicts, memory."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_prices, upsert_macro, get_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def populated_db(db_path):
    """게이트 테스트용 데이터."""
    # 포트폴리오
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "TEST", 100, 50.0, "USD", "Technology"),
        )

    # 가격 300일
    dates = pd.bdate_range("2024-01-01", periods=300)
    close = np.linspace(100, 150, 300) + np.random.normal(0, 1, 300)
    df = pd.DataFrame({
        "ticker": "SPY", "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": [50000000] * 300, "adj_close": close,
    })
    upsert_prices(df, db_path)

    # TEST 종목 가격
    df2 = df.copy()
    df2["ticker"] = "TEST"
    upsert_prices(df2, db_path)

    # VIX
    upsert_macro([{"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"),
                    "value": 18.0, "source": "test"}], db_path)
    # Fear & Greed
    upsert_macro([{"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"),
                    "value": 50.0, "source": "test"}], db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# Gate 테스트
# ═══════════════════════════════════════════════════════


class TestGate:

    def test_empty_db_all_fail(self, db_path):
        from nuri.engine.gate import check_gate
        result = check_gate(db_path=db_path)
        assert result.passed < result.total
        assert result.ready is False

    def test_populated_db_passes_basics(self, populated_db):
        from nuri.engine.gate import check_gate
        result = check_gate(phase="collect", db_path=populated_db)
        # portfolio_exists should pass
        portfolio_cond = [c for c in result.conditions if c.id == "portfolio_exists"]
        assert len(portfolio_cond) == 1
        assert portfolio_cond[0].passed is True

    def test_regime_gate_with_spy(self, populated_db):
        from nuri.engine.gate import check_gate
        result = check_gate(phase="regime", db_path=populated_db)
        spy_cond = [c for c in result.conditions if c.id == "spy_data"]
        assert spy_cond[0].passed is True  # 300일 > 200일

    def test_gate_score_range(self, populated_db):
        from nuri.engine.gate import check_gate
        result = check_gate(db_path=populated_db)
        assert 0.0 <= result.score <= 1.0

    def test_all_gates(self, populated_db):
        from nuri.engine.gate import check_all_gates
        gates = check_all_gates(db_path=populated_db)
        assert "collect" in gates
        assert "regime" in gates
        assert "recommend" in gates


# ═══════════════════════════════════════════════════════
# Conflict 테스트
# ═══════════════════════════════════════════════════════


class TestConflicts:

    def test_direction_conflict_detected(self):
        """같은 종목에 BUY + SELL → direction_conflict."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.engine.conflicts import detect_conflicts

        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 380.0, ""),
            Candidate("TSLA", "macd_dead", "2025-03-24", "SELL", 55, 0.70, 1.4, True, 380.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        assert len(conflicts) >= 1
        tsla_conflict = [c for c in conflicts if c.ticker == "TSLA" and c.conflict_type == "direction_conflict"]
        assert len(tsla_conflict) == 1
        assert tsla_conflict[0].severity == "high"  # 둘 다 regime_fit=True

    def test_no_conflict_single_direction(self):
        """같은 방향만이면 충돌 없음."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.engine.conflicts import detect_conflicts

        candidates = [
            Candidate("NVDA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 100.0, ""),
            Candidate("NVDA", "rsi_oversold", "2025-03-24", "BUY", 60, 0.53, 1.8, True, 100.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        direction = [c for c in conflicts if c.conflict_type == "direction_conflict"]
        assert len(direction) == 0

    def test_empty_candidates(self):
        from nuri.engine.conflicts import detect_conflicts
        assert detect_conflicts([]) == []


# ═══════════════════════════════════════════════════════
# Memory 테스트
# ═══════════════════════════════════════════════════════


class TestMemory:

    def test_detect_drift_empty(self, db_path):
        from nuri.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_snapshot_and_drift(self, db_path):
        """수동으로 strategy_memory 데이터 삽입 후 drift 감지."""
        from nuri.engine.memory import detect_drift
        from nuri.core.db import get_db
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            # all_time: 승률 60%
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "all_time", 100, 0.60, 2.0, 3.5),
            )
            # recent_90d: 승률 35% (급락)
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "recent_90d", 20, 0.35, 0.8, -1.2),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) == 1
        assert drifts[0].signal_id == "rsi_oversold"
        assert drifts[0].status == "critical"  # -41% drift
