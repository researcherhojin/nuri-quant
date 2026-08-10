"""shellcheck 가 `scripts/` 하위 전체를 보는지 잠근다.

`Shell Lint` 는 required status check 인데, 세 호출부가 모두 `scripts/*.sh` 라는
비재귀 글롭을 썼다. 스크립트가 7개 하위 디렉터리로 이사한 뒤 그 글롭은 **27개 중
1개**(`scripts/_common.sh`)만 잡았다 — 필수 게이트가 사실상 비어 있었고, 그래서
`verify_all.sh` 의 파이프-종료코드 버그도 shellcheck 에 걸릴 기회가 없었다.

Gotcha-Test Pair (STRATEGY §5.3.1): 어느 호출부든 비재귀 글롭으로 되돌리면 FAIL.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CALL_SITES = (
    Path(".github/workflows/main-ci-cd.yml"),
    Path("Makefile"),
    Path("scripts/verify/pre_push_check.sh"),
)

# 비재귀 글롭이 shellcheck 인자로 쓰인 자리. 산문/주석의 언급은 잡지 않는다.
_NON_RECURSIVE = re.compile(r"(?<!')\bshellcheck\b[^\n]*\bscripts/\*\.sh")


class TestShellcheckScope:
    def test_no_call_site_uses_the_non_recursive_glob(self):
        offenders = []
        for rel in CALL_SITES:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if _NON_RECURSIVE.search(line):
                    offenders.append(f"{rel}:{i}  {line.strip()[:90]}")
        assert not offenders, (
            "`scripts/*.sh` 는 하위 디렉터리를 놓친다 (27개 중 1개). "
            "`find scripts -name '*.sh' -exec shellcheck ... {} +` 를 쓸 것:\n  "
            + "\n  ".join(offenders)
        )

    def test_every_call_site_collects_recursively(self):
        """세 곳 모두 재귀 수집 형태를 실제로 갖고 있는가 (위 테스트의 공백 통과 방지)."""
        missing = [
            str(rel)
            for rel in CALL_SITES
            if "-name '*.sh'" not in (REPO_ROOT / rel).read_text(encoding="utf-8")
        ]
        assert not missing, f"재귀 수집 형태가 없는 호출부: {missing}"

    def test_recursive_form_actually_matches_more_than_the_old_glob(self):
        """카나리아: 트리가 다시 평평해지면 이 테스트가 무의미해지므로 그때 알린다."""
        all_sh = sorted(REPO_ROOT.glob("scripts/**/*.sh"))
        top_only = sorted(REPO_ROOT.glob("scripts/*.sh"))
        assert len(all_sh) > len(top_only), (
            f"scripts/ 하위 .sh 가 최상위에만 있다 (전체 {len(all_sh)} / 최상위 {len(top_only)}). "
            "트리 구조가 바뀌었다면 이 테스트의 전제를 다시 확인할 것."
        )
