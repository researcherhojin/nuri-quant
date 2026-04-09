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
