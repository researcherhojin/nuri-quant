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
        upsert_decision(
            {
                "date": "2026-04-10",
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
            },
            self._db,
        )
        upsert_decision(
            {
                "date": "2026-04-10",
                "ticker": "TSLA",
                "action": "SELL",
                "confidence": 60.0,
            },
            self._db,
        )

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
        dec_id = upsert_decision(
            {
                "date": "2026-04-10",
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
            },
            self._db,
        )
        upsert_decision_evidence(
            dec_id,
            [
                {
                    "source_type": "agent",
                    "source_key": "technical",
                    "action": "BUY",
                    "confidence": 80.0,
                    "detail": '{"rsi": 28}',
                },
            ],
            self._db,
        )

        r = _client.get(f"/api/decisions/{dec_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "NVDA"
        assert len(data["evidence"]) == 1

    def _seed_ledger(self, rec_id, date, ticker, outcomes=()):
        """recommendations + agent_decisions 미러 + decision_outcomes (window, realized_return, notes)."""
        from nuri.core.db import get_db

        with get_db(self._db) as conn:
            conn.execute(
                "INSERT INTO recommendations (id, date, ticker, action, confidence, signals) "
                "VALUES (?, ?, ?, 'BUY', 80.0, 'golden_cross')",
                (rec_id, date, ticker),
            )
            conn.execute(
                """INSERT INTO agent_decisions
                   (decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status)
                   VALUES (?, ?, ?, 'BUY', 0.8, '{}', '{}', 'emitted')""",
                (f"rec_{rec_id}", ticker, date),
            )
            for window, realized, notes in outcomes:
                conn.execute(
                    """INSERT INTO decision_outcomes
                       (decision_id, observation_window, tracked_as_of_date, realized_return,
                        benchmark_return, alpha, hit_threshold, hypothesis_validation, notes)
                       VALUES (?, ?, '2026-08-20', ?, ?, ?, 0, ?, ?)""",
                    (
                        f"rec_{rec_id}",
                        window,
                        realized,
                        None if realized is None else 0.01,
                        None if realized is None else realized - 0.01,
                        "insufficient_data" if realized is None else "pass",
                        notes,
                    ),
                )
            conn.commit()

    def test_detail_joins_the_measurement_ledger(self, _client):
        """#1909: 같은 (date, ticker) 의 추천 → rec_{id} 원장이 상세 응답에 붙는다."""
        dec_id = upsert_decision(
            {"date": "2026-07-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, self._db
        )
        self._seed_ledger(7, "2026-07-10", "NVDA", outcomes=[(7, 0.03, None), (30, None, "lookahead guard")])

        data = _client.get(f"/api/decisions/{dec_id}").json()
        assert data["ticker"] == "NVDA" and data["evidence"] == []  # 기존 필드는 그대로
        assert data["signals"] == "golden_cross"
        assert [(o["observation_window"], o["pending"]) for o in data["outcomes"]] == [(7, False), (30, True)]
        assert data["outcomes"][0]["alpha"] == pytest.approx(0.02)
        assert data["measurement"] == {
            "sample": "judgment",
            "reasons": [],
            "benchmark": "SPY",
            "primary_window_days": 30,
            "declared_date": "2026-07-08",
        }

    def test_a_window_without_return_and_without_lookahead_is_not_pending(self, _client):
        """`/api/alpha` 와 같은 판별 — 미도래(lookahead)만 대기, 나머지는 가격 결측."""
        dec_id = upsert_decision(
            {"date": "2026-07-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, self._db
        )
        self._seed_ledger(8, "2026-07-10", "NVDA", outcomes=[(14, None, "price missing")])

        assert _client.get(f"/api/decisions/{dec_id}").json()["outcomes"][0]["pending"] is False

    def test_detail_without_a_recommendation_is_untracked(self, _client):
        dec_id = upsert_decision(
            {"date": "2026-04-10", "ticker": "NVDA", "action": "HOLD", "confidence": 50.0}, self._db
        )

        data = _client.get(f"/api/decisions/{dec_id}").json()
        assert data["signals"] is None
        assert data["outcomes"] == []
        assert data["measurement"]["sample"] == "untracked"

    def test_get_decision_not_found(self, _client):
        r = _client.get("/api/decisions/9999")
        assert r.status_code == 404
