"""recommendations.regime 라벨 백필 (#832 — 진단 전용, STRATEGY §3.11 판정 비사용).

과거 recommendations 행의 regime 을 해당 date 기준 `classify_regime(date=...)` 역산으로
채운다. 라벨은 진단 대시보드/리포트 전용 — 판정 로직에 연결하지 않는다.

규칙:
- canonical ALL_REGIMES 값이 이미 있는 행은 건드리지 않음 (멱등 — 재실행 시 skip)
- 당시 시점 데이터 부족(SPY < 200일 등)으로 분류 불가한 행은 NULL 유지 ('unknown' 라벨 금지)
- 빈문자열·free-text ("[recovery] 비중 축소" 등) 행은 재분류, 재분류 불가 시 NULL 로 정규화
  (emit 경로가 canonical-or-NULL invariant 를 강제하므로 원장도 동일 상태로 수렴)

사용법:
    .venv/bin/python scripts/ops/backfill_regime_labels.py --dry-run   # 변경 미리보기 (write 없음)
    .venv/bin/python scripts/ops/backfill_regime_labels.py             # 실제 백필
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def _coverage(db_path=None) -> tuple[int, int]:
    """(canonical 라벨 행 수, 전체 행 수) 반환."""
    from nuri.core.db import query
    from nuri.quant.regime.classifier import ALL_REGIMES

    placeholders = ",".join("?" * len(ALL_REGIMES))
    total = query("SELECT COUNT(*) AS c FROM recommendations", db_path=db_path)[0]["c"]
    labeled = query(
        f"SELECT COUNT(*) AS c FROM recommendations WHERE regime IN ({placeholders})",
        tuple(ALL_REGIMES),
        db_path=db_path,
    )[0]["c"]
    return labeled, total


def backfill_regime_labels(db_path=None, dry_run: bool = False) -> dict:
    """비-canonical regime 행을 date 기준 classify_regime 역산으로 백필.

    Returns:
        stats dict — candidates / relabeled / normalized_null / kept_null /
        unclassifiable_dates / coverage_before / coverage_after
    """
    from nuri.core.db import get_db, query
    from nuri.quant.regime.classifier import ALL_REGIMES, canonical_regime_or_none, classify_regime

    labeled_before, total = _coverage(db_path)

    placeholders = ",".join("?" * len(ALL_REGIMES))
    rows = query(
        f"SELECT id, date, regime FROM recommendations WHERE regime IS NULL OR regime NOT IN ({placeholders})",
        tuple(ALL_REGIMES),
        db_path=db_path,
    )

    # date 별 1회 classify (같은 날 행들이 라벨 공유 — emit 경로 batch classify 와 동일 semantic)
    regime_by_date: dict[str, str | None] = {}
    for d in sorted({r["date"] for r in rows}):
        state = classify_regime(date=d, db_path=db_path)
        regime_by_date[d] = canonical_regime_or_none(state.regime) if state is not None else None

    updates: list[tuple[str | None, int]] = []
    stats = {
        "candidates": len(rows),
        "relabeled": 0,  # canonical 라벨 채움
        "normalized_null": 0,  # 빈문자열/free-text 인데 분류 불가 → NULL 정규화
        "kept_null": 0,  # NULL 인데 분류 불가 → NULL 유지
    }
    for r in rows:
        label = regime_by_date.get(r["date"])
        if label is not None:
            updates.append((label, r["id"]))
            stats["relabeled"] += 1
        elif r["regime"] is not None:
            updates.append((None, r["id"]))
            stats["normalized_null"] += 1
        else:
            stats["kept_null"] += 1

    if updates and not dry_run:
        with get_db(db_path) as conn:
            conn.executemany("UPDATE recommendations SET regime = ? WHERE id = ?", updates)

    labeled_after = labeled_before if dry_run else _coverage(db_path)[0]
    stats["unclassifiable_dates"] = sorted(d for d, v in regime_by_date.items() if v is None)
    stats["coverage_before"] = f"{labeled_before}/{total}"
    stats["coverage_after"] = f"{labeled_after}/{total}" + (" (dry-run, write 없음)" if dry_run else "")
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="recommendations.regime 라벨 백필 (#832)")
    parser.add_argument("--dry-run", action="store_true", help="DB write 없이 변경 예정 카운트만 출력")
    args = parser.parse_args(argv)

    stats = backfill_regime_labels(dry_run=args.dry_run)
    print(f"백필 대상 행: {stats['candidates']}")
    print(f"  canonical 라벨 채움: {stats['relabeled']}")
    print(f"  free-text/빈문자열 → NULL 정규화 (분류 불가): {stats['normalized_null']}")
    print(f"  NULL 유지 (분류 불가): {stats['kept_null']}")
    if stats["unclassifiable_dates"]:
        print(f"  분류 불가 날짜: {', '.join(stats['unclassifiable_dates'])}")
    print(f"커버리지: {stats['coverage_before']} → {stats['coverage_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
