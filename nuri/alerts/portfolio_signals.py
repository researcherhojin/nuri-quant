"""Mechanical portfolio-axis signals → #brief (Tier 1b: 집중도 드리프트 → REBALANCE).

Tier 1a(risk_signals) 가 alpha 축(손절선 이탈 → urgent SELL) 을 표면화했다면,
여기는 **portfolio 축**(#429): 종목 비중이 계좌별 `max_single_position` 한도를
넘으면 REBALANCE 로 surface. 결정론적 룰(예측 아님).

#429 축 분리 (엄밀): 집중도/드리프트는 `portfolio_action=REBALANCE` — **절대
urgent SELL 아님**(alpha_action=FLAT 은 손절선만). 따라서 여기 payload 는
kind="REBALANCE"(렌더러 Lower Priority 버킷) + **매도/청산 동사 금지 + entry/
stop/target price_levels 금지**(REBALANCE 는 alpha exit 가 아님). 문구는 "비중
조절 권고 — 수단·타이밍 사용자 판단".

검출은 재구현하지 않고 canonical `rebalance_advisor.detect_violations()` 를
재사용(per-account, 통화정확, 팩터정렬). 손절/레버리지 위반은 여기서 제외
(손절 = Tier 1a alpha 축, 중복 방지).

Privacy: Discord private 채널이므로 ticker+비중 노출 OK. 테스트는 합성 티커만.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Optional

from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

# pension 계좌 라벨 판별 — actions.py/decision_compiler.py 와 동일한 canonical
# 키워드 게이트. (get_account_strategy_name 은 Tier 1a #868 에만 있어 여기서 재정의
# 하면 머지 충돌 → 정착된 substring 패턴 재사용.)
_PENSION_KEYWORDS = ("연금", "pension", "irp")


def _is_pension_account(account: Optional[str]) -> bool:
    return any(kw in (account or "").lower() for kw in _PENSION_KEYWORDS)


def scan_concentration_drift(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """계좌별 단일종목 비중 한도 초과(집중도 드리프트) 목록.

    `detect_violations()` 중 `position_limit_exceeded` 만 필터 — 손절(alpha 축,
    Tier 1a)·레버리지·섹터는 제외. pension 계좌는 daily action 대상 아니므로 제외
    (postmarket brief 가 pension holdings 를 이미 숨기는데 pension REBALANCE 를
    매일 emit 하면 자기모순 — Tier 1a·_filter_actionable_accounts 와 동일 정책).
    반환 dict 는 rebalance_advisor 원본 (ticker/account/current_value/limit_value/...).
    """
    from nuri.analysis.rebalance_advisor import detect_violations

    violations = detect_violations(db_path=db_path)
    return [
        v
        for v in violations
        if v.get("violation_type") == "position_limit_exceeded" and not _is_pension_account(v.get("account"))
    ]


def _build_rebalance_payload(violation: dict[str, Any], date: str) -> dict[str, Any]:
    """집중도 위반 1건 → #brief REBALANCE payload.

    kind="REBALANCE" → 렌더러 `.get(kind, 2)` 로 Lower Priority 버킷(비긴급).
    price_levels 없음(alpha exit 아님), reason 은 매도 동사 없이 비중 조절 권고.

    Privacy: detect_violations 원본 reason 은 account 키(로마자 broker name)를
    포함하므로 재사용하지 않고 numeric 필드로 재구성한다. stage_brief 는 요약
    경로의 _privacy_gate_payload 를 안 거치므로 여기서 broker name egress 를 원천
    차단 (계좌는 dedupe_key 에만, 사용자 노출 X).
    """
    return {
        "kind": "REBALANCE",
        "ticker": violation["ticker"],
        "reason": (
            f"비중 {violation['current_value']:.1f}% > 한도 {violation['limit_value'] * 100:.0f}%"
            " — 비중 조절 권고 (수단·타이밍 사용자 판단)"
        ),
        "date": date,
    }


def stage_concentration_briefs(date: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """집중도 드리프트를 #brief outbox 에 REBALANCE 로 stage. staged 건수 반환.

    dedupe_key=`rebalance:position:{ticker}:{account}:{date}` — (ticker, account)
    × 하루 1건. priority="normal"(비긴급 — 손절 SELL 의 high 와 구분).
    non-None 만 카운트(dedupe skip → None).
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    drifts = scan_concentration_drift(db_path=db_path)
    staged = 0
    for v in drifts:
        payload = _build_rebalance_payload(v, d)
        outbox_id = stage_brief(
            payload=payload,
            dedupe_key=f"rebalance:position:{v['ticker']}:{v.get('account', '')}:{d}",
            priority="normal",
            actor_name="portfolio-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("concentration REBALANCE briefs staged: %d", staged)
    return staged


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="집중도 드리프트 → #brief REBALANCE (Tier 1b)")
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 위반 목록만 출력")
    args = parser.parse_args(argv)

    drifts = scan_concentration_drift()
    if not drifts:
        print("집중도 한도 초과 없음")
        return 0
    for v in drifts:
        print(
            f"  {v['ticker']} [{v.get('account', '?')}] {v['current_value']:.1f}% > 한도 {v['limit_value'] * 100:.0f}%"
        )
    if args.dry_run:
        print(f"[dry-run] {len(drifts)}건 — stage 안 함")
        return 0
    staged = stage_concentration_briefs()
    print(f"staged {staged}건 → #brief (REBALANCE)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
