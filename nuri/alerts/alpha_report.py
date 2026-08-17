"""Monthly alpha progress report → #brief (§3.11 측정 모드 표출, #856).

판정 도구 `decision_alpha.adjudicate()` (#842) 는 구현돼 있으나 수동 CLI 뿐이라,
판정일(`measurement_mode.evaluation_date`)까지 아무도 안 본다. 측정 모드의 목적은
"감정 개입 없이 지켜보게 하는 장치"(§3.11 원안 4번)인데 지켜볼 화면이 없었다.

여기서 표면화하는 것은 **측정 상태**지 액션이 아니다 — `kind="INFO"` 고정.
BUY/SELL/REBALANCE 를 쓰면 렌더러가 Action Now 버킷에 넣고 price_levels 를 붙여
"지금 뭘 하라"는 신호로 읽힌다. 이 리포트는 매매 지시가 아니다.

조기 승격 금지(§3.11): `adjudicate()` 가 `evaluation_date` 이전이면 verdict 를
`PROGRESS_REPORT` 로 고정한다(`decision_alpha.py` 판정 우선순위 블록). 이 모듈은
`criteria_verdict_if_final` 을 **가정법으로만** 표시하고 결코 결론처럼 쓰지 않는다.

원장 단일(§3.11): adjudication 원장은 production(Mac mini) DB 뿐이다. dev 는 read
replica 라 표본이 다를 수 있으므로, stage 는 `NURI_ROLE=production` 에서만 한다.
계산·출력은 어디서나 허용 — dry-run 으로 들여다보는 것까지 막을 이유는 없다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

#: stage 를 허용하는 role. mini `.env` 에 `NURI_ROLE=production`.
PRODUCTION_ROLE = "production"

#: 판정 3조건 라벨 — decision_alpha.adjudicate() 의 conditions 키와 1:1.
_CONDITION_LABELS = {
    "mean_alpha_positive": "평균 alpha > 0",
    "permutation_significant": "순열 유의",
    "both_halves_positive": "전후반 both +",
}


def is_production() -> bool:
    """stage 허용 여부. `NURI_ROLE=production` 일 때만 True (대소문자 무시)."""
    return os.getenv("NURI_ROLE", "").strip().lower() == PRODUCTION_ROLE


def _days_until(target: Optional[str], today: str) -> Optional[int]:
    """`today` → `target` 남은 일수. 파싱 실패·`None` 이면 None (표시 생략).

    호출부가 `report.get("evaluation_date")` 를 그대로 넘기므로 `None` 은 정상 입력이다
    (아래 `except` 가 이미 처리한다). 시그니처를 `str` 로 두면 그 사실이 거짓이 된다.
    """
    try:
        return (date.fromisoformat(str(target)) - date.fromisoformat(str(today))).days
    except (ValueError, TypeError):
        return None


def build_progress_report(
    db_path: Optional[Path] = None,
    as_of: Optional[str] = None,
    n_perm: Optional[int] = None,
) -> dict[str, Any]:
    """`adjudicate()` 원본 리포트 반환 (가공 없음).

    파라미터는 전부 `config/rules.yaml measurement_mode` 에서 온다 — 여기서
    기준값을 다시 정의하지 않는다(하드코딩 금지, #856 acceptance).
    """
    from nuri.quant.validation.decision_alpha import adjudicate

    return adjudicate(db_path=db_path, as_of=as_of, n_perm=n_perm)


def format_progress_reason(report: dict[str, Any]) -> str:
    """리포트 → #brief 한 줄. 판정 3조건 + 결측률 + D-day 를 한 화면에.

    표본 0건 / 순열 미실행(NO_SAMPLE) 은 조건 키가 없으므로 축약 표기.
    """
    n = report.get("n", 0)
    min_n = report.get("min_n_required")
    missing = report.get("missing_rate_pct")
    missing_max = report.get("missing_max_pct")
    parts = [f"n={n}/{min_n}"]

    if "mean_alpha" in report:
        mean_pct = report["mean_alpha"] * 100
        parts.append(f"mean {mean_pct:+.2f}%p")
        parts.append(f"p={report['p_value']:.3f}/{report['p_max']}")
        halves = report.get("halves") or {}
        h1, h2 = halves.get("h1_mean"), halves.get("h2_mean")
        if h1 is not None and h2 is not None:
            parts.append(f"halves {h1 * 100:+.2f}/{h2 * 100:+.2f}%p")
        cond = report.get("conditions") or {}
        met = [_CONDITION_LABELS[k] for k, v in cond.items() if v and k in _CONDITION_LABELS]
        parts.append(f"조건 {len(met)}/{len(cond)} 충족")
    else:
        parts.append(report.get("reason", "표본 부족 — 순열 미실행"))

    # 결측률이 `None` = 측정 대상 0 건. 필드를 통째로 생략하면 "결측 없음"과
    # 구분이 안 되고, `0.0` 으로 찍으면 사전 등록된 무효화 기준이 통과처럼 읽힌다
    # (2026-07-28 · 08-01 프로덕션 #brief 가 실제로 `결측 0.0%/15%` 를 내보냈다).
    if "missing_rate_pct" in report:
        parts.append(f"결측 {missing}%/{missing_max}%" if missing is not None else f"결측 n/a (한도 {missing_max}%)")

    # 결측률은 **정산된 창만** 세므로, 벤치마크 수집이 멈추면 결측률이 조용히 내려간다.
    # 프런티어를 같이 찍어야 "결측 낮음"과 "측정 멈춤"이 구분된다 (판정은 안 바꾼다).
    if "settled_through" in report:
        frontier = report["settled_through"]
        lag = report.get("settlement_lag_days")
        if frontier is None:
            parts.append("정산 n/a (벤치마크 종가 없음)")
        else:
            parts.append(f"정산 {frontier}" + (f" (지연 {lag}d)" if lag is not None else ""))

    d = _days_until(report.get("evaluation_date"), report.get("as_of") or today_kst())
    if d is not None:
        parts.append(f"판정일까지 D-{d}" if d >= 0 else f"판정일 경과 +{-d}d")
    return " | ".join(parts)


def _build_payload(report: dict[str, Any]) -> dict[str, Any]:
    """리포트 → #brief INFO payload.

    ticker 는 종목이 아니라 측정 대상 라벨. price_levels 없음(액션 아님).
    `criteria_verdict_if_final` 은 판정일 이전엔 note 에 가정법으로만 — 승격으로
    읽히면 §3.11 위반이다.
    """
    verdict = report.get("verdict", "PROGRESS_REPORT")
    # ⚠ verdict 는 payload 키로만 두면 사용자에게 **안 보인다** — 렌더러
    # `_format_event_line` 은 ("regime","causal","horizon","position","reason",
    # "note") 화이트리스트만 출력한다 (nuri/agents/discord/outbox.py). 판정 결과가
    # 화면에 나와야 하므로 note 안에 실어 보낸다.
    if report.get("pre_evaluation"):
        hypo = report.get("criteria_verdict_if_final")
        note = f"{verdict} — 측정 진행 중, 조기 판정 아님"
        if hypo:
            note = f"{verdict} — 측정 진행 중, 오늘 기준이라면 '{hypo}' (조기 판정 아님)"
    else:
        # 판정일 경과 — 이제는 진짜 판정이다. "진행 중" 문구를 그대로 두면
        # §3.11 이 만들려던 단 하나의 산출물을 화면에서 지워버린다.
        note = f"{verdict} — 판정일 경과, 사전 등록 기준에 따른 최종 판정"
    return {
        "kind": "INFO",
        "ticker": "ALPHA-MEASUREMENT",
        "reason": format_progress_reason(report),
        "note": note,
        "date": report.get("as_of") or today_kst(),
        "horizon": f"{report.get('window_days')}d vs {report.get('benchmark')}",
        "verdict": verdict,
    }


def _dedupe_key(month: str) -> str:
    return f"alpha-progress:{month}"


def already_emitted(month: str, db_path: Optional[Path] = None) -> bool:
    """이번 달 리포트가 이미 outbox 에 올라갔나.

    `stage_outbox` 의 자체 dedupe 는 **`status='pending'` 행만** 본다
    (`nuri/core/db/discord_outbox_ops.py`). 발송되면 `sent` 로 바뀌어 더 이상
    매칭되지 않으므로, 그것만 믿고 매일 돌리면 매일 재발화한다. 여기서
    pending/claimed/sent 를 모두 확인해 진짜 월 1회를 만든다.

    `failed`/`dropped` 는 재시도 허용 — 못 나간 달을 영영 포기하지 않는다.
    """
    from nuri.core.db import query

    rows = query(
        """SELECT 1 FROM discord_outbox
            WHERE channel = 'brief' AND dedupe_key = ?
              AND status IN ('pending', 'claimed', 'sent')
            LIMIT 1""",
        (_dedupe_key(month),),
        db_path=db_path,
    )
    return bool(rows)


def stage_alpha_progress_brief(
    db_path: Optional[Path] = None,
    as_of: Optional[str] = None,
    n_perm: Optional[int] = None,
    force: bool = False,
) -> Optional[int]:
    """월간 진행 리포트를 #brief 에 stage. outbox id 반환 (미실행/중복 시 None).

    매일 호출해도 안전하다 — 이번 달 발화분이 있으면 `adjudicate()` 를 돌리기
    전에 빠져나온다(순열 1,000회를 매일 태우지 않으려는 목적도 있다). 덕분에
    1일에 못 나가도(재시작·절전·misfire) 다음 날 따라잡는다.

    `NURI_ROLE=production` 이 아니면 stage 하지 않는다 (§3.11 원장 단일).
    `force=True` 는 테스트 전용 role 우회 — 월 1회 가드는 우회하지 않는다.
    """
    from nuri.agents.discord.outbox import stage_brief

    if not (force or is_production()):
        # WARNING 인 이유: 이건 정상 상태가 아니라 **설정 오류**다. mini 에서
        # NURI_ROLE 이 비어 있으면 리포트가 판정일까지 한 번도 안 나가는데,
        # INFO 로 두면 "이번 달 이미 발화" 와 구분이 안 돼 아무도 모른다.
        # #859 이후 콘솔(=scheduler.err) 은 WARNING+ 만 받으므로 여기 뜬다.
        logger.warning(
            "alpha progress report: NURI_ROLE != %r → stage skip. "
            "프로덕션이라면 설정 누락 — 이 상태면 §3.11 진행 리포트가 영영 안 나간다 "
            "(scheduler plist EnvironmentVariables 확인).",
            PRODUCTION_ROLE,
        )
        return None

    month = str(as_of or today_kst())[:7]
    if already_emitted(month, db_path=db_path):
        logger.debug("alpha progress report: %s 이미 발화 → skip", month)
        return None

    report = build_progress_report(db_path=db_path, as_of=as_of, n_perm=n_perm)
    outbox_id = stage_brief(
        payload=_build_payload(report),
        dedupe_key=_dedupe_key(month),
        priority="normal",
        actor_name="alpha-report",
        db_path=db_path,
    )
    if outbox_id is not None:
        logger.info("alpha progress report staged: n=%s verdict=%s", report.get("n"), report.get("verdict"))
    return outbox_id


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="§3.11 월간 alpha 진행 리포트 → #brief (#856)")
    parser.add_argument("--db", type=Path, default=None, help="DB 경로 (기본: production 원장 규약)")
    parser.add_argument("--as-of", default=None, help="기준일 YYYY-MM-DD (기본: 오늘 KST)")
    parser.add_argument("--n-perm", type=int, default=None, help="순열 수 override (기본: config)")
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 리포트만 출력")
    parser.add_argument("--json", action="store_true", help="원본 리포트 JSON 출력")
    args = parser.parse_args(argv)

    report = build_progress_report(db_path=args.db, as_of=args.as_of, n_perm=args.n_perm)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"verdict: {report.get('verdict')}")
        print(f"  {format_progress_reason(report)}")

    if args.dry_run:
        print("[dry-run] stage 안 함")
        return 0
    if not is_production():
        print(f"NURI_ROLE != {PRODUCTION_ROLE} → stage 안 함 (§3.11 원장은 production DB 단일)")
        return 0
    outbox_id = stage_alpha_progress_brief(db_path=args.db, as_of=args.as_of, n_perm=args.n_perm)
    print("staged → #brief" if outbox_id is not None else "이미 이번 달 발화됨 (dedupe)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
