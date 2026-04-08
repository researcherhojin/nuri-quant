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
