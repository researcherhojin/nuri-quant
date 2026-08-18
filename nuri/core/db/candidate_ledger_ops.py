"""미실행 거래 원장 writes/reads — candidate_runs / candidate_ledger (#1094).

## 왜 이게 채점보다 먼저인가

실행하지 않은 거래가 기록되지 않으면 사후 채점이 **실행한 것만** 보게 되고, 그 성적표는
실제 실력보다 좋게 나온다. Codex(2026-08-18): *"Without the 'did not execute' baseline,
later post-hoc scoring will select only acted-on trades and quietly bias the evidence."*

## 테이블이 둘인 이유

**막힌 실행이 가장 정보량 많은 미실행 기록**인데 걸어 둘 티커가 없다. "왜 오늘 후보가
0이었나"(regime 차단 · VIX 차단 · 임계 미달)는 티커 단위로 표현되지 않는다. run 을 따로
두지 않으면 그 날은 원장에서 **아무 일도 없던 날**로 보인다 — 실제로는 시스템이 돌았고
차단 판단을 내렸는데도.

## `acted` 는 파생하지 않는다

`trades` 0행 · `portfolio.first_buy_date` 18/18 동일 상수(2026-08-18 실측)라 체결을 알
방법이 없다. `acted` 는 **사람이 켜는 값**이고, 자동으로 채우면 "실행 vs 미실행" 비교가
조용히 거짓이 된다.

## Surface 천장

이건 기록이지 신호가 아니다. `alpha_action`/`portfolio_action` 을 만들지 않고, §3.11 판정
표본(`recommendations` where `source IS NULL`)과도 별개 테이블이다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

#: 티커별 처분. `skipped` 는 게이트에 걸린 것(보유·쿨다운·레버리지), `below_threshold` 는
#: 채점은 됐지만 임계를 못 넘은 것. 둘을 합치면 "왜 안 샀나" 의 결이 사라진다.
DISPOSITIONS = ("emitted", "skipped", "below_threshold")


def record_candidate_run(result: Any, run_date: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """`EmitResult` 1건 → `candidate_runs` + `candidate_ledger`. run_id 반환.

    **후보가 0건이어도 run 행을 남긴다.** 그게 이 기능의 요점이다 — 차단된 날이야말로
    기록할 가치가 가장 큰 미실행 기록이다.

    같은 날 재실행은 `UNIQUE(run_date)` 로 갱신한다(하루 1행). 원장이 append-only 가
    아닌 이유: run 은 그날의 **최종 상태**를 뜻하고, 하루에 두 번 돌면 두 번째가 그날의
    결론이다. 티커 행도 같은 run 에 대해 `INSERT OR REPLACE` 로 맞춘다.
    """
    from nuri.core.timezone import today_kst

    d = run_date or today_kst()
    candidates = list(getattr(result, "candidates", None) or [])
    skipped: dict[str, str] = dict(getattr(result, "skipped", None) or {})

    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO candidate_runs
               (run_date, regime, vix, threshold, blocked_reason,
                n_scored, n_qualified, n_emitted, n_skipped)
               VALUES (:run_date, :regime, :vix, :threshold, :blocked_reason,
                       :n_scored, :n_qualified, :n_emitted, :n_skipped)
               ON CONFLICT(run_date) DO UPDATE SET
                   regime = excluded.regime,
                   vix = excluded.vix,
                   threshold = excluded.threshold,
                   blocked_reason = excluded.blocked_reason,
                   n_scored = excluded.n_scored,
                   n_qualified = excluded.n_qualified,
                   n_emitted = excluded.n_emitted,
                   n_skipped = excluded.n_skipped""",
            {
                "run_date": d,
                "regime": getattr(result, "regime", None) or None,
                "vix": getattr(result, "vix", None),
                "threshold": getattr(result, "threshold", None),
                "blocked_reason": getattr(result, "blocked_reason", None),
                "n_scored": int(getattr(result, "n_scored", 0) or 0),
                "n_qualified": int(getattr(result, "n_qualified", 0) or 0),
                "n_emitted": len(candidates),
                "n_skipped": len(skipped),
            },
        )
        row = conn.execute("SELECT id FROM candidate_runs WHERE run_date = ?", (d,)).fetchone()
        run_id = row[0]

        records = [
            {
                "run_id": run_id,
                "ticker": c.ticker,
                "disposition": "emitted",
                "reason": getattr(c, "why_now", None),
                "score": getattr(c, "score", None),
                "entry": getattr(c, "entry", None),
                "stop": getattr(c, "stop", None),
                "tp1": getattr(c, "tp1", None),
                "tp2": getattr(c, "tp2", None),
            }
            for c in candidates
        ]
        records += [
            {
                "run_id": run_id,
                "ticker": ticker,
                "disposition": "skipped",
                "reason": reason,
                "score": None,
                "entry": None,
                "stop": None,
                "tp1": None,
                "tp2": None,
            }
            for ticker, reason in skipped.items()
        ]
        if records:
            # `acted` 는 여기서 건드리지 않는다 — 사람이 켠 값을 재실행이 지우면 안 된다.
            conn.executemany(
                """INSERT INTO candidate_ledger
                   (run_id, ticker, disposition, reason, score, entry, stop, tp1, tp2)
                   VALUES (:run_id, :ticker, :disposition, :reason, :score, :entry, :stop, :tp1, :tp2)
                   ON CONFLICT(run_id, ticker) DO UPDATE SET
                       disposition = excluded.disposition,
                       reason = excluded.reason,
                       score = excluded.score,
                       entry = excluded.entry,
                       stop = excluded.stop,
                       tp1 = excluded.tp1,
                       tp2 = excluded.tp2""",
                records,
            )
    logger.info(
        "candidate run recorded: %s emitted=%d skipped=%d blocked=%s",
        d,
        len(candidates),
        len(skipped),
        getattr(result, "blocked_reason", None) or "-",
    )
    return run_id


def mark_acted(run_date: str, ticker: str, acted: bool = True, db_path: Optional[Path] = None) -> bool:
    """체결 여부를 **사람이** 표시한다. 갱신되면 True.

    파생하지 않는 이유는 모듈 docstring 참조 — 체결을 알 방법이 시스템에 없다.
    """
    from nuri.core.timezone import kst_now

    with get_db(db_path) as conn:
        cur = conn.execute(
            """UPDATE candidate_ledger SET acted = ?, acted_at = ?
                WHERE ticker = ? AND run_id = (SELECT id FROM candidate_runs WHERE run_date = ?)""",
            (1 if acted else 0, kst_now().isoformat() if acted else None, ticker, run_date),
        )
        return (cur.rowcount or 0) > 0


def get_candidate_run(run_date: str, db_path: Optional[Path] = None) -> Optional[dict]:
    """하루치 run + 티커별 원장."""
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM candidate_runs WHERE run_date = ?", (run_date,)).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["ledger"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM candidate_ledger WHERE run_id = ? ORDER BY disposition, score DESC, ticker",
                (run["id"],),
            ).fetchall()
        ]
        return run
