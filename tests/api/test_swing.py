"""Tests for swing — split from test_api_all.py."""
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


class TestSwing:
    def test_swing_positions(self, client):
        r = client.get("/api/swing/positions")
        assert r.status_code == 200
        data = r.json()
        assert "positions" in data

    def test_swing_entries(self, client):
        r = client.get("/api/swing/entries")
        assert r.status_code == 200

    def test_scan(self, client):
        r = client.get("/api/scan")
        assert r.status_code == 200
