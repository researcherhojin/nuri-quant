"""Tests for consensus — split from test_api_all.py."""
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


class TestConsensusAPI:
    def test_consensus(self, client):
        r = client.get("/api/consensus")
        assert r.status_code == 200

    def test_consensus_ticker(self, client):
        r = client.get("/api/consensus/AAPL")
        assert r.status_code == 200
