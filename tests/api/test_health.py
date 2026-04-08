"""Tests for health — split from test_api_all.py."""
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


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_redirects(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (301, 302, 307)


class TestSchedulerHealthEdge:
    def test_scheduler_health_stale(self, db_path, monkeypatch, tmp_path):
        """Scheduler health stale heartbeat."""
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        stale_time = (datetime.now() - timedelta(minutes=15)).isoformat()
        hb_path.write_text(stale_time)
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        c = TestClient(app)
        resp = c.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stale"

    def test_scheduler_health_error(self, db_path, monkeypatch, tmp_path):
        """Scheduler health with malformed file."""
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        hb_path.write_text("not-a-valid-iso-timestamp")
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)

        from nuri.api.main import app
        c = TestClient(app)
        resp = c.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
