"""§3.11 측정 모드 실험 슬리브 — 소속 판별 + 계좌별 사용률 (#834).

`config/rules.yaml measurement_mode.sleeve_max_equity_pct` 는 선언만 되어 있고
읽는 코드가 없었다. 이 모듈이 그 유일한 소비 지점이며, `rebalance_advisor`(초과 →
REBALANCE 권고)와 `ExecutionFirewall`(잔여 소진 → 신규 BUY 차단) 둘 다 여기서
계산을 가져간다. 두 곳에 각자 구현하면 오늘 종일 본 drift 가 그대로 재현된다.

**소속 판별이 이 모듈의 핵심이자 유일한 함정이다.**
슬리브는 "측정 모드 이후 시스템 추천을 **실행해** 투입된 자본"이다. 티커가 BUY 추천에
등장했다는 사실만으로는 부족하다 — 실측(2026-07-28) 상 사전등록일 이후 BUY 추천 종목이
**전부 이미 보유 중**이었고, 다수는 측정 모드보다 한참 앞서 열린 포지션이었다. 등장만으로
판정하면 기존 보유가 통째로 슬리브로 오분류돼 사용률이 허구가 되고, 그 숫자가 신규
매수를 차단한다.

그래서 **두 조건을 모두** 요구한다:
  1. `portfolio.first_buy_date >= declared_date` — 측정 모드 이후 새로 연 포지션
  2. 그 창 안에서 해당 티커에 BUY 추천 이력 존재 — 시스템 추천에 기인

#848 위임 결정 "기존보유 제외" 가 (1) 이다. 실측상 현재 슬리브는 비어 있다(사용률 0%).

축(#429): 초과는 **portfolio_action=REBALANCE** 로만 표면화한다. 슬리브 초과는
alpha 신호가 아니므로 SELL/청산으로 승격하지 않는다 (STRATEGY §3.11 "cap-breach
resolution surfaces as portfolio_action=REBALANCE only").
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from nuri.core.db import query
from nuri.core.rules import RULES

logger = logging.getLogger(__name__)

# 슬리브 상한이 적용되지 않는 자산군 — 상한은 주식(us_equity + kr_equity) 대비 비율이다.
_EQUITY_CURRENCIES = ("USD", "KRW")


def _measurement_mode() -> dict[str, Any]:
    mm = RULES.get("measurement_mode")
    if not mm:
        raise RuntimeError("config/rules.yaml 에 measurement_mode 블록 없음 (§3.11)")
    return mm


def sleeve_caps() -> dict[str, float]:
    """account_strategy → 상한 %. canonical 소스는 rules.yaml 뿐이다."""
    caps = _measurement_mode().get("sleeve_max_equity_pct") or {}
    return {str(k): float(v) for k, v in caps.items()}


def sleeve_members(db_path: Optional[Path] = None) -> set[tuple[str, str]]:
    """슬리브 소속 `(account, ticker)` 집합.

    두 조건 **모두** 만족해야 한다 — 모듈 docstring 의 오분류 함정 참조.
    """
    mm = _measurement_mode()
    declared = str(mm["declared_date"])

    recommended = {
        row["ticker"]
        for row in query(
            """SELECT DISTINCT r.ticker
               FROM recommendations r
               JOIN agent_decisions ad ON ad.decision_id = ? || r.id
               WHERE ad.action = ? AND r.date >= ?""",
            ("rec_", "BUY", declared),
            db_path=db_path,
        )
    }
    if not recommended:
        return set()

    return {
        (str(row["account"]), str(row["ticker"]))
        for row in query(
            "SELECT account, ticker FROM portfolio WHERE ticker <> ? AND first_buy_date >= ?",
            ("", declared),
            db_path=db_path,
        )
        if str(row["ticker"]) in recommended
    }


def sleeve_utilization(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """계좌별 슬리브 사용률.

    Returns: `[{account, strategy, cap_pct, sleeve_usd, equity_usd, used_pct, over}]`
    상한이 정의되지 않은 전략은 건너뛴다(판정 대상 아님).
    """
    from nuri.analysis.portfolio import analyze_portfolio
    from nuri.core.rules import get_account_strategy_name

    # analyze_portfolio() 는 db_path 를 받지 않는다 (기본 DB 고정). 테스트는
    # 이 함수를 patch 하거나 sleeve_members/caps 를 직접 검증한다.
    df = analyze_portfolio()
    if df.empty:
        return []

    members = sleeve_members(db_path=db_path)
    caps = sleeve_caps()
    out: list[dict[str, Any]] = []

    for account, grp in df.groupby("account"):
        strategy = get_account_strategy_name(str(account))
        if strategy not in caps:
            continue
        equity = float(grp["current_value_usd"].sum())
        if equity <= 0:
            continue
        sleeve = float(grp[grp["ticker"].isin([t for a, t in members if a == str(account)])]["current_value_usd"].sum())
        used = sleeve / equity * 100.0
        cap = caps[strategy]
        out.append(
            {
                "account": str(account),
                "strategy": strategy,
                "cap_pct": cap,
                "sleeve_usd": round(sleeve, 2),
                "equity_usd": round(equity, 2),
                "used_pct": round(used, 2),
                "over": used > cap,
            }
        )
    return out


def sleeve_headroom(account: str, db_path: Optional[Path] = None) -> Optional[float]:
    """해당 계좌의 잔여 슬리브 여력(USD). 상한 미정의 전략이면 None(=제한 없음).

    ExecutionFirewall 이 신규 BUY 를 판단할 때 쓴다. 0 이하면 여력 소진.
    """
    for row in sleeve_utilization(db_path=db_path):
        if row["account"] == account:
            return round(row["equity_usd"] * row["cap_pct"] / 100.0 - row["sleeve_usd"], 2)
    return None
