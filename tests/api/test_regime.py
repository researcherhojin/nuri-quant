"""Tests for regime — split from test_api_all.py."""
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


class TestRegimeAPI:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app
        return TestClient(app)

    def test_get_regime_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: None)
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        assert resp.json()["error"] == "SPY 데이터 부족"

    def test_get_regime_success(self, _client, monkeypatch):
        @dataclass
        class FakeRegimeState:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.85
            details: dict = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {"vix": 15.0, "fear_greed": 60}

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: FakeRegimeState())
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_macro(self, _client, monkeypatch):
        @dataclass
        class FakeMacro:
            total_score: float = 65.0
            interpretation: str = "Positive"
            details: dict = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {}

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda: FakeMacro())
        resp = _client.get("/api/macro")
        assert resp.status_code == 200

    def test_get_strategy_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: None)
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_get_strategy_success(self, _client, monkeypatch):
        class FakeStrategy:
            regime = "bull_low_vol"
            macro_interpretation = "Positive"
            position_sizing = "aggressive"
            recommended_signals = ["rsi_oversold", "macd_golden"]
            avoid_signals = ["sma_dead"]
            sector_preference = ["Technology"]
            signal_regime_stats = {}
            notes = "Test note"

        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: FakeStrategy())
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_report_context(self, _client, monkeypatch):
        class FakeContext:
            gate_score = 80
            known_tickers = {"AAPL", "MSFT"}

        monkeypatch.setattr("nuri.llm.report.gather_context", lambda: FakeContext())
        monkeypatch.setattr("nuri.llm.report.format_prompt", lambda ctx: "test prompt")
        resp = _client.get("/api/report/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gate_score"] == 80
