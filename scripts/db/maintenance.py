#!/usr/bin/env python3
"""DB 유지보수 — 오래된 데이터 정리 + WAL checkpoint + VACUUM.

보존정책:
  - pipeline_events: 90일
  - strategy_memory: 365일
  - recommendations (outcome 기록 완료): 180일

사용법:
    python scripts/maintenance.py
    python scripts/maintenance.py --dry-run
"""
import argparse
import logging

from nuri.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("db_maintenance")

RETENTION_POLICIES = [
    ("pipeline_events", "timestamp", 90),
    ("strategy_memory", "date", 365),
]


def run_maintenance(dry_run: bool = False):
    """데이터 정리 + WAL checkpoint + VACUUM."""
    with get_db() as conn:
        # 1. 보존정책에 따라 오래된 데이터 삭제
        for table, date_col, days in RETENTION_POLICIES:
            count_sql = f"SELECT COUNT(*) as cnt FROM {table} WHERE {date_col} < date('now', '-{days} days')"  # noqa: E501
            try:
                row = conn.execute(count_sql).fetchone()
                count = row["cnt"] if row else 0
            except Exception:
                logger.warning("테이블 %s 조회 실패 (미존재 가능)", table)
                continue

            if count == 0:
                logger.info("%s: 삭제 대상 없음", table)
                continue

            if dry_run:
                logger.info("[DRY-RUN] %s: %d행 삭제 예정 (%d일 초과)", table, count, days)
            else:
                conn.execute(
                    f"DELETE FROM {table} WHERE {date_col} < date('now', '-{days} days')"  # noqa: E501
                )
                logger.info("%s: %d행 삭제 완료 (%d일 초과)", table, count, days)

        # 2. WAL checkpoint (WAL 파일을 main DB에 통합)
        if not dry_run:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 완료")

    # 3. VACUUM (get_db 밖에서 실행 — autocommit 모드 필요)
    if not dry_run:
        import sqlite3

        from nuri.core.db import DB_PATH
        vc = sqlite3.connect(str(DB_PATH))
        vc.execute("VACUUM")
        vc.close()
        logger.info("VACUUM 완료")

    logger.info("DB 유지보수 %s", "시뮬레이션 완료" if dry_run else "완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DB 유지보수")
    parser.add_argument("--dry-run", action="store_true", help="삭제 없이 시뮬레이션")
    args = parser.parse_args()
    run_maintenance(dry_run=args.dry_run)
