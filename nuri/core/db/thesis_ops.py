"""논지 원장 writes/reads — theses / thesis_evidence (#1083).

이 모듈이 존재하는 이유는 "논지를 저장할 곳이 없다" 가 아니라 **저장된 논지가 내용이
없어도 통과하던 전례**다. `agent_decisions.rationale_json` 은 NOT NULL 이었고 851행이
전부 같은 리터럴이었다. 그래서 스키마 제약이 아니라 **writer** 가 내용을 검증한다:

- `bear_case` 가 비면 거부 — 상승 논리만 쓰는 것이 기본값이 되면 원장이 응원가가 된다
- `bear_case == bull_case` 면 거부 — 채워 넣기 회피
- 근거 0건이면 거부 — 출처 없는 주장은 사후에 되짚을 수 없다

LLM 이 만든 논지는 `status='draft'` 로만 들어온다. 자동 `active` 승격은 없다
(STRATEGY §7.1 · Escalation Ladder — 이 층은 Surface 전용).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .connection import get_db

#: PIT 조인이 붙일 수 있는 상태. `draft` 는 사람이 승격하기 전까지 결정에 붙지 않는다.
ATTACHABLE_STATUS = ("active", "superseded")


class ThesisValidationError(ValueError):
    """writer 검증 실패 — 스키마는 통과하지만 내용이 없는 논지."""


def _require_substance(bull_case: str, bear_case: str, evidence: list[dict]) -> None:
    """내용 검증. NOT NULL 로는 못 잡는 것만 본다."""
    bull = (bull_case or "").strip()
    bear = (bear_case or "").strip()
    if not bull:
        raise ThesisValidationError("bull_case 가 비었다")
    if not bear:
        raise ThesisValidationError("bear_case 가 비었다 — 하락 논리 없는 논지는 기록이 아니라 응원가다")
    if bull == bear:
        raise ThesisValidationError("bull_case 와 bear_case 가 동일하다 — 채워 넣기")
    if not evidence:
        raise ThesisValidationError("근거가 0건이다 — 출처 없는 주장은 사후에 되짚을 수 없다")


def upsert_thesis(
    ticker: str,
    author: str,
    stance: str,
    bull_case: str,
    bear_case: str,
    evidence: list[dict],
    effective_date: Optional[str] = None,
    status: str = "draft",
    db_path: Optional[Path] = None,
) -> int:
    """논지 1건 + 근거를 기록하고 `theses.id` 를 돌려준다.

    같은 ticker 의 기존 논지가 있으면 새 version 으로 쌓고, 직전 것을 `superseded` 로
    내리며 `supersedes_id` 로 잇는다 — 덮어쓰지 않는다. 논지가 언제 어떻게 바뀌었는지가
    사후 채점의 핵심 재료이기 때문이다.

    `effective_date` 는 KST 날짜다. `created_at` 의 `datetime('now')` 는 UTC 라 KST 오전에
    쓴 논지가 당일 결정에 안 붙는다 — PIT 조인은 이 컬럼만 본다.

    Raises: `ThesisValidationError` — 내용 검증 실패 (모듈 docstring 참조).
    """
    from nuri.core.timezone import today_kst

    _require_substance(bull_case, bear_case, evidence)

    effective = effective_date or today_kst()
    with get_db(db_path) as conn:
        prev = conn.execute(
            "SELECT id, version FROM theses WHERE ticker = ? ORDER BY version DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        prev_id = prev[0] if prev else None
        version = (prev[1] + 1) if prev else 1

        cur = conn.execute(
            """INSERT INTO theses
               (ticker, version, supersedes_id, author, stance, bull_case, bear_case,
                effective_date, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, version, prev_id, author, stance, bull_case, bear_case, effective, status),
        )
        thesis_id = cur.lastrowid or 0

        # 직전 논지는 `superseded` 로 내린다. draft 를 올릴 때도 마찬가지다 — 새 초안이
        # 나왔는데 옛 active 가 계속 붙어 있으면 화면이 낡은 논지를 사실처럼 보여준다.
        if prev_id is not None:
            conn.execute(
                "UPDATE theses SET status = 'superseded', updated_at = datetime('now') "
                "WHERE id = ? AND status = 'active'",
                (prev_id,),
            )

        conn.executemany(
            """INSERT INTO thesis_evidence
               (thesis_id, side, claim, source_type, source_key, source_url, as_of, quote)
               VALUES (:thesis_id, :side, :claim, :source_type, :source_key, :source_url,
                       :as_of, :quote)""",
            [
                {
                    "thesis_id": thesis_id,
                    "side": e["side"],
                    "claim": e["claim"],
                    "source_type": e["source_type"],
                    "source_key": e.get("source_key"),
                    "source_url": e.get("source_url"),
                    "as_of": e.get("as_of"),
                    "quote": e.get("quote"),
                }
                for e in evidence
            ],
        )
        return thesis_id


def get_active_thesis(
    ticker: str,
    as_of: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    """`as_of` 시점에 유효했던 논지 1건 + 근거 (point-in-time).

    `as_of` 를 주지 않으면 오늘 기준. `effective_date <= as_of` 중 가장 늦은 것을 고르므로
    **논지를 처음 쓰는 순간 그 티커의 기존 결정 전부가 논지를 갖는다** — `decisions` 에
    `thesis_id` 컬럼을 붙였다면 기존 333행이 영원히 NULL 이었을 자리다.

    `draft` 는 붙지 않는다 (`ATTACHABLE_STATUS`). LLM 초안이 사람 승격 없이 결정 화면에
    사실처럼 실리면 안 된다.
    """
    from nuri.core.timezone import today_kst

    cutoff = as_of or today_kst()
    placeholders = ", ".join("?" * len(ATTACHABLE_STATUS))
    with get_db(db_path) as conn:
        row = conn.execute(
            f"""SELECT * FROM theses
                WHERE ticker = ? AND effective_date <= ? AND status IN ({placeholders})
                ORDER BY effective_date DESC, version DESC LIMIT 1""",
            (ticker, cutoff, *ATTACHABLE_STATUS),
        ).fetchone()
        if row is None:
            return None
        thesis = dict(row)
        thesis["evidence"] = [
            dict(e)
            for e in conn.execute(
                "SELECT * FROM thesis_evidence WHERE thesis_id = ? ORDER BY side, id",
                (thesis["id"],),
            ).fetchall()
        ]
    # 기준은 별도 커넥션에서 — `get_criteria` 가 자체 `get_db` 를 열기 때문.
    thesis["criteria"] = get_criteria(thesis["id"], db_path=db_path)
    return thesis


def add_criteria(thesis_id: int, criteria: list[dict], db_path: Optional[Path] = None) -> int:
    """반증 기준을 논지에 붙인다 (#1092). 등록 건수 반환.

    **machine 기준 최소 1개를 강제한다.** 전부 `human` 이면 자동 점검이 아무것도 안 하고,
    등록한 사람은 도는 줄 안다 — 그게 게이트가 있는데 안 잡는 상태다.

    metric 해소 가능성은 `thesis_criteria.validate_criterion` 이 본다: 스키마 CHECK 는
    `machine` 이면 metric/op/threshold 가 **있는지**만 보고, 그 metric 을 실제로 **해소할
    수 있는지**는 모른다. 오타 하나면 매일 `unevaluable` 만 쌓인다.

    Raises: `ThesisValidationError` — 내용 검증 실패.
    """
    from nuri.trading.engine.thesis_criteria import CriterionValidationError, validate_criterion

    if not criteria:
        raise ThesisValidationError("반증 기준이 0건이다 — 틀렸음을 확인할 방법 없는 논지는 서사다")
    if not any(c.get("kind") == "machine" for c in criteria):
        raise ThesisValidationError("machine 기준이 최소 1개 필요하다 — 전부 human 이면 자동 점검이 장식이다")

    for c in criteria:
        if not (c.get("statement") or "").strip():
            raise ThesisValidationError("statement 가 비었다 — 무엇이 반증인지 문장으로 남길 것")
        try:
            validate_criterion(c.get("kind", ""), c.get("metric"), c.get("op"), c.get("threshold"))
        except CriterionValidationError as e:
            raise ThesisValidationError(str(e)) from e

    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT INTO thesis_criteria
               (thesis_id, kind, statement, metric, op, threshold, deadline_date)
               VALUES (:thesis_id, :kind, :statement, :metric, :op, :threshold, :deadline_date)""",
            [
                {
                    "thesis_id": thesis_id,
                    "kind": c["kind"],
                    "statement": c["statement"],
                    "metric": c.get("metric"),
                    "op": c.get("op"),
                    "threshold": c.get("threshold"),
                    "deadline_date": c.get("deadline_date"),
                }
                for c in criteria
            ],
        )
    return len(criteria)


def get_criteria(thesis_id: int, db_path: Optional[Path] = None) -> list[dict]:
    """논지의 기준 + 최신 판정 (없으면 `last_result=None`)."""
    with get_db(db_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """SELECT c.*,
                          (SELECT k.result FROM thesis_criteria_checks k
                            WHERE k.criterion_id = c.id ORDER BY k.check_date DESC LIMIT 1) AS last_result,
                          (SELECT k.check_date FROM thesis_criteria_checks k
                            WHERE k.criterion_id = c.id ORDER BY k.check_date DESC LIMIT 1) AS last_checked
                     FROM thesis_criteria c
                    WHERE c.thesis_id = ? AND c.status = 'active'
                    ORDER BY c.kind, c.id""",
                (thesis_id,),
            ).fetchall()
        ]


def get_thesis_history(ticker: str, db_path: Optional[Path] = None) -> list[dict]:
    """한 티커의 논지 전 버전 (최신 우선). 근거는 붙이지 않는다 — 목록용."""
    with get_db(db_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM theses WHERE ticker = ? ORDER BY version DESC",
                (ticker,),
            ).fetchall()
        ]
