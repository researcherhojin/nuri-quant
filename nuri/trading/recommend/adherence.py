"""추천 이행 여부 진단 (#1722) — 합의 BUY/SELL 을 운영자가 따랐는가.

운영자는 주문을 손으로 낸다(§7.1). 그래서 추천의 결과가 나빴을 때 "추천이 틀렸다" 와 "추천을
안 따랐다" 가 구분되지 않았다. 보유 변경 원장(`portfolio_changes`, #1720)의 순변화로 분류한다.

- **에피소드** — 합의는 보유 종목마다 매일 판정을 낸다. 같은 종목의 같은 BUY/SELL 을, 앞 추천과의
  간격이 `adherence.window_days` 이하인 한 한 에피소드로 묶는다 (매도 한 번에 연속 SELL 열 번이
  전부 '따름' 으로 세지지 않게). HOLD 는 행동 추천이 아니라 건너뛴다 — 끊으면 SELL·HOLD·SELL 의
  두 창이 겹쳐 매도 한 번이 두 번 세진다. 반대 행동이 끼거나 간격이 창보다 길면 새 에피소드다.
- **분류** — 시작일 **다음 날**부터 마지막 추천일 + `window_days` 까지의 그 종목 순변화:
  추천 방향이면 `followed`, 반대면 `contrary`. 순변화 0 이면 그 창에 **이 종목을 담은 계좌**의
  가져오기·편집 흔적이 있을 때만 `not_followed` (처음 사는 종목이면 어느 계좌든) — 다른 계좌만
  가져왔다면 이 종목은 본 적이 없으니 `unknown`. 원장 시작 전 에피소드도 `unknown`, 창이 아직
  닫히지 않았으면 `open` — 지어내지 않는다.

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


@dataclass(frozen=True)
class Episode:
    ticker: str
    action: str
    start: str
    end: str
    days: int


def episodes(db_path: Optional[Path] = None, since: Optional[str] = None) -> list[Episode]:
    """합의 추천(`source IS NULL`)을 종목별 BUY/SELL 에피소드로. `since` 는 **묶은 뒤** 시작일로 거른다
    — 먼저 거르면 이어지던 에피소드가 그 날짜에서 새로 시작하는 것처럼 보인다."""
    from nuri.core.rules import ADHERENCE

    max_gap = int(ADHERENCE["window_days"])
    rows = query(
        "SELECT ticker, date, action FROM recommendations WHERE source IS NULL AND action IN ('BUY', 'SELL') "
        "ORDER BY ticker, date",
        db_path=db_path,
        readonly=True,
    )
    out: list[Episode] = []
    cur: Optional[list] = None  # [ticker, action, start, end, days]
    for r in rows:
        ticker, day, action = r["ticker"], r["date"], r["action"]
        if (
            cur
            and cur[0] == ticker
            and cur[1] == action
            and (date.fromisoformat(day) - date.fromisoformat(cur[3])).days <= max_gap
        ):
            cur[3], cur[4] = day, cur[4] + 1
            continue
        if cur:
            out.append(Episode(*cur))
        cur = [ticker, action, day, day, 1]
    if cur:
        out.append(Episode(*cur))
    return [e for e in out if since is None or e.start >= since]


def classify(episode: Episode, window_days: int, today: str, db_path: Optional[Path] = None) -> str:
    lo = (date.fromisoformat(episode.start) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(episode.end) + timedelta(days=1 + window_days)).isoformat()
    if hi > today:
        return "open"
    log_start = query("SELECT MIN(changed_at) AS t FROM portfolio_changes", db_path=db_path, readonly=True)[0]["t"]
    if log_start is None or log_start[:10] > lo:
        return "unknown"
    window = query(
        "SELECT account, ticker, COALESCE(new_quantity, 0) - COALESCE(old_quantity, 0) AS delta "
        "FROM portfolio_changes WHERE changed_at >= ? AND changed_at < ?",
        (lo, hi),
        db_path=db_path,
        readonly=True,
    )
    net = sum(r["delta"] for r in window if r["ticker"] == episode.ticker)
    wanted = 1 if episode.action == "BUY" else -1
    if net * wanted > 0:
        return "followed"
    if net * wanted < 0:
        return "contrary"
    # 순변화 0 — 이 종목을 담은 계좌를 그 창에 본 적이 있어야 '안 따름' 이다
    holders = {
        r["account"]
        for r in query(
            "SELECT DISTINCT account FROM portfolio_changes WHERE ticker = ? AND changed_at < ?",
            (episode.ticker, hi),
            db_path=db_path,
            readonly=True,
        )
    }
    seen = any(r["account"] in holders for r in window) if holders else bool(window)
    return "not_followed" if seen else "unknown"


def summarize(db_path: Optional[Path] = None, since: Optional[str] = None, today: Optional[str] = None) -> dict:
    from nuri.core.rules import ADHERENCE
    from nuri.core.timezone import today_kst

    window = int(ADHERENCE["window_days"])
    today = today or str(today_kst())
    counts: Counter = Counter()
    for ep in episodes(db_path=db_path, since=since):
        counts[(ep.action, classify(ep, window, today, db_path=db_path))] += 1
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
