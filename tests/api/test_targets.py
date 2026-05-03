"""Tests for targets — split from test_api_all.py."""

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


class TestTargetsAPI:
    def test_targets(self, client):
        r = client.get("/api/targets")
        assert r.status_code == 200

    def test_targets_ticker(self, client):
        r = client.get("/api/targets/AAPL")
        assert r.status_code == 200


class TestTargetsCoverageGaps:
    """Lock-tests for missing branches (lines 22-23, 26-27, 29-33, 50-52, 64-88)."""

    def test_targets_with_signals(self, client, monkeypatch):
        """tp/ts signals get attached to targets."""
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.calculate_portfolio_targets",
            lambda: [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.check_take_profit_signals",
            lambda: [{"ticker": "AAPL", "level": "TP1", "sell_pct": 0.5}],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.check_trailing_stop_signals",
            lambda: [{"ticker": "MSFT"}],
        )
        r = client.get("/api/targets")
        assert r.status_code == 200
        data = r.json()
        m = {t["ticker"]: t for t in data["targets"]}
        assert m["AAPL"]["take_profit_triggered"] == "TP1"
        assert m["AAPL"]["take_profit_sell_pct"] == 0.5
        assert m["MSFT"]["trailing_stop_triggered"] is True

    def test_targets_signal_failures_swallowed(self, client, monkeypatch):
        """tp/ts signal exceptions don't block response (lines 22-23, 26-27)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.calculate_portfolio_targets",
            lambda: [{"ticker": "AAPL"}],
        )

        def boom_tp():
            raise RuntimeError("tp fail")

        def boom_ts():
            raise RuntimeError("ts fail")

        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.check_take_profit_signals",
            boom_tp,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.price_targets.check_trailing_stop_signals",
            boom_ts,
        )
        r = client.get("/api/targets")
        assert r.status_code == 200
        data = r.json()
        assert data["targets"][0]["take_profit_triggered"] is None
        assert data["targets"][0]["trailing_stop_triggered"] is False

    def test_rebalance_advisor_endpoint(self, client, monkeypatch):
        """/rebalance-advisor (lines 50-52)."""
        monkeypatch.setattr(
            "nuri.analysis.rebalance_advisor.generate_advisor_report",
            lambda: {"violations": []},
        )
        r = client.get("/api/rebalance-advisor")
        assert r.status_code == 200
        assert r.json() == {"violations": []}

    def test_certify_endpoint(self, client, monkeypatch):
        """/certify (lines 64-88)."""
        from dataclasses import dataclass, field

        @dataclass
        class FakeCondition:
            name: str = "g1"
            status: str = "PASS"

        @dataclass
        class FakeCert:
            certified: bool = True
            score: float = 90.0
            passed: int = 9
            failed: int = 1
            warnings: int = 0
            total_conditions: int = 10
            timestamp: str = "2026-05-04T00:00:00"
            conditions: list = field(default_factory=lambda: [FakeCondition()])

        monkeypatch.setattr(
            "nuri.trading.engine.certification.certify",
            lambda **kw: FakeCert(),
        )
        # Ensure cache is cleared
        from nuri.api.routes import targets as targets_mod

        targets_mod._certify_cache["data"] = None
        targets_mod._certify_cache["ts"] = 0
        r = client.get("/api/certify")
        assert r.status_code == 200
        data = r.json()
        assert data["certified"] is True
        assert data["score"] == 90.0
        assert data["total"] == 10

    def test_certify_cache_hit(self, client, monkeypatch):
        """certify cache 5분 (line 68-69)."""
        from nuri.api.routes import targets as targets_mod

        targets_mod._certify_cache["data"] = {"cached": True}
        targets_mod._certify_cache["ts"] = 9_999_999_999
        r = client.get("/api/certify")
        assert r.status_code == 200
        assert r.json() == {"cached": True}
        targets_mod._certify_cache["data"] = None


class TestRemediateAPI:
    def test_remediate_returns_200(self, client):
        r = client.get("/api/remediate")
        assert r.status_code == 200
        data = r.json()
        assert "certified" in data
        assert "actions" in data
        assert "post_remediation_pass" in data

    def test_remediate_structure(self, client):
        r = client.get("/api/remediate")
        data = r.json()
        assert isinstance(data["failed_gates"], list)
        assert isinstance(data["warning_gates"], list)
        assert isinstance(data["actions"], list)
        assert isinstance(data["score"], (int, float))
