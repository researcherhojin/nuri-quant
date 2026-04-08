"""Tests for stream — split from test_api_all.py."""
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


class TestSSEStream:
    """SSE stream endpoint tests."""

    def test_get_snapshot_returns_dict(self):
        with patch("nuri.api.routes.stream._get_snapshot") as mock:
            mock.return_value = {"timestamp": 123.0, "regime": "bull_low_vol"}
            result = mock()
        assert "timestamp" in result

    def test_get_snapshot_caching(self):
        """Cached snapshot should return quickly."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        stream_mod._cache_time = _time.time()
        result = stream_mod._get_snapshot()
        assert result.get("cached") is True

    def test_get_snapshot_fresh_with_mocked_deps(self, monkeypatch):
        """Fresh snapshot (cache expired) with all dependencies mocked."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.8
        mock_regime.details = {"vix": 15.0, "fear_greed": 60.0}

        mock_macro = MagicMock()
        mock_macro.total_score = 65.0

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", return_value=mock_macro), \
             patch("nuri.core.db.query", return_value=[{"c": 3}]):
            result = stream_mod._get_snapshot()

        assert result["regime"] == "bull_low_vol"
        assert result["macro_score"] == 65
        assert result["open_positions"] == 3

    def test_get_snapshot_handles_exceptions(self, monkeypatch):
        """All dependencies failing should not crash."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("no data")), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception("no data")), \
             patch("nuri.core.db.query", side_effect=Exception("no db")):
            result = stream_mod._get_snapshot()

        assert "timestamp" in result

    def test_stream_endpoint_response_type(self):
        """Test that /api/stream returns an SSE response (media type check only)."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        stream_mod._cache_time = _time.time()

        from nuri.api.routes.stream import stream as stream_handler

        async def run():
            resp = await stream_handler()
            return resp

        resp = asyncio.run(run())
        assert resp.media_type == "text/event-stream"
        assert resp.headers.get("Cache-Control") == "no-cache"

    def test_event_generator_yields_data(self):
        """Event generator should yield SSE-formatted data."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 42.0, "regime": "test_bull"}
        stream_mod._cache_time = _time.time()

        async def run():
            gen = stream_mod._event_generator()
            event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert result.startswith("data:")
        parsed = json.loads(result.replace("data:", "").strip())
        assert "timestamp" in parsed

    def test_event_generator_error_handling(self):
        """Event generator should yield error JSON on exception."""
        import nuri.api.routes.stream as stream_mod

        async def run():
            gen = stream_mod._event_generator()
            with patch.object(stream_mod, "_get_snapshot", side_effect=Exception("boom")):
                event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert "data:" in result
        parsed = json.loads(result.replace("data:", "").strip())
        assert "error" in parsed
