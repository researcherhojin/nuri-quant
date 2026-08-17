"""git `pre-push` 훅을 **실행해서** 검증 (Gotcha-Test Pair, #1070).

`scripts/verify/pre_push_check.sh` 는 존재했고 정상 동작했고 수동 실행하면 전 항목을
통과했다. 그런데 `scripts/hooks/` 에 `pre-push` 소스가 없어서, `make setup-hooks` 가
정상 동작하면서도 **아무것도 설치하지 않았다.** STRATEGY §4.4.1 이 선언한 3층 방어 중
2층(로컬 pre-push)이 통째로 비어 있었고, `.claude/rules/enforcement.md` 는 그 내내
게이트가 도는 것처럼 적혀 있었다.

이건 dead gate 가 아니라 **absent gate** 라 더 조용하다 — #910/#911(rc=127) 과
#953/#954(exit 0) 는 최소한 exit code 라도 남겼지만, 실행 자체가 없으면 로그도
exit code 도 없다. 그래서 여기서도 훅을 grep 하지 않고 **셸로 실행해 exit code 만**
믿는다.

세 축:
- 소스 파일 존재 → 설치기가 심을 것이 있다 (#1070 의 결함 그 자체)
- 게이트 exit code 전달 (0 → 0, 1 → 1) → 삼키지도, 상시 red 도 아니다
- 인터프리터 부재 시 **정직한 실패** → "미실행" 을 "깨끗함" 으로도, 다른 발견으로도
  보고하지 않는다
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pre-push"
GATE_REL = "scripts/verify/pre_push_check.sh"

#: git 이 pre-push 훅 stdin 으로 넘기는 한 줄 (`<local ref> <local sha> <remote ref> <remote sha>`).
_PUSH_LINE = "refs/heads/main 0123456789abcdef0123456789abcdef01234567 refs/heads/main " + "0" * 40


def test_hook_source_exists_so_the_installer_can_install_it():
    """`scripts/dev/install_hooks.sh` 는 `scripts/hooks/*` 를 심는다 — 소스가 없으면 영원히 미설치.

    이 한 줄이 #1070 의 결함 그 자체다. 설치기도 게이트 스크립트도 멀쩡했고, 없는 것은
    둘을 잇는 파일 하나였다.
    """
    assert HOOK.is_file(), f"{HOOK} 부재 — make setup-hooks 가 pre-push 를 설치할 수 없다"


@pytest.mark.parametrize("gate_rc", [0, 1])
def test_hook_propagates_the_gate_exit_code(tmp_path, gate_rc):
    """게이트가 낸 판정을 그대로 push 차단 여부로 옮긴다.

    두 방향을 다 잠근다 — 1 을 삼키면 게이트가 무력해지고, 0 을 1 로 만들면 상시 red 가
    되어 `--no-verify` 가 습관이 된다. 둘 다 결과적으로 absent gate 다.

    실제 레포 상태(작업 트리 dirty · lint · 문서 카운트)에 의존하지 않도록 게이트를
    스텁으로 갈아끼운 임시 레포에서 실행한다.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "scripts" / "verify").mkdir(parents=True)
    argv_log = tmp_path / "argv.txt"
    (tmp_path / GATE_REL).write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > {argv_log}\nexit {gate_rc}\n',
        encoding="utf-8",
    )
    hook_copy = tmp_path / "scripts" / "hooks" / "pre-push"
    hook_copy.parent.mkdir(parents=True)
    shutil.copy2(HOOK, hook_copy)

    proc = subprocess.run(
        ["bash", str(hook_copy), "origin", "git@example.invalid:x/y.git"],
        cwd=tmp_path,
        input=_PUSH_LINE + "\n",
        capture_output=True,
        text=True,
    )

    assert proc.returncode == gate_rc, f"게이트 rc={gate_rc} 인데 훅은 rc={proc.returncode}"
    assert argv_log.read_text(encoding="utf-8").split() == ["--skip-tests"], (
        "테스트 단계는 CI 4-shard 가 미러한다 — 훅이 full 모드로 돌면 320.8s 라 우회당한다"
    )


def test_missing_gate_blocks_instead_of_passing_silently(tmp_path):
    """게이트 스크립트가 없으면 통과가 아니라 차단이다 — '미검증' 은 '깨끗함' 이 아니다."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    hook_copy = tmp_path / "scripts" / "hooks" / "pre-push"
    hook_copy.parent.mkdir(parents=True)
    shutil.copy2(HOOK, hook_copy)

    proc = subprocess.run(
        ["bash", str(hook_copy), "origin", "git@example.invalid:x/y.git"],
        cwd=tmp_path,
        input=_PUSH_LINE + "\n",
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "게이트 부재를 exit 0 으로 넘기면 훅이 있으나 마나다"


def test_absent_interpreter_reports_non_execution_not_a_finding():
    """python 이 없으면 그렇게 말한다 — 다른 단계의 '발견' 으로 위장하지 않는다.

    `$PYTHON` 은 존재 확인 없는 경로라, 없으면 각 단계가 rc=127 로 죽고 그 단계의 `if`
    가 그것을 자기 발견으로 보고한다. `.venv` 없는 clone 에서 "Personal financial data
    leak detected" 가 찍히는데 스캐너는 한 번도 돈 적이 없다 — 실패와 미실행이 구분
    안 되는 형태(#910/#911)다. 훅으로 돌 때 이 거짓말은 곧 `--no-verify` 습관이 된다.

    Mutation lock: preflight 를 걷어내면 출력이 유출 주장으로 바뀌어 FAIL.
    """
    proc = subprocess.run(
        ["bash", GATE_REL, "--skip-tests"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHON": "/nonexistent/python", "HOME": str(Path.home())},
        capture_output=True,
        text=True,
    )
    out = proc.stdout + proc.stderr

    assert proc.returncode != 0, "검사를 못 돌렸는데 통과시키면 안 된다"
    assert "인터프리터 없음" in out, f"미실행을 미실행이라고 말하지 않는다:\n{out}"
    assert "leak detected" not in out, f"미실행을 유출 발견으로 보고했다:\n{out}"
