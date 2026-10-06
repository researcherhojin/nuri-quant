"""#1642 / #1634 — runpy 로 재실행하는 모듈의 속성을 패치하는 테스트는 아무것도 패치하지 않는다.

`runpy.run_module("pkg.mod")` 는 `pkg/mod.py` 소스를 다시 실행하므로 그 모듈 객체의 속성 패치 —
`monkeypatch.setattr("pkg.mod.f", …)`, `monkeypatch.setattr(pkg.mod, "f", …)`, `patch("pkg.mod.f")`,
`patch.object(pkg.mod, "f")`, f-string 타깃 — 는 재실행된 코드에 닿지 않는다. 그 패턴이 두 번 실제
외부 호출(Codex·Qwen #1634, SEC EDGAR #1642)을 테스트 스위트에 숨겼다.

패키지(`pkg/__main__.py` 실행)는 예외다 — `__main__` 이 패키지에서 이름을 다시 import 하므로 패키지
속성 패치는 산다. 레포의 runpy 래퍼(`_run_module*`)도 run_module 로 본다.

`ALLOWED` 는 양방향이다: 등재된 위반이 사라지면(고쳐지면) 그 항목을 지워야 하고, 새 위반은 등재 이유
없이 통과하지 않는다. 잠금 이전부터 있던 5건은 #1650 에서 고쳐 지금은 비어 있다 — 가드만 실행할 때는
`--help`, 산출물이 있으면 `main(argv)` 의 출력 경로 인자, 그 외엔 다른 모듈의 경계를 패치한다.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
_RUNNER = re.compile(r"run_module\w*$")  # runpy.run_module · _run_module · _run_module_capture · _run_module_with_argv

# (파일, Class::test) -> 등재 이유
ALLOWED: dict[tuple[str, str], str] = {}


def _is_plain_module(dotted: str) -> bool:
    spec = importlib.util.find_spec(dotted)
    return spec is not None and spec.submodule_search_locations is None


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _module_aliases(nodes) -> dict[str, str]:
    """`import a.b as c` → {c: a.b}, `from a import b` → {b: a.b}, `import a.b` → {a.b: a.b}."""
    out: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _string_prefix(node: ast.expr) -> str | None:
    """ "a.b.c" → "a.b.c", f"a.b.{x}" → "a.b." (포맷 자리 앞까지)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        head = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                head += part.value
            else:
                break
        return head
    return None


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _patch_targets(fn: ast.FunctionDef, aliases: dict[str, str]) -> list[str]:
    """테스트 함수 안의 패치 호출이 겨누는 'module.attr' (또는 'module.*') 목록."""
    targets: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = _call_name(node.func)
        is_object_form = (
            name == "object" and isinstance(node.func, ast.Attribute) and _call_name(node.func.value) == "patch"
        )
        if name not in {"setattr", "patch"} and not is_object_form:
            continue
        first = node.args[0]
        text = _string_prefix(first)
        if text is not None:
            if name == "setattr" and len(node.args) >= 2 and not text.count("."):
                continue  # setattr(obj, "attr") 의 첫 인자가 문자열인 경우는 없다 — 방어
            targets.append(text if "." in text else text)
            continue
        dotted = _dotted(first)
        if dotted is None:
            continue
        head, _, rest = dotted.partition(".")
        mod = aliases.get(head)
        if mod is None:
            continue
        full_mod = f"{mod}.{rest}" if rest else mod
        attr = node.args[1].value if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) else "*"
        targets.append(f"{full_mod}.{attr}")
    return targets


def _rerun_modules(fn: ast.FunctionDef) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and _RUNNER.search(_call_name(node.func)) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                mods.add(first.value)
    return mods


def _violations_in_source(src: str) -> list[tuple[str, str, str]]:
    """[(Class::test, 재실행 모듈, 패치 타깃)]."""
    tree = ast.parse(src)
    module_aliases = _module_aliases(tree.body)
    out = []

    def visit(fn: ast.FunctionDef, owner: str | None):
        mods = {m for m in _rerun_modules(fn) if _is_plain_module(m)}
        if not mods:
            return
        aliases = {**module_aliases, **_module_aliases(ast.walk(fn))}
        label = f"{owner}::{fn.name}" if owner else fn.name
        for target in _patch_targets(fn, aliases):
            for mod in sorted(mods):
                if target == mod or target.startswith(mod + "."):
                    out.append((label, mod, target))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            visit(node, None)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name.startswith("test_"):
                    visit(sub, node.name)
    return out


def _sweep() -> dict[tuple[str, str], list[tuple[str, str]]]:
    found: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for f in sorted(TESTS.rglob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        src = f.read_text(encoding="utf-8")
        if "run_module" not in src:
            continue
        rel = str(f.relative_to(TESTS.parent))
        for label, mod, target in _violations_in_source(src):
            found.setdefault((rel, label), []).append((mod, target))
    return found


class TestRunpyTestsDoNotPatchTheModuleTheyRerun:
    def test_no_unregistered_violation(self):
        found = _sweep()
        new = {k: v for k, v in found.items() if k not in ALLOWED}
        assert not new, "runpy 가 버리는 패치 — 재실행 코드가 다른 모듈을 통해 닿는 경계를 stub 할 것:\n" + "\n".join(
            f"  {f}::{t} patches {', '.join(sorted({x[1] for x in v}))} then re-runs {sorted({x[0] for x in v})}"
            for (f, t), v in new.items()
        )

    def test_every_allowed_entry_is_still_a_violation(self):
        """고쳐진 항목은 등재를 지운다 — 낡은 allowlist 는 다음 위반을 가린다."""
        found = _sweep()
        stale = [k for k in ALLOWED if k not in found]
        assert not stale, f"ALLOWED 에 있지만 더는 위반이 아닌 항목: {stale}"

    @pytest.mark.parametrize(
        ("snippet", "expected"),
        [
            (
                'def test_x(monkeypatch):\n    import runpy\n    monkeypatch.setattr("nuri.collectors.filings.parse_10k", lambda t: None)\n    runpy.run_module("nuri.collectors.filings", run_name="__main__")\n',
                [("test_x", "nuri.collectors.filings", "nuri.collectors.filings.parse_10k")],
            ),
            (
                'from nuri.collectors import filings\ndef test_x(monkeypatch):\n    import runpy\n    monkeypatch.setattr(filings, "parse_10k", lambda t: None)\n    runpy.run_module("nuri.collectors.filings", run_name="__main__")\n',
                [("test_x", "nuri.collectors.filings", "nuri.collectors.filings.parse_10k")],
            ),
            (
                'import nuri.collectors.filings as fm\nfrom unittest.mock import patch\ndef test_x():\n    import runpy\n    with patch.object(fm, "collect_filings", return_value=[]):\n        runpy.run_module("nuri.collectors.filings", run_name="__main__")\n',
                [("test_x", "nuri.collectors.filings", "nuri.collectors.filings.collect_filings")],
            ),
            (
                'def test_x(monkeypatch):\n    import runpy\n    for name in ("a",):\n        monkeypatch.setattr(f"nuri.collectors.filings.{name}", None)\n    runpy.run_module("nuri.collectors.filings", run_name="__main__")\n',
                [("test_x", "nuri.collectors.filings", "nuri.collectors.filings.")],
            ),
            (
                'def _run_module_capture(m, mp):\n    pass\ndef test_x(monkeypatch):\n    monkeypatch.setattr("nuri.collectors.filings.parse_10k", None)\n    _run_module_capture("nuri.collectors.filings", monkeypatch)\n',
                [("test_x", "nuri.collectors.filings", "nuri.collectors.filings.parse_10k")],
            ),
            (
                'class TestK:\n    def test_y(self, monkeypatch):\n        import runpy\n        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", lambda: [])\n        runpy.run_module("nuri.trading.agents.consensus", run_name="__main__")\n',
                [],
            ),
            (
                'def test_z(monkeypatch):\n    import runpy, subprocess\n    monkeypatch.setattr(subprocess, "run", None)\n    runpy.run_module("nuri.collectors.filings", run_name="__main__")\n',
                [],
            ),
        ],
        ids=["string", "alias-setattr", "patch-object", "f-string", "wrapper", "package-exempt", "other-module-ok"],
    )
    def test_detector_canaries(self, snippet, expected):
        assert _violations_in_source(snippet) == expected
