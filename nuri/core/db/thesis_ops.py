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
        return thesis


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
