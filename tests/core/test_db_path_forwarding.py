"""`db_path` 를 받는 함수가 하위 호출에 그 값을 넘기는지 고정한다 (#1052).

왜 필요한가
-----------
`db_path=` 인자는 **받는 것만으로는 아무것도 보장하지 않는다.** 함수가 인자를
선언해 놓고 내부에서 `analyze_portfolio()` 를 인자 없이 부르면, 호출자는 격리
DB 를 넘겼는데 그 한 줄만 기본 DB 로 샌다. 서명은 맞고 타입 체커도 통과하고
테스트도 초록이다 — 프로덕션 데이터를 읽으면서.

실제로 그렇게 샜다. #1049 가 전역 테스트 격리를 켜자 #1050·#1051 에서 8곳이
드러났고, 그 두 PR 을 머지한 **뒤에** 같은 계열이 8곳 더 남아 있었다
(2026-08-14 Codex 리뷰 + AST 스윕). 사람이 훑어서는 반복해서 놓친다.

무엇을 잠그는가
---------------
`nuri/` 안에서 `db_path` 파라미터를 가진 함수 F 가, 역시 `db_path` 를 받을 수
있는 함수 G 를 호출하면서 **위치로도 키워드로도** 그 값을 넘기지 않으면 FAIL.
호출 형태 세 가지(`g()` · `mod.g()` · `from x import g as h; h()`)를 모두 본다 —
이름 호출만 검사하면 나머지 둘로 새고, 그 둘은 오늘 0건이라 지금 덮어두는 게
가장 싸다. 예외는 아래 `ALLOWED` 에 이유와 함께 등재해야 한다. 목록이 낡지
않도록 **양방향**으로 검사한다 — 해소된 항목이 남아 있어도 FAIL.

한계: 간접 호출(`fn = analyze_portfolio; fn()`)은 정적으로 못 본다. 레포에 현재
그런 형태는 없다.

Gotcha-Test Pair: 배선된 `db_path=db_path` 를 하나 지우면 FAIL.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NURI = REPO_ROOT / "nuri"

# (파일, 호출하는 함수, 호출되는 함수) → 왜 안 넘겨도 되는가.
# 줄 번호로 키를 잡지 않는다 — 무관한 편집에도 깨진다.
ALLOWED: dict[tuple[str, str, str], str] = {
    (
        "nuri/trading/engine/certification.py",
        "_capture_snapshot",
        "_compute_portfolio_hash",
    ): "`rows=portfolio_raw` 를 이미 넘긴다 — rows 가 주어지면 DB 를 안 읽는다(codex R4).",
    (
        "nuri/trading/engine/decisions.py",
        "main",
        "init_db",
    ): "`init_db(db_path) if db_path is not None else init_db()` 삼항 — 이미 명시 분기.",
}


def _accepts_db_path(tree: ast.Module) -> set[str]:
    """이 트리에서 `db_path` 파라미터를 가진 함수 이름."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if any(a.arg == "db_path" for a in params):
                names.add(node.name)
    return names


def _forwards_db_path(call: ast.Call) -> bool:
    """호출이 `db_path` 를 (위치든 키워드든) **명시적으로** 넘기는가.

    `**kwargs` / `*args` 는 통과로 쳐주지 않는다. `def f(db_path=None, **kw):
    g(**kw)` 는 `kw` 가 비면 그대로 새는데, unpack 을 forward 로 인정하면 스윕이
    영영 침묵한다. 레포에 그런 형태가 지금 0건이라 여기서 막는 게 가장 싸다.
    나중에 정당한 unpack 이 생기면 `ALLOWED` 에 이유와 함께 올리면 된다.
    """
    for kw in call.keywords:
        if kw.arg == "db_path":
            return True
        if isinstance(kw.value, ast.Name) and kw.value.id == "db_path":
            return True
    return any(isinstance(arg, ast.Name) and arg.id == "db_path" for arg in call.args)


# 커넥션 객체의 메서드. 이름이 우연히 `db_path` 를 받는 모듈 함수와 겹쳐도
# `conn.execute(...)` 는 이미 경로가 정해진 커넥션 위의 호출이라 판정 대상이 아니다.
_CONNECTION_METHODS = frozenset(
    {"execute", "executemany", "executescript", "cursor", "commit", "close", "fetchall", "fetchone"}
)


def _aliased_imports(tree: ast.Module, accepts: set[str]) -> dict[str, str]:
    """`from x import f as g` — 별칭으로 부르면 def 이름과 안 맞아 스윕을 빠져나간다."""
    return {
        alias.asname: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname and alias.name in accepts
    }


def _callee_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    """호출 대상 이름. 세 형태를 모두 본다 — 하나만 보면 나머지 둘로 샌다.

    `f()` · `mod.f()` (속성 호출) · `g()` (별칭 import). 오늘 레포에는 뒤 둘이
    0건이지만, 이름 호출만 검사하면 다음에 그렇게 쓰는 순간 조용히 통과한다.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute) and func.attr not in _CONNECTION_METHODS:
        return func.attr
    return None


def _scan() -> list[tuple[str, int, str, str]]:
    """(파일, 줄, 호출자, 피호출자) — db_path 를 안 넘긴 지점."""
    trees: dict[Path, ast.Module] = {}
    accepts: set[str] = set()
    for path in sorted(NURI.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        trees[path] = tree
        accepts |= _accepts_db_path(tree)

    findings = []
    for path, tree in trees.items():
        rel = str(path.relative_to(REPO_ROOT))
        aliases = _aliased_imports(tree, accepts)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
            if not any(a.arg == "db_path" for a in params):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                callee = _callee_name(call, aliases)
                if callee is None or callee not in accepts or callee == fn.name:  # 재귀 제외
                    continue
                if _forwards_db_path(call):
                    continue
                findings.append((rel, call.lineno, fn.name, callee))
    return findings


class TestDbPathIsForwarded:
    def test_every_db_path_aware_call_receives_it(self):
        leaks = [f for f in _scan() if (f[0], f[2], f[3]) not in ALLOWED]
        assert not leaks, "db_path 를 받고도 하위 호출에 안 넘기는 지점:\n" + "\n".join(
            f"  {rel}:{line}  {caller}() -> {callee}()" for rel, line, caller, callee in leaks
        )

    def test_allowlist_has_no_stale_entries(self):
        """해소된 항목이 목록에 남아 있으면 FAIL — 목록이 낡지 않게."""
        seen = {(rel, caller, callee) for rel, _, caller, callee in _scan()}
        stale = sorted(set(ALLOWED) - seen)
        assert not stale, "ALLOWED 에 있으나 더는 발생하지 않는 항목 (지울 것):\n" + "\n".join(
            f"  {rel}  {caller}() -> {callee}()" for rel, caller, callee in stale
        )

    def test_the_scan_finds_something_to_look_at(self):
        """스윕이 조용히 0건을 훑고 통과하는 걸 막는다.

        `_accepts_db_path` 나 경로 glob 이 깨지면 findings 가 빈 리스트가 되고 위
        두 테스트가 **아무것도 검사하지 않은 채** 초록이 된다.
        """
        trees = [ast.parse(p.read_text(encoding="utf-8")) for p in NURI.rglob("*.py")]
        accepts = collections.Counter()
        for t in trees:
            accepts.update(_accepts_db_path(t))
        assert len(accepts) > 100, f"db_path 를 받는 함수가 {len(accepts)}개뿐 — 스캐너가 깨졌다"
