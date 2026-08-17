#!/usr/bin/env python3
"""pyright 오류 수가 기록된 baseline 을 **넘지 않는지** 검사 (#1086).

## 왜 래칫인가

`make typecheck` 는 이미 존재했지만 어떤 게이트도 부르지 않아, 진단이 **에디터에만**
떴다. 2026-08-18 에 사용자가 Pylance 경고를 직접 붙여넣어 알려줬고, 그중 하나는 그 직전에
머지된 마이그레이션이 만든 새 경고였다.

그렇다고 "0 이 될 때까지 고치기" 를 게이트로 걸 수는 없다. baseline 172건 중 실측 다수가
pandas/numpy 타이핑 소음(`Scalar * float`, `ArrayLike` vs `ndarray`, `Series | bool` 조건절)
이고, 고치려면 `cast()` 를 흩뿌려야 하는데 그건 가독성을 깎으면서 안전성은 안 올린다.
이전 세션에서 None 계열 27건을 재현 시도했을 때 **실제 크래시는 정확히 1건**이었다.

래칫이 답하는 질문은 "지금 몇 개인가" 가 아니라 **"내 변경이 늘렸는가"** 다.

## 줄었을 때 실패시키지 않는 이유

엄격한 래칫(줄어도 FAIL, baseline 갱신 강제)이 회귀 방지력은 더 세지만, 무관한 PR 이
우연히 오류를 줄였다는 이유로 빨개진다. 그러면 사람은 게이트를 끄거나 우회한다 — 그게
이 레포가 #1070 에서 배운 것이다(느린 훅 = 우회당한 훅). 그래서 줄면 통과시키되 **갱신
명령을 크게 찍는다.**

## 실행 불가 ≠ 통과

npx 나 pyright 가 없으면 **차단**한다. "검사를 못 돌렸다" 를 "깨끗하다" 로 보고하는 것이
#910/#911(rc=127) · #953/#954(exit 0) 계열의 핵심 실패다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "scripts" / "verify" / "pyright_baseline.json"
TARGETS = ("nuri/", "tests/", "scripts/")


def _load_baseline() -> int:
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return int(data["errors"])


def run_pyright() -> list[dict]:
    """pyright 를 돌려 severity=error 진단만 돌려준다.

    Raises: `RuntimeError` — 실행 자체가 불가능한 경우. 호출자는 이걸 통과로 바꾸면 안 된다.
    """
    try:
        proc = subprocess.run(
            ["npx", "--yes", "-p", "pyright", "pyright", *TARGETS, "--outputjson"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"npx 를 찾을 수 없다: {e}") from e
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        # pyright 는 오류가 있으면 exit 1 이므로 returncode 로는 판단하지 않는다.
        # 판단 기준은 **JSON 을 받았는가** 뿐이다.
        raise RuntimeError(f"pyright 출력을 해석할 수 없다: {e}\n{proc.stderr[:500]}") from e
    return [d for d in data.get("generalDiagnostics", []) if d.get("severity") == "error"]


def main(argv: list[str] | None = None) -> int:
    baseline = _load_baseline()
    try:
        errors = run_pyright()
    except RuntimeError as e:
        print(f"✗ pyright 를 실행하지 못했다 — '깨끗함' 이 아니라 '미확인' 이다:\n  {e}", file=sys.stderr)
        return 1

    count = len(errors)
    files = len({d["file"] for d in errors})

    if count > baseline:
        print(
            f"✗ pyright {count} errors (baseline {baseline}) — 이 변경이 {count - baseline}건 늘렸다", file=sys.stderr
        )
        # 어느 파일이 늘었는지는 diff 가 아니라 사람이 판단한다. 상위 파일만 보여준다.
        by_file: dict[str, int] = {}
        for d in errors:
            by_file[d["file"]] = by_file.get(d["file"], 0) + 1
        for f, n in sorted(by_file.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {n:3d}  {Path(f).relative_to(REPO_ROOT)}", file=sys.stderr)
        print("  전체 목록: make typecheck", file=sys.stderr)
        return 1

    if count < baseline:
        print(f"✓ pyright {count} errors across {files} files (baseline {baseline} — {baseline - count}건 감소)")
        print(
            f"  baseline 을 낮춰 두면 되돌림이 막힌다: {BASELINE_PATH.relative_to(REPO_ROOT)} 의 errors 를 {count} 로"
        )
        return 0

    print(f"✓ pyright {count} errors across {files} files (baseline {baseline})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
