"""정직한 alpha 추적 — tracking-completeness + 데이터 품질. 검증된 edge 가 아님.

decision_outcomes 의 각 행은 (decision, observation_window) 단위다. 생산자
(ForwardOutcomeTracker)는 윈도우(as_of + window 영업일)가 도래하기 전이면
lookahead guard 로 realized_return=NULL 을 기록한다. 따라서 realized_return 유무가
완료/열림의 신뢰 가능한 신호이며, 이 엔드포인트는 자체 날짜 재계산 없이 이를 그대로
사용한다. realized_return 절대값이 임계값 초과인 행은 price-measurement 오류 의심으로
별도 카운트한다.

P0c (Lean MVP). edge 증명은 멀티레짐 walk-forward(P1/P7) 통과 후에만 가능 →
이 엔드포인트는 항상 edge_status=NOT_MEASURABLE 로 신뢰도를 명시한다.
"""

import logging

from fastapi import APIRouter

from nuri.core.db import query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alpha"])

# 추적 호라이즌 (영업일)
WINDOWS = (7, 14, 30)
# |realized_return| 이 초과면 측정 오류 의심 (해당 호라이즌에서 물리적으로 비현실적)
SUSPECT_ABS_RETURN = 0.5


def _sleeve_block() -> dict:
    """§3.11 실험 슬리브 사용률 — 계좌별 상한 대비 (#834).

    이 엔드포인트의 alpha 숫자가 **어떤 자본으로** 만들어졌는지가 슬리브다. 사용률
    없이 alpha 만 보이면 "상한 안에서 난 결과"인지 판단할 수 없어서 같은 응답에 둔다.

    실패해도 alpha 헤드라인을 죽이지 않는다(soft error) — 슬리브는 부가 맥락이고,
    이 엔드포인트의 본 계약은 tracking-completeness 다.
    """
    try:
        from nuri.analysis.sleeve import sleeve_utilization

        rows = sleeve_utilization()
    except Exception:
        logger.exception("sleeve utilization 계산 실패")
        return {"accounts": [], "count": 0, "error": "sleeve utilization unavailable"}

    # account 는 broker name 이라 응답에 넣지 않는다 (전략 라벨만 노출).
    accounts = [
        {
            "strategy": r["strategy"],
            "cap_pct": r["cap_pct"],
            "used_pct": r["used_pct"],
            "over": r["over"],
        }
        for r in rows
    ]
    return {
        "accounts": accounts,
        "count": len(accounts),
        "any_over": any(a["over"] for a in accounts),
        "note": "실험 슬리브 = 사전등록일 이후 시스템 BUY 추천을 실행해 새로 연 포지션. 초과는 REBALANCE 권고이며 매도 신호가 아니다 (§3.11 · #429).",
    }


def _median(values: list[float]) -> float | None:
    n = len(values)
    if n == 0:
        return None
    s = sorted(values)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


@router.get("/alpha")
def alpha_summary() -> dict:
    """결정 추적 완성도 + alpha 데이터 품질 요약 (검증된 edge 아님)."""
    rows = query(
        "SELECT decision_id AS did, observation_window AS w, "
        "realized_return AS rr, alpha AS a, notes "
        "FROM decision_outcomes WHERE observation_window IN (7, 14, 30)"
    )

    buckets: dict[int, dict] = {w: {"completed": [], "pending": 0, "unmeasured": 0} for w in WINDOWS}
    clean_decisions: set[str] = set()
    suspect = 0
    unmeasured_total = 0

    for r in rows:
        w = r["w"]
        if w not in buckets:  # pragma: no cover — SQL 이 IN (7,14,30) 으로 이미 필터, 방어용
            continue
        rr = r["rr"]
        if rr is None:
            # 생산자가 realized_return=NULL 을 쓰는 두 경우 구분:
            # lookahead(윈도우 미도래) vs price-missing(도래했으나 가격 없음=데이터 갭).
            # 생산자 notes 자유텍스트 매칭이라 대소문자 무시 (tracker 테스트도 case-insensitive 잠금).
            if "lookahead" in (r["notes"] or "").lower():
                buckets[w]["pending"] += 1
            else:
                buckets[w]["unmeasured"] += 1
                unmeasured_total += 1
            continue
        buckets[w]["completed"].append(r)
        if abs(rr) > SUSPECT_ABS_RETURN:
            suspect += 1
        elif r["a"] is not None:
            clean_decisions.add(r["did"])

    windows_out = []
    for w in WINDOWS:
        completed = buckets[w]["completed"]
        # clean = 오염 아님 + alpha 측정됨 (벤치마크 가용)
        clean = [c for c in completed if abs(c["rr"]) <= SUSPECT_ABS_RETURN and c["a"] is not None]
        med = _median([c["a"] for c in clean])
        windows_out.append(
            {
                "window": w,
                "n_completed": len(completed),
                "n_pending": buckets[w]["pending"],  # 윈도우 미도래
                "n_unmeasured": buckets[w]["unmeasured"],  # 도래했으나 가격 없음 (데이터 갭)
                "n_clean": len(clean),
                # outlier-robust median, clean 부분집합만. edge 아님 (NOT_MEASURABLE).
                "median_alpha_pct": round(med * 100, 2) if med is not None else None,
            }
        )

    return {
        "as_of": today_kst(),
        "windows": windows_out,
        # clean alpha 의 distinct 결정 수 — median 의 실제 표본 크기 (coverage 아님).
        "effective_bets": len(clean_decisions),
        # 이 alpha 가 어떤 자본으로 만들어졌는지 (§3.11 슬리브 사용률).
        "sleeve": _sleeve_block(),
        "data_quality": {
            "suspect_rows": suspect,
            "suspect_threshold_pct": int(SUSPECT_ABS_RETURN * 100),
            "unmeasured_rows": unmeasured_total,
            "note": "suspect=|realized_return|>임계값(측정오류 의심). unmeasured=윈도우 도래했으나 가격 없음(데이터 갭). 둘 다 alpha 헤드라인 비신뢰.",
        },
        # 멀티레짐 walk-forward(P1) 통과 전엔 항상 미측정. 단기·강세장 표본 + 오염 가능.
        "edge_status": "NOT_MEASURABLE",
        "caveat": "추적 완성도(tracking-completeness)이며 검증된 edge 가 아님. 표본은 단기·강세장 편향 + 오염 가능. 멀티레짐 walk-forward 통과 전 edge 미측정.",
    }
