"""Tests for regime — split from test_api_all.py."""

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


class TestRegime:
    def test_regime_no_data(self, client):
        """SPY 데이터 없으면 에러 dict 반환."""
        r = client.get("/api/regime")
        assert r.status_code == 200

    def test_macro(self, client):
        r = client.get("/api/macro")
        assert r.status_code == 200

    def test_strategy(self, client):
        r = client.get("/api/strategy")
        assert r.status_code == 200


class TestRegimeAPI:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app

        return TestClient(app)

    def test_get_regime_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: None)
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        assert resp.json()["error"] == "SPY 데이터 부족"

    def test_get_regime_success(self, _client, monkeypatch):
        @dataclass
        class FakeRegimeState:
            regime: str = "bull_low_vol"
            trend: str = "bull"
            volatility: str = "low"
            confidence: float = 0.85
            details: dict | None = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {"vix": 15.0, "fear_greed": 60}

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda: FakeRegimeState())
        resp = _client.get("/api/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_macro(self, _client, monkeypatch):
        @dataclass
        class FakeMacro:
            total_score: float = 65.0
            interpretation: str = "Positive"
            details: dict | None = None

            def __post_init__(self):
                if self.details is None:
                    self.details = {}

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", lambda: FakeMacro())
        resp = _client.get("/api/macro")
        assert resp.status_code == 200

    def test_get_strategy_none(self, _client, monkeypatch):
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: None)
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_get_strategy_success(self, _client, monkeypatch):
        class FakeStrategy:
            regime = "bull_low_vol"
            macro_interpretation = "Positive"
            position_sizing = "aggressive"
            recommended_signals = ["rsi_oversold", "macd_golden"]
            avoid_signals = ["sma_dead"]
            sector_preference = ["Technology"]
            signal_regime_stats = {}
            notes = "Test note"

        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda: FakeStrategy())
        resp = _client.get("/api/strategy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull_low_vol"

    def test_get_report_success(self, _client, monkeypatch):
        """/report 성공 path — generate_llm_report 가 dict 반환."""
        monkeypatch.setattr(
            "nuri.llm.report.generate_llm_report",
            lambda: {"summary": "test report", "ok": True},
        )
        resp = _client.get("/api/report")
        assert resp.status_code == 200
        assert resp.json()["summary"] == "test report"

    def test_get_report_exception_returns_500(self, _client, monkeypatch):
        """/report 실패 시 stack-trace 노출 없이 500."""

        def boom():
            raise RuntimeError("LLM down")

        monkeypatch.setattr("nuri.llm.report.generate_llm_report", boom)
        resp = _client.get("/api/report")
        assert resp.status_code == 500
        assert "LLM report" in resp.json()["detail"]

    def test_get_report_context(self, _client, monkeypatch):
        class FakeContext:
            gate_score = 80
            known_tickers = {"AAPL", "MSFT"}

        monkeypatch.setattr("nuri.llm.report.gather_context", lambda: FakeContext())
        monkeypatch.setattr("nuri.llm.report.format_prompt", lambda ctx: "test prompt")
        resp = _client.get("/api/report/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gate_score"] == 80


class TestReportContextCache:
    """`/report/context` 가 매 요청 전액을 다시 물지 않는지 잠근다 (#1119).

    회귀 전에는 캐시가 없어 cold 28.4초 · warm 28.9초였다. 그 중 약 20초가
    `gather_context()` 안의 `consensus.analyze_portfolio` 인데, 바로 옆
    `/api/consensus` 가 5분 캐시로 이미 갖고 있는 계산이다.
    """

    def _reset(self):
        import nuri.api.routes.regime as m

        m._context_cache["data"] = None
        m._context_cache["ts"] = 0.0

    def test_second_request_does_not_recompute(self, client, monkeypatch):
        class FakeContext:
            gate_score = 80
            known_tickers = {"AAPL"}

        calls = []

        def counted():
            calls.append(1)
            return FakeContext()

        self._reset()
        monkeypatch.setattr("nuri.llm.report.gather_context", counted)
        monkeypatch.setattr("nuri.llm.report.format_prompt", lambda ctx: "p")
        try:
            assert client.get("/api/report/context").status_code == 200
            assert client.get("/api/report/context").status_code == 200
            assert len(calls) == 1, f"gather_context 가 {len(calls)}회 실행됐다"
        finally:
            self._reset()

    def test_concurrent_requests_compute_once(self, client, monkeypatch):
        """락 안쪽 double-check 경로 — 경합 없이는 실행되지 않는다."""
        import threading

        class FakeContext:
            gate_score = 1
            known_tickers = set()

        calls = []
        barrier = threading.Barrier(4)

        def slow():
            calls.append(1)
            _time.sleep(0.25)
            return FakeContext()

        self._reset()
        monkeypatch.setattr("nuri.llm.report.gather_context", slow)
        monkeypatch.setattr("nuri.llm.report.format_prompt", lambda ctx: "p")

        import nuri.api.routes.regime as m

        def worker():
            barrier.wait(timeout=5)
            m.get_report_context()

        try:
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            assert len(calls) == 1, f"동시 4요청이 {len(calls)}회 계산했다 — single-flight 없음"
        finally:
            self._reset()
