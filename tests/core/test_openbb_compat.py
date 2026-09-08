"""`get_obb()` — 실패한 openbb import 를 프로세스당 한 번만 지불한다 (#1477).

CI 의 덩어리 테스트(#1475) 두 개가 워커마다 첫 `from openbb import obb` 실패(13~17s)를 `call` 로
떠안고 있었다. 실패는 sys.modules 에 남지 않아 호출 지점마다 재시도됐다.
"""

from __future__ import annotations

import ast
import builtins
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nuri.core import openbb_compat

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_memo(monkeypatch):
    monkeypatch.setattr(openbb_compat, "_FAILED", False)
    monkeypatch.delitem(sys.modules, "openbb", raising=False)


def _break_openbb(monkeypatch, counter: list[int], delay: float = 0.0):
    """실제 openbb 처럼 — import 가 예외를 내고 sys.modules 에 아무것도 남기지 않는다. `delay` 는 실제 1.6s 의 축소판."""
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "openbb":
            counter.append(1)
            time.sleep(delay)
            raise AttributeError("'_IncludedRouter' object has no attribute 'path'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)


class TestFailureIsPaidOnce:
    def test_second_call_does_not_import_again(self, monkeypatch, caplog):
        attempts: list[int] = []
        _break_openbb(monkeypatch, attempts)
        with caplog.at_level("WARNING", logger="nuri.core.openbb_compat"):
            assert openbb_compat.get_obb() is None
            assert openbb_compat.get_obb() is None
            assert openbb_compat.get_obb() is None
        assert len(attempts) == 1, "실패를 기억하지 않는다 — 호출마다 1.6~17s 를 다시 지불한다"
        warns = [r for r in caplog.records if "openbb" in r.getMessage()]
        assert len(warns) == 1, "WARNING 은 프로세스당 한 번"

    def test_ten_threads_arriving_together_pay_once(self, monkeypatch):
        """stock.py 의 10-worker 풀 — 첫 배치가 동시에 `_FAILED` 체크를 지나면 10번 지불한다."""
        attempts: list[int] = []
        _break_openbb(monkeypatch, attempts, delay=0.05)
        gate = threading.Barrier(10)

        def worker():
            gate.wait()
            openbb_compat.get_obb()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert len(attempts) == 1, f"동시 진입 {len(attempts)}회 시도 — 락 없이는 워커 수만큼 지불한다"

    def test_a_stub_in_sys_modules_is_honoured_even_after_a_failure(self, monkeypatch):
        """테스트들이 쓰는 `monkeypatch.setitem(sys.modules, "openbb", stub)` 경로 — 실패 기억이 스텁을 가리면 안 된다."""
        attempts: list[int] = []
        _break_openbb(monkeypatch, attempts)
        assert openbb_compat.get_obb() is None
        monkeypatch.undo()  # 진짜 import 로 돌아온다
        monkeypatch.setattr(openbb_compat, "_FAILED", True)
        stub_obb = MagicMock(name="obb")
        monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace(obb=stub_obb))
        assert openbb_compat.get_obb() is stub_obb

    def test_a_partial_module_without_obb_does_not_reopen_retries(self, monkeypatch, caplog):
        """`sys.modules["openbb"]` 가 있어도 `obb` 가 없으면 스텁이 아니다 — 실패 기억을 풀면 안 된다 (Codex P3)."""
        attempts: list[int] = []
        _break_openbb(monkeypatch, attempts)
        monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace())
        with caplog.at_level("WARNING", logger="nuri.core.openbb_compat"):
            assert openbb_compat.get_obb() is None
            assert openbb_compat.get_obb() is None
        assert len(attempts) == 1
        assert openbb_compat._FAILED is True
        assert len([r for r in caplog.records if "openbb" in r.getMessage()]) == 1

    def test_success_is_returned_as_is(self, monkeypatch):
        stub_obb = MagicMock(name="obb")
        monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace(obb=stub_obb))
        assert openbb_compat.get_obb() is stub_obb
        assert openbb_compat._FAILED is False


class TestSoleImporter:
    def test_only_openbb_compat_imports_openbb(self):
        """호출 지점이 다시 `from openbb import obb` 를 직접 쓰면 그 지점은 실패 비용을 매번 낸다."""
        offenders = []
        for py in (REPO_ROOT / "nuri").rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any(n == "openbb" or n.startswith("openbb.") for n in names):
                    offenders.append(str(py.relative_to(REPO_ROOT)))
                # `importlib.import_module("openbb")` / `__import__("openbb")` 는 정적 import 검사를 비켜간다
                if _is_dynamic_openbb_import(node):
                    offenders.append(f"{py.relative_to(REPO_ROOT)} (dynamic)")
        assert offenders == ["nuri/core/openbb_compat.py"], f"openbb 를 직접 import 하는 곳: {offenders}"

    @pytest.mark.parametrize(
        ("rel", "func"),
        [
            ("nuri/collectors/etf_flows.py", "_fetch_etf"),
            ("nuri/collectors/stock.py", "_collect_ticker"),
            ("nuri/collectors/news.py", "_fetch_ticker_news"),
            ("nuri/analysis/portfolio.py", "get_exchange_rate"),
        ],
    )
    def test_the_four_call_sites_call_get_obb(self, rel, func):
        """캐너리 — 위 테스트가 '아무도 openbb 를 안 쓴다' 로도 통과하는 상태를 배제. 문자열이 아니라 실제 호출을 본다."""
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func)
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "get_obb"
        ]
        assert calls, f"{rel}::{func} 가 get_obb() 를 호출하지 않는다"


def _is_dynamic_openbb_import(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not node.args:
        return False
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    target = first.value == "openbb" or first.value.startswith("openbb.")
    f = node.func
    is_import_module = isinstance(f, ast.Attribute) and f.attr == "import_module"
    is_dunder = isinstance(f, ast.Name) and f.id == "__import__"
    return target and (is_import_module or is_dunder)
