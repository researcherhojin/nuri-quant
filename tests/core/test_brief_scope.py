"""`brief_scope` / `memo` — 범위 객체·워커 전파·닫힌 범위·single-flight (#1499, Codex P1/P2)."""

from __future__ import annotations

import concurrent.futures
import threading
import time

import pytest

from nuri.core.brief_scope import brief_scope, in_brief_scope, memo, scoped


class TestMemo:
    def test_outside_scope_every_call_computes(self):
        calls = []
        for _ in range(3):
            memo("k", lambda: calls.append(1))
        assert len(calls) == 3 and not in_brief_scope()

    def test_inside_scope_computes_once_and_forgets_on_exit(self):
        calls = []
        with brief_scope():
            assert in_brief_scope()
            for _ in range(3):
                memo("k", lambda: calls.append(1) or "v")
            assert len(calls) == 1
        memo("k", lambda: calls.append(1))
        assert len(calls) == 2, "범위를 나가면 캐시가 남아 있으면 안 된다 — 상주 데몬이 낡은 가중치를 쓴다"

    def test_nested_scope_reuses_the_outer_cache(self):
        calls = []
        with brief_scope():
            memo("k", lambda: calls.append(1))
            with brief_scope():
                memo("k", lambda: calls.append(1))
            memo("k", lambda: calls.append(1))
        assert len(calls) == 1

    def test_unrelated_thread_does_not_see_the_scope(self):
        """겹친 API 요청·백그라운드 스레드는 다른 컨텍스트다 — 전역 카운터였을 때는 이게 공유됐다 (Codex P1)."""
        seen = {}
        with brief_scope():
            memo("k", lambda: "mine")
            t = threading.Thread(target=lambda: seen.update(inside=in_brief_scope(), v=memo("k", lambda: "theirs")))
            t.start()
            t.join()
        assert seen == {"inside": False, "v": "theirs"}

    def test_executor_workers_see_the_scope_when_submitted_scoped(self):
        """analyze_ticker 의 제출 형태 — 제출 스레드에서 scoped() 로 감싸야 워커가 같은 범위를 본다."""
        calls = []
        lock = threading.Lock()

        def compute():
            with lock:
                calls.append(1)
            return "v"

        with brief_scope():
            memo("k", compute)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                futs = [ex.submit(scoped(memo), "k", compute) for _ in range(8)]
                results = [f.result() for f in futs]
        assert results == ["v"] * 8 and len(calls) == 1

    def test_concurrent_cold_miss_computes_once(self):
        """8 스레드가 동시에 같은 키를 처음 요청 — single-flight 없이는 8번 계산한다 (Codex P2)."""
        calls = []
        lock = threading.Lock()
        gate = threading.Barrier(8)

        def compute():
            with lock:
                calls.append(1)
            time.sleep(0.05)  # 실제 원장 스캔의 축소판 — 지연이 없으면 GIL 스케줄링이 경쟁 창을 숨긴다
            return "v"

        def worker():
            gate.wait()
            return memo("k", compute)

        with brief_scope():
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                futs = [ex.submit(scoped(worker)) for _ in range(8)]
                results = [f.result() for f in futs]
        assert results == ["v"] * 8
        assert len(calls) == 1, f"cold miss 가 {len(calls)}번 계산됐다"

    def test_exception_is_not_cached(self):
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("x")

        with brief_scope():
            with pytest.raises(RuntimeError):
                memo("k", boom)
            with pytest.raises(RuntimeError):
                memo("k", boom)
            assert memo("k", lambda: "ok") == "ok"
        assert len(calls) == 2

    def test_late_worker_cannot_reach_the_next_brief(self):
        """타임아웃 뒤에 끝난 워커는 자기가 복사해 간 (끝난) 범위 객체에 쓴다 — 다음 브리프는 새 객체다 (Codex P1)."""
        release = threading.Event()

        def slow():
            release.wait(5)
            return "stale"

        with brief_scope():
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(scoped(memo), "k", slow)
        release.set()  # 범위가 끝난 뒤에야 워커가 끝난다
        assert fut.result(timeout=5) == "stale"
        ex.shutdown(wait=True)
        with brief_scope():
            assert memo("k", lambda: "fresh") == "fresh"
