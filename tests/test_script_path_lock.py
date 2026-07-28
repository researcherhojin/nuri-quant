"""스크립트 경로 drift 클래스 킬러 (#846/#852/#910, Gotcha-Test Pair).

#557 scripts/ 7-subdir 리팩터가 만든 silent 고장 — 실증 4건:
- scheduler backup (scripts/backup.sh → db/) — 2개월 무백업 (#836)
- discord /health (scripts/health_check.sh → ops/) — rc=127 (#846)
- pre_push_check.sh 의 flat 경로 호출 — 로컬 pre-push 게이트 일부 무력화 (#852)
- pre_push_check.sh 의 **따옴표 없는** 호출 — 테스트 단계가 통째로 no-op (#910)

개별 상수 lock 대신 "scripts/…" 참조를 전수 수집해 실존을 검증한다 — 다음 리팩터가
어떤 스크립트를 옮겨도 즉시 FAIL. mock-only 테스트 (subprocess patch) 로는 경로
drift 를 못 잡는다 (§5.3).

**두 문법을 모두 본다.** #852 는 따옴표 친 리터럴만 스캔해서 `bash scripts/x.sh`
같은 셸 호출 라인을 통째로 놓쳤고, 그래서 #853 이 "pre-push 경로 수리"를 하고도
`scripts/ci_local.sh` 를 남겨 테스트 단계가 rc=127 로 계속 죽었다 — 게이트가 빨간불인
것과 테스트가 실패한 것이 구분되지 않아 아무도 눈치채지 못했다.

주석 라인은 제외한다. docstring 의 usage 예시(`python scripts/foo.py`)는 실행되지
않는 문서라 여기 대상이 아니다 (문서 drift 는 별개 관심사).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# "scripts/foo/bar.sh" / 'scripts/x.py' 형태의 문자열 리터럴
_SCRIPT_LITERAL = re.compile(r"""["'](scripts/[A-Za-z0-9_\-./]+\.(?:sh|py))["']""")

# 따옴표 없는 셸/파이썬 호출 — `bash scripts/x.sh`, `if $PYTHON scripts/y.py --flag`,
# `... && python3 scripts/z.py`. 인터프리터 토큰 직후의 경로만 잡는다.
_SCRIPT_INVOCATION = re.compile(
    r"(?:bash|sh|source|\$PYTHON|\$\{PYTHON\}|python3?)\s+(scripts/[A-Za-z0-9_\-./]+\.(?:sh|py))"
)


def _collect_script_literals() -> list[tuple[str, str]]:
    """(참조 위치, 스크립트 경로) 목록 — nuri/ .py + scripts/ .sh 스캔 (#852 확장)."""
    found: list[tuple[str, str]] = []
    sources = sorted((REPO_ROOT / "nuri").rglob("*.py")) + sorted((REPO_ROOT / "scripts").rglob("*.sh"))
    for src in sources:
        text = src.read_text(encoding="utf-8")
        for m in _SCRIPT_LITERAL.finditer(text):
            found.append((str(src.relative_to(REPO_ROOT)), m.group(1)))
    return found


def _collect_script_invocations() -> list[tuple[str, int, str]]:
    """(참조 위치, 줄번호, 스크립트 경로) — scripts/ .sh 의 실행 라인만 (#910)."""
    found: list[tuple[str, int, str]] = []
    for src in sorted((REPO_ROOT / "scripts").rglob("*.sh")):
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):  # usage 주석은 실행 경로가 아님
                continue
            for m in _SCRIPT_INVOCATION.finditer(line):
                found.append((str(src.relative_to(REPO_ROOT)), lineno, m.group(1)))
    return found


class TestScriptPathLock:
    def test_all_referenced_scripts_exist(self):
        found = _collect_script_literals()
        # 스캔 자체가 비어 있으면 정규식/구조 변화 — sweep 무력화 감지
        assert found, "nuri/ 에서 scripts/ 리터럴을 하나도 못 찾음 — sweep 정규식 확인"
        missing = [(src, script) for src, script in found if not (REPO_ROOT / script).is_file()]
        assert not missing, (
            f"스크립트 경로 drift (#557 클래스, #836/#846 재발 방지): {missing} — "
            "스크립트를 옮겼다면 참조 상수를 함께 갱신할 것"
        )

    def test_known_constants_still_covered(self):
        """알려진 3개 참조가 sweep 에 잡히는지 — 정규식 회귀 방지 canary."""
        scripts = {script for _, script in _collect_script_literals()}
        assert "scripts/db/backup.sh" in scripts  # nuri/scheduler.py (#836)
        assert "scripts/ops/health_check.sh" in scripts  # nuri/agents/discord/bot.py (#846)
        assert "scripts/dev/llm_consult.py" in scripts  # nuri/llm/thesis_query.py


class TestShellInvocationPathLock:
    """따옴표 없는 셸 호출 (#910) — pre-push 테스트 단계가 죽어 있던 실제 경로."""

    def test_all_invoked_scripts_exist(self):
        found = _collect_script_invocations()
        assert found, "scripts/ .sh 에서 셸 호출을 하나도 못 찾음 — sweep 정규식 확인"
        missing = [(src, ln, script) for src, ln, script in found if not (REPO_ROOT / script).is_file()]
        assert not missing, (
            f"셸 호출 경로 drift (#910): {missing} — 존재하지 않는 스크립트를 실행하면 "
            "rc=127 이 '해당 단계 실패' 와 구분되지 않는다"
        )

    def test_pre_push_gate_invocations_are_covered(self):
        """pre-push 게이트의 두 호출이 sweep 에 잡히는지 — canary.

        Gotcha-Test Pair: `_SCRIPT_INVOCATION` 을 지우거나 따옴표 필수로 되돌리면
        여기서 FAIL — #852 가 이걸 못 봐서 #910 이 생겼다.
        """
        invoked = {(src, script) for src, _, script in _collect_script_invocations()}
        gate = "scripts/verify/pre_push_check.sh"
        assert (gate, "scripts/verify/verify_doc_counts.sh") in invoked
        assert (gate, "scripts/dev/ci_local.sh") in invoked
