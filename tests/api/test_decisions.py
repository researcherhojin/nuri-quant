"""Decision Intelligence API 테스트."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nuri.core.db import init_db, upsert_decision, upsert_decision_evidence


class TestDecisionsAPI:
    @pytest.fixture()
    def _client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod
        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")
        self._db = db
        from nuri.api.main import app
        return TestClient(app)

    def test_list_decisions_empty(self, _client):
        r = _client.get("/api/decisions")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["summary"]["total"] == 0

    def test_list_decisions_with_data(self, _client):
        upsert_decision({
            "date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0,
        }, self._db)
        upsert_decision({
            "date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0,
        }, self._db)

        r = _client.get("/api/decisions")
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_filter_by_ticker(self, _client):
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, self._db)
        upsert_decision({"date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0}, self._db)

        r = _client.get("/api/decisions?ticker=NVDA")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["decisions"][0]["ticker"] == "NVDA"

    def test_filter_by_outcome(self, _client):
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, self._db)

        r = _client.get("/api/decisions?outcome=pending")
        assert r.json()["count"] == 1

        r = _client.get("/api/decisions?outcome=success")
        assert r.json()["count"] == 0

    def test_get_decision_detail(self, _client):
        dec_id = upsert_decision({
            "date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0,
        }, self._db)
        upsert_decision_evidence(dec_id, [
            {"source_type": "agent", "source_key": "technical", "action": "BUY",
             "confidence": 80.0, "detail": '{"rsi": 28}'},
        ], self._db)

        r = _client.get(f"/api/decisions/{dec_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "NVDA"
        assert len(data["evidence"]) == 1

    def test_get_decision_not_found(self, _client):
        r = _client.get("/api/decisions/9999")
        assert r.status_code == 404
