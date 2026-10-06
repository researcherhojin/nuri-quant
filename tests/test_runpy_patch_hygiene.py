"""#1642 / #1634 — runpy 로 재실행하는 모듈의 속성을 패치하는 테스트는 아무것도 패치하지 않는다.

`runpy.run_module("pkg.mod")` 는 `pkg/mod.py` 소스를 다시 실행하므로 `monkeypatch.setattr("pkg.mod.f", …)`
/ `patch("pkg.mod.f")` 는 재실행된 코드에 닿지 않는다. 그 패턴이 두 번 실제 외부 호출(Codex·Qwen, SEC
EDGAR)을 테스트 스위트에 숨겼다. 패키지(`pkg/__main__.py` 실행)는 예외다 — `__main__` 이 패키지에서
이름을 다시 import 하므로 패키지 속성 패치는 산다.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
_RUN = re.compile(r'run_module\(\s*["\']([\w.]+)["\']')


def _is_plain_module(dotted: str) -> bool:
    spec = importlib.util.find_spec(dotted)
    return spec is not None and spec.submodule_search_locations is None


def _violations_in_source(src: str) -> list[tuple[str, str, str]]:
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        seg = ast.get_source_segment(src, node) or ""
        for mod in set(_RUN.findall(seg)):
            if not _is_plain_module(mod):
                continue
            pat = re.compile(r'(?:setattr|patch)\(\s*["\'](' + re.escape(mod) + r'\.\w+)["\']')
            for target in sorted(set(pat.findall(seg))):
                out.append((node.name, mod, target))
    return out


def _sweep() -> list[tuple[str, str, str, str]]:
    found = []
    for f in sorted(TESTS.rglob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        src = f.read_text(encoding="utf-8")
        if "run_module" not in src:
            continue
        for name, mod, target in _violations_in_source(src):
            found.append((str(f.relative_to(TESTS.parent)), name, mod, target))
    return found


class TestRunpyTestsDoNotPatchTheModuleTheyRerun:
    def test_no_runpy_test_patches_its_own_module(self):
        bad = _sweep()
        assert not bad, "runpy 가 버리는 패치 — 재실행 코드가 다른 모듈을 통해 닿는 경계를 stub 할 것:\n" + "\n".join(
            f"  {f}::{t} patches {target} then run_module({mod!r})" for f, t, mod, target in bad
        )

    def test_canary_detects_the_pattern(self):
        """탐지기가 아무것도 못 잡는 채로 초록이 되는 것을 막는다."""
        snippet = (
            "def test_x(monkeypatch):\n"
            "    import runpy\n"
            '    monkeypatch.setattr("nuri.collectors.filings.parse_10k", lambda t: None)\n'
            '    runpy.run_module("nuri.collectors.filings", run_name="__main__")\n'
        )
        assert _violations_in_source(snippet) == [
            ("test_x", "nuri.collectors.filings", "nuri.collectors.filings.parse_10k")
        ]

    def test_package_main_is_exempt(self):
        """패키지의 __main__ 재실행은 패키지 속성 패치를 본다 — 위반으로 세지 않는다."""
        snippet = (
            "def test_y(monkeypatch):\n"
            "    import runpy\n"
            '    monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", lambda: [])\n'
            '    runpy.run_module("nuri.trading.agents.consensus", run_name="__main__")\n'
        )
        assert _violations_in_source(snippet) == []

    @pytest.mark.parametrize("mod", ["nuri.collectors.filings", "nuri.llm.thesis_query"])
    def test_plain_module_detection(self, mod):
        assert _is_plain_module(mod)
