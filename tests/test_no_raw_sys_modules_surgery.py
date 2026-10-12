"""테스트가 `nuri.*` 모듈을 `sys.modules` 에서 빼거나 바꿀 때는 monkeypatch 로만 한다 (#1842).

`sys.modules.pop("nuri.x", None)` 처럼 되돌리지 않으면, 그 모듈이 이미 import 돼 있던 xdist worker 에서
`sys.modules` 와 패키지 속성이 서로 다른 상태로 남는다. 다음 import 가 두 번째 사본을 만들고, 한 사본에
건 patch 가 다른 사본을 쥔 코드에 닿지 않는다 — #1826 과 같은 계열이고, 증상은 shard 구성만 바뀐 무관한
PR 에서 나온다. `monkeypatch.delitem` / `setitem` 은 teardown 에 원본을 되돌린다.

소스를 AST 로 본다 (독스트링·주석의 언급은 세지 않는다). 원본을 다른 방법으로 되돌리는 곳만 사유와 함께
`ALLOWED` 에 두고, 없어진 항목도 실패시킨다.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

ALLOWED = {
    ("trading/recommend/test_recommend_branch_coverage.py", "nuri.alerts.discord_bot"): (
        '`patch.dict("sys.modules", ...)` 블록 안이다 — 블록이 끝나면 dict 전체가 복원된다'
    ),
}


def _is_sys_modules(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _nuri_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value == "nuri" or node.value.startswith("nuri."):
            return node.value
    return None


def _raw_surgery() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(TESTS.rglob("*.py")):
        rel = str(path.relative_to(TESTS))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # sys.modules.pop("nuri…", …)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "pop"
                and _is_sys_modules(node.func.value)
                and node.args
                and (key := _nuri_key(node.args[0]))
            ):
                found.add((rel, key))
            # del sys.modules["nuri…"] · sys.modules["nuri…"] = …
            targets = node.targets if isinstance(node, (ast.Delete, ast.Assign)) else []
            for target in targets:
                if isinstance(target, ast.Subscript) and _is_sys_modules(target.value):
                    if key := _nuri_key(target.slice):
                        found.add((rel, key))
    return found


def test_tests_take_nuri_modules_out_of_sys_modules_only_through_monkeypatch():
    stray = _raw_surgery() - ALLOWED.keys()
    assert not stray, (
        f"monkeypatch.delitem/setitem(sys.modules, …) 를 쓸 것 — teardown 이 원본을 되돌린다: {sorted(stray)}"
    )


def test_the_allowlist_has_no_stale_entries():
    stale = ALLOWED.keys() - _raw_surgery()
    assert not stale, f"더 이상 없는 항목은 ALLOWED 에서 지울 것: {sorted(stale)}"
