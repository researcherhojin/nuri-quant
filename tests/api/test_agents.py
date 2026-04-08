"""Tests for agents — split from test_api_all.py."""
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


class TestAgentsRoute:
    def test_get_consensus_cached(self, client, monkeypatch):
        """Cover cache hit path (line 17)."""
        import nuri.api.routes.agents as agents_mod
        agents_mod._cache["data"] = {"cached": True}
        agents_mod._cache["ts"] = 9999999999
        resp = client.get("/api/consensus")
        assert resp.json()["cached"] is True
        agents_mod._cache["data"] = None

    def test_get_consensus_regime_error(self, client, monkeypatch):
        """Cover regime_info exception path (lines 29-35)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio", lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            MagicMock(side_effect=Exception("no spy")),
        )
        import nuri.api.routes.agents as agents_mod
        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0
        resp = client.get("/api/consensus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] is None
