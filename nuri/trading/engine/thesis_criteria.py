"""사전등록 반증 기준의 일별 자동 점검 (#1092).

## 왜 이게 논지 다음이고 시나리오 분석보다 먼저인가

`theses` 는 상승·하락 논리를 담지만, **무엇이 사실이면 내가 틀린 것인가**가 없으면 사후에
"대체로 맞았다" 로 읽힌다. 그건 처분효과를 막지 못하는 서사다. 반증 기준이 먼저 있어야
나중의 채점(verdict)이 손 라벨링이 아니게 된다.

## 절대 굽히지 않는 규칙 — `unevaluable` 은 `holding` 이 아니다

해소되지 않는 metric 은 `unevaluable` 로 기록한다. 절대 "이상 없음"(`holding`)이 아니다.
`_check_volatility_for_class` 가 넉 달간 초록이던 이유가 정확히 이것 — 측정 못 한 것을
통과로 적으면 게이트가 **있는데 안 잡는** 상태가 되고, 그건 게이트가 없는 것보다 나쁘다
(있다고 믿게 되므로).

`unevaluable` 사유는 셋이고 전부 `detail` 에 남긴다:
  - `no_metric` — 미등록 metric (writer 가 막지만 기존 행이 있을 수 있다)
  - `no_data` — 해당 티커의 그 값이 DB 에 없음
  - `stale` — 값은 있는데 정책상 너무 낡음

## 에스컬레이션 천장 — Surface 전용

breach 는 **알림 + 화면 뱃지**까지다. 주문을 만들지 않고 `alpha_action` 을 건드리지 않는다
(STRATEGY §7.1 · Escalation Ladder). 승격하려면 STRATEGY PR + 근거가 필요하다.

## METRIC_RESOLVERS 는 실제로 채워진 테이블만

프로덕션 실측(2026-08-18): prices 270,401 · fundamentals 794 · signals 850 · factors 793.
목록에 없는 metric 은 writer 가 거부한다 — 그리고 **양방향 계약 테스트**가 목록의 모든
metric 이 실제로 해소되는지도 본다. 한쪽만 있으면 목록과 구현이 조용히 갈린다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: 낡음 판정 기준(일). 값이 이보다 오래됐으면 `holding` 이 아니라 `unevaluable(stale)` 이다.
#: 가격은 매일 갱신되지만 fundamentals/factors 는 주기가 길어 소스별로 다르다.
STALE_AFTER_DAYS: dict[str, int] = {
    "prices": 5,
    "signals": 5,
    "factors": 5,
    "fundamentals": 100,
}


def _latest(table: str, column: str, ticker: str, db_path: Optional[Path]) -> tuple[Optional[float], Optional[str]]:
    """(값, 날짜) — 없으면 (None, None). 컬럼명은 호출자가 아니라 이 모듈이 정한다."""
    from nuri.core.db import query

    rows = query(
        f"SELECT {column} AS v, date FROM {table} WHERE ticker = ? AND {column} IS NOT NULL ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    if not rows:
        return None, None
    return float(rows[0]["v"]), rows[0]["date"]


def _resolver(table: str, column: str) -> Callable[[str, Optional[Path]], tuple[Optional[float], Optional[str], str]]:
    def resolve(ticker: str, db_path: Optional[Path]) -> tuple[Optional[float], Optional[str], str]:
        value, date = _latest(table, column, ticker, db_path)
        return value, date, table

    return resolve


#: metric 이름 → (값, 날짜, 소스테이블) 해소기.
#: **여기 없는 metric 은 writer 가 거부한다.** 추가할 때는 그 컬럼이 실제로 채워지는지
#: 프로덕션에서 세어 보고 넣을 것 — 비어 있는 컬럼을 넣으면 그 기준은 영원히 unevaluable 이다.
def _close_over_sma200(ticker: str, db_path: Optional[Path]) -> tuple[Optional[float], Optional[str], str]:
    """종가의 200일선 대비 괴리율(%). 절대가격 threshold 의 함정을 피하는 상대 지표.

    절대가격 기준(예: "등록 시점 200일선 값 아래로")은 몇 달 뒤 그 숫자가 200일선도
    레짐도 아닌 그냥 과거 가격이 된다 — 반증 불가 (#1137 계열 threshold trap,
    2026-08-21 논지 원장 첫 운용에서 codex 가 지적). 괴리율은 시점 무관하게 같은
    의미를 유지한다: 0 미만 = 200일선 하회.
    """
    close, date_c = _latest("prices", "close", ticker, db_path)
    sma, date_s = _latest("signals", "sma_200", ticker, db_path)
    if close is None or sma is None or sma == 0:
        return None, None, "prices+signals"
    return (close / sma - 1.0) * 100.0, max(d for d in (date_c, date_s) if d), "prices+signals"


METRIC_RESOLVERS: dict[str, Callable[[str, Optional[Path]], tuple[Optional[float], Optional[str], str]]] = {
    "close": _resolver("prices", "close"),
    "close_over_sma200_pct": _close_over_sma200,
    "volume": _resolver("prices", "volume"),
    "rsi_14": _resolver("signals", "rsi_14"),
    "sma_50": _resolver("signals", "sma_50"),
    "sma_200": _resolver("signals", "sma_200"),
    "composite_score": _resolver("factors", "composite_score"),
    "momentum_score": _resolver("factors", "momentum_score"),
    "value_score": _resolver("factors", "value_score"),
    "quality_score": _resolver("factors", "quality_score"),
    "pe_ratio": _resolver("fundamentals", "pe_ratio"),
    "forward_pe": _resolver("fundamentals", "forward_pe"),
    "revenue_growth": _resolver("fundamentals", "revenue_growth"),
    "operating_margin": _resolver("fundamentals", "operating_margin"),
    "debt_to_equity": _resolver("fundamentals", "debt_to_equity"),
}

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class CriterionValidationError(ValueError):
    """writer 검증 실패 — 스키마는 통과하지만 자동 점검이 불가능한 기준."""


def validate_criterion(kind: str, metric: Optional[str], op: Optional[str], threshold: Optional[float]) -> None:
    """등록 전 검증. 스키마 CHECK 가 잡지 못하는 것 — **metric 이 해소 가능한가**를 본다.

    스키마는 `machine` 이면 셋이 다 있는지만 본다. 해소기가 없는 metric 이름을 넣으면
    행은 만들어지고 점검은 매일 `unevaluable` 을 찍는다 — 등록한 사람은 자동 점검이
    도는 줄 알고, 실제로는 아무것도 검증되지 않는다.
    """
    if kind == "human":
        return
    if kind != "machine":
        raise CriterionValidationError(f"kind 는 machine|human 이어야 한다: {kind!r}")
    if metric not in METRIC_RESOLVERS:
        raise CriterionValidationError(
            f"해소기 없는 metric: {metric!r} — 등록 가능: {', '.join(sorted(METRIC_RESOLVERS))}"
        )
    if op not in _OPS:
        raise CriterionValidationError(f"op 는 {'|'.join(_OPS)} 중 하나여야 한다: {op!r}")
    if threshold is None:
        raise CriterionValidationError("machine 기준은 threshold 가 필요하다")


def evaluate_criterion(
    criterion: dict[str, Any],
    ticker: str,
    as_of: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """기준 1건 판정 → `{result, observed, detail}`.

    `human` 기준은 기계가 판단할 수 없으므로 항상 `unevaluable(manual)` 이다 — 사람이
    직접 뒤집는다. 이것을 `holding` 으로 적으면 "사람 기준은 늘 지켜지고 있다" 는
    거짓말이 매일 원장에 쌓인다.
    """
    from nuri.core.timezone import today_kst

    kind = criterion.get("kind")
    if kind != "machine":
        return {"result": "unevaluable", "observed": None, "detail": "manual — 사람이 판정"}

    metric = criterion.get("metric")
    resolver = METRIC_RESOLVERS.get(metric or "")
    if resolver is None:
        return {"result": "unevaluable", "observed": None, "detail": f"no_metric:{metric}"}

    value, date, table = resolver(ticker, db_path)
    if value is None:
        return {"result": "unevaluable", "observed": None, "detail": f"no_data:{table}"}

    limit = STALE_AFTER_DAYS.get(table)
    if limit is not None and date:
        from datetime import date as _date

        try:
            age = (_date.fromisoformat(as_of or today_kst()) - _date.fromisoformat(date[:10])).days
        except ValueError:
            age = None
        if age is not None and age > limit:
            return {"result": "unevaluable", "observed": value, "detail": f"stale:{table}:{age}d>{limit}d"}

    breached = _OPS[criterion["op"]](value, float(criterion["threshold"]))
    return {
        "result": "breached" if breached else "holding",
        "observed": value,
        "detail": f"{metric}={value:g} {criterion['op']} {criterion['threshold']:g} → {breached}",
    }


def run_daily_checks(as_of: Optional[str] = None, db_path: Optional[Path] = None) -> dict[str, int]:
    """활성 논지의 활성 기준을 전부 판정하고 append-only 로 기록. 결과 카운트 반환.

    같은 (기준, 날짜) 재실행은 `INSERT OR IGNORE` 로 멱등이다 — 하루에 두 번 돌아도
    판정이 뒤집히지 않는다. 뒤집히면 그날의 판정이 무엇이었는지 사후에 알 수 없다.
    """
    from nuri.core.db import get_db, query
    from nuri.core.timezone import today_kst

    d = as_of or today_kst()
    # `effective_date` 를 안 보면 **발효 전 기간이 채점에 들어간다.** 9월 1일부터 유효한
    # 논지를 오늘 써 두면 오늘부터 판정이 쌓이고, 그 중 반증 하나면 논지는 유효해지기도
    # 전에 `broken` 이 된다 (2026-08-18 재현). 논지는 유효한 기간에 대해서만 채점한다.
    rows = query(
        """SELECT c.id, c.kind, c.metric, c.op, c.threshold, t.ticker
           FROM thesis_criteria c
           JOIN theses t ON t.id = c.thesis_id
           WHERE c.status = 'active' AND t.status = 'active' AND t.effective_date <= ?""",
        (d,),
        db_path=db_path,
    )
    counts = {"holding": 0, "breached": 0, "unevaluable": 0}
    records = []
    for row in rows:
        verdict = evaluate_criterion(dict(row), row["ticker"], as_of=d, db_path=db_path)
        counts[verdict["result"]] += 1
        records.append(
            {
                "criterion_id": row["id"],
                "check_date": d,
                "result": verdict["result"],
                "observed": verdict["observed"],
                "detail": verdict["detail"],
            }
        )
    if records:
        with get_db(db_path) as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO thesis_criteria_checks
                   (criterion_id, check_date, result, observed, detail)
                   VALUES (:criterion_id, :check_date, :result, :observed, :detail)""",
                records,
            )
    if counts["breached"]:
        logger.warning("thesis criteria breached: %d (surface only — 주문 만들지 않음)", counts["breached"])
    return counts


#: 사후 채점의 4값. `theses.verdict` CHECK 와 동일해야 한다 — 여기가 사람이 읽는 정본.
#:
#: `held` 가 가장 얻기 어렵게 설계돼 있다. 그래야 채점이 자기 편이 아니다:
#:   - 기준 **1건이라도** 반증되면 `broken` (마감을 기다리지 않는다 — 반증은 반증이다)
#:   - 논지가 교체(`superseded`)되거나 접히면(`retired`) `abandoned` — 중간에 갈아탄 논지를
#:     "지켜졌다" 로 적으면 갈아타기가 공짜가 된다
#:   - 마감이 하나라도 안 지났으면(또는 마감이 없으면) **판정하지 않는다** — 진행 중
#:   - 마감이 전부 지났고 반증 0건이어도, **모든 기준이 실제로 한 번은 측정됐어야** `held`
#:     이고 아니면 `unevaluable`. 부분 측정은 `held` 가 아니다
VERDICTS = ("broken", "held", "abandoned", "unevaluable")

#: 논지가 더 이상 살아 있지 않은 상태 → `abandoned` (단, 반증이 먼저다).
_ABANDONED_STATUS = ("superseded", "retired")


def _verdict_for(status: str, criteria: list[dict], stats: dict[int, dict], as_of: str) -> Optional[str]:
    """논지 1건의 verdict. `None` 이면 진행 중 — **기존 verdict 를 지우지 않는다.**"""
    # 기준 0건은 채점 대상이 아니다. 이 줄이 없으면 아래 `all([])` 이 **공허참**으로
    # `held` 를 돌려준다 — 반증 기준 없는 논지가 만점을 받는 셈이다. 지금은 쿼리가
    # INNER JOIN 이라 도달하지 않지만, 방어가 우연이면 다음 리팩터가 걷어간다.
    if not criteria:
        return None
    if any(stats.get(c["id"], {}).get("breached") for c in criteria):
        return "broken"
    if status in _ABANDONED_STATUS:
        return "abandoned"
    # 마감 없는 기준은 영원히 끝나지 않는다. `held` 를 원하면 마감을 박아야 한다 —
    # 끝나지 않는 관찰을 "지켜졌다" 로 결산할 수는 없다.
    if any(not c["deadline_date"] or c["deadline_date"] > as_of for c in criteria):
        return None
    if all(stats.get(c["id"], {}).get("measured") for c in criteria):
        return "held"
    return "unevaluable"


def roll_up_verdicts(as_of: Optional[str] = None, db_path: Optional[Path] = None) -> dict[str, int]:
    """기준 판정 이력에서 논지 verdict 를 굴려 올린다 (#1096). verdict 별 건수 반환.

    `theses.verdict` 는 migration 51 이래 아무도 쓰지 않던 컬럼이다. 이 함수가 유일한
    writer 이고, 값은 전부 `thesis_criteria_checks` 에서 나온다 — 손 라벨링이 아니다.

    기준이 0건인 논지(#1092 이전 유물)는 건너뛴다. 반증 기준 없는 논지는 채점 대상이
    아니라 서사이고, 그걸 `held` 로 적으면 정확히 이 시스템이 막으려는 것이 된다.
    """
    from nuri.core.db import get_db, query
    from nuri.core.timezone import today_kst

    d = as_of or today_kst()
    # **효력을 가진 적 없는 논지는 채점하지 않는다.** `draft` 는 사람이 승격한 적 없는
    # 초안이고, `effective_date` 가 미래면 아직 시작도 안 한 판단이다. 둘 다 verdict 를
    # 받으면 원장이 "있지도 않았던 판단의 성적표" 를 갖게 된다 (Codex 리뷰 2026-08-18).
    rows = query(
        """SELECT t.id AS thesis_id, t.status, t.verdict,
                  c.id AS criterion_id, c.deadline_date
             FROM theses t
             JOIN thesis_criteria c ON c.thesis_id = t.id AND c.status = 'active'
            WHERE t.status <> 'draft' AND t.effective_date <= ?""",
        (d,),
        db_path=db_path,
    )
    # 집계를 조인 안에서 하지 않는 이유: checks 는 기준당 여러 행이라 같은 쿼리에서
    # SUM 하면 기준 수가 체크 수만큼 부풀어 `all(...)` 판정이 조용히 틀어진다.
    stats = {
        r["criterion_id"]: {"breached": r["n_breached"], "measured": r["n_measured"]}
        for r in query(
            """SELECT criterion_id,
                      SUM(result = 'breached') AS n_breached,
                      SUM(result IN ('holding', 'breached')) AS n_measured
                 FROM thesis_criteria_checks
                GROUP BY criterion_id""",
            db_path=db_path,
        )
    }

    by_thesis: dict[int, dict[str, Any]] = {}
    for r in rows:
        entry = by_thesis.setdefault(r["thesis_id"], {"status": r["status"], "verdict": r["verdict"], "criteria": []})
        entry["criteria"].append({"id": r["criterion_id"], "deadline_date": r["deadline_date"]})

    counts: dict[str, int] = dict.fromkeys(VERDICTS, 0)
    updates = []
    for thesis_id, entry in by_thesis.items():
        verdict = _verdict_for(entry["status"], entry["criteria"], stats, d)
        if verdict is None:
            continue
        counts[verdict] += 1
        if verdict != entry["verdict"]:
            updates.append((verdict, thesis_id))
    if updates:
        with get_db(db_path) as conn:
            conn.executemany(
                "UPDATE theses SET verdict = ?, updated_at = datetime('now') WHERE id = ?",
                updates,
            )
    if counts["broken"]:
        logger.warning("thesis verdict broken: %d (surface only — 주문 만들지 않음)", counts["broken"])
    return counts
