"""pyright 0 오류 게이트 (#1831) — CI 의 Backend Lint 가 고정 버전으로 막는다.

pandas-stubs 가 없던 동안 오류는 174 건이었다. 0 으로 내려도 지키는 게이트가 없으면 다시 쌓인다:
pre-push 의 ratchet(`scripts/verify/check_pyright_diff.py`)은 바꾼 줄만, 그것도 로컬에서만 본다.
pyright 자체는 여기서 돌리지 않는다(네트워크 + 초 단위) — 배선만 잠근다.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts.verify import check_pyright_diff as ratchet

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"
# 고정 버전 하나만 — `|| true` 같은 꼬리가 붙으면 맞지 않는다
PIN = re.compile(r"^npx --yes pyright@(\d+\.\d+\.\d+)$")


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _lint_steps() -> list[dict]:
    return _jobs()["backend-lint"]["steps"]


def _pyright_step() -> dict:
    steps = [s for s in _lint_steps() if "pyright" in str(s.get("run", ""))]
    assert len(steps) == 1, steps
    return steps[0]


def test_backend_lint_runs_a_pinned_pyright_that_blocks():
    step = _pyright_step()
    assert PIN.match(step["run"].strip()), step["run"]
    assert not step.get("continue-on-error"), step
    assert step.get("if") == "needs.changes.outputs.run_backend == 'true'", step


def test_pyright_runs_inside_the_backend_venv():
    """venv 가 없으면 pandas-stubs 도 의존성도 못 읽어서 오류가 수백 건이 된다."""
    steps = _lint_steps()
    setup = [i for i, s in enumerate(steps) if s.get("uses") == "./.github/actions/setup-backend-env"]
    assert setup and setup[0] < steps.index(_pyright_step()), steps


def test_the_ci_pin_matches_the_local_ratchet():
    """다르면 로컬은 통과하고 CI 는 막는(또는 그 반대) 차이가 생긴다."""
    match = PIN.match(_pyright_step()["run"].strip())
    assert match and match.group(1) == ratchet.PYRIGHT_VERSION


def test_the_ratchet_invokes_the_pinned_version(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"generalDiagnostics": []}), stderr="")

    monkeypatch.setattr(ratchet.subprocess, "run", fake_run)
    assert ratchet.run_pyright(["nuri/__init__.py"]) == []
    assert calls[0][:5] == ["npx", "--yes", "-p", f"pyright@{ratchet.PYRIGHT_VERSION}", "pyright"], calls


def test_a_pyright_config_change_triggers_the_backend_jobs():
    """설정만 바꾼 PR 이 검사를 건너뛰면, 그 설정이 만든 오류가 다음 .py PR 을 빨갛게 만든다 (#1562 와 같은 형태)."""
    steps = _jobs()["changes"]["steps"]
    filters = next(s["with"]["filters"] for s in steps if str(s.get("uses", "")).startswith("dorny/paths-filter"))
    assert "pyrightconfig.json" in yaml.safe_load(filters)["backend"]
