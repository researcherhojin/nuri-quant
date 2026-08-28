"""`-m` 을 넘기는 pytest 호출은 `not integration` 을 **다시 적어야 한다** (#1290).

## 무엇이 잘못됐었나

`pyproject.toml` 은 `addopts = "-v --tb=short -m \\"not integration\\""` 로 실외부
네트워크 테스트를 기본 제외한다. 그런데 **pytest 의 `-m` 은 합쳐지지 않고 덮어쓴다.**
그래서 커맨드라인에 `-m` 을 주는 순간 addopts 의 `not integration` 이 **사라진다.**

2026-08-29 실측:

```
$ pytest tests/integration/test_universe_sync_real.py --collect-only
no tests collected (9 deselected)          ← addopts 가 먹는다

$ pytest tests/integration/test_universe_sync_real.py -m "not slow" --collect-only
9 tests collected                          ← addopts 의 -m 이 덮여 사라졌다
```

`make test-fast` 가 `-m "not slow"` 를 넘기고 있었으므로, **가장 자주 도는 게이트에만**
KRX 실서버를 치는 테스트 3건이 섞여 있었다. KRX 가 응답하지 않는 날이면 코드와 무관하게
빨간불이 뜬다 — false-red 다. 이 레포가 반복해서 배운 형태고(#1270 요일 의존 FAIL,
#1277 배포 검증 거짓 경고), 매번 뜨는 빨간불은 **진짜 빨간불을 무시하는 습관**을 만든다.

## 방향이 거꾸로였다

`make test` (전체)는 `-m` 을 안 줘서 addopts 가 그대로 먹어 **정상**이었고,
`make test-fast` (수시로 도는 것)만 깨져 있었다. CI 샤드는 처음부터
`-m "not slow and not integration"` 으로 **둘 다 적고 있었다** — 로컬만 갈라진
CI-parity 결함이라 CI 는 영원히 초록이었다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"
CI = REPO / ".github" / "workflows" / "main-ci-cd.yml"

#: `-m` 을 넘기면서 `not integration` 을 **일부러 안 적는** 호출. 사유 필수.
#: 양방향 검사라 낡은 항목(이제 적게 된 것)도 FAIL 한다.
MARKER_EXEMPT: dict[str, str] = {
    "-m integration": (
        "`make test-integration` 자체 — integration 만 골라 도는 것이 목적이다. "
        "네트워크가 필요하다는 사실은 타깃 이름과 help 문구에 명시돼 있고, "
        "이건 수시로 도는 게이트가 아니라 사람이 의도적으로 부르는 명령이다."
    ),
}


def _pytest_invocations_with_marker() -> list[tuple[str, str]]:
    """`-m <expr>` 를 넘기는 pytest 호출 전부. (출처, 마커식) 목록."""
    out: list[tuple[str, str]] = []
    for src in (MAKEFILE, CI):
        if not src.exists():
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            code = line.split("#")[0]
            if "pytest" not in code:
                continue
            # ⚠️ `python -m pytest` 의 `-m` 은 **모듈 플래그**지 마커가 아니다.
            # 처음에 줄 전체를 훑었더니 그게 잡혀 `-m pytest` 가 마커식으로 보고됐다.
            # `pytest` 라는 단어 **뒤쪽**만 본다.
            tail = code.split("pytest", 1)[1]
            m = re.search(r'-m\s+"([^"]+)"|-m\s+(\S+)', tail)
            if m:
                out.append((src.name, (m.group(1) or m.group(2)).strip()))
    return out


class TestEveryMarkerExpressionKeepsIntegrationOut:
    """구조 스윕 — `-m` 을 새로 넘기는 곳이 생겨도 배제가 유지되는지."""

    def test_no_invocation_silently_drops_the_exclusion(self):
        bad = [
            (src, expr)
            for src, expr in _pytest_invocations_with_marker()
            if "not integration" not in expr and f"-m {expr}" not in MARKER_EXEMPT
        ]
        assert not bad, (
            f"`-m` 이 addopts 의 `not integration` 을 덮어쓴다 — 이 호출들이 실네트워크 테스트를 다시 끌어들인다: {bad}"
        )

    def test_every_exemption_is_still_used(self):
        """양방향 — 예외가 사라졌는데 목록에 남아 있으면 그 사유는 이미 거짓이다."""
        live = {f"-m {expr}" for _, expr in _pytest_invocations_with_marker()}
        stale = [k for k in MARKER_EXEMPT if k not in live]
        assert not stale, f"낡은 예외 항목: {stale}"

    def test_every_exemption_states_a_reason(self):
        for key, why in MARKER_EXEMPT.items():
            assert len(why) > 40, f"{key}: 사유가 너무 짧다"

    def test_the_sweep_has_eyes(self):
        """카나리아 — 스윕이 아무것도 못 찾으면 위 검사는 영원히 공허하다."""
        found = _pytest_invocations_with_marker()
        assert len(found) >= 3, f"pytest -m 호출을 못 찾았다: {found}"
        # 옛 결함 형태를 실제로 잡는지 (양방향)
        broken = 'pytest tests/ -m "not slow"'
        m = re.search(r'-m\s+"([^"]+)"', broken)
        assert m and "not integration" not in m.group(1), "옛 결함 형태를 못 잡는다"
        # `python -m pytest` 의 모듈 플래그를 마커로 오탐하지 않는지 — 실제로 밟았다.
        assert all(expr != "pytest" for _, expr in found), "`python -m pytest` 의 `-m` 을 마커식으로 오탐한다"


class TestSelectionActuallyExcludesTheNetworkTests:
    """동작 잠금 — 구조가 맞아도 실제 선택이 틀릴 수 있다.

    수집 단계만 돌린다(`--collect-only`). 실행하면 그 자체로 네트워크를 타므로,
    이 테스트가 자기가 막으려는 문제를 일으키게 된다.
    """

    @staticmethod
    def _collected(marker: str) -> int:
        r = subprocess.run(
            [
                ".venv/bin/python",
                "-m",
                "pytest",
                "tests/integration/",
                "-m",
                marker,
                "-q",
                "--collect-only",
                "-p",
                "no:cacheprovider",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        m = re.search(r"(\d+) tests? collected", r.stdout)
        return int(m.group(1)) if m else 0

    def test_fast_selection_collects_no_integration_test(self):
        """Mutation lock: Makefile 을 `-m "not slow"` 로 되돌리면 FAIL."""
        assert self._collected("not slow and not integration") == 0

    def test_slow_selection_collects_no_integration_test(self):
        assert self._collected("slow and not integration") == 0

    def test_integration_target_still_collects_them(self):
        """대조군 — 배제가 과해서 `make test-integration` 까지 죽으면 안 된다.

        이게 없으면 "전부 배제" 라는 가짜 수정이 통과한다.
        """
        assert self._collected("integration") > 0, "integration 타깃이 아무것도 못 고른다"


class TestTheMarkerContractIsDocumented:
    def test_makefile_explains_why_the_exclusion_is_respelled(self):
        """다음 사람이 '중복' 이라고 지우지 않도록 이유가 Makefile 에 있어야 한다.

        addopts 에 이미 있는데 왜 또 적나 — 답(`-m` 이 덮어쓴다)이 없으면 지워진다.
        """
        src = MAKEFILE.read_text(encoding="utf-8")
        assert "덮어쓴다" in src and "#1290" in src, (
            "Makefile 에 `-m` 이 addopts 를 덮어쓴다는 설명이 없다 — 중복으로 보여 지워진다"
        )
