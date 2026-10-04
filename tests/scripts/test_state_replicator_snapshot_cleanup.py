"""state_replicator primary 의 스냅샷 정리가 push·스냅샷 실패와 무관하게 도는지 (#1576).

Gotcha-Test Pair: 정리가 push **뒤에** 있으면 push 실패의 `exit 2` 가 정리까지 건너뛴다.
#1531 로 push 가 3주 실패하는 동안 mini 에 스냅샷 717개 · 161G 가 쌓였다. VACUUM 뒤에
있어도 같다 — 디스크가 차서 VACUUM 이 죽으면 `set -e` 가 정리를 건너뛰어 영영 안 비워진다.

grep 이 아니라 **실행**해서 본다 — 임시 레포에 스크립트를 복사하고 `hostname` / `ssh` /
`.venv/bin/python` 을 shim 으로 바꿔 push 가 실패하는 primary 런을 재현한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

SCRIPT = Path("scripts/deploy/state_replicator.sh")

# VACUUM INTO 대상 경로에 파일을 만들고, db_digest 호출에는 가짜 digest 를 낸다.
# `{vacuum_fail}` 이 `exit 1` 이면 디스크가 차서 VACUUM 이 죽은 경우를 흉내낸다.
_FAKE_PYTHON = r"""#!/bin/sh
case "$2" in
  *"VACUUM INTO"*)
    {vacuum_fail}
    snap=$(printf '%s' "$2" | sed -n "s/.*VACUUM INTO '\([^']*\)'.*/\1/p")
    : > "$snap" ;;
  *) printf '%s\n' "sha=fake schema=0 tables=0" ;;
esac
"""


def _shim(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_primary(tmp_path: Path, *, vacuum_fails: bool = False) -> tuple[subprocess.CompletedProcess, Path]:
    """push 는 항상 실패한다(ssh exit 255). `vacuum_fails` 면 그 전에 스냅샷부터 실패한다."""
    repo = tmp_path / "repo"
    (repo / "scripts/deploy").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / SCRIPT)
    (repo / ".venv/bin").mkdir(parents=True)
    _shim(repo / ".venv/bin/python", _FAKE_PYTHON.replace("{vacuum_fail}", "exit 1" if vacuum_fails else ":"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _shim(bin_dir / "hostname", "#!/bin/sh\nprintf '%s\\n' testmacmini\n")
    _shim(bin_dir / "ssh", "#!/bin/sh\nexit 255\n")

    backups = repo / "data/backups"
    backups.mkdir(parents=True)
    old = backups / "snapshot_20200101_000000.db"
    old.touch()
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DEV2_HOST": "replica.invalid"}
    env.pop("NURI_DB_PATH", None)
    proc = subprocess.run(["bash", str(repo / SCRIPT), "primary"], capture_output=True, text=True, env=env, check=False)
    return proc, backups


class TestSnapshotCleanupSurvivesPushFailure:
    def test_old_snapshot_is_deleted_even_when_push_fails(self, tmp_path):
        proc, backups = _run_primary(tmp_path)
        assert proc.returncode == 2, f"push 실패 경로를 못 탔다:\n{proc.stdout}\n{proc.stderr}"
        assert not (backups / "snapshot_20200101_000000.db").exists(), (
            "push 가 실패하자 7일 지난 스냅샷이 남았다 — 정리가 push 뒤로 돌아갔다 (#1576)"
        )

    def test_fresh_snapshot_is_kept(self, tmp_path):
        """정리가 방금 만든 스냅샷까지 지우면 안 된다."""
        _, backups = _run_primary(tmp_path)
        remaining = [p.name for p in backups.glob("snapshot_*.db")]
        assert len(remaining) == 1 and remaining[0] != "snapshot_20200101_000000.db"

    def test_old_snapshot_is_deleted_even_when_vacuum_fails(self, tmp_path):
        """디스크가 차서 VACUUM 이 죽어도 정리는 돌아야 한다 — 아니면 디스크가 영영 안 비워진다."""
        proc, backups = _run_primary(tmp_path, vacuum_fails=True)
        assert proc.returncode != 0
        assert not (backups / "snapshot_20200101_000000.db").exists(), (
            "VACUUM 실패 후 7일 지난 스냅샷이 남았다 — 정리가 스냅샷 생성 뒤로 돌아갔다 (#1576)"
        )
