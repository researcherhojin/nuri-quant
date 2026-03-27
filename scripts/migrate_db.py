"""DB 스키마 생성/마이그레이션 스크립트."""
from nuri.core.db import get_connection, get_schema_version, init_db


def main():
    print("=== Nuri-Quant DB Migration ===")
    init_db()

    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    version = get_schema_version()
    print(f"Schema version: {version}")
    print(f"Tables ({len(tables)}):")
    for t in tables:
        print(f"  - {t['name']}")
    print("=== Migration complete ===")


if __name__ == "__main__":
    main()
