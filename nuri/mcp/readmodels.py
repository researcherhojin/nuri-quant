"""Tier 1 (비민감) read model — 순수 DB SELECT, 컬럼 allowlist 가 곧 SQL (#1306).

## 경계가 코드 구조로 성립하는 방식

- **`ALLOWED` 가 유일한 컬럼 출처다.** 모든 SELECT 는 이 dict 에서 조립되고, 어떤
  도구도 SQL/컬럼명을 입력받지 않는다. 민감 필드는 "필터링" 되는 게 아니라
  **애초에 조회되지 않는다** (deny-by-construction).
- **모든 쿼리가 `readonly=True`** — `PRAGMA query_only=ON` 으로 쓰기가 SQLite 엔진
  수준에서 `OperationalError`. read-only 는 관행이 아니라 강제다 (codex plan 리뷰 4).
- **테이블 4개만 조회한다** — holdings/행동 계열(portfolio/trades/positions/decisions)
  은 import 도 참조도 없다. `decisions` 는 **보유 종목을 채점하는 루프의 원장**이라
  (README "scores the holdings you already own") 티커 존재 자체가 보유 오라클이 된다
  → v1 전체 제외 (codex plan 리뷰 2).
- **stage 코드 import 0** — 테이블이 인터페이스다 (`nuri.core.db` facade 만 사용).
- **skipped 후보는 반환하지 않는다.** emitter 의 skip 사유가 보유·매매 활동을 그대로
  적는다 ("held (보유 중…)", "cooldown (최근 SELL/trim…)" —
  `buy_candidate_emitter.py:513-516`) — skipped 행의 **존재 자체**가 보유 신호다.
  emitted 행만, 그것도 `reason`(held-add 경로에서 실보유 손익이 문자열에 박힘 —
  `_build_why_now`: "pnl +23.4%") 없이 반환한다 (codex plan 리뷰 1 + 자체 감사).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nuri.core.db import query

#: 노출 가능한 (테이블, 컬럼) 전체 — 이 dict 밖의 어떤 것도 조회되지 않는다.
#: 항목을 늘리는 변경은 privacy 잠금 테스트(스키마 락 + 시맨틱 유출 케이스)와 함께
#: 리뷰된다. free-text 컬럼(reason/blocked_reason 제외 — 후자는 run 수준 규칙 문구)과
#: 사용자 행동 컬럼(acted/acted_at/disposition)은 등재 금지가 원칙.
ALLOWED: dict[str, tuple[str, ...]] = {
    "certifications": (
        "timestamp",
        "certified",
        "score",
        "total_conditions",
        "passed",
        "failed",
        "warnings",
        "regime",
        "caller",
    ),
    "candidate_runs": (
        "run_date",
        "regime",
        "vix",
        "threshold",
        "blocked_reason",
        "n_scored",
        "n_qualified",
        "n_emitted",
        "n_skipped",
    ),
    "candidate_ledger": ("ticker", "score", "entry", "stop", "tp1", "tp2"),
    "macro": ("indicator", "date", "value", "source"),
}


def _cols(table: str) -> str:
    return ", ".join(ALLOWED[table])


def certification_status(limit: int = 5, db_path: Path | None = None) -> list[dict[str, Any]]:
    """최근 SIEGE 3D 인증 판정 — 최상위 스칼라만.

    `conditions_json` 은 집중도/비중 상세를 품을 수 있어 제외 — certify() 자체가
    포트폴리오 스냅샷을 읽으므로 카운트 수준을 넘는 노출은 전부 Tier 2 다.
    """
    limit = max(1, min(int(limit), 50))
    return query(
        f"SELECT {_cols('certifications')} FROM certifications ORDER BY id DESC LIMIT ?",  # noqa: S608 — 컬럼은 ALLOWED 리터럴에서만 조립
        (limit,),
        db_path=db_path,
        readonly=True,
    )


def latest_buy_candidates(run_date: str | None = None, db_path: Path | None = None) -> dict[str, Any]:
    """buy candidate run 요약 + **emitted** 티커·가격레벨만.

    skipped 행은 조회 자체를 하지 않는다 (모듈 독스트링 — 존재가 보유 신호).
    run 수준 카운트(n_skipped 등)는 숫자라 보유 식별이 불가능해 유지한다.
    """
    if run_date is not None:
        runs = query(
            f"SELECT id, {_cols('candidate_runs')} FROM candidate_runs WHERE run_date = ? ORDER BY id DESC LIMIT 1",  # noqa: S608
            (str(run_date),),
            db_path=db_path,
            readonly=True,
        )
    else:
        runs = query(
            f"SELECT id, {_cols('candidate_runs')} FROM candidate_runs ORDER BY run_date DESC, id DESC LIMIT 1",  # noqa: S608
            db_path=db_path,
            readonly=True,
        )
    if not runs:
        return {"run": None, "candidates": []}

    run = dict(runs[0])
    run_id = run.pop("id")  # 내부 키 — 응답에 노출하지 않는다
    candidates = query(
        f"SELECT {_cols('candidate_ledger')} FROM candidate_ledger "  # noqa: S608
        "WHERE run_id = ? AND disposition = 'emitted' ORDER BY score DESC",
        (run_id,),
        db_path=db_path,
        readonly=True,
    )
    return {"run": run, "candidates": candidates}


def macro_facts(db_path: Path | None = None) -> dict[str, Any]:
    """VIX 최신값 + 최근 인증 run 의 regime.

    regime 의 의미: **가장 최근 certify() 실행이 본 시장 맥락**이다 — certifications
    는 브리프 외에 dashboard/health 경로도 쓰므로 "지금 이 순간의 분류" 가 아니라
    "마지막 인증 시점의 분류" 다. 그래서 timestamp·caller 를 함께 반환해 소비자가
    신선도를 스스로 판단하게 한다 (codex plan 리뷰 5). 어휘는 #1293 가드로 canonical.
    """
    vix = query(
        f"SELECT {_cols('macro')} FROM macro WHERE indicator = 'vix' ORDER BY date DESC LIMIT 1",  # noqa: S608
        db_path=db_path,
        readonly=True,
    )
    regime = query(
        "SELECT regime, timestamp, caller FROM certifications WHERE regime IS NOT NULL ORDER BY id DESC LIMIT 1",
        db_path=db_path,
        readonly=True,
    )
    return {
        "vix": vix[0] if vix else None,
        "regime": regime[0] if regime else None,
    }
