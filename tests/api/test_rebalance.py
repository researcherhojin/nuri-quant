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
