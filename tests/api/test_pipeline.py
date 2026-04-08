"""Tests for pipeline — split from test_api_all.py."""
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


class TestPipelineAPI:
    """Cover lines 21-22, 90-93, 108-110, 115, 117-129."""

    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_scheduler_health_no_file(self, _client, monkeypatch, tmp_path):
        """Scheduler health when no heartbeat file (lines 21-22)."""
        import nuri.api.routes.pipeline as pipeline_mod
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", tmp_path / "nonexistent")
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    def test_scheduler_health_valid(self, _client, monkeypatch, tmp_path):
        """Scheduler health with valid heartbeat."""
        import nuri.api.routes.pipeline as pipeline_mod
        hb_path = tmp_path / ".scheduler_heartbeat"
        from nuri.core.timezone import kst_now
        hb_path.write_text(kst_now().replace(tzinfo=None).isoformat())
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_pipeline_status(self, _client):
        """Pipeline status endpoint."""
        resp = _client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data

    def test_pipeline_timeline(self, _client):
        """Pipeline timeline endpoint."""
        resp = _client.get("/api/pipeline/timeline?limit=10")
        assert resp.status_code == 200

    def test_pipeline_timeline_invalid_step(self, _client):
        """Pipeline timeline with invalid step."""
        resp = _client.get("/api/pipeline/timeline?step=invalid")
        assert resp.status_code == 400

    def test_run_step_invalid(self, _client):
        """Run invalid step."""
        resp = _client.post("/api/pipeline/invalid_step/run")
        assert resp.status_code == 400

    def test_run_step_collect(self, _client):
        """Run collect step (lines 108-110)."""
        resp = _client.post("/api/pipeline/collect/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "not_implemented" in data.get("detail", "")

    def test_run_step_validate(self, _client, monkeypatch):
        """Run validate step (lines 108-110)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: [{"signal": "test"}],
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_run_step_classify(self, _client, monkeypatch):
        """Run classify step (lines 115)."""
        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            trend: str = "bullish"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: MockRegime(),
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "bull_low_vol" in data.get("detail", "")

    def test_run_step_classify_none(self, _client, monkeypatch):
        """Run classify step returns None (line 116)."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: None,
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown" in data.get("detail", "")

    def test_run_step_diagnose(self, _client, monkeypatch):
        """Run diagnose step (lines 117-120)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda: ["r1", "r2"],
        )
        resp = _client.post("/api/pipeline/diagnose/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "2 tickers" in data.get("detail", "")

    def test_run_step_recommend(self, _client, monkeypatch):
        """Run recommend step (lines 121-124)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda: ["c1"],
        )
        resp = _client.post("/api/pipeline/recommend/run")
        assert resp.status_code == 200

    def test_run_step_track(self, _client, monkeypatch):
        """Run track step (lines 125-128)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.tracker.track_outcomes",
            lambda: 5,
        )
        resp = _client.post("/api/pipeline/track/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "5 recommendations" in data.get("detail", "")

    def test_run_step_exception(self, _client, monkeypatch):
        """Run step that throws exception (lines 90-93)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    def test_freshness_endpoint(self, _client):
        """Freshness endpoint."""
        resp = _client.get("/api/freshness")
        assert resp.status_code == 200
