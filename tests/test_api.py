"""FastAPI 엔드포인트 통합 테스트.

TestClient로 주요 엔드포인트의 응답 형식/상태 코드를 검증한다.
실제 DB 대신 tmp_path에 빈 DB를 생성하여 격리.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """테스트용 DB로 격리된 FastAPI TestClient."""
    from nuri.core.db import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # 모든 모듈이 참조하는 DB_PATH를 테스트 DB로 교체
    import nuri.core.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    from nuri.api.main import app
    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_redirects(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (301, 302, 307)


class TestPortfolio:
    def test_portfolio_empty(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "holdings" in data
        assert "count" in data
        assert data["count"] == 0

    def test_add_holding(self, client):
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
            "currency": "USD", "sector": "Tech",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 1

    def test_delete_holding(self, client):
        client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
        })
        r = client.delete("/api/portfolio/toss/AAPL")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 0

    def test_delete_nonexistent(self, client):
        """존재하지 않는 종목 삭제 → 404."""
        r = client.delete("/api/portfolio/test/XXXX")
        assert r.status_code == 404

    def test_delete_invalid_account(self, client):
        """유효하지 않은 계좌명 → 400."""
        r = client.delete("/api/portfolio/fake/XXXX")
        assert r.status_code == 400

    def test_risk_graceful(self, client):
        """빈 DB에서도 에러 대신 에러 dict 반환."""
        r = client.get("/api/risk")
        assert r.status_code == 200


class TestEngine:
    def test_gate_all(self, client):
        r = client.get("/api/gate")
        assert r.status_code == 200
        data = r.json()
        # 4개 phase가 있어야 함
        assert len(data) >= 1

    def test_gate_phase(self, client):
        r = client.get("/api/gate/collect")
        assert r.status_code == 200
        data = r.json()
        assert "phase" in data
        assert "passed" in data or "status" in data

    def test_conflicts(self, client):
        r = client.get("/api/conflicts")
        assert r.status_code == 200
        data = r.json()
        assert "conflicts" in data
        assert "count" in data

    def test_memory(self, client):
        r = client.get("/api/memory")
        assert r.status_code == 200
        data = r.json()
        assert "drifts" in data

    def test_memory_snapshot(self, client):
        r = client.post("/api/memory/snapshot")
        assert r.status_code == 200
        assert "saved" in r.json()


class TestSignals:
    def test_candidates_empty(self, client):
        r = client.get("/api/candidates")
        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert "count" in data

    def test_candidates_query_param(self, client):
        r = client.get("/api/candidates?days=10")
        assert r.status_code == 200

    def test_candidates_invalid_days(self, client):
        r = client.get("/api/candidates?days=100")
        assert r.status_code == 422  # validation error

    def test_scorecard_no_data(self, client):
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "scorecard" in data

    def test_cross_analysis(self, client):
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200


class TestRegime:
    def test_regime_no_data(self, client):
        """SPY 데이터 없으면 에러 dict 반환."""
        r = client.get("/api/regime")
        assert r.status_code == 200

    def test_macro(self, client):
        r = client.get("/api/macro")
        assert r.status_code == 200

    def test_strategy(self, client):
        r = client.get("/api/strategy")
        assert r.status_code == 200


class TestRebalance:
    def test_rebalance_rp(self, client):
        r = client.get("/api/rebalance?method=rp")
        assert r.status_code == 200

    def test_tracking(self, client):
        r = client.get("/api/tracking")
        assert r.status_code == 200


class TestTicker:
    def test_ticker_unknown(self, client):
        """존재하지 않는 종목도 200 + 빈 데이터 반환."""
        r = client.get("/api/ticker/FAKE")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"

    def test_ticker_prices(self, client):
        r = client.get("/api/ticker/FAKE/prices?days=30")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"
        assert "prices" in data


class TestSwing:
    def test_swing_positions(self, client):
        r = client.get("/api/swing/positions")
        assert r.status_code == 200
        data = r.json()
        assert "positions" in data
