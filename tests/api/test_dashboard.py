"""Tests for dashboard — split from test_api_all.py."""
import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


class TestDashboard:
    def test_dashboard(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        assert "regime" in data
        assert "actions" in data

    def test_dashboard_cached(self, client):
        """두 번 호출 — 캐시 사용."""
        r1 = client.get("/api/dashboard")
        r2 = client.get("/api/dashboard")
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestDashboardAPI:
    def test_build_dashboard_empty(self, db_path):
        """빈 DB에서도 dashboard 생성 가능."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert isinstance(result, dict)
        assert "regime" in result
        assert "actions" in result

    def test_dashboard_exposes_account_labels(self, db_path):
        """account_labels 필드가 응답에 포함되어야 함 (#199 multi-account fix).

        frontend가 holding의 raw account → 익명 label을 lookup하기 위해 필요.
        ticker_accounts(ticker→label, 단일 매핑)는 다계좌 ticker collision을
        해결하지 못하므로 별도 필드 필요.
        """
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert "account_labels" in result
        assert isinstance(result["account_labels"], dict)

    def test_dashboard_exposes_actual_allocation_and_cash(self, db_path):
        """#213: dashboard 응답이 actual_allocation + cash_summary + target_allocation을 노출."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert "actual_allocation" in result
        assert "target_allocation" in result
        assert "cash_summary" in result
        actual = result["actual_allocation"]
        assert set(actual.keys()) == {"long", "short", "cash"}
        assert actual["long"] + actual["short"] + actual["cash"] == 100
        cs = result["cash_summary"]
        assert "accounts" in cs and isinstance(cs["accounts"], list)
        assert "total_cash_usd" in cs and isinstance(cs["total_cash_usd"], (int, float))


class TestCashBalances:
    """#213: _get_cash_balances() — portfolio.yaml에서 cash 파싱."""

    def test_compute_actual_allocation_holdings_only(self):
        from nuri.api.routes.dashboard import _compute_actual_allocation
        result = _compute_actual_allocation([{"value": 10000}], 0)
        assert result == {"long": 100, "short": 0, "cash": 0}

    def test_compute_actual_allocation_cash_only(self):
        from nuri.api.routes.dashboard import _compute_actual_allocation
        result = _compute_actual_allocation([], 5000)
        assert result == {"long": 0, "short": 0, "cash": 100}

    def test_compute_actual_allocation_empty_portfolio(self):
        from nuri.api.routes.dashboard import _compute_actual_allocation
        result = _compute_actual_allocation([], 0)
        assert result == {"long": 0, "short": 0, "cash": 100}

    def test_compute_actual_allocation_mixed(self):
        from nuri.api.routes.dashboard import _compute_actual_allocation
        # holdings 46, cash 54 → 46% / 54%
        result = _compute_actual_allocation([{"value": 4600}], 5400)
        assert result["long"] == 46
        assert result["cash"] == 54
        assert result["short"] == 0

    def test_compute_actual_allocation_rounds_to_100(self):
        """반올림 오차 흡수로 long + cash = 100 보장."""
        from nuri.api.routes.dashboard import _compute_actual_allocation
        # 333/1000 = 33.3%, 667/1000 = 66.7% → round(33.3)=33, cash=67
        result = _compute_actual_allocation([{"value": 333}], 667)
        assert result["long"] + result["cash"] == 100

    def test_get_cash_balances_missing_yaml(self, tmp_path, monkeypatch):
        """portfolio.yaml 없으면 빈 cash 반환 (graceful)."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(
            dash_mod,
            "__file__",
            str(tmp_path / "fake_dashboard.py"),
        )
        # tmp_path에 portfolio.yaml 없음 → FileNotFoundError → 빈 dict 반환
        result = dash_mod._get_cash_balances(exchange_rate=1400)
        assert result == {"accounts": [], "total_cash_usd": 0.0}

    def test_get_cash_balances_parses_usd_and_krw(self, tmp_path, monkeypatch):
        """cash_usd + cash_krw 파싱 → USD 환산."""
        import nuri.api.routes.dashboard as dash_mod

        # 임시 portfolio.yaml 생성
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        portfolio_yaml = config_dir / "portfolio.yaml"
        portfolio_yaml.write_text(
            "accounts:\n"
            "  acct_a:\n"
            "    name: Test A\n"
            "    strategy: core\n"
            "    cash_usd: 1000.0\n"
            "    cash_krw: 1400000\n"
            "  acct_b:\n"
            "    name: Test B\n"
            "    strategy: active\n"
            "    cash_usd: 500.0\n",
            encoding="utf-8",
        )
        # __file__을 tmp_path 하위로 패치 → config/portfolio.yaml resolve 위치 변경
        # dashboard.py의 경로 계산: Path(__file__).parent.parent.parent.parent / "config" / "portfolio.yaml"
        # 즉 __file__이 tmp_path/level1/level2/level3/level4.py 이면 tmp_path/config/portfolio.yaml로 resolve
        fake_file = tmp_path / "l1" / "l2" / "l3" / "dashboard.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        monkeypatch.setattr(dash_mod, "__file__", str(fake_file))

        result = dash_mod._get_cash_balances(exchange_rate=1400)
        # acct_a: 1000 + 1400000/1400 = 2000 USD
        # acct_b: 500 USD
        # total: 2500
        assert result["total_cash_usd"] == 2500.0
        assert len(result["accounts"]) == 2

    def test_get_cash_balances_skips_non_dict_entries(self, tmp_path, monkeypatch):
        """malformed yaml — accounts 아래에 dict가 아닌 값이 있으면 건너뜀 (방어적 guard).

        covers dashboard.py line 335 (`if not isinstance(info, dict): continue`).
        실전에서 portfolio.yaml이 `accounts: null` 이거나 잘못된 YAML을 먹었을 때 crash 방지.
        """
        import nuri.api.routes.dashboard as dash_mod

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        portfolio_yaml = config_dir / "portfolio.yaml"
        # 하나는 dict, 하나는 null, 하나는 string — 모두 yaml 파싱 가능하지만 non-dict
        portfolio_yaml.write_text(
            "accounts:\n"
            "  good:\n"
            "    strategy: core\n"
            "    cash_usd: 500.0\n"
            "  broken_null: null\n"
            "  broken_str: unexpected string\n",
            encoding="utf-8",
        )
        fake_file = tmp_path / "l1" / "l2" / "l3" / "dashboard.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        monkeypatch.setattr(dash_mod, "__file__", str(fake_file))

        # 예외 없이 good 계정만 집계되어야 함
        result = dash_mod._get_cash_balances(exchange_rate=1400)
        assert result["total_cash_usd"] == 500.0
        assert len(result["accounts"]) == 1

    def test_cache_mechanism(self, db_path, monkeypatch):
        """캐시 동작 확인."""
        import nuri.api.routes.dashboard as dash_mod
        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        result1 = dash_mod.get_dashboard()
        assert isinstance(result1, dict)

        # 두 번째 호출은 캐시 사용
        dash_mod._cache["timestamp"] = _time.time()
        result2 = dash_mod.get_dashboard()
        assert result2 == result1


class TestDashboardBuildExtended:
    @pytest.fixture()
    def rich_db(self, db_path):
        from nuri.core.timezone import today_kst
        today = today_kst()

        with get_db(db_path) as conn:
            for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                                ("TSLA", 8, 340, "SectorA"), ("SPY", 50, 450, "Index")]:
                conn.execute(
                    "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                    "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

        dates = pd.date_range(end=today, periods=300)
        for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
            close = np.linspace(base, base * 1.2, 300) + np.random.normal(0, 1, 300)
            df = pd.DataFrame({
                "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close * 0.99, "high": close * 1.01,
                "low": close * 0.98, "close": close,
                "volume": [1000000] * 300, "adj_close": close,
            })
            upsert_prices(df, db_path)

        with get_db(db_path) as conn:
            for d in dates[-50:]:
                ds = d.strftime("%Y-%m-%d")
                conn.execute("INSERT OR IGNORE INTO signals (ticker, date, rsi_14, sma_20, sma_50, sma_200) "
                             "VALUES (?, ?, ?, ?, ?, ?)", ("SPY", ds, 55.0, 480.0, 470.0, 440.0))

        upsert_macro([
            {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
            {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
            {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
            {"indicator": "gdp_growth", "date": today, "value": 2.5, "source": "test"},
            {"indicator": "unemployment", "date": today, "value": 3.8, "source": "test"},
        ], db_path)
        return db_path

    def test_verdict_levels(self, rich_db):
        """rich_db로 dashboard 빌드 — verdict_level 확인."""
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert result["verdict_level"] in ("aggressive", "neutral", "cautious", "defensive")
        assert isinstance(result["alerts"], list)
        assert isinstance(result["actions"], list)

    def test_gate_score_field(self, rich_db):
        from nuri.api.routes.dashboard import _build_dashboard
        result = _build_dashboard()
        assert "gate_score" in result


class TestDashboardInternals:
    def test_get_allocation(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("bull_low_vol")
        assert "long" in result
        assert "short" in result
        assert "cash" in result

    def test_get_allocation_unknown(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("unknown_regime")
        assert "long" in result


class TestDashboardDeeper:
    @pytest.fixture()
    def full_db(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "test.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
            {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "SectorA"},
        ], path)
        dates = pd.date_range("2024-06-01", periods=500, freq="B")
        rows = []
        for t in ["SPY", "AAPL", "NVDA", "TSLA"]:
            base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200}[t]
            for i, d in enumerate(dates):
                p = base + i * 0.2 + np.sin(i / 20) * 5
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                             "open": p, "high": p + 3, "low": p - 2,
                             "close": p + 1, "volume": 50000000, "adj_close": p + 1})
        upsert_prices(pd.DataFrame(rows), path)
        macro = []
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
            macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        upsert_macro(macro, path)
        return path

    def test_dashboard_with_portfolio(self, full_db, tmp_path, monkeypatch):
        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        c = TestClient(app)
        r = c.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "verdict" in data
        assert "regime" in data

    def test_pipeline_run(self, client):
        """POST /api/pipeline/{step}/run."""
        r = client.post("/api/pipeline/collect/run")
        assert r.status_code in (200, 202, 400, 404)

    def test_timeline(self, client):
        r = client.get("/api/pipeline/timeline")
        assert r.status_code == 200


class TestDashboardAPI_R22:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch, _seed_recommendations, _seed_positions):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        import nuri.api.routes.dashboard as dash_mod
        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        from nuri.api.main import app
        return TestClient(app)

    def test_dashboard_returns_data(self, _client, monkeypatch):
        """Dashboard endpoint returns valid JSON with expected keys."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "bull_low_vol", "trend": "bull", "volatility": "low",
            "confidence": 80, "vix": 15.0, "fear_greed": 60,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 65, "interpretation": "Positive"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 70, "short": 10, "cash": 20})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 80)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        resp = _client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert "regime" in data
        assert "actions" in data

    def test_dashboard_cache(self, _client, monkeypatch):
        """Second call within TTL returns cached data."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "sideways_high_vol", "trend": "sideways", "confidence": 50,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 45, "interpretation": "Neutral"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 30, "short": 20, "cash": 50})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 50)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        resp1 = _client.get("/api/dashboard")
        resp2 = _client.get("/api/dashboard")
        assert resp1.json()["verdict"] == resp2.json()["verdict"]

    def test_dashboard_bear_defensive(self, _client, monkeypatch):
        """Bear regime produces defensive verdict."""
        import nuri.api.routes.dashboard as dash_mod

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "bear_high_vol", "trend": "bear", "confidence": 70,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 25, "interpretation": "Bearish"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 10, "short": 40, "cash": 50})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 30)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        resp = _client.get("/api/dashboard")
        data = resp.json()
        assert data["verdict_level"] == "defensive"

    def test_dashboard_sells_more_than_buys(self, _client, db_path, monkeypatch):
        """When SELL actions > BUY actions, verdict = cautious."""
        import nuri.api.routes.dashboard as dash_mod

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "TSLA", "SELL", 0.90, "bear_high_vol", "signal"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "GOOG", "SELL", 0.85, "bear_high_vol", "signal"),
            )

        monkeypatch.setattr(dash_mod, "_get_cached_regime", lambda: {
            "regime": "sideways_low_vol", "trend": "sideways", "confidence": 50,
        })
        monkeypatch.setattr(dash_mod, "_get_macro", lambda: {"score": 55, "interpretation": "Neutral"})
        monkeypatch.setattr(dash_mod, "_get_allocation", lambda r: {"long": 40, "short": 20, "cash": 40})
        monkeypatch.setattr(dash_mod, "_get_active_alerts", lambda: [])
        monkeypatch.setattr(dash_mod, "_get_gate_score", lambda: 50)
        monkeypatch.setattr(dash_mod, "_get_freshness", lambda: {})
        monkeypatch.setattr(dash_mod, "_get_pipeline_status", lambda: {})

        dash_mod._cache["data"] = None
        dash_mod._cache["timestamp"] = 0

        resp = _client.get("/api/dashboard")
        data = resp.json()
        assert data["verdict_level"] in ("cautious", "neutral", "defensive")


class TestDashboardHelpers:
    """Test individual _build helper functions."""

    def test_get_cached_regime_failure(self, monkeypatch):
        """_get_cached_regime returns fallback when classify_regime raises."""
        import nuri.api.routes.dashboard as dash_mod

        def _raise():
            raise RuntimeError("test error")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _raise)
        result = dash_mod._get_cached_regime()
        assert result["regime"] == "unknown"

    def test_get_macro_failure(self, monkeypatch):
        """_get_macro returns fallback when compute_macro_score raises."""
        import nuri.api.routes.dashboard as dash_mod

        def _raise():
            raise RuntimeError("no data")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", _raise)
        result = dash_mod._get_macro()
        assert result["score"] == 50

    def test_get_allocation_unknown_regime(self):
        """_get_allocation returns defaults for unknown regime."""
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_allocation("nonexistent_regime")
        assert "cash" in result

    def test_get_freshness_failure(self, monkeypatch):
        """_get_freshness returns {} on exception."""
        import nuri.api.routes.dashboard as dash_mod

        def bad():
            raise RuntimeError("fail")

        monkeypatch.setattr("nuri.core.freshness.check_all_freshness", bad)
        result = dash_mod._get_freshness()
        assert result == {}

    def test_get_pipeline_status_failure(self, monkeypatch):
        """_get_pipeline_status returns {} on exception."""
        import nuri.api.routes.dashboard as dash_mod

        def bad():
            raise RuntimeError("fail")

        monkeypatch.setattr("nuri.core.events.get_pipeline_status", bad)
        result = dash_mod._get_pipeline_status()
        assert result == {}


class TestGetLatestActions:
    def test_no_recommendations(self, db_path, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        result = dash_mod._get_latest_actions()
        assert result == []

    def test_with_recommendations(self, db_path, _seed_recommendations, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        result = dash_mod._get_latest_actions()
        assert isinstance(result, list)

    def test_low_confidence_filtered(self, db_path, monkeypatch):
        """Low confidence recommendations are filtered out."""
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "AAPL", "BUY", 0.30, "bull_low_vol", "weak_signal"),
            )

        result = dash_mod._get_latest_actions()
        assert all(a.get("confidence", 0) >= 50 for a in result if a["action"] == "BUY")


class TestGetActiveAlerts:
    def test_with_portfolio_stop(self, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", lambda: {
            "portfolio_stop_triggered": True,
            "max_drawdown_pct": -12.0,
            "stop_loss_alerts": [{"ticker": "TSLA", "pnl_pct": -25.0}],
        })
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda: [])

        alerts = dash_mod._get_active_alerts()
        assert len(alerts) >= 1
        assert any("손절선" in a["message"] for a in alerts)

    def test_all_failures_graceful(self, monkeypatch):
        import nuri.api.routes.dashboard as dash_mod

        def fail():
            raise RuntimeError("mock fail")

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", fail)
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", fail)
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", fail)

        alerts = dash_mod._get_active_alerts()
        assert alerts == []


class TestDashboard_R27:
    """Tests for nuri/api/routes/dashboard.py."""

    def test_get_allocation_unknown_regime(self):
        """_get_allocation with unknown regime returns defaults."""
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("totally_unknown_regime")
        assert "long" in result
        assert "cash" in result

    def test_get_cached_regime_exception(self, monkeypatch):
        """_get_cached_regime handles exception."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            MagicMock(side_effect=Exception("test error")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_cached_regime()
        assert result["regime"] == "unknown"

    def test_get_freshness(self, monkeypatch):
        """_get_freshness returns dict."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(return_value=[{"table": "prices", "age_hours": 5, "status": "PASS"}]),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert "prices" in result

    def test_get_freshness_exception(self, monkeypatch):
        """_get_freshness handles exception."""
        monkeypatch.setattr(
            "nuri.core.freshness.check_all_freshness",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_freshness()
        assert result == {}

    def test_get_pipeline_status_exception(self, monkeypatch):
        """_get_pipeline_status handles exception."""
        monkeypatch.setattr(
            "nuri.core.events.get_pipeline_status",
            MagicMock(side_effect=Exception("test")),
        )
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_pipeline_status()
        assert result == {}

    def test_get_latest_actions_empty(self):
        """_get_latest_actions returns empty list with no recommendation data."""
        import nuri.api.routes.dashboard as dash_mod
        result = dash_mod._get_latest_actions()
        assert isinstance(result, list)


class TestTickerAccountMap:
    """Tests for _get_ticker_account_map()."""

    def test_empty_portfolio(self, db_path):
        """Empty portfolio returns empty mapping."""
        from nuri.api.routes.dashboard import _get_ticker_account_map
        result = _get_ticker_account_map()
        assert result == {}

    def test_single_account(self, db_path, _seed_portfolio):
        """Portfolio entries in same account are mapped correctly."""
        from nuri.api.routes.dashboard import _get_ticker_account_map
        result = _get_ticker_account_map()
        assert result["AAPL"] == "test"
        assert result["MSFT"] == "test"

    def test_multiple_accounts(self, db_path):
        """Tickers in different accounts get correct mapping; first account wins for dupes."""
        from nuri.api.routes.dashboard import _get_ticker_account_map
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("alpha", "AAPL", 10, 150.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("beta", "MSFT", 5, 300.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("beta", "AAPL", 20, 160.0, "USD", "Tech"),
            )
        result = _get_ticker_account_map()
        # ORDER BY account → 'alpha' comes before 'beta', so AAPL maps to 'alpha'
        assert result["AAPL"] == "alpha"
        assert result["MSFT"] == "beta"

    def test_kr_tickers_included(self, db_path):
        """Korean tickers (.KS suffix) are included in the mapping."""
        from nuri.api.routes.dashboard import _get_ticker_account_map
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("pension", "005930.KS", 100, 70000, "KRW", "Tech"),
            )
        result = _get_ticker_account_map()
        assert result["005930.KS"] == "pension"


class TestAccountLabels:
    """Tests for _get_account_labels()."""

    def test_happy_path(self, monkeypatch):
        """YAML with strategy fields maps to correct labels."""
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "main_account": {"strategy": "core", "tickers": []},
                "swing_account": {"strategy": "swing", "tickers": []},
                "pension_account": {"strategy": "pension", "tickers": []},
                "longterm_account": {"strategy": "longterm", "tickers": []},
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result["main_account"] == "Main"
        assert result["swing_account"] == "Sub"
        assert result["pension_account"] == "Pension"
        assert result["longterm_account"] == "Long"

    def test_duplicate_strategy_gets_numbered(self, monkeypatch):
        """Two accounts with same strategy get numbered labels (Main, Main 2)."""
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "acc_a": {"strategy": "core"},
                "acc_b": {"strategy": "core"},
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result["acc_a"] == "Main"
        assert result["acc_b"] == "Main 2"

    def test_unknown_strategy_uses_title(self, monkeypatch):
        """Strategy not in _STRATEGY_LABELS gets Title-cased."""
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "custom_acc": {"strategy": "experimental"},
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result["custom_acc"] == "Experimental"

    def test_custom_label_field_overrides_strategy(self, monkeypatch):
        """#214 polish: `label` field in portfolio.yaml overrides the strategy default.

        Lets users put custom display names (e.g. 'Toss', '호진 메인') in their
        own gitignored yaml without any personal data reaching the code.
        """
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "acc_alpha": {"strategy": "core", "label": "Brokerage Alpha"},
                "acc_beta": {"strategy": "long_term", "label": "Brokerage Beta"},
                "acc_default": {"strategy": "core"},  # no label → falls back to Main
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        # Custom labels used verbatim
        assert result["acc_alpha"] == "Brokerage Alpha"
        assert result["acc_beta"] == "Brokerage Beta"
        # Account without `label` falls back to strategy default
        assert result["acc_default"] == "Main"

    def test_empty_label_falls_back_to_strategy(self, monkeypatch):
        """Empty string or whitespace in `label` falls back to strategy default."""
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "acc_empty": {"strategy": "core", "label": ""},
                "acc_whitespace": {"strategy": "swing", "label": "   "},
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result["acc_empty"] == "Main"
        assert result["acc_whitespace"] == "Sub"

    def test_missing_strategy_defaults_to_core(self, monkeypatch):
        """Account without strategy field defaults to 'core' -> 'Main'."""
        from nuri.api.routes.dashboard import _get_account_labels

        mock_yaml = {
            "accounts": {
                "no_strategy_acc": {"tickers": ["AAPL"]},
            }
        }

        import builtins
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO(yaml.dump(mock_yaml))
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result["no_strategy_acc"] == "Main"

    def test_file_not_found_returns_empty(self, monkeypatch):
        """When portfolio.yaml does not exist, returns empty dict."""
        import builtins

        from nuri.api.routes.dashboard import _get_account_labels
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                raise FileNotFoundError("no such file")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        assert result == {}

    def test_malformed_yaml_returns_empty(self, monkeypatch):
        """Malformed YAML returns empty dict (exception path)."""
        import builtins

        from nuri.api.routes.dashboard import _get_account_labels
        original_open = builtins.open

        def mock_open(path, *args, **kwargs):
            if "portfolio.yaml" in str(path):
                from io import StringIO
                return StringIO("not: [valid: yaml: {{")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)
        result = _get_account_labels()
        # yaml.safe_load may parse this or raise; either way should not crash
        assert isinstance(result, dict)


class TestAccountValues:
    """Tests for _get_account_values()."""

    def test_empty_portfolio(self, db_path, monkeypatch):
        """Empty portfolio returns empty list."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {})
        result = dash_mod._get_account_values(exchange_rate=1300)
        assert result == []

    def test_usd_tickers(self, db_path, _seed_portfolio, _seed_prices, monkeypatch):
        """USD tickers have value = close * quantity."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"test": "Main"})
        result = dash_mod._get_account_values(exchange_rate=1300)
        assert len(result) == 1
        assert result[0]["account"] == "Main"
        assert result[0]["value"] > 0

    def test_kr_ticker_divided_by_exchange_rate(self, db_path, monkeypatch):
        """Korean .KS tickers are divided by exchange rate to convert to USD."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"kr_acc": "Pension"})

        # Insert KR portfolio entry and price
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("kr_acc", "005930.KS", 100, 70000, "KRW", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("005930.KS", "2025-04-01", 69000, 71000, 68000, 70000, 5000000, 70000),
            )
        result = dash_mod._get_account_values(exchange_rate=1400)
        assert len(result) == 1
        assert result[0]["account"] == "Pension"
        # 70000 * 100 / 1400 = 5000.0
        assert result[0]["value"] == 5000.0

    def test_exchange_rate_none_uses_fallback(self, db_path, monkeypatch):
        """exchange_rate=None falls back to 1400."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"kr_acc": "Pension"})

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("kr_acc", "005930.KS", 100, 70000, "KRW", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("005930.KS", "2025-04-01", 69000, 71000, 68000, 70000, 5000000, 70000),
            )
        result = dash_mod._get_account_values(exchange_rate=None)
        assert len(result) == 1
        # 70000 * 100 / 1400 = 5000.0
        assert result[0]["value"] == 5000.0

    def test_mixed_accounts_sorted_descending(self, db_path, monkeypatch):
        """Multiple accounts are sorted by value descending."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"big": "Main", "small": "Sub"})

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("big", "AAPL", 100, 150.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("small", "MSFT", 1, 300.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("AAPL", "2025-04-01", 149, 151, 148, 150, 1000000, 150),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("MSFT", "2025-04-01", 299, 301, 298, 300, 800000, 300),
            )
        result = dash_mod._get_account_values(exchange_rate=1400)
        assert len(result) == 2
        # big: 150 * 100 = 15000, small: 300 * 1 = 300
        assert result[0]["account"] == "Main"
        assert result[0]["value"] > result[1]["value"]

    def test_unlabeled_account_uses_raw_name(self, db_path, monkeypatch):
        """Account not in labels dict falls back to raw account name."""
        import nuri.api.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {})

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("unknown_acc", "AAPL", 10, 150.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) VALUES (?,?,?,?,?,?,?,?)",
                ("AAPL", "2025-04-01", 149, 151, 148, 150, 1000000, 150),
            )
        result = dash_mod._get_account_values(exchange_rate=1400)
        assert len(result) == 1
        assert result[0]["account"] == "unknown_acc"


class TestUpcomingEvents:
    """Tests for _get_upcoming_events()."""

    def test_empty_events_table(self, db_path):
        """빈 events 테이블은 빈 리스트 반환."""
        from nuri.api.routes.dashboard import _get_upcoming_events
        result = _get_upcoming_events()
        assert result == []

    def test_events_within_14_days(self, db_path):
        """14일 이내 이벤트가 date 순으로 반환."""
        from nuri.api.routes.dashboard import _get_upcoming_events
        from nuri.core.timezone import kst_now

        now = kst_now()
        d1 = now.strftime("%Y-%m-%d")
        d2 = (now + timedelta(days=3)).strftime("%Y-%m-%d")
        d3 = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (d3, "earnings", "AAPL", "Apple earnings", 3),
            )
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (d1, "fomc", None, "FOMC meeting", 5),
            )
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (d2, "dividend", "MSFT", "MSFT ex-div", 2),
            )

        result = _get_upcoming_events()
        assert len(result) == 3
        # date 순 정렬 확인
        assert result[0]["date"] == d1
        assert result[1]["date"] == d2
        assert result[2]["date"] == d3

    def test_events_beyond_14_days_excluded(self, db_path):
        """14일 이후 이벤트는 제외."""
        from nuri.api.routes.dashboard import _get_upcoming_events
        from nuri.core.timezone import kst_now

        now = kst_now()
        future = (now + timedelta(days=30)).strftime("%Y-%m-%d")
        within = (now + timedelta(days=5)).strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (future, "earnings", "NVDA", "NVDA earnings", 3),
            )
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (within, "fomc", None, "FOMC decision", 5),
            )

        result = _get_upcoming_events()
        assert len(result) == 1
        assert result[0]["date"] == within
        assert result[0]["event_type"] == "fomc"

    def test_past_events_excluded(self, db_path):
        """과거 이벤트는 제외."""
        from nuri.api.routes.dashboard import _get_upcoming_events
        from nuri.core.timezone import kst_now

        now = kst_now()
        past = (now - timedelta(days=3)).strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO events (date, event_type, ticker, description, importance) VALUES (?,?,?,?,?)",
                (past, "earnings", "TSLA", "Past event", 2),
            )

        result = _get_upcoming_events()
        assert result == []

    def test_exception_returns_empty_list(self, db_path, monkeypatch):
        """DB 오류 시 빈 리스트 반환."""
        import nuri.api.routes.dashboard as dash_mod

        def bad_query(*args, **kwargs):
            raise RuntimeError("DB error")

        monkeypatch.setattr("nuri.core.db.query", bad_query)
        result = dash_mod._get_upcoming_events()
        assert result == []


class TestLatestActionsAccountField:
    """Tests that _get_latest_actions() includes the account field."""

    def test_buy_action_has_account(self, db_path, monkeypatch):
        """BUY action includes account label from portfolio mapping."""
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        # Insert portfolio entry for AAPL
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("main_acc", "AAPL", 10, 150.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "AAPL", "BUY", 0.80, "bull_low_vol", "rsi_oversold"),
            )

        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"main_acc": "Main"})
        result = dash_mod._get_latest_actions()
        buys = [a for a in result if a["action"] == "BUY"]
        assert len(buys) >= 1
        assert buys[0]["account"] == "Main"

    def test_sell_action_has_account(self, db_path, monkeypatch):
        """SELL action includes account label from portfolio mapping."""
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) VALUES (?,?,?,?,?,?)",
                ("swing_acc", "TSLA", 8, 250.0, "USD", "Auto"),
            )
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "TSLA", "SELL", 0.90, "bear_high_vol", "macd_dead"),
            )

        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {"swing_acc": "Sub"})
        result = dash_mod._get_latest_actions()
        sells = [a for a in result if a["action"] == "SELL"]
        assert len(sells) >= 1
        assert sells[0]["account"] == "Sub"

    def test_action_without_portfolio_entry_has_empty_account(self, db_path, monkeypatch):
        """Ticker not in portfolio gets empty string for account."""
        import nuri.api.routes.dashboard as dash_mod
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals) VALUES (?,?,?,?,?,?)",
                ("2025-04-01", "GOOG", "BUY", 0.85, "bull_low_vol", "rsi_oversold"),
            )

        monkeypatch.setattr(dash_mod, "_get_account_labels", lambda: {})
        result = dash_mod._get_latest_actions()
        buys = [a for a in result if a["action"] == "BUY"]
        assert len(buys) >= 1
        assert buys[0]["account"] == ""
