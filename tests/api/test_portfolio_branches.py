"""portfolio.py API branch coverage — Issue #616 Phase 3-C4.

| line | branch / stmt | trigger |
|---|---|---|
| 100→105 | `if v is not None:` False (validate_quantity) | quantity=None |
| 110→115 | `if v is not None:` False (validate_avg_price) | avg_price=None |
| 393→395 | `if acct not in accounts:` False | YAML export 다중 holding 같은 account |
| 470-475 | numpy → Python conversion stmts | `/api/risk` 정상 path |
| 477-480 | `except Exception:` 흡수 | analyze_risk raise |
"""

from __future__ import annotations


class TestHoldingUpdateValidatorsNonePath:
    def test_quantity_none_skips_validation(self):
        """100→105: quantity=None → if 블록 skip → 그대로 None 반환."""
        from nuri.api.routes.portfolio import HoldingUpdate

        # quantity 누락 → validator 가 None 통과시켜야 함.
        u = HoldingUpdate(quantity=None, avg_price=100.0)
        assert u.quantity is None

    def test_avg_price_none_skips_validation(self):
        """110→115: avg_price=None 명시 → validator 호출 → if 블록 skip."""
        from nuri.api.routes.portfolio import HoldingUpdate

        u = HoldingUpdate(quantity=10.0, avg_price=None)
        assert u.avg_price is None


class TestExportYamlDuplicateAccount:
    def test_yaml_export_groups_by_account(self, tmp_path, monkeypatch):
        """393→395: 같은 account 의 두 번째 holding → if False → 기존 dict reuse."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db, upsert_portfolio

        p = tmp_path / "exp.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)

        # 같은 account 'main' 의 종목 2개 → 두번째 iter 에서 393 False.
        upsert_portfolio(
            [
                {
                    "account": "main",
                    "ticker": "AAA",
                    "quantity": 10,
                    "avg_price": 100,
                    "currency": "USD",
                    "sector": "Tech",
                },
                {
                    "account": "main",
                    "ticker": "BBB",
                    "quantity": 5,
                    "avg_price": 200,
                    "currency": "USD",
                    "sector": "Finance",
                },
            ],
            p,
        )

        from fastapi.testclient import TestClient

        from nuri.api.main import app

        client = TestClient(app)
        resp = client.get("/api/portfolio/export?format=yaml")
        assert resp.status_code == 200
        body = resp.text
        assert "AAA" in body
        assert "BBB" in body


class TestRiskEndpoint:
    def test_risk_endpoint_normal_path(self, monkeypatch):
        """470-475: analyze_risk → numpy/dict mix → Python 변환 path 모두 통과."""
        import numpy as np
        from fastapi.testclient import TestClient

        from nuri.api.main import app

        # 다양한 type 의 metrics: numpy scalar, list, dict, str, int, float, bool, None.
        fake_metrics = {
            "max_drawdown": np.float64(-0.15),  # has .item() → 471
            "var_95": -0.05,  # plain float → 472-473
            "sectors": ["tech", "finance"],  # list → 472-473
            "history": {"y2024": 0.1},  # dict → 472-473
            "name": "growth",  # str
            "count": 10,  # int
            "active": True,  # bool
            "trailing": None,  # None
            "custom_obj": object(),  # other → str() at 475
        }
        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", lambda: fake_metrics)

        client = TestClient(app)
        resp = client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["max_drawdown"], float)
        assert data["var_95"] == -0.05
        assert "history" in data

    def test_risk_endpoint_exception_returns_error(self, monkeypatch):
        """477-480: analyze_risk raise → except 흡수 → {error: ...} 반환."""
        from fastapi.testclient import TestClient

        from nuri.api.main import app

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", _raise)

        client = TestClient(app)
        resp = client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"error": "internal error"}
