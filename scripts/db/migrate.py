"""DB 스키마 생성/마이그레이션 스크립트.

`make migrate` 가 `--quiet` 로 부른다 — `collect` · `quick-scan` · `full-scan` 이 그 타깃을 먼저 돈다 (#1828).
"""

import argparse

from nuri.core.db import get_connection, get_schema_version, init_db


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DB 스키마 생성/마이그레이션")
    parser.add_argument("--quiet", action="store_true", help="테이블 목록 없이 스키마 버전 한 줄만 출력")
    args = parser.parse_args(argv)

    if not args.quiet:
        print("=== Nuri-Quant DB Migration ===")
    init_db()

    conn = get_connection()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    conn.close()

    version = get_schema_version()
    if args.quiet:
        print(f"DB schema version {version} ({len(tables)} tables)")
        return
    print(f"Schema version: {version}")
    print(f"Tables ({len(tables)}):")
    for t in tables:
        print(f"  - {t['name']}")
    print("=== Migration complete ===")


if __name__ == "__main__":
    main()
