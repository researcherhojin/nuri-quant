"""Tests for engine — split from test_api_all.py."""
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


class TestEngine:
    def test_gate_all(self, client):
        r = client.get("/api/gate")
        assert r.status_code == 200
        data = r.json()
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


class TestCertificationsAPI:
    """V1 — E4-0a certifications 테이블을 읽어오는 API.

    Dashboard V2 timeline + CLI siege_history.py 와 같은 observation loop 기반.
    Read-only, auth 불필요.
    """

    def _insert_cert(self, **overrides):
        """certifications 테이블에 row 삽입 helper — client fixture 의 DB_PATH 사용."""
        import nuri.core.db as db_mod
        from nuri.core.db import get_db

        base = {
            "timestamp": "2026-04-20T10:00:00+09:00",
            "certified": 1,
            "score": 85.0,
            "total_conditions": 15,
            "passed": 13,
            "failed": 0,
            "warnings": 2,
            "regime": "sideways_low_vol",
            "portfolio_hash": "abc123",
            "caller": "cli",
            "conditions_json": '[{"id":"position_limit","passed":true,"severity":"error"}]',
        }
        base.update(overrides)
        with get_db(db_mod.DB_PATH) as conn:
            cols = ", ".join(base.keys())
            placeholders = ", ".join(["?"] * len(base))
            conn.execute(f"INSERT INTO certifications ({cols}) VALUES ({placeholders})", list(base.values()))

    def test_list_empty(self, client):
        """빈 DB → items=[] + total_in_db=0."""
        r = client.get("/api/certifications")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["count"] == 0
        assert data["total_in_db"] == 0

    def test_list_returns_recent_rows_desc(self, client):
        """여러 row 삽입 → 최신순 (id DESC) 정렬."""
        for i in range(3):
            self._insert_cert(timestamp=f"2026-04-20T10:0{i}:00+09:00")

        r = client.get("/api/certifications")
        data = r.json()
        assert data["count"] == 3
        assert data["total_in_db"] == 3
        # id DESC → 최근 timestamp 가 먼저
        assert data["items"][0]["timestamp"] == "2026-04-20T10:02:00+09:00"
        assert data["items"][-1]["timestamp"] == "2026-04-20T10:00:00+09:00"

    def test_list_filter_by_caller(self, client):
        """caller 필터 — cli 만 반환."""
        self._insert_cert(caller="cli", timestamp="2026-04-20T10:00:00+09:00")
        self._insert_cert(caller="api:actions:health", timestamp="2026-04-20T10:01:00+09:00")
        self._insert_cert(caller="cli", timestamp="2026-04-20T10:02:00+09:00")

        r = client.get("/api/certifications?caller=cli")
        data = r.json()
        assert data["count"] == 2
        assert all(item["caller"] == "cli" for item in data["items"])

    def test_list_filter_by_regime(self, client):
        """regime 필터."""
        self._insert_cert(regime="bull_low_vol", timestamp="2026-04-20T10:00:00+09:00")
        self._insert_cert(regime="bear_high_vol", timestamp="2026-04-20T10:01:00+09:00")

        r = client.get("/api/certifications?regime=bull_low_vol")
        data = r.json()
        assert data["count"] == 1
        assert data["items"][0]["regime"] == "bull_low_vol"

    def test_list_limit_validation(self, client):
        """limit 범위 — 1 ≤ limit ≤ 500. 벗어나면 422 validation."""
        r = client.get("/api/certifications?limit=0")
        assert r.status_code == 422
        r = client.get("/api/certifications?limit=501")
        assert r.status_code == 422

    def test_list_conditions_parsed_as_list(self, client):
        """conditions_json 이 parsed list 로 노출됨 (string 아닌 list)."""
        self._insert_cert(
            conditions_json='[{"id":"a","passed":true,"severity":"error"},{"id":"b","passed":false,"severity":"warning"}]',
        )
        r = client.get("/api/certifications")
        data = r.json()
        item = data["items"][0]
        assert isinstance(item["conditions"], list)
        assert len(item["conditions"]) == 2
        assert item["conditions"][0]["id"] == "a"

    def test_summary_empty(self, client):
        """빈 DB summary → null values."""
        r = client.get("/api/certifications/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["certified_rate"] is None
        assert data["avg_score"] is None
        assert data["latest"] is None

    def test_summary_certified_rate(self, client):
        """certified_rate 계산 — 2 PASS / 4 total = 50%."""
        from nuri.core.timezone import kst_now

        now_iso = kst_now().isoformat()
        self._insert_cert(certified=1, score=90.0, timestamp=now_iso)
        self._insert_cert(certified=1, score=85.0, timestamp=now_iso)
        self._insert_cert(certified=0, score=50.0, timestamp=now_iso)
        self._insert_cert(certified=0, score=45.0, timestamp=now_iso)

        r = client.get("/api/certifications/summary")
        data = r.json()
        assert data["count"] == 4
        assert data["certified_rate"] == 50.0
        assert data["avg_score"] == 67.5
        assert data["latest"] is not None

    def test_summary_by_caller_distribution(self, client):
        """by_caller dict — caller 별 count."""
        from nuri.core.timezone import kst_now

        now_iso = kst_now().isoformat()
        self._insert_cert(caller="cli", timestamp=now_iso)
        self._insert_cert(caller="cli", timestamp=now_iso)
        self._insert_cert(caller="api:actions:health", timestamp=now_iso)

        r = client.get("/api/certifications/summary")
        data = r.json()
        assert data["by_caller"] == {"cli": 2, "api:actions:health": 1}

    def test_detail_by_id(self, client):
        """GET /certifications/{id} — 단일 row detail."""
        self._insert_cert(score=77.7)
        # row id 는 1부터 시작 (tmp_path fixture 에서 fresh DB)
        r = client.get("/api/certifications/1")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == 1
        assert data["score"] == 77.7
        assert isinstance(data["conditions"], list)

    def test_detail_404(self, client):
        """존재하지 않는 id → 404."""
        r = client.get("/api/certifications/99999")
        assert r.status_code == 404
        assert "없음" in r.json()["detail"]
