"""액터의 outbox 발행 실패는 **조용히** 넘어가면 안 된다 (carry-over audit N3).

무엇이 문제였나
---------------
`nuri/agents/actors/` 의 `stage_*` 호출 14곳이 `except Exception: pass` 로 감싸여
있었다. 감싸는 것 자체는 옳다 — #894 가 못박은 대로 **관측이 본 작업을 게이트하면
안 된다**. Discord 발행이 실패했다고 수집이나 판정을 죽일 수는 없다.

틀린 건 `pass` 다. 발행이 며칠째 실패해도 아무 흔적이 없으니, 이 레포가 이미
두 번 밟은 *"감지는 어디에도 안 닿으면 없는 것과 같다"* 가 된다. 로그 한 줄이면
액터를 죽이지 않으면서도 흔적은 남는다.

왜 사이트별 테스트가 아니라 스윕인가
------------------------------------
14곳을 한 테스트로 고치면 나머지 13곳은 잠금 없이 들어간다 (Gotcha-Test Pair
위반). 반대로 14개 테스트를 쓰면 15번째 호출부가 생길 때 아무도 안 늘린다.
그래서 **호출부 집합 자체**를 불변조건으로 만든다 — 새 `stage_*` 를 `pass` 로
감싸면 그 순간 CI 가 잡는다.

문자열 grep 이 아니라 AST 인 이유는 주석·docstring 의 같은 문구를 오탐하지 않기
위해서다 (`tests/core/test_sqlite3_sole_importer.py` 와 같은 형태).
"""

from __future__ import annotations

import ast
from pathlib import Path

ACTORS = Path(__file__).resolve().parents[2] / "nuri" / "agents" / "actors"

# outbox staging 진입점. `stage_fn` 은 채널을 런타임에 고르는 호출부의 지역 별칭이다.
STAGE_CALLS = {"stage_incident", "stage_ops", "stage_rollout", "stage_fn", "stage_outbox"}


def _called_names(node: ast.AST) -> set[str]:
    return {
        (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
    }


def _outbox_try_blocks() -> list[tuple[str, ast.Try]]:
    out: list[tuple[str, ast.Try]] = []
    for f in sorted(ACTORS.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and (_called_names(node) & STAGE_CALLS):
                out.append((f.name, node))
    return out


def _is_silent(handler: ast.ExceptHandler) -> bool:
    """본문이 `pass` 뿐이면 조용한 것. docstring 만 있는 경우도 같다."""
    body = [n for n in handler.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return not body or all(isinstance(n, ast.Pass) for n in body)


class TestOutboxFailuresAreNeverSilent:
    def test_no_stage_call_is_wrapped_in_a_bare_pass(self) -> None:
        offenders = [
            f"{name}:{h.lineno}" for name, block in _outbox_try_blocks() for h in block.handlers if _is_silent(h)
        ]
        assert not offenders, (
            "outbox 발행 실패를 조용히 삼키는 곳: "
            + ", ".join(offenders)
            + " — 액터를 죽이지 말되(#894) 로그는 남길 것 (`logger.exception(...)`)"
        )

    def test_every_such_handler_logs(self) -> None:
        """`pass` 가 아니면 됐다가 아니라, **로깅**을 해야 한다."""
        missing = []
        for name, block in _outbox_try_blocks():
            for h in block.handlers:
                logged = {
                    getattr(c.func, "attr", "")
                    for c in ast.walk(h)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                }
                if not (logged & {"exception", "error", "warning"}):
                    missing.append(f"{name}:{h.lineno}")
        assert not missing, f"발행 실패 핸들러가 로그를 남기지 않는다: {', '.join(missing)}"

    def test_modules_with_stage_calls_define_a_logger(self) -> None:
        files = {name for name, _ in _outbox_try_blocks()}
        assert files, "스윕이 아무것도 못 찾았다 — 경로가 바뀌었는지 확인할 것"
        for name in sorted(files):
            src = (ACTORS / name).read_text(encoding="utf-8")
            assert "logging.getLogger(__name__)" in src, f"{name} 에 모듈 로거가 없다"

    def test_the_sweep_actually_sees_the_known_sites(self) -> None:
        """0건을 훑고 통과하면 통과가 아무 의미도 없다.

        14는 2026-08-14 실측치다. 늘어나는 건 정상이고(새 액터), 줄면 스윕이
        호출부를 놓치기 시작했다는 신호다.
        """
        assert len(_outbox_try_blocks()) >= 14
