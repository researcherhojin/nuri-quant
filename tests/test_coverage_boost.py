"""대규모 커버리지 확장 — broker, position, longshort, dashboard API, evidence_charts 추가."""
from unittest.mock import MagicMock

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
def populated_db(db_path):
    """포트폴리오 + 가격 데이터."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        for ticker, qty, price, sector in [
            ("AAPL", 10, 150.0, "Technology"),
            ("MSFT", 5, 300.0, "Software"),
            ("TSLA", 8, 340.0, "SectorA"),
        ]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, qty, price, "USD", sector),
            )

    dates = pd.bdate_range("2024-01-01", periods=250)
    for ticker, base in [("SPY", 450), ("AAPL", 150), ("MSFT", 300), ("TSLA", 340)]:
        close = np.linspace(base, base * 1.1, 250)
        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": [1000000] * 250, "adj_close": close,
        })
        upsert_prices(df, db_path)

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
    ], db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# Broker 모듈
# ═══════════════════════════════════════════════════════

class TestOrder:
    def test_create_filled(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled", 155.0)
        assert o.filled_qty == 10
        assert o.unfilled_qty == 0.0
        assert o.is_partial is False

    def test_create_submitted(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "submitted")
        assert o.filled_qty == 0.0
        assert o.unfilled_qty == 10

    def test_partial_fill(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "partially_filled", 155.0, 5, 5)
        assert o.is_partial is True

    def test_timestamp_auto(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled")
        assert o.timestamp != ""


class TestDryRunBroker:
    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "dry_run"
        assert order.ticker == "AAPL"
        assert order.quantity == 10

    def test_sell_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("TSLA", "sell", 5, "limit")
        assert order.side == "sell"
        assert order.status == "dry_run"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        value = broker.get_account_value()
        assert isinstance(value, (int, float))


class TestGetBroker:
    def test_returns_dryrun_by_default(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        from nuri.trading.execution.broker import get_broker
        broker = get_broker()
        assert broker.__class__.__name__ == "DryRunBroker"


# ═══════════════════════════════════════════════════════
# Position 모듈
# ═══════════════════════════════════════════════════════

class TestPositionCertification:
    def test_create(self):
        from nuri.trading.strategy.position import PositionCertification
        cert = PositionCertification(
            regime_aligned=True, agent_consensus=True, concentration_ok=True,
            daily_limit_ok=True, drift_safe=True, certified=True, details={},
        )
        assert cert.certified is True

    def test_not_certified(self):
        from nuri.trading.strategy.position import PositionCertification
        cert = PositionCertification(
            regime_aligned=False, agent_consensus=True, concentration_ok=True,
            daily_limit_ok=True, drift_safe=True, certified=False, details={"reason": "regime mismatch"},
        )
        assert cert.certified is False


class TestCertifyPosition:
    def test_basic_certification(self, db_path, monkeypatch):
        """기본 인증 — 에이전트 합의 mock."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="AAPL", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.8, dissent=[], reasoning="test",
            verdicts=[
                AgentVerdict("technical", "AAPL", "BUY", 70, "ok"),
                AgentVerdict("fundamental", "AAPL", "BUY", 65, "ok"),
                AgentVerdict("macro", "AAPL", "HOLD", 50, "ok"),
                AgentVerdict("risk", "AAPL", "HOLD", 40, "ok"),
                AgentVerdict("smart_money", "AAPL", "BUY", 55, "ok"),
            ],
        )
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: mock_result, raising=False)

        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", db_path=db_path)
        assert cert.regime_aligned is True
        assert cert.concentration_ok is True
        assert cert.daily_limit_ok is True

    def test_bear_long_misaligned(self, db_path, monkeypatch):
        """bear에서 long은 레짐 불일치."""
        monkeypatch.setattr("nuri.trading.strategy.position.analyze_ticker",
                            lambda t, db_path=None: MagicMock(final_action="SELL", verdicts=[]), raising=False)
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", db_path=db_path)
        assert cert.regime_aligned is False


# ═══════════════════════════════════════════════════════
# Long/Short Strategy
# ═══════════════════════════════════════════════════════

class TestLongShort:
    def test_regime_allocation_exists(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        assert "bull_low_vol" in REGIME_ALLOCATION
        assert "bear_high_vol" in REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc.get("long_pct", 0) + alloc.get("short_pct", 0) + alloc.get("cash_pct", 0)
            assert total == 100, f"{regime}: allocations don't sum to 100"

    def test_etf_universe(self):
        from nuri.trading.strategy.longshort import LONG_ETFS, SHORT_ETFS
        assert "QQQ" in LONG_ETFS or "SPY" in LONG_ETFS
        assert len(SHORT_ETFS) > 0

    def test_allocation_sums(self):
        from nuri.trading.strategy.longshort import REGIME_ALLOCATION
        for regime, alloc in REGIME_ALLOCATION.items():
            total = alloc.get("long_pct", 0) + alloc.get("short_pct", 0) + alloc.get("cash_pct", 0)
            assert total == 100, f"{regime}: allocations don't sum to 100"


# ═══════════════════════════════════════════════════════
# Evidence Charts 추가
# ═══════════════════════════════════════════════════════

class TestEvidenceChartsExtended:
    def test_load_latest_scorecard(self, db_path):
        from nuri.analysis.evidence_charts import _load_latest_scorecard
        df = _load_latest_scorecard()
        # 없으면 None 반환
        assert df is None or isinstance(df, pd.DataFrame)

    def test_load_drift_map(self, db_path):
        from nuri.analysis.evidence_charts import _load_drift_map
        result = _load_drift_map(db_path=db_path)
        assert isinstance(result, dict)

    def test_detect_violations_empty(self, db_path, monkeypatch):
        monkeypatch.setattr("nuri.analysis.evidence_charts.analyze_portfolio",
                            lambda **kw: pd.DataFrame(), raising=False)
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        result = _detect_portfolio_violations(db_path=db_path)
        assert isinstance(result, list)

    def test_regime_chart_no_data(self, db_path, tmp_path):
        """SPY 데이터 없으면 경로만 반환 (파일 생성 안됨)."""
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=db_path)
        # SPY 없으면 빈 HTML 경로 반환 (exists or not)
        assert isinstance(result, type(output_dir / "test"))

    def test_generate_all_evidence_empty(self, db_path, tmp_path, monkeypatch):
        """빈 DB에서 전체 증거 차트 생성."""
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path)
        results = ec_mod.generate_all_evidence(db_path=db_path)
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════
# Dashboard API route
# ═══════════════════════════════════════════════════════

class TestDashboardAPI:
    def test_build_dashboard_empty(self, db_path):
        """빈 DB에서도 dashboard 생성 가능."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert isinstance(result, dict)
        assert "regime" in result
        assert "actions" in result

    def test_cache_mechanism(self, db_path, monkeypatch):
        """캐시 동작 확인."""
        import nuri.api.routes.dashboard as dash_mod
        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        result1 = dash_mod.get_dashboard()
        assert isinstance(result1, dict)

        # 두 번째 호출은 캐시 사용
        import time
        dash_mod._cache["timestamp"] = time.time()
        result2 = dash_mod.get_dashboard()
        assert result2 == result1


# ═══════════════════════════════════════════════════════
# API Routes — targets, agents
# ═══════════════════════════════════════════════════════

class TestAPIRoutes:
    def test_targets_route_exists(self):
        from nuri.api.routes.targets import router
        routes = [r.path for r in router.routes]
        assert any("targets" in r for r in routes)

    def test_agents_route_exists(self):
        from nuri.api.routes.agents import router
        routes = [r.path for r in router.routes]
        assert any("consensus" in r for r in routes)
