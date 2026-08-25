"""무거운 엔드포인트 동시성 상한 (#1119).

라우트는 동기 `def` 라 AnyIO 스레드풀(기본 40)에서 돈다. 무거운 핸들러
(/api/report 26.7s, /api/report/context 161s 실측 등)가 풀을 독식하면
`/api/health` 를 포함한 모든 요청이 그 뒤에 줄을 서고, 클라이언트가 끊어도
핸들러는 계속 돌아 부하가 끝난 뒤에도 백로그가 남는다 (#1119 실측: 유휴
0.015s → 포화 46.7s, 종료 수 분 뒤에도 57s).

처방: 무거운 라우트만 전용 슬롯(기본 8)을 지나가게 한다. **비블로킹 획득** —
슬롯이 없으면 기다리지 않고 즉시 503 을 돌려준다 (대기 자체가 풀 스레드를
소모하므로 blocking 획득은 문제를 재생산한다). 가벼운 라우트는 항상 남은
32개 스레드를 쓸 수 있어 포화가 구조적으로 불가능해진다.

단일-플라이트 TTL 캐시(#1119 선행 수정)와의 관계: 캐시는 재계산을 1회로
줄이지만 **대기자들이 스레드를 점유**하는 건 못 막는다 — 슬롯이 그 대기자
수를 8로 자른다.

한계: 이미 실행 중인 핸들러는 취소할 수 없다 (동기 스레드 — Python 의
구조적 한계). 이 모듈은 새 요청의 유입만 제어한다.
"""

import logging
import os
import threading

from fastapi import HTTPException

logger = logging.getLogger(__name__)

#: 무거운 핸들러 동시 실행 상한. 스레드풀 40 중 8 — 나머지 32는 가벼운 라우트 몫.
#: 인프라 튜닝 값이라 config/rules.yaml(투자 룰)이 아닌 env 로 조정한다.
DEFAULT_HEAVY_SLOTS = 8


def _slots_from_env() -> int:
    """env 파싱 — 비정상 값은 기본값으로 강등 (관측은 로그만, 기동은 막지 않는다)."""
    raw = os.getenv("NURI_API_HEAVY_SLOTS", "")
    if not raw:
        return DEFAULT_HEAVY_SLOTS
    try:
        n = int(raw)
    except ValueError:
        logger.warning("NURI_API_HEAVY_SLOTS=%r 파싱 실패 — 기본값 %d 사용", raw, DEFAULT_HEAVY_SLOTS)
        return DEFAULT_HEAVY_SLOTS
    if n < 1:
        logger.warning("NURI_API_HEAVY_SLOTS=%d 는 1 미만 — 기본값 %d 사용", n, DEFAULT_HEAVY_SLOTS)
        return DEFAULT_HEAVY_SLOTS
    return n


_heavy_slots = threading.BoundedSemaphore(_slots_from_env())


def heavy_slot():
    """FastAPI dependency — 무거운 라우트 데코레이터에 `dependencies=[Depends(heavy_slot)]`.

    비블로킹: 슬롯이 없으면 즉시 503 (Retry-After: 5). 클라이언트 메시지는
    generic (스택/내부 상태 노출 금지 — 이 디렉터리의 에러 컨벤션).
    """
    if not _heavy_slots.acquire(blocking=False):
        logger.warning("heavy slot 포화 — 503 shed")
        raise HTTPException(
            status_code=503,
            detail="서버가 무거운 요청을 처리 중입니다. 잠시 후 다시 시도하세요.",
            headers={"Retry-After": "5"},
        )
    try:
        yield
    finally:
        _heavy_slots.release()
