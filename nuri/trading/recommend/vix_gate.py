"""VIX 게이트 입력 — 단일 출처.

**왜 별도 모듈인가**: 같은 규칙이 두 곳에 흩어져 있었고 한쪽만 고쳐졌다.
`buy_candidate_emitter` 는 부재를 `20.0` 으로, `candidates` 는 `0.0` 으로 메웠다.
둘 다 차단(>30)·caution(≥25) 임계 **아래**라, 측정 불가가 조용히 '평온'으로 둔갑해
게이트를 열었다. `0.0` 쪽은 API 4개 라우트 · LLM 리포트 · 리밸런스가 소비한다.

**정책** (STRATEGY §2.6, 2026-08-10 채택): 위험 게이트의 입력 부재는 그 게이트의 가장
보수적 관측치와 같은 등급 — VIX 미상은 caution 과 동일한 Soft penalty(절반 포지션).
지어낸 숫자를 돌려주지 않고 `None` 을 돌려 부르는 쪽이 그렇게 처리하게 한다.

**노후 판정은 영업일 기준**이다. 달력일로 재면 월요일 휴장 뒤 화요일에 금요일 VIX 가
4일치가 되어 **정상 데이터인데 미상**으로 떨어진다 (Codex 리뷰 2026-08-10). VIX 는
미국 장이 열려야 갱신되므로 주말·단일 휴장은 영업일 계산이 자동으로 흡수한다.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np

from nuri.core.db import DatabaseError, OperationalError, query_df
from nuri.core.rules import VIX_MAX_AGE_BUSINESS_DAYS
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)


def latest_vix(db_path=None) -> float | None:
    """최신 VIX. 없거나·조회 실패·노후면 **None** — 숫자를 지어내지 않는다.

    VIX 는 macro 테이블(indicator='vix')에만 수집된다. `prices.VIX` 는 미수집이라
    그 경로를 읽으면 항상 폴백으로 떨어져 게이트가 무력화된다 (#753).
    """
    # 조회만 감싼다. 이후 계산까지 넣으면 그 안의 **코딩 오류**가 "VIX 미상" 으로 위장해
    # 영구 반포지션이 된다 — 초안에서 `today_kst()`(str)에 timedelta 를 빼다 난 TypeError 를
    # 넓은 except 가 삼켰다.
    try:
        rows = query_df(
            "SELECT date, value FROM macro WHERE indicator = 'vix' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
    except (OperationalError, DatabaseError):
        logger.warning("VIX 조회 실패 — 미상 처리", exc_info=True)
        return None

    if rows.empty:
        logger.warning("macro 에 VIX 행이 없음 — 미상 처리")
        return None

    # 파싱은 별도로 감싼다: 깨진 date 문자열·컬럼 누락은 상류 **데이터 결함**이지
    # 이 함수의 버그가 아니다. 그걸로 emitter 전체를 죽이면 안 된다 (Codex P2).
    # TypeError 는 일부러 안 잡는다 — 그건 코딩 오류다.
    try:
        observed = date.fromisoformat(str(rows["date"].iloc[0])[:10])
        value = float(rows["value"].iloc[0])
    except (ValueError, KeyError, IndexError):
        logger.warning("VIX 행이 깨졌음 — 미상 처리", exc_info=True)
        return None

    age = int(np.busday_count(observed, date.fromisoformat(today_kst())))
    if age > VIX_MAX_AGE_BUSINESS_DAYS:
        logger.warning("VIX 가 영업일 %d일 노후(임계 %d) — 미상 처리", age, VIX_MAX_AGE_BUSINESS_DAYS)
        return None
    return value
