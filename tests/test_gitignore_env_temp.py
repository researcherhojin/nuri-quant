"""rsync .env 임시 사본이 git 에 절대 못 들어온다 (#1316 계열, 2026-08-30 니어미스).

MBP `.env` 는 UF_IMMUTABLE 이라 sync 의 rsync 가 rename 에 실패하면
`..env.<random>` 임시 사본(= 송신측 .env 전문, 시크릿 포함)을 워킹트리에
남긴다. `.env` 패턴은 이 이름을 커버하지 않아 `git add -A` 가 쓸어 담고,
2026-08-30 실제로 커밋까지 갔다가 GitHub push protection 이 차단했다.
마지막 방어선이 외부 서비스여선 안 된다 — 패턴을 잠근다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestRsyncEnvTempIsIgnored:
    def test_env_temp_pattern_is_ignored(self) -> None:
        """`..env.<random>` 형태가 check-ignore 에 걸려야 한다 — 패턴을 지우면 FAIL."""
        rc = subprocess.run(
            ["git", "check-ignore", "-q", "..env.pJM94Qcxzw"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        assert rc.returncode == 0, "..env.* 가 gitignore 에 없다 — rsync 임시 시크릿 사본이 add -A 에 쓸린다"

    def test_no_env_temp_is_tracked(self) -> None:
        """혹시 이미 추적된 사본이 있으면 그 자체가 사고다."""
        out = subprocess.run(
            ["git", "ls-files", "..env.*"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert out == "", f"추적된 .env 임시 사본 발견: {out}"
