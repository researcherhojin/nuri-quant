#!/usr/bin/env python3
"""첫째-party import 가 실제로 존재하는 모듈을 가리키는지 검사 (#902).

이전 구현은 `verify_all.sh` 안의 grep 한 줄이었고, **옛 경로 목록을 하드코딩**하고
제외 목록으로 예외를 뺐다. 그 뒤 새로 생긴 1급 패키지(`nuri/agents/` actor fleet,
`nuri/quant/backtest` 등)가 제외 목록에 없어 정당한 import 353건이 전부 orphan 으로
잡혔다 — `make verify-all` 이 **구조적으로 통과 불가**였고, 그래서 1~4단계(테스트·
백엔드·엔드포인트)의 진짜 신호까지 같이 무시됐다.

접근을 뒤집는다: "옛 경로인가" 가 아니라 **"이 모듈이 존재하는가"** 를 묻는다.
목록이 없으므로 패키지가 추가/이동돼도 드리프트하지 않는다.

해석은 파일시스템으로만 한다 — `importlib.util.find_spec` 은 부모 패키지를 실제로
import 해서 `__init__` 부작용(로깅 설정 등)을 일으킬 수 있다. 검증 스크립트가
프로덕션 모듈을 실행하면 안 된다.

사용:
    python scripts/verify/check_orphan_imports.py          # 개수만 stdout
    python scripts/verify/check_orphan_imports.py -v       # 위반 목록도 stderr
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("nuri", "tests", "scripts")
FIRST_PARTY = "nuri"


def _resolve(dotted: str) -> bool:
    """`nuri.a.b` → `nuri/a/b.py` 또는 `nuri/a/b/__init__.py` 존재 여부."""
    rel = Path(*dotted.split("."))
    return (REPO_ROOT / rel).with_suffix(".py").is_file() or (REPO_ROOT / rel / "__init__.py").is_file()


def _imported_modules(tree: ast.AST) -> set[str]:
    """절대 import 된 모듈명. 상대 import(`from . import x`)는 제외."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module)
    return mods


def find_orphans() -> list[str]:
    """존재하지 않는 첫째-party 모듈을 import 하는 지점 목록."""
    orphans: list[str] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                # 문법 오류는 lint/test 가 잡는다 — 여기서 중복 실패시키지 않는다.
                continue
            for mod in sorted(_imported_modules(tree)):
                if mod != FIRST_PARTY and not mod.startswith(FIRST_PARTY + "."):
                    continue
                if not _resolve(mod):
                    orphans.append(f"{path.relative_to(REPO_ROOT)}: {mod}")
    return orphans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="존재하지 않는 nuri.* import 검사")
    parser.add_argument("-v", "--verbose", action="store_true", help="위반 목록을 stderr 로 출력")
    args = parser.parse_args(argv)

    orphans = find_orphans()
    print(len(orphans))
    if args.verbose:
        for o in orphans:
            print(f"  {o}", file=sys.stderr)
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main())
