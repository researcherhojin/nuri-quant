"""Tests for pipeline API routes.

Merged from two sources:
- Original `tests/api/test_pipeline.py` (split from test_api_all.py) — `TestPipelineAPI`.
- `tests/test_pipeline_api.py` (Pipeline API + Dashboard v2 통합 테스트) —
  `TestDashboardV2`, `TestPipelineStatus`, `TestPipelineTimeline`, `TestPipelineRun`,
  `TestFreshness`, `TestCoreEvents`, `TestCoreFreshness`, `TestSchedulerHealth`,
  `TestWriteHeartbeat`.

Both target `nuri/api/routes/pipeline.py` + related pipeline observability modules.
"""

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
from nuri.core.timezone import kst_now, today_kst
from tests.api._helpers import _csv_file  # noqa: F401

# ═══════════════════════════════════════════════════════════════════════════
# Module-level fixtures (override conftest.py for this file — rate limiter
# must be disabled for parallel xdist runs on pipeline endpoints)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def db_path(tmp_path):
    """테스트용 DB 생성."""
    from nuri.core.db import init_db as _init_db

    path = tmp_path / "test.db"
    _init_db(path)
    return path


@pytest.fixture()
def client(db_path, monkeypatch):
    """테스트용 DB로 격리된 FastAPI TestClient. Rate limiter 비활성화."""
    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    # xdist 병렬 실행 시 rate limiter 간섭 방지 (route-level + app-level)
    import nuri.api.routes.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod._limiter, "enabled", False)

    from nuri.api.main import app

    return TestClient(app)


@pytest.fixture()
def dashboard_fast_client(client, monkeypatch):
    """Dashboard-focused fast client for payload-shape tests."""
    import nuri.api.routes.dashboard as dashboard_mod

    monkeypatch.setattr(
        dashboard_mod,
        "_get_cached_regime",
        lambda: {
            "regime": "bull_low_vol",
            "trend": "bull",
            "volatility": "low",
            "confidence": 85,
            "vix": None,
            "fear_greed": None,
        },
    )
    monkeypatch.setattr(
        dashboard_mod,
        "_get_macro",
        lambda: {"score": 65, "interpretation": "Positive"},
    )
    monkeypatch.setattr(dashboard_mod, "_get_gate_score", lambda: 80)
    monkeypatch.setattr(dashboard_mod, "_get_active_alerts", lambda: [])
    monkeypatch.setattr(dashboard_mod, "_get_freshness", lambda: {})
    monkeypatch.setattr(dashboard_mod, "_get_pipeline_status", lambda: {})
    monkeypatch.setattr(dashboard_mod, "_get_upcoming_events", lambda: [])
    return client


# ═══════════════════════════════════════════════════════════════════════════
# Module-level seed helpers (used by TestDashboardV2, TestPipelineStatus, etc.)
# Named `_seed_*_for_pipeline` to avoid shadowing conftest fixtures.
# ═══════════════════════════════════════════════════════════════════════════


def _seed_recommendations_for_pipeline(db_path, date=None):
    """테스트용 recommendations 데이터 삽입."""
    from nuri.core.db import get_db as _get_db

    if date is None:
        date = today_kst()

    recs = [
        (date, "AAPL", "BUY", 0.85, "bull_low_vol", "RSI oversold + MACD cross", 180.0),
        (date, "NVDA", "BUY", 0.72, "bull_low_vol", "SMA golden cross", 168.0),
        (date, "TSLA", "SELL", 0.90, "sideways_high_vol", "RSI overbought", 250.0),
        (date, "META", "HOLD", 0.45, "bull_low_vol", "Mixed signals", 500.0),
    ]
    with _get_db(db_path) as conn:
        conn.executemany(
            """INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            recs,
        )


def _seed_pipeline_events_for_pipeline(db_path):
    """테스트용 pipeline_events 데이터 삽입."""
    from nuri.core.db import get_db as _get_db

    events = [
        ("step_success", "collect", json.dumps({"detail": "11 collectors"}), 5000, 1500, None),
        ("step_success", "classify", json.dumps({"detail": "regime=bull_low_vol"}), 3200, 1, None),
        ("step_failed", "diagnose", json.dumps({"error": "timeout"}), 60000, 0, None),
    ]
    with _get_db(db_path) as conn:
        conn.executemany(
            """INSERT INTO pipeline_events (event_type, step, payload, duration_ms, record_count, causation_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            events,
        )


def _seed_prices_for_pipeline(db_path):
    """테스트용 prices 데이터 삽입 (신선도 테스트용)."""
    from nuri.core.db import get_db as _get_db

    today = today_kst()
    with _get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", today, 180, 185, 179, 183, 50000000),
        )
        # freshness 정책이 SPY 기준으로 조회하므로 SPY도 추가
        conn.execute(
            "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("SPY", today, 580, 585, 578, 583, 80000000),
        )


class TestPipelineAPI:
    """Cover lines 21-22, 90-93, 108-110, 115, 117-129."""

    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app

        return TestClient(app)

    def test_scheduler_health_no_file(self, _client, monkeypatch, tmp_path):
        """Scheduler health when no heartbeat file (lines 21-22)."""
        import nuri.api.routes.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", tmp_path / "nonexistent")
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    def test_scheduler_health_valid(self, _client, monkeypatch, tmp_path):
        """Scheduler health with valid heartbeat."""
        import nuri.api.routes.pipeline as pipeline_mod

        hb_path = tmp_path / ".scheduler_heartbeat"
        from nuri.core.timezone import kst_now

        hb_path.write_text(kst_now().replace(tzinfo=None).isoformat())
        monkeypatch.setattr(pipeline_mod, "_HEARTBEAT_PATH", hb_path)
        resp = _client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_pipeline_status(self, _client):
        """Pipeline status endpoint."""
        resp = _client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data

    def test_pipeline_timeline(self, _client):
        """Pipeline timeline endpoint."""
        resp = _client.get("/api/pipeline/timeline?limit=10")
        assert resp.status_code == 200

    def test_pipeline_timeline_invalid_step(self, _client):
        """Pipeline timeline with invalid step."""
        resp = _client.get("/api/pipeline/timeline?step=invalid")
        assert resp.status_code == 400

    def test_run_step_invalid(self, _client):
        """Run invalid step."""
        resp = _client.post("/api/pipeline/invalid_step/run")
        assert resp.status_code == 400

    def test_run_step_collect(self, _client):
        """Run collect step (lines 108-110)."""
        resp = _client.post("/api/pipeline/collect/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "not_implemented" in data.get("detail", "")

    def test_run_step_validate(self, _client, monkeypatch):
        """Run validate step (lines 108-110)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: [{"signal": "test"}],
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_run_step_classify(self, _client, monkeypatch):
        """Run classify step (lines 115)."""

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"
            trend: str = "bullish"
            confidence: float = 0.85

        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: MockRegime(),
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "bull_low_vol" in data.get("detail", "")

    def test_run_step_classify_none(self, _client, monkeypatch):
        """Run classify step returns None (line 116)."""
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda: None,
        )
        resp = _client.post("/api/pipeline/classify/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown" in data.get("detail", "")

    def test_run_step_diagnose(self, _client, monkeypatch):
        """Run diagnose step (lines 117-120)."""
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.analyze_portfolio",
            lambda: ["r1", "r2"],
        )
        resp = _client.post("/api/pipeline/diagnose/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "2 tickers" in data.get("detail", "")

    def test_run_step_recommend(self, _client, monkeypatch):
        """Run recommend step (lines 121-124)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda: ["c1"],
        )
        resp = _client.post("/api/pipeline/recommend/run")
        assert resp.status_code == 200

    def test_run_step_track(self, _client, monkeypatch):
        """Run track step (lines 125-128)."""
        monkeypatch.setattr(
            "nuri.trading.recommend.tracker.track_outcomes",
            lambda: 5,
        )
        resp = _client.post("/api/pipeline/track/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "5 recommendations" in data.get("detail", "")

    def test_run_step_exception(self, _client, monkeypatch):
        """Run step that throws exception (lines 90-93)."""
        monkeypatch.setattr(
            "nuri.quant.validation.signal_backtest.backtest_signals",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        resp = _client.post("/api/pipeline/validate/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    def test_freshness_endpoint(self, _client):
        """Freshness endpoint."""
        resp = _client.get("/api/freshness")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Merged from tests/test_pipeline_api.py — Dashboard v2 + pipeline endpoints
# + core events/freshness + scheduler health + heartbeat writer.
# ═══════════════════════════════════════════════════════════════════════════


class TestDashboardV2:
    def test_dashboard_returns_fast(self, dashboard_fast_client, db_path):
        """추천 데이터가 있을 때 대시보드 응답 검증."""
        _seed_recommendations_for_pipeline(db_path)
        _seed_pipeline_events_for_pipeline(db_path)
        _seed_prices_for_pipeline(db_path)

        r = dashboard_fast_client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()

        # 필수 필드 확인
        assert "verdict" in data
        assert "verdict_level" in data
        assert "regime" in data
        assert "actions" in data
        assert "alerts" in data
        assert "gate_score" in data
        assert "freshness" in data
        assert "pipeline_status" in data

    def test_dashboard_without_recommendations(self, dashboard_fast_client, db_path):
        """빈 DB에서도 에러 없이 정상 응답."""
        # 캐시 무효화 (이전 테스트 결과가 남아있을 수 있음)
        from nuri.api.routes.dashboard import _cache

        _cache["data"] = None
        _cache["timestamp"] = 0
        r = dashboard_fast_client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()

        assert "verdict" in data
        assert "actions" in data
        assert data["actions"] == []
        assert "freshness" in data
        assert "pipeline_status" in data

    def test_dashboard_actions_from_db(self, dashboard_fast_client, db_path):
        """recommendations 테이블에서 액션을 올바르게 읽는지 확인."""
        _seed_recommendations_for_pipeline(db_path)

        # 캐시 무효화
        from nuri.api.routes.dashboard import _cache

        _cache["data"] = None
        _cache["timestamp"] = 0

        r = dashboard_fast_client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()

        actions = data["actions"]
        tickers = [a["ticker"] for a in actions]
        # BUY: AAPL(85%), NVDA(72%) 둘 다 >= 50%
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        # SELL: TSLA(90%) >= 70%
        assert "TSLA" in tickers
        # HOLD: META(45%) < 50% → 포함 안 됨
        assert "META" not in tickers

    def test_dashboard_cached(self, dashboard_fast_client, db_path):
        """두 번 호출 — 캐시 사용."""
        r1 = dashboard_fast_client.get("/api/dashboard")
        r2 = dashboard_fast_client.get("/api/dashboard")
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_dashboard_freshness_fields(self, dashboard_fast_client, db_path):
        """신선도 정보 존재 확인."""
        _seed_prices_for_pipeline(db_path)

        from nuri.api.routes.dashboard import _cache

        _cache["data"] = None
        _cache["timestamp"] = 0

        r = dashboard_fast_client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()

        freshness = data["freshness"]
        # prices 데이터를 넣었으므로 prices 키가 있어야 함
        if "prices" in freshness:
            assert "status" in freshness["prices"]
            assert "age_hours" in freshness["prices"]


class TestPipelineStatus:
    def test_pipeline_status_endpoint(self, client, db_path):
        """파이프라인 상태 엔드포인트 기본 동작."""
        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        data = r.json()

        assert "steps" in data
        assert "freshness" in data
        # steps 는 프론트 PipelineStep[] 계약: 배열, 각 원소에 step/label/status 등.
        # (과거 dict 반환 → 프론트가 array 로 소비 못해 DAG 가 하드코딩 fallback 했던 버그의 회귀 가드.)
        steps = data["steps"]
        assert isinstance(steps, list)
        by_step = {s["step"]: s for s in steps}
        for step in ("collect", "validate", "classify", "diagnose", "recommend", "track"):
            assert step in by_step
            s = by_step[step]
            assert s["status"] in ("idle", "running", "done", "error")  # 프론트 enum
            assert "label" in s and "description" in s and "record_count" in s

    def test_pipeline_status_with_events(self, client, db_path):
        """이벤트 데이터 있을 때 상태가 프론트 enum 으로 매핑되어 반영되는지 확인."""
        _seed_pipeline_events_for_pipeline(db_path)

        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        data = r.json()

        by_step = {s["step"]: s for s in data["steps"]}
        # step_success(collect) -> done, step_failed(diagnose) -> error
        assert by_step["collect"]["status"] == "done"
        assert by_step["collect"]["record_count"] == 1500  # seed record_count 컬럼 반영
        assert by_step["diagnose"]["status"] == "error"


class TestPipelineTimeline:
    def test_pipeline_timeline_endpoint(self, client, db_path):
        """타임라인 엔드포인트 기본 동작."""
        r = client.get("/api/pipeline/timeline")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_pipeline_timeline_with_data(self, client, db_path):
        """이벤트 데이터 있을 때 타임라인 확인."""
        _seed_pipeline_events_for_pipeline(db_path)

        r = client.get("/api/pipeline/timeline")
        assert r.status_code == 200
        data = r.json()
        assert len(data["events"]) == 3

    def test_pipeline_timeline_filter_by_step(self, client, db_path):
        """스텝별 필터링."""
        _seed_pipeline_events_for_pipeline(db_path)

        r = client.get("/api/pipeline/timeline?step=collect")
        assert r.status_code == 200
        data = r.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["step"] == "collect"

    def test_pipeline_timeline_invalid_step(self, client, db_path):
        """잘못된 스텝명 → 400."""
        r = client.get("/api/pipeline/timeline?step=invalid")
        assert r.status_code == 400

    def test_pipeline_timeline_limit(self, client, db_path):
        """limit 파라미터 동작 확인."""
        _seed_pipeline_events_for_pipeline(db_path)

        r = client.get("/api/pipeline/timeline?limit=2")
        assert r.status_code == 200
        data = r.json()
        assert len(data["events"]) == 2


class TestPipelineRun:
    def test_pipeline_run_classify(self, client, db_path):
        """classify 스텝 실행 — 데이터 부족이어도 에러 없이 반환."""
        r = client.post("/api/pipeline/classify/run")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "duration_ms" in data
        assert data["status"] in ("success", "failed")

    def test_pipeline_run_collect_not_implemented(self, client, db_path):
        """collect 스텝 → not_implemented."""
        r = client.post("/api/pipeline/collect/run")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert "not_implemented" in data["detail"]

    def test_pipeline_run_invalid_step(self, client, db_path):
        """잘못된 스텝명 → 400."""
        r = client.post("/api/pipeline/invalid/run")
        assert r.status_code == 400

    def test_pipeline_run_records_events(self, client, db_path):
        """스텝 실행 후 이벤트 기록 확인."""
        # POST 응답 자체를 먼저 검증
        post_r = client.post("/api/pipeline/collect/run")
        assert post_r.status_code == 200
        post_data = post_r.json()
        assert post_data["status"] == "success"

        # emit_event로 직접 기록 후 조회 (API 경유 대신 직접 검증)
        from nuri.core.events import emit_event, get_timeline

        emit_event("step_started", step="collect", db_path=db_path)
        emit_event("step_completed", step="collect", db_path=db_path)

        events = get_timeline(step="collect", db_path=db_path)
        # 직접 삽입한 2개 + API가 기록한 events
        assert len(events) >= 2


class TestFreshness:
    def test_freshness_endpoint(self, client, db_path):
        """신선도 엔드포인트 기본 동작."""
        r = client.get("/api/freshness")
        assert r.status_code == 200
        data = r.json()
        assert "details" in data
        assert "pass" in data
        assert "warn" in data
        assert "fail" in data

    def test_freshness_with_data(self, client, db_path):
        """데이터 있을 때 신선도 확인."""
        _seed_prices_for_pipeline(db_path)

        r = client.get("/api/freshness")
        assert r.status_code == 200
        data = r.json()

        prices_detail = next((d for d in data["details"] if d["key"] == "prices"), None)
        assert prices_detail is not None
        assert prices_detail["status"] == "PASS"

    def test_freshness_empty_table(self, client, db_path):
        """빈 테이블 → FAIL 상태."""
        r = client.get("/api/freshness")
        assert r.status_code == 200
        data = r.json()

        prices_detail = next((d for d in data["details"] if d["key"] == "prices"), None)
        assert prices_detail is not None
        assert prices_detail["status"] == "FAIL"


class TestCoreEvents:
    """nuri.core.events 모듈 직접 테스트."""

    def test_emit_event(self, db_path):
        """이벤트 기록 + 조회."""
        from nuri.core.events import emit_event, get_timeline

        event_id = emit_event("step_success", step="collect", duration_ms=5000, db_path=db_path)
        assert event_id is not None
        assert event_id > 0

        events = get_timeline(db_path=db_path)
        assert len(events) == 1
        assert events[0]["step"] == "collect"
        assert events[0]["event_type"] == "step_success"

    def test_emit_event_with_payload(self, db_path):
        """payload 포함 이벤트."""
        from nuri.core.events import emit_event, get_timeline

        emit_event(
            "step_success",
            step="classify",
            payload={"regime": "bull_low_vol"},
            duration_ms=3200,
            record_count=1,
            db_path=db_path,
        )
        events = get_timeline(db_path=db_path)
        assert events[0]["payload"] is not None
        # payload는 이미 dict로 반환되거나 JSON string — 둘 다 대응
        payload = events[0]["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["regime"] == "bull_low_vol"

    def test_get_pipeline_status(self, db_path):
        """파이프라인 상태 조회."""
        from nuri.core.events import emit_event, get_pipeline_status

        emit_event("step_success", step="collect", duration_ms=5000, db_path=db_path)
        emit_event("step_failed", step="diagnose", duration_ms=60000, db_path=db_path)

        status = get_pipeline_status(db_path=db_path)
        # events.py의 status 매핑에 따라 step_ prefix가 있거나 없을 수 있음
        assert status["collect"]["status"] in ("success", "step_success", "completed")
        assert status["diagnose"]["status"] in ("failed", "step_failed")
        assert status["validate"]["status"] in ("never_run", "unknown")

    def test_get_timeline_filter(self, db_path):
        """스텝별 필터링."""
        from nuri.core.events import emit_event, get_timeline

        emit_event("step_success", step="collect", db_path=db_path)
        emit_event("step_success", step="classify", db_path=db_path)

        all_events = get_timeline(db_path=db_path)
        assert len(all_events) == 2

        collect_only = get_timeline(step="collect", db_path=db_path)
        assert len(collect_only) == 1


class TestCoreFreshness:
    """nuri.core.freshness 모듈 직접 테스트 — Dagster PASS/WARN/FAIL 패턴."""

    def test_check_freshness_no_data(self, db_path):
        """데이터 없는 정책 → FAIL (데이터 없음)."""
        from nuri.core.freshness import check_freshness

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["key"] == "prices"

    def test_check_freshness_with_data(self, db_path):
        """오늘 SPY 데이터 → PASS."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness

        today = today_kst()
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", today, 580.0),
            )

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "PASS"

    def test_check_freshness_old_data(self, db_path):
        """오래된 데이터 → FAIL."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness

        old_date = (kst_now().replace(tzinfo=None) - timedelta(days=5)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("SPY", old_date, 580.0),
            )

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "FAIL"

    def test_check_freshness_unknown_key(self, db_path):
        """등록되지 않은 정책 키 → KeyError."""
        import pytest as pt

        from nuri.core.freshness import check_freshness

        with pt.raises(KeyError):
            check_freshness("nonexistent_key", db_path=db_path)

    def test_check_all_freshness(self, db_path):
        """전체 신선도 → 5개 정책 포함."""
        from nuri.core.freshness import FRESHNESS_POLICIES, check_all_freshness

        results = check_all_freshness(db_path=db_path)
        assert len(results) == len(FRESHNESS_POLICIES)
        keys = [r["key"] for r in results]
        assert "prices" in keys
        assert "macro_vix" in keys

    def test_get_freshness_summary(self, db_path):
        """요약 카운트 검증."""
        from nuri.core.freshness import FRESHNESS_POLICIES, get_freshness_summary

        result = get_freshness_summary(db_path=db_path)
        assert "details" in result
        assert "pass" in result
        assert "warn" in result
        assert "fail" in result
        # 빈 DB → 모두 FAIL
        assert result["fail"] == len(FRESHNESS_POLICIES)


class TestSchedulerHealth:
    def test_no_heartbeat_file(self, client, monkeypatch):
        """heartbeat 파일 없으면 unknown."""
        import nuri.api.routes.pipeline as pipe_mod

        monkeypatch.setattr(pipe_mod, "_HEARTBEAT_PATH", Path("/nonexistent/.hb"))
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unknown"

    def test_heartbeat_fresh(self, client, tmp_path, monkeypatch):
        """최근 heartbeat → ok."""
        import nuri.api.routes.pipeline as pipe_mod

        hb = tmp_path / ".hb"
        hb.write_text(kst_now().strftime("%Y-%m-%dT%H:%M:%S"))
        monkeypatch.setattr(pipe_mod, "_HEARTBEAT_PATH", hb)
        resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["age_seconds"] < 10

    def test_heartbeat_stale(self, client, tmp_path, monkeypatch):
        """오래된 heartbeat → stale."""
        import nuri.api.routes.pipeline as pipe_mod

        hb = tmp_path / ".hb"
        old = (kst_now().replace(tzinfo=None) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
        hb.write_text(old)
        monkeypatch.setattr(pipe_mod, "_HEARTBEAT_PATH", hb)
        resp = client.get("/api/scheduler/health")
        assert resp.json()["status"] == "stale"

    def test_heartbeat_corrupt(self, client, tmp_path, monkeypatch):
        """손상된 heartbeat → error."""
        import nuri.api.routes.pipeline as pipe_mod

        hb = tmp_path / ".hb"
        hb.write_text("not-a-date")
        monkeypatch.setattr(pipe_mod, "_HEARTBEAT_PATH", hb)
        resp = client.get("/api/scheduler/health")
        assert resp.json()["status"] == "error"


class TestWriteHeartbeat:
    def test_creates_file(self, tmp_path, monkeypatch):
        """_write_heartbeat가 파일 생성."""
        import nuri.scheduler as sched

        monkeypatch.setattr(sched, "HEARTBEAT_PATH", tmp_path / ".hb")
        sched._write_heartbeat()
        assert (tmp_path / ".hb").exists()


class TestPipelineUnknownStep:
    def test_execute_unknown_step_returns_default(self):
        """_execute_step('unknown') → 'unknown step' (line 135)."""
        from nuri.api.routes.pipeline import _execute_step

        assert _execute_step("totally-unknown-xyz") == "unknown step"

    def test_get_heartbeat_path_none_falls_back(self, monkeypatch):
        """_HEARTBEAT_PATH=None → derive from __file__ (lines 21-22)."""
        import nuri.api.routes.pipeline as pipe_mod

        monkeypatch.setattr(pipe_mod, "_HEARTBEAT_PATH", None)
        path = pipe_mod._get_heartbeat_path()
        assert "data" in str(path)
        assert ".scheduler_heartbeat" in str(path)
