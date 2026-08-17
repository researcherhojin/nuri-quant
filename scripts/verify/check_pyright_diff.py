#!/usr/bin/env python3
"""이번 push 가 **추가/변경한 줄**에 pyright 오류가 있는지 검사 (#1088).

## 왜 baseline 숫자가 아니라 diff 인가

#1086 은 `pyright_baseline.json` 에 총 오류 수(172)를 적어 두고 그걸 넘으면 막는 래칫이었다.
세 가지가 틀렸다:

1. **손으로 유지하는 숫자는 낡고, 낡으면 게이트가 느슨해진다.** 누가 20건을 고쳐 실제 152 가
   되어도 baseline 은 172 로 남아 그때부터 새 오류 20건이 조용히 통과한다. 무장된 것처럼
   보이는데 안 잡는 형태 — #910/#911 · #953/#954 와 같은 계열이다.
2. **총합은 "내 변경이 늘렸나" 에 답하지 못한다.** 남이 3건 줄이고 내가 3건 늘리면 상쇄된다.
3. 172 소음 바닥 위의 ±1 을 보느라 신호가 약했다.

diff 스코핑은 상태가 없다. 실측(최근 머지 4건 #1079/#1081/#1085/#1087): 파일 단위로 보면
각각 8·0·2·0 건이 걸리지만(전부 **기존** 오류라 오탐), **추가한 줄** 기준으로는 넷 다 0 이다.
새 오류만 잡고 오탐은 없다.

## 아는 한계 — 이걸 덮는다고 착각하지 말 것

줄 스코핑은 **다른 파일로 번지는 파손**을 놓친다. 시그니처를 바꿔 호출부에서 오류가 나면
그 줄은 내 diff 에 없다. merge-base 를 즉석 계산해 두 번 돌리면 잡히지만 ~20s+ 라 훅에
못 넣는다(느린 훅 = 우회당한 훅, #1070). 그 파손은 테스트 스위트에 맡긴다.

## 실행 불가 ≠ 통과

npx/pyright 가 없으면 **차단**한다. "검사를 못 돌렸다" 를 "깨끗하다" 로 보고하는 것이
#910/#911(rc=127) · #953/#954(exit 0) 계열의 핵심 실패다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: diff 기준점 후보. 앞에서부터 해석되는 첫 번째를 쓴다 — clone 상태에 따라 origin/main 이
#: 없을 수 있고, 그때 "기준을 못 잡았으니 통과" 로 빠지면 게이트가 조용히 사라진다.
BASE_CANDIDATES = ("origin/main", "main", "HEAD~1")
#: git 이 최초 커밋을 diff 할 때 쓰는 빈 트리 해시. 마지막 fallback.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout


def resolve_base() -> str:
    """diff 기준 커밋. 어떤 상태에서도 반드시 하나를 돌려준다."""
    for ref in BASE_CANDIDATES:
        merged = _git("merge-base", "HEAD", ref).strip()
        if merged:
            return merged
    return EMPTY_TREE


def changed_lines(base: str) -> dict[str, set[int]]:
    """`base..HEAD` + 작업 트리 + **untracked** 에서 추가/변경된 .py 파일별 줄 번호.

    셋을 다 봐야 하는 이유가 각각 다르다:
    - `base...HEAD` — 실제로 push 되는 것
    - 작업 트리 — 커밋 전에 손으로 돌릴 때 대상이 있어야 한다
    - untracked — `git diff` 는 추적되지 않는 파일을 **한 줄도 보고하지 않는다.**
      새 모듈 전체가 검사 대상에서 조용히 빠지는 구멍이라, 파일 전체를 변경분으로 센다.
    """
    out: dict[str, set[int]] = {}
    for rel in _git("ls-files", "--others", "--exclude-standard").split():
        if rel.endswith(".py"):
            path = REPO_ROOT / rel
            try:
                n = len(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                continue
            out[rel] = set(range(1, n + 1))
    for diff_args in (
        ("diff", "-U0", "--diff-filter=ACM", f"{base}...HEAD"),
        ("diff", "-U0", "--diff-filter=ACM", "HEAD"),
    ):
        cur: str | None = None
        for line in _git(*diff_args).splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:].strip()
                if cur.endswith(".py"):
                    out.setdefault(cur, set())
                else:
                    cur = None
            elif line.startswith("@@") and cur:
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if m:
                    start, count = int(m.group(1)), int(m.group(2) or 1)
                    out[cur].update(range(start, start + count))
    return {f: lines for f, lines in out.items() if lines}


def run_pyright(files: list[str]) -> list[dict]:
    """지정 파일에 대한 severity=error 진단.

    Raises: `RuntimeError` — 실행 자체가 불가능한 경우. 호출자는 이걸 통과로 바꾸면 안 된다.
    """
    try:
        proc = subprocess.run(
            ["npx", "--yes", "-p", "pyright", "pyright", *files, "--outputjson"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"npx 를 찾을 수 없다: {e}") from e
    try:
        # pyright 는 오류가 있으면 exit 1 이므로 returncode 로 판단하지 않는다.
        # 판단 기준은 **JSON 을 받았는가** 뿐이다.
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"pyright 출력을 해석할 수 없다: {e}\n{proc.stderr[:500]}") from e
    return [d for d in data.get("generalDiagnostics", []) if d.get("severity") == "error"]


def diagnostics_on_changed_lines(errors: list[dict], changed: dict[str, set[int]]) -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for e in errors:
        line = e["range"]["start"]["line"] + 1
        for f, lines in changed.items():
            if e["file"].endswith("/" + f) and line in lines:
                hits.append((f, line, e.get("rule", "?"), e["message"].splitlines()[0]))
                break
    return sorted(hits)


def main(argv: list[str] | None = None) -> int:
    base = resolve_base()
    changed = changed_lines(base)
    if not changed:
        print("✓ pyright: 변경된 .py 없음 — 검사 생략")
        return 0

    try:
        errors = run_pyright(sorted(changed))
    except RuntimeError as e:
        print(f"✗ pyright 를 실행하지 못했다 — '깨끗함' 이 아니라 '미확인' 이다:\n  {e}", file=sys.stderr)
        return 1

    hits = diagnostics_on_changed_lines(errors, changed)
    if hits:
        print(f"✗ pyright: 이번 변경이 추가한 줄에 오류 {len(hits)}건", file=sys.stderr)
        for f, line, rule, msg in hits[:20]:
            print(f"    {f}:{line} [{rule}] {msg}", file=sys.stderr)
        print("  기존 오류는 무시한다 — 여기 뜬 것은 이번 변경이 만든 것이다.", file=sys.stderr)
        return 1

    print(f"✓ pyright: 변경 {len(changed)}개 파일의 추가된 줄에 오류 없음 (기존 오류는 대상 아님)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
