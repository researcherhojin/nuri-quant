"""`scripts/` 하위 셸 스크립트가 repo root 를 올바로 계산하는지 검증 (#946).

Gotcha-Test Pair:
#557 이 스크립트를 `scripts/` → `scripts/<subdir>/` 로 옮기면서 (커밋 메시지가
"no rename" 이다) 내부의 `cd "$(dirname "$0")/.."` 를 안 고쳤다. 한 단계만 올라가
**repo root 가 아니라 `scripts/` 에 착지**한 채로 4개가 남았고, 실패 방식이 전부
조용했다:

  - `state_replicator.sh` — `.venv/bin/python` 못 찾고 launchd exit 1
  - `health_check.sh`     — `❌ DB missing`, python 검사가 `|| echo 0` 폴백으로
                            빠져 **실패를 0 으로 보고** (검사 미실행 = 검사 통과)
  - `sync_dev.sh`         — 파일 목록이 전부 `[[ -e ]] || continue` 로 탈락, no-op
  - `autopull_receiver.sh`— git 이 하위 디렉터리에서도 작동해 **운으로** 동작

launchd 에 미설치라(#939) 안 도는 동안은 아무도 몰랐다. 다음 이동 때 같은 일이
반복되지 않도록, 중첩 깊이와 `..` 개수를 기계적으로 대조한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS_DIR = Path("scripts")

# **root 해석만** 잡는다. `source "$(dirname "$0")/../_common.sh"` 같은 형제 디렉터리
# 참조는 대상이 아니다 — `scripts/dev/` → `scripts/` 로 한 단계가 정답이라 같이 잡으면
# 오탐이 된다. root 해석은 두 형태뿐이고 둘 다 모호하지 않다:
#   (a) 문장 맨 앞의 bare `cd "$(dirname "$0")/../.."`
#   (b) `ROOT/REPO 이름의 변수 = "$(cd "$(dirname "$0")/../.." && pwd)"`
_ROOT_EXPRS = (
    re.compile(r'^\s*cd\s+"\$\(dirname\s+"\$(?:0|\{BASH_SOURCE\[0\]\})"\)((?:/\.\.)+)"', re.MULTILINE),
    # `LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"` 와
    # `REPO="${NURI_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"` 를 모두 받는다.
    re.compile(
        r'\w*(?:ROOT|REPO)\w*=\s*"(?:\$\{[^"\n]*?:-)?'
        r'\$\(cd\s+"\$\(dirname\s+"\$(?:0|\{BASH_SOURCE\[0\]\})"\)((?:/\.\.)+)"\s*&&\s*pwd\)',
    ),
    # SCRIPT_DIR 2-step 패턴: SCRIPT_DIR 로 스크립트 위치를 잡은 뒤 거기서 올라간다.
    re.compile(r'\w*(?:ROOT|REPO)\w*=\s*"\$\(cd\s+"\$\{SCRIPT_DIR\}((?:/\.\.)+)"\s*&&\s*pwd\)"'),
)


def _shell_scripts() -> list[Path]:
    return sorted(p for p in SCRIPTS_DIR.rglob("*.sh"))


def _root_expr_depths(path: Path) -> list[int]:
    """스크립트 안의 root 해석식들이 올라가는 단계 수."""
    text = path.read_text(encoding="utf-8")
    out = []
    for pattern in _ROOT_EXPRS:
        for m in pattern.finditer(text):
            out.append(m.group(1).count(".."))
    return out


def _nesting_depth(path: Path) -> int:
    """`scripts/` 기준 중첩 깊이 = repo root 까지 올라가야 하는 단계 수."""
    # scripts/x.sh        → 1  (scripts → root)
    # scripts/deploy/x.sh → 2
    return len(path.parts) - 1


class TestScriptRootResolution:
    def test_sweep_is_not_blind(self):
        """캐너리 — 스윕이 아무 스크립트도 못 찾으면 아래 검사가 공짜로 통과한다."""
        scripts = _shell_scripts()
        assert len(scripts) >= 8, f"scripts/ 하위 .sh 를 {len(scripts)}개만 찾았다 — 스윕이 고장난 것"
        assert any(_root_expr_depths(p) for p in scripts), "root 해석식을 하나도 못 찾았다 — 정규식이 눈멀었다"

    @pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: str(p))
    def test_root_expression_matches_nesting(self, script: Path):
        """`..` 개수가 실제 중첩 깊이와 일치해야 repo root 에 착지한다."""
        expected = _nesting_depth(script)
        for depth in _root_expr_depths(script):
            assert depth == expected, (
                f"{script} 의 root 해석식이 {depth}단계만 올라간다 (필요: {expected}단계).\n"
                f"실제 착지: {(script.parent / ('../' * depth)).resolve()}\n"
                "#557 처럼 스크립트를 옮기고 경로를 안 고치면 조용히 잘못된 곳에서 실행된다 (#946)."
            )

    def test_known_broken_scripts_are_fixed(self):
        """#946 이 고친 4개를 이름으로 고정 — 회귀 시 무엇이 깨졌는지 바로 보인다."""
        for name in (
            "scripts/deploy/state_replicator.sh",
            "scripts/ops/health_check.sh",
            "scripts/deploy/sync_dev.sh",
            "scripts/deploy/autopull_receiver.sh",
        ):
            p = Path(name)
            assert p.exists(), f"{name} 이 사라졌다 — 이 테스트를 갱신할 것"
            depths = _root_expr_depths(p)
            assert depths, f"{name} 에서 root 해석식을 못 찾았다 — 형태가 바뀌었으면 정규식을 갱신할 것"
            assert all(d == 2 for d in depths), f"{name}: {depths} (전부 2여야 한다)"
