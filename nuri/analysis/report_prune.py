"""`data/reports/` 날짜 디렉터리 보존 (#1654).

하루치 실행이 `data/reports/YYYY-MM-DD/` 에 증거 차트(24–32 MB)와 CSV/MD 산출물을 남긴다.
지우는 주체가 없어 dev 에서 69 디렉터리 1.2 GB 까지 자랐다. 어떤 소비자도 날짜 디렉터리를
**가로질러** 이력을 읽지 않는다 — 전부 "그 산출물이 있는 가장 최근 디렉터리" 하나를 집는다:
`routes/evidence.py` · `evidence_data.py` 는 `evidence/` 가 있는 최신 디렉터리, `routes/signals.py` ·
`engine/gate.py` · `recommend/candidates.py` 는 최신 `signal_scorecard.csv`, `engine/memory.py` ·
`regime/strategy_map.py` 는 최신 `signal_results.csv`.

그 산출물은 **자동으로 다시 만들어지지 않는다** — 스케줄러에는 scorecard/results 를 쓰는 잡이 없고
`make validate` / `make full-scan` (Phase C) 를 사람이 돌릴 때만 생긴다(dev 실측: scorecard 가 있는
디렉터리는 08-17 · 08-30 · 10-06 셋뿐, 그 사이는 evidence 만). 그래서 "가장 최근 디렉터리" 만
남기면 scorecard 가 든 8월 디렉터리를 지우고 소비자가 빈손이 된다(Codex #1654 P1). 보존 규칙은
두 겹이다: 보존 기간 안의 날짜 디렉터리, 그리고 **소비되는 산출물마다 그것이 있는 최신 디렉터리**.

지우지 않는 것: 비-날짜 디렉터리(`briefs/` `postmarket/` `theses/` `buy_tracking/` — 원장 성격),
오늘보다 뒤인 날짜 디렉터리(잘못 생성된 미래 디렉터리 — `evidence_data.py` 참조. 여기서 판단하지 않는다).

보존 일수는 인프라 상수다 (CONTRIBUTING "What goes in config vs hardcoded"). 2026-10-06 maintainer 결정 30일.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
REPORT_RETENTION_DAYS = 30
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 소비자가 "있는 가장 최근 디렉터리" 로 찾는 산출물 — 각각 최신 보유 디렉터리는 나이와 무관하게 남긴다.
# 새 소비자가 생기면 여기에 더한다; 빠뜨리면 보존 기간이 지난 어느 일요일에 그 소비자가 빈손이 된다.
CONSUMED_ARTIFACTS: tuple[str, ...] = (
    "signal_scorecard.csv",
    "signal_results.csv",
    "superinvestor_scorecard.csv",
    "evidence",
)


def prunable_report_dirs(
    report_dir: Path = REPORT_DIR,
    retention_days: int = REPORT_RETENTION_DAYS,
    today: str | None = None,
) -> list[Path]:
    """보존 기간을 지난 날짜 디렉터리 — 오름차순.

    비-날짜 · 미래 디렉터리, 가장 최근 날짜 디렉터리, 그리고 `CONSUMED_ARTIFACTS` 각각을 가진
    가장 최근 디렉터리는 제외한다.
    """
    today = today or today_kst()
    cutoff = (date.fromisoformat(today) - timedelta(days=retention_days)).isoformat()
    if not report_dir.exists():
        return []
    dated = sorted(d for d in report_dir.iterdir() if d.is_dir() and _DATE_DIR_RE.match(d.name))
    past = [d for d in dated if d.name <= today]
    keep: set[Path] = set(past[-1:])
    for artifact in CONSUMED_ARTIFACTS:
        holders = [d for d in past if (d / artifact).exists()]
        if holders:
            keep.add(holders[-1])
    return [d for d in past if d.name < cutoff and d not in keep]


def prune_report_dirs(
    report_dir: Path = REPORT_DIR,
    retention_days: int = REPORT_RETENTION_DAYS,
    today: str | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """보존 기간을 지난 날짜 디렉터리를 지우고 지운(또는 지울) 목록을 돌려준다."""
    targets = prunable_report_dirs(report_dir, retention_days, today)
    for d in targets:
        if dry_run:
            logger.info("prune (dry-run): %s", d)
        else:
            shutil.rmtree(d)
            logger.info("pruned: %s", d)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="data/reports 날짜 디렉터리 보존 정리")
    parser.add_argument(
        "--days", type=int, default=REPORT_RETENTION_DAYS, help=f"보존 일수 (기본 {REPORT_RETENTION_DAYS})"
    )
    parser.add_argument("--dry-run", action="store_true", help="지우지 않고 대상만 출력")
    args = parser.parse_args(argv)
    # 기본 인자는 정의 시점에 묶이므로 모듈 전역을 호출 시점에 읽는다 (테스트가 REPORT_DIR 을 바꾼다)
    targets = prune_report_dirs(REPORT_DIR, args.days, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    for d in targets:
        print(f"  {verb} {d.name}")
    print(f"{verb} {len(targets)} report directories older than {args.days} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
