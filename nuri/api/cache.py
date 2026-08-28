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

import hashlib
import logging

from nuri.core.db import DatabaseError, OperationalError, query

logger = logging.getLogger(__name__)

#: 버전을 읽지 못했을 때의 고정 sentinel. **매번 다른 값을 돌려주면 안 된다** —
#: 캐시가 영구 미스가 되어 무거운 핸들러가 매 요청 재계산된다(#1119 의 stampede).
#: 조회 실패는 TTL-only 동작으로 degrade 시키고, 대신 로그를 남긴다.
_UNKNOWN = "unknown"


def portfolio_version(db_path=None) -> str:
    """포트폴리오의 현재 버전. **보유 내용 자체**의 해시다.

    타임스탬프가 아니라 내용을 해싱하는 이유 — 초안은 `COUNT(*) + MAX(updated_at)` 이었고
    세 축에서 뚫렸다 (codex 리뷰 P1 + 실측):

    1. **같은 초 안의 연속 갱신** — `upsert_portfolio` 는 `datetime('now')`, 즉 **초
       해상도**로 찍는다. 1초 안에 같은 행을 두 번 쓰면(연속 수동 편집, 다계좌 일괄 sync)
       행 수도 타임스탬프도 그대로라 버전이 안 바뀐다. 초안 테스트가 `time.sleep(1.05)`
       를 넣어야 통과했다는 게 이미 그 증거였다 — 우회로 덮은 셈이다.
    2. **상쇄되는 변경** — `SUM(quantity)` 같은 집계로 바꿔도 A 에서 -1, B 에서 +1 이면
       합계가 같아 못 잡는다 (실측 확인).
    3. 삭제·행 수 변화는 해시가 자연히 덮는다.

    내용 해시는 이 셋을 한 번에 닫는다. 비용은 보유 행 수에 비례하지만 이 테이블은
    **한 사람의 보유**라 수십 행 규모이고, 캐시 히트를 지키는 대가로 붙는 유일한 DB
    작업이다 (miss 시 핸들러는 초 단위다).

    반대로 **내용이 같으면 버전도 같아야** 한다 — 재import 가 실제 변경 없이 끝났을 때
    캐시를 버리면 무거운 핸들러가 헛돈다. 그래서 `updated_at` 은 해시에 넣지 않는다.
    """
    try:
        rows = query(
            "SELECT account, ticker, quantity, avg_price, currency, sector FROM portfolio",
            db_path=db_path,
        )
    except (OperationalError, DatabaseError):
        # 진단이 본 작업을 게이트하면 안 된다 (#894) — 캐시는 TTL 로 계속 동작한다.
        logger.warning("portfolio 버전 조회 실패 — 캐시가 TTL 만으로 동작한다", exc_info=True)
        return _UNKNOWN
    # SQL 의 행 순서는 보장되지 않는다 — 정렬하지 않으면 같은 내용이 다른 해시를 낸다.
    payload = "\n".join(
        sorted(
            f"{r['account']}|{r['ticker']}|{r['quantity']}|{r['avg_price']}|{r['currency']}|{r['sector']}" for r in rows
        )
    )
    return f"{len(rows)}:{hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()}"
