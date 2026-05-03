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

    def test_market_context_macro_exception(self, client, monkeypatch):
        """compute_macro_score raise → macro_score=None (lines 86-87)."""

        def boom():
            raise RuntimeError("macro down")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", boom)
        r = client.get("/api/tickers/market-context")
        assert r.status_code == 200
        assert r.json()["macro_score"] is None

    def test_market_context_classify_returns_regime(self, client, monkeypatch):
        """classify_regime returns truthy → trend set (line 95)."""

        class FakeRegime:
            trend = "bull"

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: FakeRegime(),
        )
        r = client.get("/api/tickers/market-context")
        assert r.status_code == 200
        assert r.json()["trend"] == "bull"

    def test_market_context_classify_exception(self, client, monkeypatch):
        """classify_regime raise → trend=None (lines 96-97)."""

        def boom():
            raise RuntimeError("spy stale")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", boom)
        r = client.get("/api/tickers/market-context")
        assert r.status_code == 200
        assert r.json()["trend"] is None

    def test_ticker_consensus_exception(self, client, monkeypatch):
        """analyze_ticker raise → consensus.error 필드 (lines 164-165)."""

        def boom(t):
            raise RuntimeError("consensus down")

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", boom)
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data["consensus"]

    def test_ticker_candidates_exception(self, client, monkeypatch):
        """screen_candidates raise → signals=[] (lines 209-210)."""

        def boom(**kw):
            raise RuntimeError("scan fail")

        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", boom)
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        data = r.json()
        assert data["signals"] == []
