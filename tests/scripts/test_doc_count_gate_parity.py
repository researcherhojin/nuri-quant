"""sync 가 쓰는 테스트-수 사이트 = verify 가 읽는 사이트 를 잠근다 (#1132).

`sync_doc_counts.sh` 는 테스트 수를 3곳에 썼지만 `verify_doc_counts.sh` 는
그 3곳을 읽지 않았다 — 17개 드리프트가 게이트 초록인 채 통과했다. 두 스크립트의
실측 함수 집합이 조용히 갈리는 것이 재발 형태이므로, 패턴을 **문자 그대로**
양방향 대조한다 (한쪽에만 있는 사이트는 즉시 FAIL).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC = REPO_ROOT / "scripts" / "doc" / "sync_doc_counts.sh"
VERIFY = REPO_ROOT / "scripts" / "verify" / "verify_doc_counts.sh"


def _live_lines(path: Path) -> str:
    """주석 줄 제거 — 정규식 sweep 은 따옴표/주석 경계에서 조용히 눈이 먼다.

    주석 처리로 사이트를 죽여도 grep 은 그대로 집는다 — 실측: 이 필터 없이는
    README 사이트를 주석 처리한 mutant 가 파리티 검사를 통과했다.
    """
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))


def _sync_sites() -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2)) for m in re.finditer(r"update_comma_number (\S+)\s+'([^']+)'", _live_lines(SYNC))}


def _verify_sites() -> set[tuple[str, str]]:
    return {
        (m.group(1).strip('"'), m.group(2))
        for m in re.finditer(r'check_comma_claim "tests_be" "\$TESTS_BE" (\S+)\s+\'([^\']+)\'', _live_lines(VERIFY))
    }


class TestDocCountGateParity:
    def test_sites_found(self):
        """정규식이 0건을 집으면 아래 동등성 검사가 공허하게 통과한다 — 먼저 잠근다."""
        assert len(_sync_sites()) >= 3, "sync 의 update_comma_number 사이트를 못 찾았다"
        assert len(_verify_sites()) >= 3, "verify 의 check_comma_claim 사이트를 못 찾았다"

    def test_sync_and_verify_read_the_same_sites(self):
        sync, verify = _sync_sites(), _verify_sites()
        assert sync == verify, (
            f"sync 에만: {sorted(sync - verify)}\nverify 에만: {sorted(verify - sync)}\n"
            "→ 한쪽만 고치면 드리프트가 다시 게이트를 지나간다"
        )


class TestCommaClaimBehavior:
    """check_comma_claim 이 comma-number 를 실제로 잡는지 — grep 이 아니라 실행으로.

    기존 extract_nums 는 마지막 숫자런을 집어 "7,446" 을 446 으로 읽는다.
    그 축이 회귀하면 게이트는 초록인 채 눈이 먼다 (green dead gate).
    """

    def _run(self, doc_line: str, expected: str) -> int:
        text = VERIFY.read_text(encoding="utf-8")
        m = re.search(r"check_comma_claim\(\) \{.*?\n\}", text, re.DOTALL)
        assert m, "check_comma_claim 함수를 verify 스크립트에서 못 찾았다"
        script = (
            "pass() { :; }; fail() { :; }; warn() { :; }\n"
            + m.group(0)
            + f'\nprintf \'%s\\n\' "{doc_line}" > "$TMPF"\n'
            + f"check_comma_claim tests_be '{expected}' \"$TMPF\" '[0-9,]+ backend tests across'\n"
        )
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            tmpf = f.name
        proc = subprocess.run(
            ["bash", "-c", script],
            env={"TMPF": tmpf, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        return proc.returncode

    def test_matching_comma_number_passes(self):
        assert self._run("7,446 backend tests across 493 files", "7446") == 0

    def test_drifted_comma_number_fails(self):
        assert self._run("7,446 backend tests across 493 files", "7461") != 0
