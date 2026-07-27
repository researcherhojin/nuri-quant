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

    def test_get_consensus_with_regime(self, client, monkeypatch):
        """classify_regime 가 truthy → regime_info dict 채워짐 (line 37)."""
        from dataclasses import dataclass, field

        @dataclass
        class FakeRegime:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            details: dict = field(default_factory=lambda: {"vix": 15.0, "fear_greed": 60})

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: FakeRegime(),
        )
        import nuri.api.routes.agents as agents_mod

        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0
        resp = client.get("/api/consensus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"]["regime"] == "bull_low_vol"
        assert data["regime"]["vix"] == 15.0

    def test_get_consensus_regime_no_details(self, client, monkeypatch):
        """regime.details=None → vix/fear_greed=None (line 40 ternary)."""
        from dataclasses import dataclass

        @dataclass
        class FakeRegime:
            regime: str = "bull"
            trend: str = "bull"
            details: dict | None = None

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda **kw: [],
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: FakeRegime(),
        )
        import nuri.api.routes.agents as agents_mod

        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0
        resp = client.get("/api/consensus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"]["vix"] is None
        assert data["regime"]["fear_greed"] is None

    def test_stream_consensus_ticker(self, client, monkeypatch):
        """SSE stream endpoint (lines 97-128)."""
        import time
        from dataclasses import dataclass

        @dataclass
        class Evt:
            ticker: str = "AAPL"
            text: str = "step"

        def fake_stream(ticker):
            # Sleep to force asyncio.sleep loop hit (line 112)
            time.sleep(0.1)
            yield ("agent_start", Evt())
            time.sleep(0.1)
            yield ("agent_finish", Evt(text="done"))

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.stream_analyze_ticker",
            fake_stream,
        )
        with client.stream("GET", "/api/consensus/AAPL/stream") as resp:
            assert resp.status_code == 200
            chunks = b"".join(resp.iter_bytes())
        body = chunks.decode("utf-8")
        assert "agent_start" in body
        assert "done" in body

    def test_stream_consensus_keepalive_while_agents_are_slow(self, client, monkeypatch):
        """느린 에이전트 대기 중에도 소켓을 살려두는 keepalive 가 나가야 한다.

        Gotcha-Test Pair — `use-trace-stream.ts` 가 상대 경로로 바뀌며 이 SSE 가
        Next 프록시를 타게 됐다. 프록시는 30초 무통신이면 소켓을 abort 하고
        (`proxyTimeout || 30000`), 훅은 onerror 에서 es.close() 를 부르므로
        복구되지 않는다. 큐 대기 루프에서 keepalive 를 빼면 이 테스트가 FAIL 한다.

        폴링 간격을 크게 잡아 실시간 대기 없이 KEEPALIVE_INTERVAL 을 넘긴다.
        """
        import nuri.api.routes.agents as agents_mod

        monkeypatch.setattr(agents_mod, "_POLL_INTERVAL", 0.01)
        monkeypatch.setattr(agents_mod, "KEEPALIVE_INTERVAL", 0.02)

        @dataclass
        class Evt:
            ticker: str = "AAPL"
            text: str = "step"

        def slow_stream(ticker):
            # 첫 이벤트까지 폴링 몇 바퀴를 돌게 해 큐가 비어 있는 구간을 만든다.
            _time.sleep(0.3)
            yield ("agent_finish", Evt(text="done"))

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.stream_analyze_ticker",
            slow_stream,
        )
        with client.stream("GET", "/api/consensus/AAPL/stream") as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes()).decode("utf-8")

        assert ": keepalive" in body, "큐 대기 중 keepalive 가 나가지 않았다"
        # keepalive 는 SSE 주석이라 EventSource 의 onmessage 를 깨우지 않는다.
        assert "done" in body

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
