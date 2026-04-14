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
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda **kw: [],
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

    def test_get_consensus_exposes_divergence_fields(self, client, monkeypatch):
        """P1 A2: divergence_flag/reason 이 /api/consensus 응답에 포함되어야 한다."""
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="JKHY",
            final_action="BUY",
            final_confidence=42.4,
            agreement_rate=0.3,
            verdicts=[],
            dissent=["technical(SELL, 100): 데드크로스"],
            reasoning="mock",
            divergence_flag=True,
            divergence_reason="기술지표 반대: TechnicalAgent 가 SELL",
        )
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda **kw: [mock_result],
        )
        import nuri.api.routes.agents as agents_mod

        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0
        resp = client.get("/api/consensus")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        row = data["results"][0]
        assert row["divergence_flag"] is True
        assert "기술지표 반대" in row["divergence_reason"]

    def test_get_consensus_ticker_exposes_divergence_fields(self, client, monkeypatch):
        """P1 A2: /api/consensus/{ticker} 단일 엔드포인트도 divergence 필드 노출."""
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="AAPL",
            final_action="HOLD",
            final_confidence=50.0,
            agreement_rate=0.5,
            verdicts=[],
            dissent=[],
            reasoning="mock",
            divergence_flag=False,
            divergence_reason="",
        )
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_ticker",
            lambda *a, **kw: mock_result,
        )
        resp = client.get("/api/consensus/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["divergence_flag"] is False
        assert data["divergence_reason"] == ""
