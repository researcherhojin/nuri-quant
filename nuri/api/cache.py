"""API 응답 캐시의 **포트폴리오 버전 키** (#1279).

## 왜 TTL 만으로는 부족한가

`actions.py` / `dashboard.py` 의 모듈 캐시는 프로세스 로컬이고 **write-blind** 다.
게다가 포트폴리오를 바꾸는 정상 경로(`scripts/ops/import_portfolio.py`)는 API 를
거치지 않고 **DB 에 직접 쓴다** — POST 조차 아니라서 API 프로세스는 변경 사실을
알 방법이 없고, TTL 만료(5분)만이 유일한 복구 경로였다.

그 5분이 위험한 이유는 단순히 숫자가 낡아서가 아니다. 2026-08-29 실측: 보유를
갱신한 직후 `/api/actions` 가 현대차를 **`urgent` 버킷 · conf 100 · "손절선 -20%
돌파"** 로 반환했는데 실제 손익은 -13.1% 로 돌파하지 않았다. -31.9% 는 갱신 **전**
평단으로 계산된 값이었다. 그리고 "보유를 갱신하고 바로 대시보드를 연다" 는 가장
자연스러운 순서라, 거짓 신호 창과 사용자의 확인 시점이 정확히 겹친다.

## 왜 무효화 엔드포인트가 아니라 버전 키인가

`POST /api/cache/invalidate` 를 두고 import 스크립트가 부르게 할 수도 있다. 하지만
그건 **프로세스 경계를 타는** 해법이라 세 가지로 샌다: (1) API 가 안 떠 있으면
무효화가 유실되고, (2) 앞으로 생길 다른 writer(수동 SQL, 다른 스크립트, 백필)가
호출을 빠뜨리면 조용히 되살아나고, (3) 워커가 여러 프로세스면 하나만 비워진다.

버전 키는 **읽는 쪽에 방어를 둔다** — 데이터가 어떻게 바뀌었든 캐시가 스스로
알아챈다. 이 레포가 반복해서 배운 형태다(쓰는 쪽에 규율을 요구하면 새 writer 가
생길 때마다 다시 샌다).
"""

from __future__ import annotations

import logging

from nuri.core.db import DatabaseError, OperationalError, query

logger = logging.getLogger(__name__)

#: 버전을 읽지 못했을 때의 고정 sentinel. **매번 다른 값을 돌려주면 안 된다** —
#: 캐시가 영구 미스가 되어 무거운 핸들러가 매 요청 재계산된다(#1119 의 stampede).
#: 조회 실패는 TTL-only 동작으로 degrade 시키고, 대신 로그를 남긴다.
_UNKNOWN = "unknown"


def portfolio_version(db_path=None) -> str:
    """포트폴리오의 현재 버전 문자열. 보유가 바뀌면 값이 바뀐다.

    `COUNT(*)` 와 `MAX(updated_at)` 을 **함께** 쓴다. `MAX` 만 보면 행이 삭제되기만
    한 경우(남은 행의 타임스탬프는 그대로)를 놓친다. 반대로 `COUNT` 만 보면 수량·평단만
    바뀐 갱신을 놓친다. 두 축이 서로의 사각을 덮는다.
    """
    try:
        rows = query("SELECT COUNT(*) AS n, MAX(updated_at) AS mx FROM portfolio", db_path=db_path)
    except (OperationalError, DatabaseError):
        # 진단이 본 작업을 게이트하면 안 된다 (#894) — 캐시는 TTL 로 계속 동작한다.
        logger.warning("portfolio 버전 조회 실패 — 캐시가 TTL 만으로 동작한다", exc_info=True)
        return _UNKNOWN
    if not rows:
        return _UNKNOWN
    return f"{rows[0]['n']}:{rows[0]['mx']}"
