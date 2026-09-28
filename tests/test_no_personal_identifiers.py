"""추적 파일에 개인 식별자(macOS 계정명 · 실명 기기명)가 없다 (#1557).

privacy 스캐너(`scripts/verify/check_privacy_leak.py`)는 이제 `personal_identifier` 범주로 이 식별자의
**모양**을 잡지만 값은 모른다 — 정확한 이름은 여기서만 잠근다. 처음(#1557 이전)엔 §4.4.1 금융 데이터만 봤다. 그 범위 밖의 식별자 — 배포 스크립트의 계정명 fallback, 테스트 fixture 의
실명 기기명, 문서에 붙여넣은 `ls -l` 소유자 — 가 2026-09-28 감사에서 추적 파일 10곳에
남아 있었다. 치환한 뒤 이 테스트가 재유입을 막는다.

패턴은 **런타임 조립**이다 — 리터럴로 적으면 이 파일이 자기 자신을 잡고, PreToolUse 훅이
파일 저장을 막는 privacy 픽스처와 같은 이유다 (`tests/CLAUDE.md` "Privacy 가드").
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 소문자 부분 일치. 기기명 접두사는 계정명을 품지만 실패 메시지가 무엇을 잡았는지 말하도록 따로 둔다.
IDENTIFIERS = {
    "macos-account": "ehb" + "ebe",
    "hostname-prefix": "Ehbeb" + "eui",
}


def _tracked_text_files() -> list[tuple[str, str]]:
    """git 이 추적하는 파일 중 UTF-8 로 읽히는 것. 바이너리는 건너뛴다."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True).stdout
    files = []
    for rel in out.decode().split("\0"):
        path = REPO_ROOT / rel
        if not rel or not path.is_file():
            continue
        try:
            files.append((rel, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return files


class TestNoPersonalIdentifiers:
    @pytest.mark.parametrize("kind", sorted(IDENTIFIERS))
    def test_tracked_files_carry_no_identifier(self, kind):
        needle = IDENTIFIERS[kind].lower()
        hits = [rel for rel, text in _tracked_text_files() if needle in text.lower()]
        assert hits == [], (
            f"개인 식별자({kind})가 추적 파일에 있다: {hits} — 플레이스홀더(`user@macmini.local`, "
            "`Test-Macmini` 등)로 바꿀 것. 코드는 소문자 `macmini`/`macbook`/`mbp` 부분 일치만 쓴다 (#1557)."
        )

    def test_the_scan_actually_sees_tracked_files(self):
        """가드의 가드 — `git ls-files` 가 비거나 디코딩이 전부 실패하면 위 테스트는 공허하게 통과한다."""
        rels = {rel for rel, _ in _tracked_text_files()}
        assert {"Makefile", ".cspell.json", "scripts/deploy/deploy_remote.sh"} <= rels
