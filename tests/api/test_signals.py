"""Tests for signals — split from test_api_all.py."""
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


class TestSignals:
    def test_candidates_empty(self, client):
        r = client.get("/api/candidates")
        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert "count" in data

    def test_candidates_query_param(self, client):
        r = client.get("/api/candidates?days=10")
        assert r.status_code == 200

    def test_candidates_invalid_days(self, client):
        r = client.get("/api/candidates?days=100")
        assert r.status_code == 422

    def test_scorecard_no_data(self, client):
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "scorecard" in data

    def test_cross_analysis(self, client):
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200
