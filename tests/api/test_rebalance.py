"""Tests for rebalance — split from test_api_all.py."""
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


class TestRebalance:
    def test_rebalance_rp(self, client):
        r = client.get("/api/rebalance?method=rp")
        assert r.status_code == 200

    def test_tracking(self, client):
        r = client.get("/api/tracking")
        assert r.status_code == 200


class TestRebalanceAdvisor:
    def test_rebalance_advisor(self, client):
        r = client.get("/api/rebalance-advisor")
        assert r.status_code == 200


class TestRebalanceAdvisorContract_R87:
    """Lock the response shape for the /api/rebalance-advisor endpoint (#87).

    The frontend `AdvisorReport.actions[].priority` and `.violation_type`
    fields drive the priority badge in `frontend/src/components/ui/client-table.tsx`
    (advisor variant). If those keys disappear from the response or get
    renamed, the dashboard would silently render badge-less rows. These
    tests are the contract guard.
    """

    def _stub_advisor(self, monkeypatch, actions=None):
        """Patch generate_advisor_report at the import site used by the route."""
        from nuri.api.routes import targets as targets_mod

        if actions is None:
            actions = [
                {
                    "ticker": "TSLL",
                    "violation_type": "leverage_etf",
                    "priority": 1,
                    "current_value": 0.0,
                    "limit_value": 0,
                    "severity": "critical",
                    "action": "SELL_ALL",
                    "sell_shares": 10,
                    "sell_value_usd": 200.0,
                    "reason": "leveraged ETF banned",
                    "cumulative_recovery_usd": 200.0,
                },
                {
                    "ticker": "AAA",
                    "violation_type": "stop_loss_exceeded",
                    "priority": 2,
                    "current_value": -12.5,
                    "limit_value": -7,
                    "severity": "critical",
                    "action": "SELL_ALL",
                    "sell_shares": 5,
                    "sell_value_usd": 500.0,
                    "reason": "stop loss exceeded",
                    "cumulative_recovery_usd": 700.0,
                },
                {
                    "ticker": "BBB",
                    "violation_type": "position_limit_exceeded",
                    "priority": 4,
                    "current_value": 22.0,
                    "limit_value": 0.15,
                    "severity": "high",
                    "action": "REDUCE",
                    "sell_shares": 3,
                    "sell_value_usd": 300.0,
                    "reason": "position limit exceeded",
                    "cumulative_recovery_usd": 1000.0,
                },
            ]

        def _stub():
            return {
                "actions": actions,
                "total_violations": len(actions),
                "total_recovery_usd": sum(a["sell_value_usd"] for a in actions),
                "violations_by_type": {a["violation_type"]: 1 for a in actions},
                "violations_by_severity": {a["severity"]: 1 for a in actions},
                "has_critical": any(a["severity"] == "critical" for a in actions),
            }

        # Module-level import in the route — patch at the source.
        import nuri.analysis.rebalance_advisor as advisor_mod
        monkeypatch.setattr(advisor_mod, "generate_advisor_report", _stub)
        return targets_mod

    def test_priority_field_present_in_each_action(self, client, monkeypatch):
        self._stub_advisor(monkeypatch)
        resp = client.get("/api/rebalance-advisor")
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert len(data["actions"]) > 0

        for action in data["actions"]:
            assert "priority" in action, f"missing priority field in {action}"
            assert isinstance(action["priority"], int)
            assert 1 <= action["priority"] <= 10

    def test_violation_type_field_present(self, client, monkeypatch):
        self._stub_advisor(monkeypatch)
        resp = client.get("/api/rebalance-advisor")
        data = resp.json()
        for action in data["actions"]:
            assert "violation_type" in action
            assert isinstance(action["violation_type"], str)
            assert action["violation_type"]

    def test_actions_are_sorted_by_priority_ascending(self, client, monkeypatch):
        """1 = highest priority (sell first); response must be ordered."""
        self._stub_advisor(monkeypatch)
        resp = client.get("/api/rebalance-advisor")
        priorities = [a["priority"] for a in resp.json()["actions"]]
        assert priorities == sorted(priorities), (
            f"actions not sorted by priority: {priorities}"
        )

    def test_priority_one_is_leverage_etf(self, client, monkeypatch):
        """The most critical category (leverage_etf) gets priority 1."""
        self._stub_advisor(monkeypatch)
        resp = client.get("/api/rebalance-advisor")
        first = resp.json()["actions"][0]
        assert first["priority"] == 1
        assert first["violation_type"] == "leverage_etf"

    def test_response_shape_matches_frontend_advisor_report(self, client, monkeypatch):
        """Top-level keys consumed by frontend/src/app/advisor/page.tsx."""
        self._stub_advisor(monkeypatch)
        data = client.get("/api/rebalance-advisor").json()
        for key in (
            "actions",
            "total_violations",
            "total_recovery_usd",
            "violations_by_type",
            "violations_by_severity",
            "has_critical",
        ):
            assert key in data, f"missing top-level key: {key}"


class TestRebalanceRoute:
    def test_get_rebalance_error(self, client, monkeypatch):
        """Cover exception path (lines 20-21)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.rebalance.regime_aware_rebalance",
            MagicMock(side_effect=Exception("no data")),
        )
        resp = client.get("/api/rebalance")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
