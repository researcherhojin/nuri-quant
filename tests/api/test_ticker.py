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

    def test_market_context_macro_score_present(self, client, monkeypatch):
        """#754 회귀: compute_macro_score 는 MacroScore dataclass 를 반환한다.

        과거 코드는 ``isinstance(macro, dict)`` 체크로 dataclass 를 항상 None
        처리해 macro_score 가 영구 null 이었다. dataclass 속성 접근으로 노출.
        """

        class FakeMacro:
            total_score = 62.5

        monkeypatch.setattr(
            "nuri.quant.regime.macro_score.compute_macro_score",
            lambda: FakeMacro(),
        )
        r = client.get("/api/tickers/market-context")
        assert r.status_code == 200
        assert r.json()["macro_score"] == 62.5

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

    def test_ticker_consensus_db_miss_falls_back_to_live(self, client, monkeypatch):
        """recommendations 행 없음 → live analyze_ticker fallback, raise 시 error 필드."""

        def boom(t):
            raise RuntimeError("consensus down")

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", boom)
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data["consensus"]

    def test_ticker_consensus_read_from_db_no_live_call(self, client, tmp_path, monkeypatch):
        """recommendations 행 존재(fresh) → DB read 로 복원, analyze_ticker 미호출.

        P2 핵심: 매 GET 10-agent 재실행 제거. live 경로가 불리면 즉시 FAIL.
        """
        from nuri.core.timezone import today_kst

        def explode(t):
            raise AssertionError("analyze_ticker 가 호출되면 안 됨 (DB read 경로)")

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", explode)

        verdicts = [
            {
                "agent_name": "technical",
                "ticker": "AAPL",
                "action": "BUY",
                "confidence": 72.0,
                "reasoning": "RSI oversold",
                "data_points": {},
                "alpha_action": "LONG",
                "portfolio_action": None,
            },
            {
                "agent_name": "fundamental",
                "ticker": "AAPL",
                "action": "HOLD",
                "confidence": 40.0,
                "reasoning": "fair value",
                "data_points": {},
                "alpha_action": None,
                "portfolio_action": None,
            },
        ]
        # ⚠️ freshness 가드(now-window)와 결합되므로 날짜는 today_kst() 앵커 (time-bomb 방지)
        today = today_kst()
        with get_db(tmp_path / "test.db") as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, signals, agent_verdicts) "
                "VALUES (?,?,?,?,?,?)",
                (
                    today,
                    "AAPL",
                    "BUY",
                    72.0,
                    json.dumps({"agreement_rate": 0.5, "dissent_count": 1}),
                    json.dumps(verdicts, ensure_ascii=False),
                ),
            )

        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        c = r.json()["consensus"]
        assert c["final_action"] == "BUY"
        assert c["agreement_rate"] == 0.5
        assert c["as_of"] == today
        assert len(c["verdicts"]) == 2
        # dissent 는 final_action(BUY)과 다른 verdict 에서 재구성
        assert any("fundamental" in d for d in c["dissent"])

    def test_ticker_consensus_stale_row_falls_back_to_live(self, client, tmp_path, monkeypatch):
        """오래된 행(>7일)은 stale → live analyze_ticker 재계산.

        스케줄러 정지 등으로 행이 오래되면 stale 값을 권위 있게 serve 하지 않는다.
        """
        from datetime import timedelta

        from nuri.core.timezone import kst_now, today_kst
        from nuri.trading.agents.consensus.models import ConsensusResult

        called = {"live": False}

        def fake_live(t):
            called["live"] = True
            return ConsensusResult(
                ticker=t,
                final_action="HOLD",
                final_confidence=55.0,
                agreement_rate=0.9,
                verdicts=[],
                dissent=[],
                reasoning="live recompute",
            )

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", fake_live)

        stale_date = (kst_now().date() - timedelta(days=10)).isoformat()
        with get_db(tmp_path / "test.db") as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, signals, agent_verdicts) "
                "VALUES (?,?,?,?,?,?)",
                (stale_date, "AAPL", "BUY", 80.0, json.dumps({"agreement_rate": 0.3}), "[]"),
            )
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        c = r.json()["consensus"]
        assert called["live"] is True
        assert c["final_action"] == "HOLD"  # stale BUY 가 아닌 live HOLD
        assert c["as_of"] == today_kst()

    def test_ticker_consensus_db_miss_live_fallback_shape(self, client, monkeypatch):
        """DB 미스(포트폴리오 외 종목) → live 복원 + 정상 shape (error 아님)."""
        from nuri.core.timezone import today_kst
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus.models import ConsensusResult

        def fake_live(t):
            return ConsensusResult(
                ticker=t,
                final_action="BUY",
                final_confidence=70.0,
                agreement_rate=0.6,
                verdicts=[AgentVerdict("technical", t, "BUY", 70.0, "breakout")],
                dissent=["fundamental(HOLD, 40): rich"],
                reasoning="live",
            )

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", fake_live)
        r = client.get("/api/ticker/ZZZZ")
        assert r.status_code == 200
        c = r.json()["consensus"]
        assert "error" not in c
        assert c["final_action"] == "BUY"
        assert c["as_of"] == today_kst()
        assert c["verdicts"][0]["agent_name"] == "technical"

    def test_ticker_consensus_malformed_json_graceful(self, client, tmp_path, monkeypatch):
        """legacy 행: agent_verdicts/signals 가 비-JSON 문자열 → graceful 빈 복원."""
        from nuri.core.timezone import today_kst

        def explode(t):
            raise AssertionError("DB 행이 있으면 live 호출 금지")

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", explode)
        with get_db(tmp_path / "test.db") as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, signals, agent_verdicts) "
                "VALUES (?,?,?,?,?,?)",
                (today_kst(), "AAPL", "HOLD", 50.0, "rsi_oversold,macd_golden", "not-json"),
            )
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        c = r.json()["consensus"]
        assert c["final_action"] == "HOLD"
        assert c["verdicts"] == []
        assert c["dissent"] == []
        assert c["agreement_rate"] is None

    def test_ticker_consensus_verdicts_non_list_coerced(self, client, tmp_path, monkeypatch):
        """agent_verdicts 가 valid JSON 이나 list 가 아니면(예: object) verdicts=[]."""
        from nuri.core.timezone import today_kst

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_ticker",
            lambda t: (_ for _ in ()).throw(AssertionError("live 금지")),
        )
        with get_db(tmp_path / "test.db") as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, signals, agent_verdicts) "
                "VALUES (?,?,?,?,?,?)",
                (today_kst(), "AAPL", "HOLD", 50.0, json.dumps({"agreement_rate": 0.1}), "{}"),
            )
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        assert r.json()["consensus"]["verdicts"] == []

    def test_ticker_candidates_exception(self, client, monkeypatch):
        """screen_candidates raise → signals=[] (캐시 cold 강제)."""
        from nuri.api.routes import ticker as ticker_mod

        ticker_mod._candidates_cache["data"] = None
        ticker_mod._candidates_cache["timestamp"] = 0.0

        def boom(**kw):
            raise RuntimeError("scan fail")

        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", boom)
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        data = r.json()
        assert data["signals"] == []

    def test_ticker_signals_cache_hit_skips_rescan(self, client, monkeypatch):
        """캐시 warm 시 screen_candidates 재호출 없이 캐시 결과 필터."""
        from nuri.api.routes import ticker as ticker_mod

        @dataclass
        class _FakeCandidate:
            ticker: str
            signal_id: str = "rsi_oversold"
            confidence: float = 80.0

        ticker_mod._candidates_cache["data"] = [
            _FakeCandidate(ticker="AAPL"),
            _FakeCandidate(ticker="MSFT"),
        ]
        ticker_mod._candidates_cache["timestamp"] = _time.time()

        def explode(**kw):
            raise AssertionError("warm 캐시인데 screen_candidates 가 호출됨")

        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", explode)
        r = client.get("/api/ticker/AAPL")
        assert r.status_code == 200
        signals = r.json()["signals"]
        assert len(signals) == 1
        assert signals[0]["ticker"] == "AAPL"
