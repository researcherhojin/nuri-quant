r"""state_replicator 의 원격 수신 경로 검증 (#947).

Gotcha-Test Pair (두 개, 둘 다 조용히 틀리는 종류):

1. **`host:relative/path` 는 수신 측 홈 기준으로 풀린다.** 보내는 쪽 cwd 와 무관하다.
   예전 코드는 `$DEV2_HOST:data/replicas/...` 라 스냅샷이 레포가 아니라
   `~/data/replicas/` 로 떨어졌다 (2026-07-29 실측: 136MB 가 홈에 쌓였다).
   rsync 는 성공을 보고하므로 아무도 몰랐다.

2. **`${VAR#~/}` 는 `~` 를 안 지운다.** bash 가 **패턴 쪽 물결표를 홈으로 확장**해
   `/Users/<user>/` 와 비교하므로 매칭이 실패한다. `\~/` 로 escape 해야 한다.
   이걸 놓치면 원격 경로가 `~/workspace/...` 리터럴이 되어 또 엉뚱한 곳에 만들어진다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/deploy/state_replicator.sh")


def _bash(snippet: str) -> str:
    return subprocess.run(["bash", "-c", snippet], capture_output=True, text=True, check=True).stdout.strip()


class TestRemotePathIsRepoRelativeNotHome:
    def test_rsync_destination_uses_remote_repo_path(self):
        """rsync 목적지가 `$REMOTE_REPLICAS` 여야 한다 — `$REPLICAS_DIR` 이면 홈에 떨어진다."""
        text = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r'rsync[^\n]*"\$DEV2_HOST:([^"]+)"', text)
        assert m, "rsync push 라인을 못 찾았다 — 형태가 바뀌었으면 이 테스트를 갱신할 것"
        dest = m.group(1)
        assert dest.startswith("$REMOTE_REPLICAS"), (
            f"rsync 목적지가 {dest!r} — 홈 기준으로 풀려 레포 밖에 떨어진다 (#947)"
        )

    def test_remote_directory_is_created_before_push(self):
        """macOS openrsync 는 목적지 디렉터리를 안 만든다 — 선행 mkdir 필수."""
        text = SCRIPT.read_text(encoding="utf-8")
        mkdir_at = text.find("mkdir -p '$REMOTE_REPLICAS'")
        rsync_at = text.find('rsync -avz --partial "$SNAP"')
        assert mkdir_at != -1, "원격 mkdir 이 없다 — 신규 머신에서 rsync 가 죽는다 (#947)"
        assert mkdir_at < rsync_at, "mkdir 이 rsync 뒤에 있으면 소용없다"


class TestTildeStripping:
    """`${VAR#~/}` 함정 — 패턴의 `~` 가 확장돼 매칭이 조용히 실패한다."""

    def test_bare_tilde_pattern_does_not_strip(self):
        """이 테스트는 **bash 동작 자체**를 고정한다 — 함정이 실재함을 증명."""
        assert _bash('D="~/workspace/nuri-quant"; echo "${D#~/}"') == "~/workspace/nuri-quant"

    def test_escaped_tilde_pattern_strips(self):
        assert _bash(r'D="~/workspace/nuri-quant"; echo "${D#\~/}"') == "workspace/nuri-quant"

    def test_script_uses_escaped_form(self):
        text = SCRIPT.read_text(encoding="utf-8")
        assert r"${REMOTE_REPO#\~/}" in text, (
            r"`${REMOTE_REPO#~/}` 는 `~` 를 안 지운다 — `\~/` 로 escape 해야 한다 (#947)"
        )

    def test_normalisation_result(self):
        """세 가지 입력 모두 홈 기준 상대경로로 정규화된다."""
        norm = r'REMOTE_REPO="${DEV2_PATH:-~/workspace/nuri-quant}"; echo "${REMOTE_REPO#\~/}"'
        assert _bash(norm) == "workspace/nuri-quant"
        assert _bash(f'DEV2_PATH="~/workspace/nuri-quant"; {norm}') == "workspace/nuri-quant"
        assert _bash(f'DEV2_PATH="workspace/nuri-quant"; {norm}') == "workspace/nuri-quant"
