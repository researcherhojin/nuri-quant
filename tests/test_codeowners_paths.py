"""`.github/CODEOWNERS` 의 모든 패턴이 트리의 무언가와 매칭된다 (#1559).

죽은 패턴은 오류가 아니라 **침묵**이다 — GitHub 는 매칭 파일이 없는 줄을 그냥 무시하므로
그 파일의 리뷰 배정이 조용히 빠진다. `/scripts/pre_push_check.sh` 가 `scripts/verify/` 로
이사한 뒤에도 옛 경로가 남아 있었고(#1558 Codex 리뷰 발견), 어떤 게이트도 그걸 보지 않았다.

패턴 의미는 CODEOWNERS 규칙을 따른다: 선행 `/` 는 레포 루트 앵커, 후행 `/` 는 디렉터리,
그 외는 파일 또는 디렉터리. 매칭 대상은 `git ls-files` — 워킹트리의 gitignored 파일이
죽은 패턴을 살려 보이게 하면 안 된다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"


def _patterns() -> list[str]:
    out = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.split()[0])
    return out


def _tracked() -> list[str]:
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True).stdout
    return [p for p in raw.decode().split("\0") if p]


def _matches(pattern: str, tracked: list[str]) -> bool:
    if pattern == "*":
        return bool(tracked)
    anchored = pattern.startswith("/")
    rel = pattern.lstrip("/")
    is_dir = rel.endswith("/")
    rel = rel.rstrip("/")
    for path in tracked:
        candidates = [path] if anchored else [path[i:] for i in range(len(path)) if i == 0 or path[i - 1] == "/"]
        for c in candidates:
            if "*" in rel or "?" in rel:
                if _glob(rel).fullmatch(c) or _glob(rel + "/**").fullmatch(c):
                    return True
            elif c.startswith(rel + "/") or (not is_dir and c == rel):
                return True
    return False


def _glob(pattern: str) -> re.Pattern[str]:
    """gitignore 식 glob — `*`/`?` 는 `/` 를 넘지 않고 `**` 만 넘는다. `fnmatch` 는 `*` 가 `/` 를
    넘어 `/scripts/*.sh` 가 하위 디렉터리까지 살려 보인다."""
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


class TestCodeownersPatternsAreLive:
    @pytest.mark.parametrize("pattern", _patterns())
    def test_pattern_matches_a_tracked_path(self, pattern):
        assert _matches(pattern, _tracked()), (
            f"CODEOWNERS 패턴 {pattern!r} 이 추적 파일 어느 것과도 매칭되지 않는다 — "
            "파일이 이사했거나 이름이 바뀌었다. 죽은 패턴은 리뷰 배정을 조용히 빠뜨린다 (#1559)."
        )

    def test_the_file_declares_more_than_the_catch_all(self):
        """가드의 가드 — 파서가 전부 주석으로 읽으면 parametrize 가 비어 공허하게 통과한다."""
        assert len(_patterns()) > 1


class TestMatcherSemantics:
    TRACKED = ["scripts/verify/pre_push_check.sh", "nuri/core/db/connection.py", "README.md"]

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("/scripts/verify/pre_push_check.sh", True),
            ("/scripts/pre_push_check.sh", False),  # 이사 전 옛 경로 — #1559 의 실제 사고
            ("/nuri/core/db/", True),
            ("/nuri/core/", True),
            ("/nuri/core/db", True),
            ("/README.md", True),
            ("README.md", True),
            ("/nuri/core/db/connection", False),  # 접두사 부분 일치는 매칭이 아니다
            ("/scripts/*.sh", False),  # 앵커된 glob 은 하위 디렉터리를 안 본다
            ("/scripts/verify/*.sh", True),
        ],
    )
    def test_codeowners_rules(self, pattern, expected):
        assert _matches(pattern, self.TRACKED) is expected
