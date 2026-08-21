"""`patch("nuri.core.db.query")` 금지를 기계로 잠근다 (#1149 클래스킬러).

facade patch 창 안에서 first-import 되는 모듈이 `from nuri.core.db import query` 를
하면 mock 을 전역에 복사해 patch 종료 후에도 남는다. #1150 이 fixture 를 고쳤지만
같은 파일의 resilience 테스트에 1곳이 잔존해 3주 잠복하다 CI 샤드 재구성(#1157) 후
발화했다 (PR #1172 red) — 사람 눈은 반복해서 놓치므로 텍스트 sweep 으로 잠근다.

allowlist: patch 창의 import 표면이 함수-로컬 lazy import 뿐이라 모듈 전역 오염이
구조적으로 불가능한 파일만, 사유와 함께. 양방향 — 새 위반도, 낡은 allowlist 도 FAIL.
"""

from __future__ import annotations

from pathlib import Path

TESTS = Path(__file__).resolve().parent
PATTERN = 'patch("nuri.core.db.query"'

#: 파일 → 허용 사유. 대상 함수가 query 를 **함수 안에서** lazy import 하면 patch 는
#: 로컬 바인딩만 잡고 모듈 전역이 오염되지 않는다.
ALLOWED = {
    "collectors/test_fallbacks.py": "cboe._collect_db_stale 은 함수-로컬 lazy import — 전역 오염 불가",
    "core/test_ticker_names.py": "ticker_names.get_ticker_name 은 함수-로컬 lazy import — 전역 오염 불가",
    "api/test_stream.py": "stream._get_snapshot 은 함수-로컬 lazy import — 전역 오염 불가",
}


def _live_occurrences(path: Path) -> int:
    """실제 `patch("nuri.core.db.query", ...)` **호출 노드**만 센다 (AST).

    텍스트 sweep 은 주석/독스트링 경계에서 오탐·눈멂 둘 다 낸다 — 실측: 이 파일의
    v1 텍스트 판이 #1149 교훈을 적어둔 독스트링을 위반으로 오인했다.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
        if name != "patch" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and arg.value == "nuri.core.db.query":
            n += 1
    return n


class TestNoFacadeQueryPatch:
    def test_canary_detects_a_real_call(self, tmp_path):
        """sweep 이 실제 호출을 못 집으면 아래가 공허 통과 — 카나리아.
        독스트링/주석 속 언급은 세지 않아야 한다 (v1 텍스트 판의 오탐 축)."""
        f = tmp_path / "test_canary.py"
        f.write_text(
            '"""독스트링 언급: patch("nuri.core.db.query") 는 금지다."""\n'
            "from unittest.mock import patch\n"
            "def test_x():\n"
            '    with patch("nuri.core.db.query", return_value=[]):\n'
            "        pass\n",
            encoding="utf-8",
        )
        assert _live_occurrences(f) == 1

    def test_only_allowlisted_files_use_the_facade_patch(self):
        offenders: dict[str, int] = {}
        for f in TESTS.rglob("test_*.py"):
            if f.name == Path(__file__).name:
                continue
            n = _live_occurrences(f)
            if n:
                offenders[str(f.relative_to(TESTS))] = n
        unexpected = set(offenders) - set(ALLOWED)
        stale = set(ALLOWED) - set(offenders)
        assert not unexpected, (
            f"금지 패턴 신규 사용: {sorted(unexpected)} — 빈 격리 DB(init_db + DB_PATH "
            "monkeypatch) 또는 use-site patch 로 바꿀 것 (tests/CLAUDE.md #1149)"
        )
        assert not stale, f"allowlist 낡음 (더는 안 쓰는 파일): {sorted(stale)} — 목록에서 제거"
