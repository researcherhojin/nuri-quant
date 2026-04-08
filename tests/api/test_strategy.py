"""Tests for strategy — split from test_api_all.py."""
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


class TestStrategyAPI:
    def test_strategy_status(self, client):
        r = client.get("/api/strategy/status")
        assert r.status_code == 200

    def test_backtest(self, client):
        r = client.get("/api/backtest")
        assert r.status_code == 200
