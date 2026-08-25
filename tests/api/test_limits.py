"""heavy_slot 동시성 상한 (#1119) — 의미·배선·차단 동작 잠금."""

import threading
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import nuri.api.limits as limits
from nuri.api.limits import DEFAULT_HEAVY_SLOTS, _slots_from_env, heavy_slot

# 배선 계약 — 이 목록에서 하나라도 빠지면 FAIL (#1119 회귀 잠금)
HEAVY_PATHS = [
    "/scan",
    "/swing/entries",
    "/backtest",
    "/backtest/equity",
    "/strategy/status",
    "/consensus",
    "/conflicts",
    "/candidates",
    "/rebalance",
    "/report",
    "/report/context",
    "/certify",
    "/remediate",
    "/pipeline/{step}/run",
    # 단일-플라이트 캐시 3종 — 콜드 미스 대기자가 lock 에서 스레드를 점유한다 (codex #1239 P1)
    "/dashboard",
    "/actions",
    "/market-context",
]


class TestSlotsFromEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("NURI_API_HEAVY_SLOTS", raising=False)
        assert _slots_from_env() == DEFAULT_HEAVY_SLOTS

    def test_valid_override(self, monkeypatch):
        monkeypatch.setenv("NURI_API_HEAVY_SLOTS", "3")
        assert _slots_from_env() == 3

    def test_garbage_falls_back(self, monkeypatch):
        monkeypatch.setenv("NURI_API_HEAVY_SLOTS", "many")
        assert _slots_from_env() == DEFAULT_HEAVY_SLOTS

    def test_below_one_falls_back(self, monkeypatch):
        monkeypatch.setenv("NURI_API_HEAVY_SLOTS", "0")
        assert _slots_from_env() == DEFAULT_HEAVY_SLOTS


class TestHeavySlotDependency:
    def test_exhaustion_returns_503_and_release_restores(self, monkeypatch):
        monkeypatch.setattr(limits, "_heavy_slots", threading.BoundedSemaphore(2))
        gens = []
        for _ in range(2):
            g = heavy_slot()
            next(g)  # 슬롯 획득
            gens.append(g)

        with pytest.raises(HTTPException) as exc:
            next(heavy_slot())
        assert exc.value.status_code == 503
        assert exc.value.headers["Retry-After"] == "5"
        # 내부 상태를 노출하지 않는 generic 메시지 (이 디렉터리 에러 컨벤션)
        assert "무거운 요청" in exc.value.detail

        gens[0].close()  # 해제 → 다시 획득 가능
        g = heavy_slot()
        next(g)
        g.close()
        for g in gens[1:]:
            g.close()

    def test_handler_exception_still_releases_the_slot(self, monkeypatch):
        """획득 후 핸들러 예외 → finally 가 슬롯을 해제한다 (codex #1239 P3)."""
        monkeypatch.setattr(limits, "_heavy_slots", threading.BoundedSemaphore(1))
        g = heavy_slot()
        next(g)
        with pytest.raises(RuntimeError):
            g.throw(RuntimeError("handler exploded"))
        # 예외 후에도 슬롯이 새지 않았다 — 즉시 재획득 가능
        g2 = heavy_slot()
        next(g2)
        g2.close()


class TestWiring:
    def test_every_heavy_route_carries_the_slot_dependency(self):
        """배선 잠금 — 데코레이터에서 dependencies 를 지우면 여기서 FAIL."""
        from nuri.api.main import app

        wired = {}
        for route in app.routes:
            deps = getattr(route, "dependencies", None) or []
            has = any(getattr(d, "dependency", None) is heavy_slot for d in deps)
            wired[getattr(route, "path", "")] = wired.get(getattr(route, "path", ""), False) or has

        missing = [p for p in HEAVY_PATHS if not wired.get(f"/api{p}", False)]
        assert not missing, f"heavy_slot 미배선: {missing}"


class TestRouteBehavior:
    def test_full_slots_shed_503_while_health_stays_up(self, db_path, monkeypatch):
        """슬롯 1 + 점유 중: 두 번째 무거운 요청은 즉시 503, /health 는 정상 (#1119 핵심)."""
        monkeypatch.setattr(limits, "_heavy_slots", threading.BoundedSemaphore(1))
        from nuri.api.main import app

        client = TestClient(app)
        hold = threading.Event()
        entered = threading.Event()

        def slow_rebalance(method="rp"):
            entered.set()
            assert hold.wait(timeout=10), "테스트 하네스 타임아웃"
            return []

        with patch("nuri.trading.recommend.rebalance.regime_aware_rebalance", side_effect=slow_rebalance):
            results = {}

            def first():
                results["first"] = client.get("/api/rebalance").status_code

            t = threading.Thread(target=first)
            t.start()
            assert entered.wait(timeout=10), "첫 요청이 핸들러에 진입하지 못함"

            # 슬롯 점유 중 — 두 번째 무거운 요청은 대기 없이 shed
            start = time.monotonic()
            second = client.get("/api/rebalance")
            elapsed = time.monotonic() - start
            assert second.status_code == 503
            assert second.headers["retry-after"] == "5"
            assert elapsed < 5, f"503 이 즉시가 아님 ({elapsed:.1f}s) — 비블로킹 계약 위반"

            # 가벼운 라우트는 영향 없음
            assert client.get("/api/health").status_code == 200

            hold.set()
            t.join(timeout=10)
            assert results["first"] == 200

        # 해제 후 정상 복귀
        with patch("nuri.trading.recommend.rebalance.regime_aware_rebalance", return_value=[]):
            assert client.get("/api/rebalance").status_code == 200
