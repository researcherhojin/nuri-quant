#!/usr/bin/env python3
"""DB 유지보수 — WAL checkpoint + VACUUM. 행을 지우지 않는다.

지우지 않는 이유는 테이블마다 문서화된 계약이다:
  - pipeline_events — append-only event journal (STRATEGY §2.4, `nuri/core/CLAUDE.md`
    "Never delete events").
  - strategy_memory — append-only learning memory (`nuri/trading/engine/memory.py`).
  - recommendations·decisions — 측정 원장 (STRATEGY §3.11).

여기 있던 보존 정책(pipeline_events 90일 · strategy_memory 365일)은 한 번도 커밋되지 않았다.
strategy_memory 는 없는 컬럼(`date`)을 가리켰고, 광범위 except 가 그 예외를 "테이블 미존재
가능" 경고로 바꿨다. 지울 행이 있는 주에는 checkpoint 가 DELETE 와 같은 트랜잭션 안에서
"database table is locked" 로 실패해 get_db 가 DELETE 를 롤백했다. 버그를 고치면 위 계약을
처음으로 깨게 되므로 정책을 걷어냈다 (#1786). 보존 정리를 켜는 것은 그 계약을 바꾸는 일이다.

사용법:
    python scripts/db/maintenance.py
    python scripts/db/maintenance.py --dry-run
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("db_maintenance")


def run_maintenance(dry_run: bool = False):
    """WAL checkpoint + VACUUM — 둘 다 트랜잭션 밖(autocommit)에서."""
    if dry_run:
        logger.info("[DRY-RUN] WAL checkpoint + VACUUM 생략")
        return

    import sqlite3

    from nuri.core.db import DB_PATH

    vc = sqlite3.connect(str(DB_PATH))
    vc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    logger.info("WAL checkpoint 완료")
    vc.execute("VACUUM")
    vc.close()
    logger.info("DB 유지보수 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DB 유지보수")
    parser.add_argument("--dry-run", action="store_true", help="checkpoint·VACUUM 없이 종료")
    args = parser.parse_args()
    run_maintenance(dry_run=args.dry_run)
