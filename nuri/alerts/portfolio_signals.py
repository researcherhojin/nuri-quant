"""Mechanical portfolio-axis signals → #brief (Tier 1b 집중도 · 1c 섹터 · 1d 슬리브 → REBALANCE).

Tier 1a(risk_signals) 가 alpha 축(손절선 이탈 → urgent SELL) 을 표면화했다면,
여기는 **portfolio 축**(#429): (1b) 종목 비중이 계좌별 `max_single_position` 한도,
(1c) 섹터 합산 비중이 `max_sector_exposure` 한도, (1d) §3.11 실험 슬리브가 계좌
전략별 `sleeve_max_equity_pct` 상한을 넘으면 REBALANCE 로 surface. 결정론적 룰(예측 아님).

#429 축 분리 (엄밀): 집중도/드리프트는 `portfolio_action=REBALANCE` — **절대
urgent SELL 아님**(alpha_action=FLAT 은 손절선만). 따라서 여기 payload 는
kind="REBALANCE"(렌더러 Lower Priority 버킷) + **매도/청산 동사 금지 + entry/
stop/target price_levels 금지**(REBALANCE 는 alpha exit 가 아님). 문구는 "비중
조절 권고 — 수단·타이밍 사용자 판단".

검출은 재구현하지 않고 canonical `rebalance_advisor.detect_violations()` 를
재사용(per-account, 통화정확, 팩터정렬). 손절/레버리지 위반은 여기서 제외
(손절 = Tier 1a alpha 축, 중복 방지).

Tier 1e (`INPUT_STALE`, #1090) 는 이 셋과 성격이 다르다 — **포지션 신호가 아니라 관측
신뢰도 경고**다. 그래서 축(`alpha_action`/`portfolio_action`)을 만들지 않는다. 포트폴리오가
15일(360.5h) 낡은 채로 지나간 적이 있는데, `get_freshness_summary` 는 정상 동작했지만 결과가
프리마켓 임베드 **색**으로만 표현돼 사용자가 매일 읽는 카드 스트림에 안 떴다.

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


def scan_sector_drift(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """섹터 합산 비중 한도(`max_sector_exposure`) 초과 목록 — 섹터당 1건.

    `detect_violations()` 중 `sector_limit_exceeded` 만 필터. 섹터 위반은 트림
    대상 종목당 1건씩 나오므로 `sector` 필드로 dedup 해 섹터당 1건으로 collapse
    (detect_violations 는 Unknown/빈 섹터를 이미 제외).

    **의도적 설계 — 섹터는 pension 포함 total 위험 (1b 집중도와 스코프 다름)**:
    섹터 캡은 코드베이스 전체가 **global** 로 강제한다 — detect_violations 와
    certification 모두 계좌별이 아니라 portfolio-wide 합에 flat `MAX_SECTOR_EXPOSURE`
    (0.35) 를 적용(per-account 섹터 캡은 config 에 있으나 미구현·deferred). 따라서
    섹터 비중은 pension 을 포함한 **총 섹터 노출**이며 이는 룰 정의와 일치한다.
    1b 집중도가 pension 을 제외하는 건 그게 **per-account** 룰이라서고(pension 은
    자체 높은 캡), 섹터는 global 룰이라 total 로 보는 게 정합. drawback: 드물게
    섹터 초과가 pension-주도면 daily-actionable sleeve 에서 트림할 게 적을 수 있으나,
    총위험 가시성이 목적이므로 수용(사용자는 non-pension 종목 트림으로 총 노출 감축).
    """
    from nuri.analysis.rebalance_advisor import detect_violations

    violations = detect_violations(db_path=db_path)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for v in violations:
        if v.get("violation_type") != "sector_limit_exceeded":
            continue
        sector = v.get("sector")
        if not sector or sector in seen:
            continue
        seen.add(sector)
        out.append(v)
    return out


def _build_sector_rebalance_payload(violation: dict[str, Any], date: str) -> dict[str, Any]:
    """섹터 위반 1건 → #brief REBALANCE payload. ticker 슬롯에 섹터명 표시.

    집중도(1b)와 동일 #429 규칙: kind="REBALANCE"(Lower Priority), price_levels
    없음, 매도 동사 없음. 섹터명은 public 라벨(broker name 아님)이라 노출 OK.
    """
    return {
        "kind": "REBALANCE",
        "ticker": violation["sector"],
        "reason": (
            f"섹터 비중 {violation['current_value']:.1f}% > 한도 {violation['limit_value'] * 100:.0f}%"
            " — 비중 조절 권고 (수단·타이밍 사용자 판단)"
        ),
        "date": date,
    }


def stage_sector_briefs(date: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """섹터 드리프트를 #brief outbox 에 REBALANCE 로 stage. staged 건수 반환.

    dedupe_key=`rebalance:sector:{sector}:{date}` — 섹터 × 하루 1건.
    priority="normal". non-None 만 카운트.
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    drifts = scan_sector_drift(db_path=db_path)
    staged = 0
    for v in drifts:
        payload = _build_sector_rebalance_payload(v, d)
        outbox_id = stage_brief(
            payload=payload,
            dedupe_key=f"rebalance:sector:{v['sector']}:{d}",
            priority="normal",
            actor_name="portfolio-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("sector REBALANCE briefs staged: %d", staged)
    return staged


def scan_sleeve_breach(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """§3.11 실험 슬리브 상한 초과 계좌 목록 (Tier 1d).

    `sleeve_utilization()` 이 canonical 계산이고 여기는 필터만 한다 — 상한은
    `rules.yaml measurement_mode.sleeve_max_equity_pct` 단일 출처.

    1b/1c 와 달리 **pension 을 제외하지 않는다**: pension/long_term 의 상한은 0 이라
    "시스템 추천 자본이 한 푼도 들어가면 안 되는 계좌"라는 뜻이고, 그 위반은 daily
    action 대상이 아니라 사전등록 위반이다. 조용히 감추면 판정일에 표본이 오염된
    채로 발견된다.
    """
    from nuri.analysis.sleeve import sleeve_utilization

    return [row for row in sleeve_utilization(db_path=db_path) if row["over"]]


def _build_sleeve_rebalance_payload(row: dict[str, Any], date: str) -> dict[str, Any]:
    """슬리브 초과 1건 → #brief REBALANCE payload.

    1b/1c 와 동일 #429 규칙: kind="REBALANCE", price_levels 없음, 매도 동사 없음.
    §3.11 은 "cap-breach resolution surfaces as portfolio_action=REBALANCE only" 로
    이 축을 명시 고정한다 — 슬리브 초과를 청산 신호로 승격하면 사전등록 위반이다.

    Privacy: ticker 슬롯에 계좌 키(로마자 broker name) 대신 **전략 라벨**(core/active/
    swing)을 넣는다. 전략명은 config public 라벨이고 계좌는 dedupe_key 에만 남는다.
    """
    return {
        "kind": "REBALANCE",
        "ticker": f"실험슬리브({row['strategy']})",
        "reason": (
            f"슬리브 {row['used_pct']:.1f}% > 상한 {row['cap_pct']:.0f}%"
            " — 비중 조절 권고 (수단·타이밍 사용자 판단). 여력 회복까지 신규 시스템 추천 집행 보류"
        ),
        "date": date,
    }


def stage_sleeve_briefs(date: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """슬리브 상한 초과를 #brief outbox 에 REBALANCE 로 stage. staged 건수 반환.

    dedupe_key=`rebalance:sleeve:{account}:{date}` — 계좌 × 하루 1건. priority="normal".
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    staged = 0
    for row in scan_sleeve_breach(db_path=db_path):
        outbox_id = stage_brief(
            payload=_build_sleeve_rebalance_payload(row, d),
            dedupe_key=f"rebalance:sleeve:{row['account']}:{d}",
            priority="normal",
            actor_name="portfolio-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("sleeve REBALANCE briefs staged: %d", staged)
    return staged


#: 낡아도 카드를 내지 않는 소스. 여기 있는 것은 "낡음이 판단을 왜곡하지 않는다" 는
#: 주장이므로 추가할 때는 왜 그런지 같이 적을 것. 지금은 비어 있다 — 7개 정책 전부
#: 판단 입력이다.
FRESHNESS_CARD_EXEMPT: tuple[str, ...] = ()


def scan_stale_inputs(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """신선도 FAIL 인 데이터 소스 목록 (Tier 1e, #1090).

    **매매 신호가 아니라 관측 신뢰도 경고다.** 포트폴리오·가격·팩터는 방어 규칙 전부의
    입력이라, 낡은 입력 위에서 계산된 비중·섹터·손절 판단은 정밀한 헛소리가 된다.

    WARN 은 카드로 내지 않는다 — 주가/팩터가 주말이면 정상적으로 WARN 에 머무르므로
    매주 발화하는 소음이 되고, 소음이 된 알림은 읽히지 않는다. FAIL 만 낸다.
    """
    from nuri.core.freshness import check_all_freshness

    return [d for d in check_all_freshness(db_path) if d["status"] == "FAIL" and d["key"] not in FRESHNESS_CARD_EXEMPT]


#: 소스별 조치. 카드에 **틀린 조치**를 적으면 없느니만 못하다 — 가격이 낡은데
#: "portfolio.yaml 을 갱신하라" 고 하면 사용자가 엉뚱한 곳을 보고 진짜 원인은 남는다.
#: 미등재 키는 일반 문구로 떨어진다(새 정책이 추가돼도 죽지 않는다).
_REMEDY: dict[str, str] = {
    "portfolio": "config/portfolio.yaml 을 실제 잔고로 갱신 후 재동기화 (수동 원장 — 자동 import 는 낡은 값을 최신으로 재기록할 뿐)",
    "prices": "가격 수집 잡 상태 확인 (scheduler collect)",
    "factors": "팩터 합성 잡 상태 확인 — BUY 점수의 최대 입력이다",
    "macro_vix": "VIX 수집 확인 — VIX 게이트가 이 값으로 신규 매수를 막는다",
    "macro_fear_greed": "Fear & Greed 수집 확인",
    # 잡 이름만 적고 시각은 적지 않는다 — cron 은 옮겨 다니고(4차 리뷰에서 실제로 옮겼다),
    # 낡은 시각은 운영자를 엉뚱한 로그 창으로 보낸다 (Codex 5차 P3).
    "signals": "technical 잡 확인 — RSI/SMA 가 BUY 점수와 SIEGE 게이트에 들어간다",
    "signals_kr": "technical_close_kr 잡과 KR 가격 수집(stock_kr_universe_daily) 확인",
    "consensus": "합의 잡(07:05) 실행 여부 확인",
    "certification": "SIEGE 인증 실행 여부 확인",
}


def _remedy(key: str) -> str:
    return _REMEDY.get(key, "해당 수집 경로 점검")


def _build_stale_input_payload(entry: dict[str, Any], date: str) -> dict[str, Any]:
    """신선도 FAIL 1건 → #brief INPUT_STALE payload.

    **축을 만들지 않는다.** `alpha_action`/`portfolio_action` 둘 다 없다 — 이건 종목에
    대한 판단이 아니라 "지금 나오는 판단을 믿지 말라" 는 메타 경고다. 축을 붙이면
    렌더러와 소비자가 이것을 매매 신호로 읽고, 관측이 본 작업을 게이트하게 된다 (#894).

    Privacy: `label` 은 config 의 공개 라벨(`주가 데이터` / `포트폴리오 sync`)이고
    age 는 시간 수치라 계좌·보유·금액이 섞이지 않는다.
    """
    age = entry.get("age_hours")
    if not isinstance(age, (int, float)):
        # `age_hours=None` 은 "낡음" 이 아니라 **행이 하나도 없음**(또는 날짜 파싱 실패)이다.
        # 둘을 같은 문구로 내면 "며칠 지났나" 를 찾다가 실제 상태(수집 자체가 안 됨)를
        # 놓친다. 여기서 죽던 것을 스모크 테스트가 잡았다 — 빈 소스가 흔한 FAIL 이다.
        state = "데이터 없음"
    else:
        state = f"{age / 24:.0f}일 낡음" if age >= 48 else f"{age:.0f}시간 낡음"
    return {
        "kind": "INPUT_STALE",
        "ticker": f"입력({entry['label']})",
        "reason": f"{state} — 이 입력에 기대는 판단을 그대로 믿지 말 것. {_remedy(entry['key'])}",
        "date": date,
    }


def stage_stale_input_briefs(date: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """신선도 FAIL 을 #brief outbox 에 INPUT_STALE 로 stage. staged 건수 반환.

    dedupe_key=`input-stale:{key}:{date}` — 소스 × 하루 1건. priority="high": 낡은 입력은
    그날 나온 **모든** 다른 카드의 신뢰도를 깎으므로 개별 REBALANCE 보다 먼저 읽혀야 한다.

    이 카드가 없던 동안 포트폴리오가 15일(360.5h) 낡은 채로 지나갔다 — `get_freshness_summary`
    는 정상 동작했지만 결과가 프리마켓 임베드 **색**으로만 표현돼 카드 스트림에 안 떴다.
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    staged = 0
    for entry in scan_stale_inputs(db_path=db_path):
        outbox_id = stage_brief(
            payload=_build_stale_input_payload(entry, d),
            dedupe_key=f"input-stale:{entry['key']}:{d}",
            priority="high",
            actor_name="portfolio-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("stale input briefs staged: %d", staged)
    return staged


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="포트폴리오 드리프트(집중도·섹터·슬리브) → #brief REBALANCE (Tier 1b/1c/1d)"
    )
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 위반 목록만 출력")
    args = parser.parse_args(argv)

    conc = scan_concentration_drift()
    sect = scan_sector_drift()
    sleeve = scan_sleeve_breach()
    stale = scan_stale_inputs()
    if not conc and not sect and not sleeve and not stale:
        print("포트폴리오 드리프트 없음 (집중도·섹터·슬리브) · 낡은 입력 없음")
        return 0
    for e in stale:
        print(f"  [입력낡음] {e['label']} {e['message']}")
    for v in conc:
        print(
            f"  [집중도] {v['ticker']} [{v.get('account', '?')}] {v['current_value']:.1f}% > 한도 {v['limit_value'] * 100:.0f}%"
        )
    for v in sect:
        print(f"  [섹터] {v['sector']} {v['current_value']:.1f}% > 한도 {v['limit_value'] * 100:.0f}%")
    for v in sleeve:
        print(f"  [슬리브] {v['strategy']} {v['used_pct']:.1f}% > 상한 {v['cap_pct']:.0f}%")
    if args.dry_run:
        print(
            f"[dry-run] 집중도 {len(conc)}건 · 섹터 {len(sect)}건 · 슬리브 {len(sleeve)}건 "
            f"· 낡은 입력 {len(stale)}건 — stage 안 함"
        )
        return 0
    staged = stage_stale_input_briefs() + stage_concentration_briefs() + stage_sector_briefs() + stage_sleeve_briefs()
    print(f"staged {staged}건 → #brief (INPUT_STALE + REBALANCE)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
