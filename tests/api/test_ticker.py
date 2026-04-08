"""Tests for ticker — split from test_api_all.py."""
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


class TestTicker:
    def test_ticker_unknown(self, client):
        """존재하지 않는 종목도 200 + 빈 데이터 반환."""
        r = client.get("/api/ticker/FAKE")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"

    def test_ticker_prices(self, client):
        r = client.get("/api/ticker/FAKE/prices?days=30")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "FAKE"
        assert "prices" in data
