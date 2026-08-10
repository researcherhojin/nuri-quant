"""`verify_all.sh` 가 실제 실패를 종료코드로 전파하는지 잠근다.

2026-08-10: 1단계가 `pytest ... | tail -1` 이고 바로 다음 줄의 `check()` 가 ambient
`$?` 를 읽었다. 그 `$?` 는 pytest 가 아니라 **`tail` 의 것**이라 항상 0 이었다. 3단계
(`npm run build | grep -c | xargs`)도 같은 구조로 `xargs` 의 종료코드를 봤다. 그 결과
`test_90d_tracking` 이 5일간 깨진 채로 `make verify-all` 이 "ALL 5/5 PASSED" 를 찍었다.

Gotcha-Test Pair (STRATEGY §5.3.1): 아래 두 테스트는 파이프-기반 구조로 되돌리면
FAIL 한다. 검증 방식이 중요하다 —
  * 파이썬 mock 은 쓸모없다. 버그가 bash 에 있다.
  * 실제 pytest/npm 을 돌리면 느리고 불안정하다.
  * 그래서 PATH 앞에 **실행 가능한 shim** 을 놓아 결정론적으로 실패시킨다.
  * 전체 종료코드만 보면 안 된다 — 다른 단계가 실패해도 통과해버려 정확히 이 버그를
    놓친다. 그래서 해당 단계의 `✗ <label>` 문자열까지 함께 assert 한다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify" / "verify_all.sh"

# 4·5 단계까지 가지 않고 1·3 단계 판정만 보면 되므로, shim 은 나머지를 값싸게 통과시킨다.
_PY_SHIM = """#!/usr/bin/env bash
# pytest 만 실패시키고 나머지 python 호출은 통과시킨다.
for a in "$@"; do
    if [ "$a" = "pytest" ]; then
        echo "1 failed, 2 passed"
        exit 1
    fi
done
# check_orphan_imports.py -v 는 정수 하나를 뱉어야 한다 ('$old' -eq 0 비교).
case "$*" in
    *check_orphan_imports.py*) echo 0; exit 0 ;;
esac
exit 0
"""

_NPM_OK = """#!/usr/bin/env bash
echo "ƒ /  ○ /about"
exit 0
"""

_NPM_FAIL = """#!/usr/bin/env bash
echo "Failed to compile."
exit 1
"""


def _shim(dirpath: Path, name: str, body: str) -> None:
    p = dirpath / name
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)


def _run(tmp_path: Path, npm_body: str) -> subprocess.CompletedProcess:
    binp = tmp_path / "bin"
    binp.mkdir()
    _shim(binp, "npm", npm_body)
    py = binp / "pyshim"
    py.write_text(_PY_SHIM, encoding="utf-8")
    py.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{binp}:{os.environ['PATH']}",
        # _common.sh 가 PYTHON 을 이미 설정했다면 존중하도록 되어 있어야 한다.
        "PYTHON": str(py),
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.slow
class TestVerifyAllExitPropagation:
    def test_pytest_failure_marks_unit_tests_failed(self, tmp_path):
        """pytest 가 실패하면 1단계가 ✗ 로 찍히고 스크립트가 non-zero 로 끝난다."""
        r = _run(tmp_path, _NPM_OK)
        out = r.stdout + r.stderr
        assert "✗ Unit Tests" in out, f"pytest 실패가 1단계에 반영되지 않음:\n{out}"
        assert "✓ Unit Tests" not in out, f"실패했는데 초록으로도 찍힘:\n{out}"
        assert r.returncode != 0, f"단계가 실패했는데 exit 0:\n{out}"

    def test_npm_build_failure_marks_frontend_failed(self, tmp_path):
        """npm run build 가 실패하면 3단계가 ✗ 로 찍힌다."""
        r = _run(tmp_path, _NPM_FAIL)
        out = r.stdout + r.stderr
        assert "✗ Frontend" in out, f"빌드 실패가 3단계에 반영되지 않음:\n{out}"
        assert "✓ Frontend" not in out, f"실패했는데 초록으로도 찍힘:\n{out}"
        assert r.returncode != 0, f"단계가 실패했는데 exit 0:\n{out}"

    def test_summary_never_claims_all_passed_when_a_step_failed(self, tmp_path):
        """'ALL n/n PASSED' 배너가 실패와 공존하면 안 된다 — 실제로 목격된 증상."""
        r = _run(tmp_path, _NPM_FAIL)
        out = r.stdout + r.stderr
        assert "ALL" not in out or "PASSED" not in out, f"실패 상태에서 ALL PASSED 배너:\n{out}"
        assert "FAILED" in out, f"실패 요약이 없음:\n{out}"
