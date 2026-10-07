"""추천 이행 여부 진단 (#1722) — 합의 BUY/SELL 을 운영자가 따랐는가.

운영자는 주문을 손으로 낸다(§7.1). 그래서 추천의 결과가 나빴을 때 "추천이 틀렸다" 와 "추천을
안 따랐다" 가 구분되지 않았다. 보유 변경 원장(`portfolio_changes`, #1720)의 순변화로 분류한다.

- **에피소드** — 합의는 보유 종목마다 매일 판정을 낸다. 같은 종목에 같은 BUY/SELL 이 연달아
  나오면 한 에피소드로 묶는다 (매도 한 번에 연속 SELL 열 번이 전부 '따름' 으로 세지지 않게).
  HOLD 는 행동 추천이 아니라 건너뛰고, 다른 행동이 끼면 에피소드가 끊긴다.
- **분류** — 에피소드 시작일 **다음 날**부터 `adherence.window_days` 일 동안의 그 종목 순변화:
  추천 방향이면 `followed`, 반대면 `contrary`. 순변화 0 인데 그 창에 가져오기·편집 흔적(어떤
  종목이든 원장 행)이 있으면 `not_followed`, 흔적이 없으면 `unknown` — 지어내지 않는다.
  원장이 시작되기 전 에피소드도 `unknown`.

**진단 전용** — §3.11 판정(`decision_alpha`)은 이것을 읽지 않는다. 판정 표본 규약은 사전등록이다.
**알려진 오탐** — 액면분할·병합은 수량을 바꾸므로 BUY/SELL 로 보인다(기업행동 피드가 없다, 특히 KR).
결과는 저장하지 않는다 — 규칙을 다듬을 때마다 낡는 표가 생기지 않도록 매번 원장에서 계산한다.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from nuri.core.db import query

ACTIONS = ("BUY", "SELL")


@dataclass(frozen=True)
class Episode:
    ticker: str
    action: str
    start: str
    end: str
    days: int


def episodes(db_path: Optional[Path] = None, since: Optional[str] = None) -> list[Episode]:
    """합의 추천(`source IS NULL`)을 종목별 연속 BUY/SELL 묶음으로."""
    rows = query(
        "SELECT ticker, date, action FROM recommendations WHERE source IS NULL AND date >= ? ORDER BY ticker, date",
        (since or "0000-00-00",),
        db_path=db_path,
        readonly=True,
    )
    out: list[Episode] = []
    cur: Optional[list] = None  # [ticker, action, start, end, days]
    for r in rows:
        ticker, day, action = r["ticker"], r["date"], r["action"]
        if cur and cur[0] == ticker and cur[1] == action:
            cur[3], cur[4] = day, cur[4] + 1
            continue
        if cur:
            out.append(Episode(*cur))
        cur = [ticker, action, day, day, 1] if action in ACTIONS else None
    if cur:
        out.append(Episode(*cur))
    return out


def classify(episode: Episode, window_days: int, db_path: Optional[Path] = None) -> str:
    start = date.fromisoformat(episode.start)
    lo = (start + timedelta(days=1)).isoformat()
    hi = (start + timedelta(days=1 + window_days)).isoformat()
    log_start = query("SELECT MIN(changed_at) AS t FROM portfolio_changes", db_path=db_path, readonly=True)[0]["t"]
    if log_start is None or log_start[:10] > lo:
        return "unknown"
    window = query(
        "SELECT ticker, COALESCE(new_quantity, 0) - COALESCE(old_quantity, 0) AS delta "
        "FROM portfolio_changes WHERE changed_at >= ? AND changed_at < ?",
        (lo, hi),
        db_path=db_path,
        readonly=True,
    )
    if not window:
        return "unknown"
    net = sum(r["delta"] for r in window if r["ticker"] == episode.ticker)
    wanted = 1 if episode.action == "BUY" else -1
    if net * wanted > 0:
        return "followed"
    if net * wanted < 0:
        return "contrary"
    return "not_followed"


def summarize(db_path: Optional[Path] = None, since: Optional[str] = None) -> dict:
    from nuri.core.rules import ADHERENCE

    window = int(ADHERENCE["window_days"])
    counts: Counter = Counter()
    for ep in episodes(db_path=db_path, since=since):
        counts[(ep.action, classify(ep, window, db_path=db_path))] += 1
    return {"window_days": window, "counts": {f"{a}:{c}": n for (a, c), n in sorted(counts.items())}}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="합의 추천 이행 여부 진단 (#1722, 진단 전용)")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--since", default=None, help="이 날짜(YYYY-MM-DD) 이후 에피소드만")
    args = parser.parse_args(argv)
    result = summarize(db_path=args.db, since=args.since)
    print(f"창 {result['window_days']}일 — 에피소드 분류 (종목명 없이 집계만)")
    for key, n in result["counts"].items():
        print(f"  {key:24} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
