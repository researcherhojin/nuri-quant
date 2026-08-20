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


class TestConsensusSingleFlight:
    """TTL 만료 시 동시 요청이 재계산을 중복 수행하지 않는지 잠근다 (#1119).

    실측 2026-08-20: 락이 없을 때 빈 캐시에 `/api/consensus` 8개를 동시에 던지면
    8개가 **각자** 20.9~32.7초를 태웠다 (스케줄러 로그 마커 기준 계산 144회 =
    8배). 40개짜리 AnyIO 스레드풀 중 8칸이 30초간 묶여 `/api/health` 까지 뒤에
    줄을 섰다. 락 적용 후 같은 8요청에서 계산은 1회.
    """

    def test_concurrent_requests_compute_once(self):
        import threading

        import nuri.api.routes.agents as agents_mod

        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0

        calls = []
        barrier = threading.Barrier(4)

        def _slow_analyze():
            calls.append(1)
            # 모든 스레드가 캐시 미스를 확인한 뒤에야 계산이 끝나도록 —
            # 락이 없으면 4개가 전부 여기 들어온다.
            _time.sleep(0.3)
            return []

        def _worker():
            barrier.wait(timeout=5)
            agents_mod.get_consensus()

        with patch("nuri.trading.agents.consensus.analyze_portfolio", side_effect=_slow_analyze):
            with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
                threads = [threading.Thread(target=_worker) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=15)

        assert len(calls) == 1, f"동시 4요청이 {len(calls)}회 계산했다 — single-flight 락이 없다"
        agents_mod._cache["data"] = None
        agents_mod._cache["ts"] = 0


class TestRouteCacheSingleFlight:
    """나머지 TTL 캐시 6개 모듈의 single-flight 를 한 자리에서 잠근다 (#1119).

    락 안쪽 double-check(`다른 스레드가 이미 채웠다` 경로)는 경합 없이는 절대
    실행되지 않아 codecov patch 가 misses 7 / partials 8 로 잡았다. 각 캐시마다
    4 스레드를 barrier 로 동시 진입시켜 compute 가 정확히 1회인지 본다.

    ⚠️ compute 결과가 **falsy** 면 (`{}` / `[]`) 캐시 판정이 `if _cache["data"]`
    라서 저장돼도 미스로 읽힌다 — 락이 있어도 매 요청 재계산한다. 이 패턴은
    이 PR 이전부터 있었고 여기서 고치지 않는다. 그래서 아래 mock 은 전부
    truthy 를 돌려준다 (`{}` 를 쓰면 락이 아니라 그 성질 때문에 실패한다).

    `test_agents.py` 에 모인 이유: 새 테스트 파일은 `test_files_be` 문서 카운트를
    건드려 동시 진행 PR 과 반드시 충돌한다. 위 `TestConsensusSingleFlight` 와
    같은 성격이라 함께 둔다.
    """

    @staticmethod
    def _race(call, patches, resets, make_result, expected_calls=1):
        import threading

        calls = []
        barrier = threading.Barrier(4)

        def counted(*a, **k):
            calls.append(1)
            _time.sleep(0.25)
            return make_result(*a, **k)

        def worker():
            barrier.wait(timeout=5)
            try:
                call()
            except Exception:  # 캐시 경로만 관심 — 하위 계산 실패는 무시
                pass

        for reset in resets:
            reset()
        ctxs = [pf(side_effect=counted) for pf in patches]
        for c in ctxs:
            c.__enter__()
        threads = [threading.Thread(target=worker) for _ in range(4)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        finally:
            for c in reversed(ctxs):
                c.__exit__(None, None, None)
            for reset in resets:
                reset()
        assert len(calls) == expected_calls, f"compute 가 {len(calls)}회 (기대 {expected_calls})"

    def test_actions_cache(self):
        import nuri.api.routes.actions as m

        def reset():
            m._actions_cache["data"] = None
            m._actions_cache["timestamp"] = 0

        self._race(
            m.get_actions,
            [lambda **kw: patch.object(m, "_build_actions", **kw)],
            [reset],
            lambda *a, **k: {"urgent": [], "check": [], "hold": [], "portfolio": []},
        )

    def test_opportunities_cache(self):
        import nuri.api.routes.actions as m

        def reset():
            m._opportunities_cache["data"] = None
            m._opportunities_cache["timestamp"] = 0

        self._race(
            m.get_opportunities,
            [lambda **kw: patch.object(m, "_build_opportunities", **kw)],
            [reset],
            lambda *a, **k: [{"ticker": "TST_A"}],
        )

    def test_market_context_cache(self):
        import nuri.api.routes.actions as m

        def reset():
            m._market_context_cache["data"] = None
            m._market_context_cache["timestamp"] = 0

        # 두 함수를 같은 카운터로 patch → 1회 계산 = 2 호출
        self._race(
            m.get_market_context,
            [
                lambda **kw: patch.object(m, "_get_macro_events", **kw),
                lambda **kw: patch.object(m, "_get_system_health", **kw),
            ],
            [reset],
            lambda *a, **k: [{"x": 1}],
            expected_calls=2,
        )

    def test_dashboard_cache(self):
        import nuri.api.routes.dashboard as m

        def reset():
            m._cache["data"] = None
            m._cache["timestamp"] = 0

        self._race(
            m.get_dashboard,
            [lambda **kw: patch.object(m, "_build_dashboard", **kw)],
            [reset],
            lambda *a, **k: {"verdict": "test"},
        )

    def test_learning_memory_cache(self):
        import nuri.api.routes.learning_memory as m

        def reset():
            m._cache["data"] = None
            m._cache["ts"] = 0.0

        self._race(
            m.get_readiness,
            [lambda **kw: patch("nuri.trading.agents.consensus.agent_readiness", **kw)],
            [reset],
            lambda *a, **k: {"agents": [], "summary": {}},
        )

    def test_certify_cache(self):
        from types import SimpleNamespace

        import nuri.api.routes.targets as m

        def reset():
            m._certify_cache["data"] = None
            m._certify_cache["ts"] = 0

        def cert(*a, **k):
            return SimpleNamespace(
                certified=True,
                score=100,
                passed=1,
                failed=0,
                warnings=0,
                total_conditions=1,
                conditions=[],
                timestamp="2026-08-20",
            )

        self._race(
            m.get_certification,
            [lambda **kw: patch("nuri.trading.engine.certification.certify", **kw)],
            [reset],
            cert,
        )

    def test_backtest_equity_cache(self):
        import nuri.api.routes.swing as m

        def reset():
            m._interactive_backtest_cache.clear()

        # 캐시 쓰기가 `_run_interactive_backtest` **안**에 있으므로 mock 이 대신 쓴다
        def run(sma, period, sl, tp, cache_key, now):
            m._interactive_backtest_cache[cache_key] = (now, {"equity": []})
            return {"equity": []}

        self._race(
            lambda: m.get_backtest_equity(sma=50, period="3Y", sl=-7, tp=20),
            [lambda **kw: patch.object(m, "_run_interactive_backtest", **kw)],
            [reset],
            run,
        )

    def test_ticker_signals_cache(self):
        import nuri.api.routes.ticker as m

        def reset():
            m._candidates_cache["data"] = None
            m._candidates_cache["timestamp"] = 0.0

        self._race(
            lambda: m._get_signals("TST_A"),
            [lambda **kw: patch("nuri.trading.recommend.candidates.screen_candidates", **kw)],
            [reset],
            lambda *a, **k: [],
        )
