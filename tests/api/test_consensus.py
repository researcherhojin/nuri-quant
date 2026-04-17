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


class TestConsensusScoringDetailExpose:
    """A-2b — /consensus endpoints 가 scoring_detail 을 노출. A-2c frontend 가
    10-agent contribution breakdown 을 시각화하려면 이 필드가 필수.

    STRATEGY §5.3.1 Gotcha-Test Pair — endpoint response 에서 scoring_detail 를
    실수로 제거하면 이 test fail. PR #364 로 backend persist 완성 상태를 API 가
    pass-through 하는지 lock-in.
    """

    def test_consensus_portfolio_includes_scoring_detail(self, client):
        """GET /api/consensus — 각 result 에 scoring_detail 포함 (None 허용)."""
        from unittest.mock import MagicMock, patch

        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="TSLA",
            final_action="BUY",
            final_confidence=70.0,
            agreement_rate=0.8,
            verdicts=[AgentVerdict("technical", "TSLA", "BUY", 70, "r")],
            dissent=[],
            reasoning="t",
            scoring_detail={
                "source": "consensus",
                "schema_version": 1,
                "final_action": "BUY",
                "basis_action": "BUY",
                "final_action_source": "weighted_sum",
                "contributions": [],
                "weights": {},
                "action_scores": {"BUY": 0.7, "SELL": 0.0, "HOLD": 0.3},
                "agreement_rate": 0.8,
                "risk_veto_fired": False,
                "divergence_flag": False,
                "penalty_applied": False,
                "pre_penalty_action": "",
            },
        )
        # 캐시 무효화 + analyze_portfolio mock
        with patch("nuri.api.routes.agents._cache", {"data": None, "ts": 0}):
            with patch("nuri.api.routes.agents.analyze_portfolio" if False else "nuri.trading.agents.consensus.analyze_portfolio", return_value=[mock_result]):
                with patch("nuri.quant.regime.classifier.classify_regime", return_value=MagicMock(regime="bull", trend="up", details={})):
                    r = client.get("/api/consensus")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        first = data["results"][0]
        assert "scoring_detail" in first, (
            "A-2b regression: /consensus response 에 scoring_detail 누락 — "
            "A-2c frontend 가 agent breakdown 을 consume 할 수 없음"
        )
        sd = first["scoring_detail"]
        assert sd is not None
        # Discriminator + basis_action + final_action_source pass-through
        assert sd["source"] == "consensus"
        assert sd["schema_version"] == 1
        assert sd["basis_action"] == "BUY"
        assert sd["final_action_source"] == "weighted_sum"

    def test_consensus_ticker_includes_scoring_detail(self, client):
        """GET /api/consensus/{ticker} — scoring_detail 포함."""
        from unittest.mock import patch

        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult

        mock_result = ConsensusResult(
            ticker="NVDA",
            final_action="HOLD",
            final_confidence=50.0,
            agreement_rate=0.5,
            verdicts=[AgentVerdict("technical", "NVDA", "HOLD", 50, "r")],
            dissent=[],
            reasoning="t",
            scoring_detail={
                "source": "consensus",
                "schema_version": 1,
                "final_action": "HOLD",
                "basis_action": "HOLD",
                "final_action_source": "weighted_sum",
                "contributions": [],
                "weights": {},
                "action_scores": {"BUY": 0.3, "SELL": 0.2, "HOLD": 0.5},
                "agreement_rate": 0.5,
                "risk_veto_fired": False,
                "divergence_flag": False,
                "penalty_applied": False,
                "pre_penalty_action": "",
            },
        )
        with patch("nuri.trading.agents.consensus.analyze_ticker", return_value=mock_result):
            r = client.get("/api/consensus/NVDA")
        assert r.status_code == 200
        data = r.json()
        assert "scoring_detail" in data
        assert data["scoring_detail"]["source"] == "consensus"
