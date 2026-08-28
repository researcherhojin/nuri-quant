"""USD/KRW 환율의 **단일 읽기 지점** (#1278).

## 왜 생겼나

"최신 환율" 을 `ORDER BY date DESC LIMIT 1` 로 읽는 곳이 **8군데** 흩어져 있었고,
전부 **날짜 상한이 없었다.** `macro` 에 미래 날짜 행이 하나라도 들어오면 그게 영구히
"최신" 자리를 차지한다.

2026-08-29 실측 — dev DB 에 `toss` 소스의 미래 행 3건(`2026-11-08` · `2027-02-06` ·
`2027-09-14`)이 섞여 있었고, `get_exchange_rate()` 가 **1417.4** 를 반환했다. 같은 시각
정상 최신 행은 `2026-08-21 1385.01`(FRED), 프로덕션은 `1383.35`. 오차 +2.46% 가
모든 KRW 환산 총액·계좌 비중·현금 합산에 곱해진다.

`2027-09-14` 행은 **1년 넘게** 최신 자리를 지킨다 — 시간이 지나도 스스로 낫지 않는다.

## 왜 읽는 쪽에 방어를 두나

미래 행의 출처는 미상이다. `collectors/macro.py` 의 toss 경로는 `date: today_kst()` 를
쓰므로 **자기 힘으로는 미래 날짜를 만들 수 없다** — 테스트/에이전트의 dev DB 오염이
유력하고, 이 레포는 전례가 있다. **그래서 더더욱 읽는 쪽이 막아야 한다**: 행이 어떻게
들어왔든 미래 환율을 "현재" 로 쓰면 안 된다. 쓰는 쪽에 규율을 요구하면 새 writer 가
생길 때마다 다시 샌다 (#1279 캐시 버전 키와 같은 논리).

## 미래 행을 조용히 버리지 않는다

버리기만 하면 수집기 결함이 영영 안 보인다. 발견 시 WARNING 을 남긴다 — 다만 그
진단이 **본 작업을 게이트하면 안 되므로**(#894) 자체 try 로 감싸고 실패해도 환율은 낸다.
"""

from __future__ import annotations

import logging

from nuri.core.db import DatabaseError, OperationalError, query
from nuri.core.ticker_names import is_kr_ticker
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)


def _warn_if_future_rows(today: str, db_path=None) -> None:
    """미래 날짜 행이 있으면 경고. 진단 전용 — 실패해도 호출자를 막지 않는다 (#894)."""
    try:
        rows = query(
            "SELECT COUNT(*) AS n, MAX(date) AS mx FROM macro WHERE indicator = 'usd_krw' AND date > ?",
            (today,),
            db_path=db_path,
        )
    except (OperationalError, DatabaseError):
        return
    if rows and rows[0]["n"]:
        logger.warning(
            "usd_krw 에 미래 날짜 행 %d건 (최대 %s) — 무시하고 오늘 이하 최신을 쓴다. "
            "수집기 결함이거나 DB 오염이니 원인을 확인할 것 (#1278)",
            rows[0]["n"],
            rows[0]["mx"],
        )


def latest_usd_krw(db_path=None) -> tuple[float, str] | None:
    """오늘(KST) 이하에서 가장 최신인 USD/KRW 와 그 날짜. 없으면 `None`.

    **숫자를 지어내지 않는다** — 부재는 `None` 이고, 무엇으로 메울지는 호출자가 정한다
    (STRATEGY §2.6 의 VIX 게이트와 같은 원칙).
    """
    today = today_kst()
    _warn_if_future_rows(today, db_path=db_path)
    rows = query(
        "SELECT value, date FROM macro WHERE indicator = 'usd_krw' AND date <= ? ORDER BY date DESC LIMIT 1",
        (today,),
        db_path=db_path,
    )
    if not rows or rows[0]["value"] is None:
        return None
    # 환율은 **양수**다. 0 이나 음수는 손상된 행이지 환율이 아니므로 부재로 다룬다 (#1283).
    # 이 불변식이 없으면 0.0 이 "값이 있다" 로 통과해 호출자마다 다르게 터진다 — 나눗셈
    # 하는 쪽은 ZeroDivisionError, `or` 폴백을 둔 쪽은 조용히 지어낸 숫자.
    value = float(rows[0]["value"])
    if value <= 0:
        logger.warning("usd_krw 값이 %s (날짜 %s) — 환율이 아니므로 부재로 다룬다 (#1283)", value, rows[0]["date"])
        return None
    return value, str(rows[0]["date"])


def latest_usd_krw_value(db_path=None) -> float | None:
    """`latest_usd_krw` 의 값만 필요한 호출자를 위한 얇은 래퍼."""
    got = latest_usd_krw(db_path=db_path)
    return got[0] if got else None


#: 환산 불가 사유 — 사람이 읽는 문장. 조용한 빈칸은 결함처럼 보이므로 **이유를 같이** 낸다.
FX_UNAVAILABLE_REASON = (
    "USD/KRW 미수집 — 원화 자산이 있어 통화 혼합 합계를 낼 수 없습니다 (`make collect` 으로 환율 갱신)"
)


def is_krw_holding(ticker, currency) -> bool:
    """이 보유가 원화 표시인가. **레포 정본 술어** (#1283 codex P1).

    `currency == "KRW"` 이거나 `.KS`/`.KQ`. 접미사만 보면 `currency="KRW"` 인 무접미
    보유가 "달러 자산" 으로 오분류된다. 같은 식이 `analysis/portfolio.py` ·
    `analysis/sector.py` · `alerts/risk_signals.py` 에 인라인으로 흩어져 있고, 그 통합은
    #1286 이 다룬다 — 여기서는 새 사본을 만들지 않으려고 이 함수를 쓴다.
    """
    return currency == "KRW" or is_kr_ticker(str(ticker))


def cross_currency_unavailable(rate: float | None, has_krw_exposure: bool) -> str | None:
    """통화 혼합 합계를 낼 수 있나. 낼 수 있으면 `None`, 없으면 사유 문자열.

    ## 왜 이 판단이 한 곳에 있어야 하나

    환율이 없을 때 무엇이 불가능해지는지는 **분모** 하나로 정해진다. 총 자산·계좌별
    평가액·비중%·자산배분은 전부 "원화 자산과 달러 자산을 더한 값" 을 분모로 쓰므로,
    원화 보유가 하나라도 있으면 **그 합계 전체가 미상**이 된다 — KR 종목만 미상인 게
    아니다. 비중의 분모가 미상이면 US 종목의 비중도 말할 수 없다.

    반대로 **환산이 필요 없는 것은 그대로 정확하다**: 종목별 현재가·수량, 한 통화 안에서
    계산되는 손익률, 그리고 원화 자산이 전혀 없는 포트폴리오의 모든 합계.

    이 구분을 소비자마다 다시 유도하면 갈린다 — 실제로 #1283 이 고친 4곳이 서로 다른
    상수(1400 / 1450)를 쓰고 있었다.
    """
    if rate is not None or not has_krw_exposure:
        return None
    return FX_UNAVAILABLE_REASON
