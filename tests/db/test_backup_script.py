"""원장 백업 스크립트 계약 (`scripts/db/backup.sh`, #835).

두 가지를 잠근다:
1. **WAL 안전성** — writer 가 붙어 커밋이 아직 `-wal` 에 있을 때도 스냅샷이
   완전해야 한다. 예전 `cp` 는 여기서 테이블 자체를 통째로 놓쳤다.
2. **검증 후 산출** — 깨진 스냅샷은 남기지 않고 실패로 끝나야 한다. SHA256 은
   "복사 후 안 바뀜"만 증명하므로, 검증 없이는 못 쓰는 백업에 정상 체크섬이
   붙어 거짓 안심을 준다.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "db" / "backup.sh"
LEDGER_TABLES = ("decision_outcomes", "decisions", "recommendations", "portfolio")


def _make_ledger(db: Path, rows: int = 300) -> sqlite3.Connection:
    """WAL 모드 원장 + **열린 writer 연결** 반환 (커밋은 아직 -wal 에)."""
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    for t in LEDGER_TABLES:
        conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, v TEXT)")  # noqa: S608
    conn.commit()
    conn.executemany("INSERT INTO decision_outcomes(v) VALUES (?)", [(f"r{i}",) for i in range(rows)])
    conn.commit()
    return conn


class TestWalSafety:
    def test_snapshot_is_complete_while_a_writer_holds_the_wal(self, tmp_path):
        """열린 writer + 미체크포인트 상태에서도 행이 전부 보존된다.

        Gotcha-Test Pair: `cp` 로 되돌리면 이 테스트가 실패한다 — 실측상
        `cp` 는 이 상황에서 `no such table` 이 나올 정도로 아무것도 못 가져온다.
        """
        db = tmp_path / "portfolio.db"
        writer = _make_ledger(db, rows=300)
        try:
            assert (tmp_path / "portfolio.db-wal").exists(), "WAL 사이드카 전제 실패"
            out = tmp_path / "snap.db"
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            dst = sqlite3.connect(out)
            src.backup(dst)
            dst.close()
            src.close()
        finally:
            writer.close()

        c = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
        try:
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0] == 300
        finally:
            c.close()

    def test_plain_copy_loses_wal_data(self, tmp_path):
        """왜 primitive 를 바꿨는지를 고정 — 회귀 시 근거가 남아 있어야 한다."""
        db = tmp_path / "portfolio.db"
        writer = _make_ledger(db, rows=300)
        try:
            copied = tmp_path / "cp.db"
            shutil.copyfile(db, copied)
        finally:
            writer.close()

        c = sqlite3.connect(f"file:{copied}?mode=ro", uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                c.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()
        finally:
            c.close()


class TestScriptBehaviour:
    """스크립트를 실제로 실행한다 — 레포 복사본 안에서만.

    `BACKUP_DIR` 는 스크립트가 자기 위치로부터 계산하므로, 레포 원본을 그대로
    돌리면 진짜 `data/backups/` 에 쓴다. 스크립트 + venv 심볼릭만 갖춘 최소
    복사본을 tmp_path 에 만들어 격리한다 (tests/CLAUDE.md DB 격리와 같은 취지).
    """

    @pytest.fixture
    def sandbox(self, tmp_path):
        root = tmp_path / "repo"
        (root / "scripts" / "db").mkdir(parents=True)
        (root / "data").mkdir()
        shutil.copy2(SCRIPT, root / "scripts" / "db" / "backup.sh")
        return root

    def _run(self, sandbox: Path, db: Path):
        return subprocess.run(
            ["bash", str(sandbox / "scripts" / "db" / "backup.sh")],
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "NURI_DB_PATH": str(db)},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_missing_db_fails_loudly(self, sandbox, tmp_path):
        r = self._run(sandbox, tmp_path / "absent.db")
        assert r.returncode == 1
        assert "DB 파일 없음" in (r.stderr + r.stdout)

    def test_corrupt_db_leaves_no_snapshot_behind(self, sandbox, tmp_path):
        """깨진 원장이면 실패로 끝나고 산출물을 남기지 않는다.

        Gotcha-Test Pair: `set -e` 하에서 검증을 `if !` 로 감싸지 않으면 python
        실패 순간 스크립트가 죽어 정리(rm)에 **도달하지 못하고** 깨진 스냅샷이
        남는다. 그러면 다음 복원 때 '최신 백업' 으로 집혀 그 시점에야 발각된다.
        (이 테스트가 실제로 그 버그를 잡았다.)
        """
        db = tmp_path / "portfolio.db"
        db.write_bytes(b"this is definitely not a sqlite database")
        r = self._run(sandbox, db)

        assert r.returncode == 1, f"손상 DB 인데 성공함: {r.stdout}"
        left = list((sandbox / "data" / "backups").glob("portfolio_*.db"))
        assert left == [], f"검증 실패한 스냅샷이 남았다: {left}"

    def test_healthy_db_produces_verified_snapshot_and_checksum(self, sandbox, tmp_path):
        db = tmp_path / "portfolio.db"
        _make_ledger(db, rows=50).close()
        r = self._run(sandbox, db)

        assert r.returncode == 0, r.stderr
        assert "verified: integrity=ok" in r.stdout
        snaps = list((sandbox / "data" / "backups").glob("portfolio_*.db"))
        assert len(snaps) == 1
        assert snaps[0].with_suffix(".db.sha256").exists(), "체크섬 사이드카 누락"
        c = sqlite3.connect(f"file:{snaps[0]}?mode=ro", uri=True)
        try:
            assert c.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0] == 50
        finally:
            c.close()
