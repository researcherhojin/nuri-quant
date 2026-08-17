"""`make verify-*` 티어의 소요 시간 클레임이 **모든 표기 지점에서 같은 수를 말하는지** 잠근다.

이 수치들은 어떤 게이트도 검사하지 않아서 조용히 낡는다 — `.claude/rules/architecture.md`
가 그 사실을 본문에 적어두기까지 했다. 실제로 #1054 가 아홉 개 클레임을 재측정해 일곱 개
`.md` 파일을 고쳤는데 **`Makefile` 은 sweep 에 없었다.** 그래서 문서는 `84.9s`/`320.8s`
를 말하는 동안 `make verify-help` 와 `make help` 는 `~10s`/`~30s` 를 계속 출력했다 —
실측의 1/9·1/11 이고, 하필 개발자가 실제로 읽는 쪽이 틀린 값이었다.

한 파일만 고치고 나머지를 잊는 것이 이 결함의 유일한 발생 형태다. 그래서 여기서 잠그는
것은 "값이 정확한가"(기계가 알 수 없다)가 아니라 **"모든 지점이 서로 같은가"** 다.
재측정하면 전 지점을 같이 옮겨야 하고, 한 곳만 옮기면 FAIL 한다.

정본은 `.claude/rules/architecture.md` — 항상 로드되는 rules 파일이라 여기가 어긋나면
에이전트가 먼저 틀린다.

`verify-fast` / `verify` 는 `.md` 정본이 없고 `Makefile` 안에만 두 번(도움말 표 + `##`
주석) 나오므로, 그 둘이 서로 일치하는지만 본다 — 반쪽 수정을 잡는 데는 그걸로 충분하다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MAKEFILE = REPO_ROOT / "Makefile"
CANONICAL = REPO_ROOT / ".claude" / "rules" / "architecture.md"

# `84.9s` 는 잡고 `%-9s` / `%-14s` (printf 형식 지정자) 와 `~10s` (역사적 서술로 남긴
# 옛 값)는 잡지 않는다. 앞 문자가 `%` `-` `~` `.` 또는 단어 문자면 배제.
_SECONDS = r"(?<![%\w.~-])(\d+(?:\.\d+)?)s\b"


def _find(path: Path, pattern: str) -> list[str]:
    return re.findall(pattern, path.read_text())


# 정본 두 값을 architecture.md 한 줄에서 뽑는다.
_CANONICAL_LINE = re.compile(r"`make verify-quick`[^/]*?" + _SECONDS + r"[^/]*?/[^`]*?`make verify-all`.*?" + _SECONDS)

# 등재된 표기 지점. (파일, 그 파일에서 해당 티어의 초 값을 뽑는 정규식).
# 새 지점을 추가하면 아래 `test_no_unregistered_site` 가 등재를 요구한다.
SITES: dict[str, list[tuple[Path, str]]] = {
    "verify-quick": [
        (REPO_ROOT / "AGENTS.md", r"make verify-quick\s+#[^\n]*?" + _SECONDS),
        (REPO_ROOT / "CONTRIBUTING.md", r"make verify-quick\s+#[^\n]*?" + _SECONDS),
        (REPO_ROOT / ".claude/skills/nuri-verify/SKILL.md", r"## Quick check \(" + _SECONDS),
        (MAKEFILE, r"'verify-quick'\s+'" + _SECONDS + r"'"),
        (MAKEFILE, r"^verify-quick:[^\n]*?\(" + _SECONDS + r"\)"),
    ],
    "verify-all": [
        (REPO_ROOT / "AGENTS.md", r"make verify-all\s+#[^\n]*?" + _SECONDS),
        (MAKEFILE, r"'verify-all'\s+'" + _SECONDS + r"'"),
        (MAKEFILE, r"^verify-all:[^\n]*?\(" + _SECONDS + r"[,)]"),
    ],
}

# `.md` 정본이 없어 Makefile 안에서만 교차 검증하는 티어.
MAKEFILE_ONLY = {
    "verify-fast": (r"'verify-fast'\s+'" + _SECONDS + r"'", r"^verify-fast:[^\n]*?\(" + _SECONDS + r"\)"),
    "verify": (r"'verify'\s+'" + _SECONDS + r"'", r"^verify:[^\n]*?\(" + _SECONDS + r"\)"),
}


def _canonical() -> dict[str, str]:
    m = _CANONICAL_LINE.search(CANONICAL.read_text())
    assert m, (
        f"{CANONICAL.relative_to(REPO_ROOT)} 에서 verify-quick/verify-all 정본 수치를 못 찾았다 — "
        "형식이 바뀌었으면 이 테스트의 _CANONICAL_LINE 도 같이 고칠 것"
    )
    return {"verify-quick": m.group(1), "verify-all": m.group(2)}


class TestEverySiteQuotesTheSameNumber:
    def test_canonical_is_parseable(self):
        """카나리아 — 정본 파싱이 깨지면 아래 비교가 통째로 공허해진다."""
        canonical = _canonical()
        assert canonical["verify-quick"] and canonical["verify-all"]
        assert canonical["verify-quick"] != canonical["verify-all"], (
            "두 티어가 같은 수일 리 없다 — 정규식이 한 값을 두 번 잡았다"
        )

    def test_every_registered_site_matches_canonical(self):
        """Gotcha-Test Pair: 한 지점만 고치면 FAIL.

        #1054 가 `.md` 일곱 개를 고치고 `Makefile` 을 빼먹은 것이 정확히 이 형태다.
        """
        canonical = _canonical()
        mismatches = []
        for tier, sites in SITES.items():
            for path, pattern in sites:
                found = re.findall(pattern, path.read_text(), re.MULTILINE)
                rel = path.relative_to(REPO_ROOT)
                if not found:
                    mismatches.append(f"{rel}: `{tier}` 표기를 못 찾음 (지점이 사라졌거나 형식이 바뀜)")
                elif any(v != canonical[tier] for v in found):
                    mismatches.append(f"{rel}: `{tier}` = {found} 인데 정본은 {canonical[tier]}")
        assert not mismatches, (
            "verify 티어 수치가 지점마다 다르다:\n  " + "\n  ".join(mismatches) + "\n"
            f"정본: {CANONICAL.relative_to(REPO_ROOT)}. 재측정했다면 전 지점을 같이 옮길 것."
        )

    def test_makefile_only_tiers_are_internally_consistent(self):
        """`verify-fast` / `verify` 는 Makefile 안 두 곳이 서로 맞아야 한다."""
        text = MAKEFILE.read_text()
        for tier, (table_re, comment_re) in MAKEFILE_ONLY.items():
            table = re.findall(table_re, text, re.MULTILINE)
            comment = re.findall(comment_re, text, re.MULTILINE)
            assert table, f"Makefile 도움말 표에서 `{tier}` 수치를 못 찾음"
            assert comment, f"Makefile `##` 주석에서 `{tier}` 수치를 못 찾음"
            assert table[0] == comment[0], f"`{tier}`: 도움말 표는 {table[0]}, `##` 주석은 {comment[0]} — 반쪽만 고쳤다"

    def test_no_unregistered_site(self):
        """카나리아 — 새 표기 지점이 생기면 SITES 에 등재될 때까지 FAIL.

        등재를 강제하지 않으면 다음 재측정이 또 한 곳을 빠뜨리고, 이 테스트는
        모르는 채 초록으로 통과한다.
        """
        canonical = _canonical()
        # `s` 를 붙여서 찾는다 — 맨숫자로 찾으면 무관한 파일의 우연한 `84.9`
        # (thesis 프롬프트의 예시 수치 등)까지 걸려 오탐만 만든다.
        needle = canonical["verify-quick"] + "s"
        tracked = subprocess.run(
            ["git", "grep", "-lF", "--", needle],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        # 제외 둘: 정본 파일(값의 출처라 당연히 등장)과 이 테스트 파일 자신
        # (docstring 이 결함 서술로 값을 인용한다). 둘 다 "표기 지점"이 아니다.
        #
        # ⚠️ `git grep` 은 **추적되는 파일만** 본다. 그래서 이 테스트를 커밋 전에
        # 돌리면 자기 자신이 안 잡혀 초록이고, 커밋 직후 빨개진다 — 실제로 그렇게
        # 밟았다. 새 파일을 등재 목록에 넣을 땐 `git add` 후에 확인할 것.
        excluded = {
            str(CANONICAL.relative_to(REPO_ROOT)),
            str(Path(__file__).resolve().relative_to(REPO_ROOT)),
        }
        tracked = [f for f in tracked if f not in excluded]
        registered = {str(p.relative_to(REPO_ROOT)) for p, _ in SITES["verify-quick"]}
        unregistered = set(tracked) - registered
        assert not unregistered, (
            f"`{needle}` 를 말하는데 SITES 에 없는 파일: {sorted(unregistered)}\n"
            "새 표기 지점은 등재할 것 — 안 그러면 다음 재측정이 여길 빠뜨려도 아무도 모른다."
        )
        assert registered <= set(tracked), (
            f"SITES 에 등재됐는데 실제로는 그 값을 안 쓰는 파일: {sorted(registered - set(tracked))}"
        )
