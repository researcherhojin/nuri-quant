"""DB 스키마 생성/마이그레이션 스크립트."""
from nuri.db import init_db, get_connection


def main():
    print("=== Nuri-Quant DB Migration ===")
    init_db()

    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    print(f"Created {len(tables)} tables:")
    for t in tables:
        print(f"  - {t['name']}")
    print("=== Migration complete ===")


if __name__ == "__main__":
    main()
