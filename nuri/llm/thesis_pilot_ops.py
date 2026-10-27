"""thesis 파일럿 운영 — 경보와 원장 보고 (#1998).

파일럿 러너(#1964)는 밤마다 분리된 프로세스로 돈다. 그 프로세스가 안 돌았거나 실패해도 아무도 보지 않으면, 파일럿
기간이 지나서야 빈 날이 드러난다. 여기서 그걸 #ops 로 올리고, E 가 쓸 운영 숫자를 원장에서 집계한다.

- **경보 네 가지** — 하루(코호트) · 종류마다 #ops 한 건. 같은 키가 outbox 에 한 번이라도 있었으면 다시 올리지
  않는다(`dedupe_key` 는 pending 만 막는다 — `nuri/alerts/data_sanity.py` 와 같은 이유).
  - `missing` — 동결 창 안의 세션 다음 날(오늘 이전)인데 밤 기록이 없다(러너가 뜨지 않았다). 지연은 최대 하루.
  - `failed` — `no_session` 외의 거절, 0 이 아닌 종료, 또는 예외.
  - `stuck` — `open` 배치나 끝나지 않은 밤이 `THESIS_DEFER_HOURS` 를 넘겼다(배포가 그동안 막힌다, #1989).
  - `canary_changed` — 배치 도중 런타임이 바뀌어 그 배치의 실행을 믿을 수 없다.
- **보고는 집계만** — 종목 · 등급 · 수익은 내지 않는다(공개 매체로 옮겨질 수 있다).
- 시각: 원장의 `started_at` 은 오프셋 있는 UTC ISO, `collector_runs` · `agent_run_ledger` 는 SQLite
  `datetime('now')`(오프셋 없는 UTC) — 둘 다 UTC 로 읽어 비교한다.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from nuri.core.db import query
from nuri.core.timezone import KST, kst_now
from nuri.llm import thesis_freeze
from nuri.llm import thesis_pilot as tp

DEFAULT_DEFER_HOURS = 6  # autopull 의 THESIS_DEFER_HOURS 기본값과 같다 (#1989)


def defer_hours(raw: Optional[str]) -> int:
    """autopull 과 같은 규칙 — 1~99 의 정수만, 그 밖은 기본값(#1989 의 SQL 주입 방지와 같은 판정)."""
    return int(raw) if raw is not None and raw.isdigit() and 1 <= int(raw) <= 99 else DEFAULT_DEFER_HOURS


def _utc(text: str) -> datetime:
    t = datetime.fromisoformat(text)
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


def findings(
    pilot: tp.Pilot,
    now: datetime,
    *,
    defer_hours: int = DEFAULT_DEFER_HOURS,
    freeze_path: Path = thesis_freeze.FREEZE_PATH,
    db_path: Optional[Path] = None,
) -> list[dict[str, str]]:
    """그 실험의 **모든** 코호트에 대한 경보 거리 — [{kind, cohort, detail}]. 한 번 놓친 경보가 다음 날 사라지지
    않게 오늘만 보지 않는다(반복은 outbox 키가 막는다, Codex 리뷰)."""
    today = now.astimezone(KST).date()
    out: list[dict[str, str]] = []
    nights = {
        n["cohort_date"]: n
        for n in query(
            "SELECT cohort_date, started_at, ended_at, outcome, exit_code FROM thesis_pilot_nights "
            "WHERE experiment = ?",
            (pilot.experiment,),
            db_path=db_path,
        )
    }
    # 빠진 밤 — 오늘 이전의 세션 다음 날만 본다(오늘 것은 러너가 아직 안 돌았을 수 있다). 지연은 최대 하루.
    for f in thesis_freeze.load(freeze_path):
        if f.experiment != pilot.experiment:
            continue
        day = f.start
        while day <= min(f.end, today - timedelta(days=1)):
            if tp.after_session(day) and day.isoformat() not in nights:
                out.append({"kind": "missing", "cohort": day.isoformat(), "detail": "no pilot night was recorded"})
            day += timedelta(days=1)
    for cohort, n in sorted(nights.items()):
        if n["ended_at"] is None:
            # 예약 뒤 러너가 죽었다(배치 전이든 정산 중이든) — 배치 상태와 무관하게 기한으로 본다
            if now - _utc(n["started_at"]) > timedelta(hours=defer_hours):
                out.append({"kind": "stuck", "cohort": cohort, "detail": f"night unfinished after {defer_hours}h"})
        elif n["outcome"] != "ran" or n["exit_code"] != 0:
            detail = f"outcome {n['outcome']}, exit {n['exit_code']}"
            out.append({"kind": "failed", "cohort": cohort, "detail": detail})
    for b in query(
        "SELECT started_at, status FROM thesis_batches WHERE experiment = ? AND status IN ('open', 'canary_changed')",
        (pilot.experiment,),
        db_path=db_path,
    ):
        started = _utc(b["started_at"])
        day = started.astimezone(KST).date().isoformat()
        if b["status"] == "canary_changed":
            out.append({"kind": "canary_changed", "cohort": day, "detail": "runtime changed during the batch"})
        elif now - started > timedelta(hours=defer_hours):
            out.append({"kind": "stuck", "cohort": day, "detail": f"batch open for more than {defer_hours}h"})
    return out


def stage(found: list[dict[str, str]], experiment: str, *, db_path: Optional[Path] = None) -> int:
    """#ops 로 — 키가 outbox 에 이미 있었으면(보낸 뒤 포함) 다시 올리지 않는다. 올린 건수."""
    from nuri.agents.discord.outbox import stage_ops

    staged = 0
    for f in found:
        key = f"thesis-pilot:{experiment}:{f['cohort']}:{f['kind']}"
        if query("SELECT 1 FROM discord_outbox WHERE dedupe_key = ? LIMIT 1", (key,), db_path=db_path):
            continue
        summary = f"⚠️ thesis pilot {experiment} {f['cohort']}: {f['kind']} — {f['detail']}"
        stage_ops({"summary": summary, "kind": "thesis_pilot"}, dedupe_key=key, db_path=db_path)
        staged += 1
    return staged


def _ticker_wall_seconds(experiment: str, db_path: Optional[Path]) -> list[float]:
    """밤마다 종목 하나가 끝나는 데 걸린 시간 — 배치 시작부터 종목별 마지막 기록까지의 간격."""
    starts = {
        r["batch_id"]: _utc(r["started_at"])
        for r in query(
            "SELECT batch_id, started_at FROM thesis_batches WHERE experiment = ?", (experiment,), db_path=db_path
        )
    }
    last: dict[str, dict[str, datetime]] = defaultdict(dict)
    for r in query(
        "SELECT batch_id, ticker, recorded_at FROM thesis_runs WHERE experiment = ? AND scored = 1",
        (experiment,),
        db_path=db_path,
    ):
        t = _utc(r["recorded_at"])
        prev = last[r["batch_id"]].get(r["ticker"])
        last[r["batch_id"]][r["ticker"]] = max(prev, t) if prev else t
    out: list[float] = []
    for batch_id, ends in last.items():
        if batch_id not in starts:
            continue
        mark = starts[batch_id]
        for end in sorted(ends.values()):
            out.append((end - mark).total_seconds())
            mark = end
    return out


def _overlaps(experiment: str, db_path: Optional[Path]) -> Counter[str]:
    """배치가 도는 동안 함께 돈 예약 작업 — 이름별 건수."""
    nights = [
        (_utc(n["started_at"]), _utc(n["ended_at"]))
        for n in query(
            "SELECT started_at, ended_at FROM thesis_pilot_nights "
            "WHERE experiment = ? AND outcome = 'ran' AND ended_at IS NOT NULL",
            (experiment,),
            db_path=db_path,
        )
    ]
    jobs = [
        # 끝나지 않은 작업은 아직 돌고 있다 — 시작 시각으로 접으면 밤 내내 돈 작업을 놓친다 (Codex 리뷰)
        (
            r["name"],
            _utc(r["started_at"]),
            _utc(r["finished_at"]) if r["finished_at"] else datetime.max.replace(tzinfo=timezone.utc),
        )
        for r in query(
            "SELECT collector_name AS name, started_at, finished_at FROM collector_runs "
            "UNION ALL SELECT actor_name, started_at, finished_at FROM agent_run_ledger",
            db_path=db_path,
        )
    ]
    return Counter(name for start, end in nights for name, s, e in jobs if s < end and e > start)


def report(experiment: str, *, db_path: Optional[Path] = None) -> dict[str, Any]:
    """E 가 쓸 운영 숫자 — 집계만."""
    nights = query(
        "SELECT cohort_date, outcome, exit_code, tickers FROM thesis_pilot_nights WHERE experiment = ?",
        (experiment,),
        db_path=db_path,
    )
    runs = query(
        "SELECT arm, outcome, rating, cohort_date FROM thesis_runs WHERE experiment = ? AND scored = 1",
        (experiment,),
        db_path=db_path,
    )
    # 완료율의 분자 · 분모는 같은 밤들에서 — 끝까지 돈 밤(`ran`)의 추첨 수와 그 밤들의 판정 (Codex 리뷰: 1.6)
    ran = {n["cohort_date"] for n in nights if n["outcome"] == "ran"}
    drawn = sum(n["tickers"] or 0 for n in nights if n["cohort_date"] in ran)
    arms: dict[str, Any] = {}
    for arm in sorted({r["arm"] for r in runs}):
        mine = [r for r in runs if r["arm"] == arm]
        verdicts = sum(r["outcome"] == "verdict" and r["cohort_date"] in ran for r in mine)
        arms[arm] = {
            "runs": len(mine),
            "outcomes": dict(sorted(Counter(r["outcome"] for r in mine).items())),
            "review_rate": round(sum(r["rating"] == "REVIEW" for r in mine) / len(mine), 3),
            "completion": round(verdicts / drawn, 3) if drawn else None,
        }
    wall = _ticker_wall_seconds(experiment, db_path)
    mem = query(
        # 스왑은 최댓값만 보면 배치 전부터 있던 사용량을 배치 탓으로 읽는다 — 최소 · 최대 · 증가분을 함께 (리허설 실측)
        "SELECT MIN(available_pct) AS min_available_pct, MIN(swap_used_mb) AS min_swap_mb, "
        "MAX(swap_used_mb) AS max_swap_mb, MAX(swap_used_mb) - MIN(swap_used_mb) AS swap_growth_mb, "
        "COUNT(*) AS samples "
        "FROM thesis_pilot_samples WHERE experiment = ?",
        (experiment,),
        db_path=db_path,
    )[0]
    return {
        "experiment": experiment,
        "nights": dict(sorted(Counter(n["outcome"] or "unfinished" for n in nights).items())),
        "drawn_tickers": drawn,
        "arms": arms,
        "ticker_wall_s": {
            "n": len(wall),
            "median": statistics.median(wall) if wall else None,
            "max": max(wall) if wall else None,
        },
        "memory": dict(mem),
        "overlapping_jobs": dict(sorted(_overlaps(experiment, db_path).items())),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Thesis pilot ops: alerts to #ops and an aggregate ledger report.")
    p.add_argument("command", choices=["check", "report"])
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    pilot = tp.load_pilot(tp.PILOT_PATH)
    if pilot is None:
        print("disabled")
        return 0
    if args.command == "report":
        print(json.dumps(report(pilot.experiment, db_path=args.db), indent=2))
        return 0
    found = findings(pilot, kst_now(), defer_hours=defer_hours(os.getenv("THESIS_DEFER_HOURS")), db_path=args.db)
    print(json.dumps({"findings": len(found), "staged": stage(found, pilot.experiment, db_path=args.db)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
