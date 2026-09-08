"""브리프 1회 범위의 메모 — 종목과 무관한 계산을 종목마다 되풀이하지 않는다 (#1499).

`gather_context()` 한 번이 `analyze_ticker` 를 18종목에 돌리며 `compute_canonical_weights`(원장 스캔)를 18회,
`classify_regime` 을 23회 계산했다 — mini 실측 34.6s 중 22s. 둘 다 입력이 종목과 무관하다.

설계 (Codex #1499 P1/P2 반영):
- **범위는 객체다.** `brief_scope()` 가 `_Scope` 를 만들어 ContextVar 에 건다. 무관한 스레드·겹친 API 요청은
  다른 컨텍스트라 캐시를 공유하지 않는다 — 전역 depth 카운터였을 때는 프로세스의 모든 활성 범위가 하나로
  합쳐졌다. **Test:** `tests/core/test_brief_scope.py::TestMemo::test_unrelated_thread_does_not_see_the_scope`
- **워커에는 명시적으로 전파한다.** ContextVar 는 ThreadPoolExecutor 로 저절로 넘어가지 않는다.
  `analyze_ticker` 가 `scoped(fn)` 으로 제출한다 — 제출 스레드에서 제출마다 컨텍스트를 복사해 워커에 넘긴다.
  **Test:** `tests/core/test_brief_scope.py::TestMemo::test_executor_workers_see_the_scope_when_submitted_scoped`
- **늦은 워커는 다음 브리프로 새지 않는다.** 타임아웃 뒤에 끝난 워커는 자기가 복사해 간 (이미 끝난) 범위
  객체에 쓴다 — 다음 브리프는 새 객체라 닿을 수 없다. 별도 플래그는 두지 않는다(관측 불가능한 방어 코드).
  **Test:** `tests/core/test_brief_scope.py::TestMemo::test_late_worker_cannot_reach_the_next_brief`
- **범위 밖에서는 캐시하지 않는다.** 상주 스케줄러는 07:02 outcome tracking 뒤 07:05 consensus 를 같은
  프로세스에서 돌린다 — 프로세스 전역/TTL 캐시였다면 갱신 전 가중치를 그대로 썼을 것이다.
  **Test:** `tests/core/test_brief_scope.py::TestMemo::test_inside_scope_computes_once_and_forgets_on_exit`
- **키당 single-flight.** 같은 키의 동시 cold miss 는 하나만 계산한다. 예외는 캐시하지 않고 그대로 올린다.
  **Test:** `tests/core/test_brief_scope.py::TestMemo::test_concurrent_cold_miss_computes_once`
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from typing import Any


class _Scope:
    __slots__ = ("cache", "key_locks", "lock")

    def __init__(self) -> None:
        self.cache: dict[Hashable, Any] = {}
        self.key_locks: dict[Hashable, threading.Lock] = {}
        self.lock = threading.Lock()


_current: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar("nuri_brief_scope", default=None)


@contextmanager
def brief_scope() -> Iterator[None]:
    """이 블록(과 `run_in_scope` 로 전파한 워커) 안에서 `memo()` 가 결과를 재사용한다. 중첩은 바깥을 재사용."""
    if _current.get() is not None:
        yield
        return
    scope = _Scope()
    token = _current.set(scope)
    try:
        yield
    finally:
        _current.reset(token)  # 캐시는 범위 객체와 함께 버려진다


def in_brief_scope() -> bool:
    return _current.get() is not None


def scoped(fn: Callable[..., Any]) -> Callable[..., Any]:
    """executor.submit 용 — **제출하는 스레드에서** 컨텍스트(현재 범위 포함)를 복사해 워커가 그 안에서 돌게 한다.

    복사는 호출 시점에 일어나야 한다: 워커 안에서 copy_context() 를 부르면 워커의 빈 컨텍스트가 복사된다.
    제출마다 새로 복사해야 한다 — 하나의 Context 는 동시에 두 스레드가 enter 할 수 없다.
    """
    ctx = contextvars.copy_context()
    return lambda *args, **kwargs: ctx.run(fn, *args, **kwargs)


def memo(key: Hashable, fn: Callable[[], Any]) -> Any:
    """범위 안이면 key 로 한 번만 계산, 밖이면 그냥 계산 — 호출자는 범위 유무를 몰라도 된다."""
    scope = _current.get()
    if scope is None:
        return fn()
    with scope.lock:
        if key in scope.cache:
            return scope.cache[key]
        key_lock = scope.key_locks.setdefault(key, threading.Lock())
    with key_lock:  # single-flight — 같은 키의 동시 miss 는 하나만 계산
        with scope.lock:
            if key in scope.cache:
                return scope.cache[key]
        value = fn()  # 예외는 캐시하지 않고 그대로 전파
        with scope.lock:
            scope.cache[key] = value
        return value
