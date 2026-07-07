"""스크립트 경로 drift 클래스 킬러 (#846, Gotcha-Test Pair).

#557 scripts/ 7-subdir 리팩터가 만든 silent 고장 3건 중 2건이 실증됨:
- scheduler backup (scripts/backup.sh → db/) — 2개월 무백업 (#836)
- discord /health (scripts/health_check.sh → ops/) — rc=127 (#846)

개별 상수 lock 대신, nuri/ 소스의 "scripts/…" 리터럴을 전수 수집해 실존을
검증한다 — 다음 리팩터가 어떤 스크립트를 옮겨도 이 테스트가 즉시 FAIL.
mock-only 테스트 (subprocess patch) 로는 경로 drift 를 못 잡는다 (§5.3).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# "scripts/foo/bar.sh" / 'scripts/x.py' 형태의 문자열 리터럴
_SCRIPT_LITERAL = re.compile(r"""["'](scripts/[A-Za-z0-9_\-./]+\.(?:sh|py))["']""")


def _collect_script_literals() -> list[tuple[str, str]]:
    """(참조 위치, 스크립트 경로) 목록 — nuri/ 전체 .py 스캔."""
    found: list[tuple[str, str]] = []
    for py in sorted((REPO_ROOT / "nuri").rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for m in _SCRIPT_LITERAL.finditer(text):
            found.append((str(py.relative_to(REPO_ROOT)), m.group(1)))
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
