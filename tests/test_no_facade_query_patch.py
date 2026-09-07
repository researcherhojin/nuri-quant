"""facade DB 리더의 **재바인딩** 금지를 기계로 잠근다 (#1149 클래스킬러, #1447).

facade patch 창 안에서 first-import 되는 모듈이 `from nuri.core.db import query` 를
하면 mock 을 전역에 복사해 patch 종료 후에도 남는다. #1150 이 fixture 를 고쳤지만
같은 파일의 resilience 테스트에 1곳이 잔존해 3주 잠복하다 CI 샤드 재구성(#1157) 후
발화했다 (PR #1172 red) — 사람 눈은 반복해서 놓치므로 sweep 으로 잠근다.

## 금지 대상은 **철자가 아니라 재바인딩**이다 (#1447)

v2 는 `patch("nuri.core.db.query")` 한 형태만 셌다. 같은 누출을 만드는 나머지 형태는
전부 0 으로 세어졌고, 실측 결과 5 종 중 1 종만 보고 있었다:

    1  <- patch("nuri.core.db.query")
    0  <- monkeypatch.setattr(dbmod, "query", ...)
    0  <- monkeypatch.setattr("nuri.core.db.query", ...)
    0  <- patch.object(dbmod, "query", ...)
    0  <- setattr(dbmod, "query", ...)

그래서 #1436 작업 중 실제 위반이 통과했다 — `monkeypatch.setattr(dbmod, "query", …)` 가
`test_data_integrity` 와 `test_rebalance` 6 건을 오염시켰는데 가드는 초록이었다. 알아챈
것은 가드가 아니라 무관한 테스트의 red 였고, `-n auto` 였다면 오염원과 피해자가 다른
워커로 가서 그마저 안 보였다. `.claude/rules/enforcement.md` 가 이름 붙인 **green dead
gate** — 실패하는 게 아니라 검사 대상을 안 보면서 통과하는 게이트다.

## 대상 범위

`tests/CLAUDE.md` 가 규정한 두 리더(`query` · `query_df`)만 본다. 누출 기전 자체는
`get_tickers` 같은 다른 facade 속성에도 똑같이 성립하지만, 그쪽은 현행 사용처가 많아
같이 넓히면 이 수정의 스코프를 넘는다 — 넓힐 거면 별도 이슈에서 사용처를 하나씩 판정할 것.

allowlist: patch 창의 import 표면이 함수-로컬 lazy import 뿐이라 모듈 전역 오염이
구조적으로 불가능한 파일만, 사유와 함께. 양방향 — 새 위반도, 낡은 allowlist 도 FAIL.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: facade 모듈과 그 DB 리더들. 재바인딩되면 import 한 모듈이 mock 사본을 들고 산다.
FACADE = "nuri.core.db"
READERS = ("query", "query_df")

#: 파일 → 허용 사유. 대상 함수가 리더를 **함수 안에서** lazy import 하면 patch 는
#: 로컬 바인딩만 잡고 모듈 전역이 오염되지 않는다.
ALLOWED = {
    "collectors/test_fallbacks.py": "cboe._collect_db_stale 은 함수-로컬 lazy import — 전역 오염 불가",
    "core/test_ticker_names.py": "ticker_names.get_ticker_name 은 함수-로컬 lazy import — 전역 오염 불가",
    "api/test_stream.py": "stream._get_snapshot 은 함수-로컬 lazy import — 전역 오염 불가",
    # 아래 4 건은 #1447 이 sweep 을 5 형태로 넓히면서 처음 보이게 된 기존 사이트다.
    # 철자만 달랐을 뿐 같은 재바인딩이라, 하나씩 판정해 사유를 남긴다.
    "api/test_dashboard.py": "dashboard 의 query 는 전부 함수-로컬 lazy import (61·254·314·409·600) — 전역 오염 불가",
    "collectors/test_collectors_branches.py": "earnings_preview.query_df 는 함수-로컬 lazy import (135) — 전역 오염 불가",
    "trading/agents/test_base.py": "BaseAgent._safe_query 가 query 를 함수 안에서 import (80) — 전역 오염 불가",
    # 이쪽만 성격이 다르다: 소비자(nuri/core/fx.py:34, price_targets.py:15)가 **모듈 레벨**로
    # 사본을 가져가므로 facade 를 갈아끼워도 아무 데도 안 닿는다. 실측으로 fake 발화 0 회 —
    # 즉 누출은 없지만 그 테스트도 무력하다 (#1448). import 순서가 반대였다면 같은 코드가
    # 이번엔 창 밖까지 mock 을 남겨 #1149 그 자체가 된다: **무력하거나 유해하거나** 다.
    "trading/recommend/test_recommend_branch_coverage_v2.py": "소비자가 모듈 레벨 사본 보유 — patch 가 무력 (#1448 에서 use-site 로 교체 예정)",
}


def _facade_aliases(tree: ast.AST) -> set[str]:
    """이 파일에서 facade 모듈을 가리키는 이름들.

    모듈 객체를 인자로 받는 형태(`monkeypatch.setattr(dbmod, "query", …)`)를 잡으려면
    별칭을 먼저 알아야 한다 — `import nuri.core.db as dbmod` 든 `from nuri.core import
    db` 든 결과는 같은 모듈 객체다.
    """
    aliases = {FACADE}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == FACADE:
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "nuri.core":
            for a in node.names:
                if a.name == "db":
                    aliases.add(a.asname or a.name)
    return aliases


def _dotted(node: ast.AST) -> str:
    """`nuri.core.db` 같은 점 표기를 원문 문자열로 되돌린다 (별칭 대조용)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _live_occurrences(path: Path) -> int:
    """facade 리더를 재바인딩하는 **호출 노드**를 센다 (AST).

    텍스트 sweep 은 주석/독스트링 경계에서 오탐·눈멂 둘 다 낸다 — 실측: 이 파일의
    v1 텍스트 판이 #1149 교훈을 적어둔 독스트링을 위반으로 오인했다.

    세는 형태 (#1447):
      - `patch("nuri.core.db.query")`            문자열 타깃
      - `monkeypatch.setattr("nuri.core.db.query", …)`
      - `patch.object(dbmod, "query", …)`        (모듈객체, 속성명)
      - `monkeypatch.setattr(dbmod, "query", …)`
      - `setattr(dbmod, "query", …)`             맨 builtin
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = _facade_aliases(tree)
    string_targets = {f"{FACADE}.{r}" for r in READERS}

    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        # `patch` / `patch.object` / `monkeypatch.setattr` / `setattr` 를 이름으로 식별.
        # 호출 주체(`mock.patch` vs `patch`)는 보지 않는다 — import 형태로 우회되면 안 된다.
        fname = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
        if fname not in ("patch", "object", "setattr"):
            continue

        first = node.args[0]
        # (a) 문자열 타깃 — "nuri.core.db.query"
        if isinstance(first, ast.Constant) and first.value in string_targets:
            n += 1
            continue
        # (b) (모듈객체, "속성명") — 별칭을 통해 facade 를 가리키는 경우만
        if len(node.args) >= 2 and _dotted(first) in aliases:
            attr = node.args[1]
            if isinstance(attr, ast.Constant) and attr.value in READERS:
                n += 1
    return n


class TestNoFacadeQueryPatch:
    def test_canary_detects_every_rebinding_form(self, tmp_path):
        """sweep 이 실제 호출을 못 집으면 아래가 공허 통과 — 형태마다 카나리아 (#1447).

        v2 는 카나리아가 `patch("…")` 하나뿐이라, 나머지 4 형태를 못 잡아도 초록이었다.
        같은 함정을 한 겹 안에서 반복하지 않으려면 형태별로 세운다.
        """
        forms = {
            'with patch("nuri.core.db.query", return_value=[]): pass': 1,
            'monkeypatch.setattr(dbmod, "query", lambda *a, **k: [])': 1,
            'monkeypatch.setattr("nuri.core.db.query", lambda *a, **k: [])': 1,
            'with patch.object(dbmod, "query", return_value=[]): pass': 1,
            'setattr(dbmod, "query", lambda *a, **k: [])': 1,
            'monkeypatch.setattr("nuri.core.db.query_df", lambda *a, **k: None)': 1,
            'monkeypatch.setattr(dbmod, "query_df", lambda *a, **k: None)': 1,
            # 무관한 것은 세지 않는다 — 오탐 축
            'monkeypatch.setattr(dbmod, "DB_PATH", tmp)': 0,
            'monkeypatch.setattr(other, "query", lambda *a, **k: [])': 0,
            '"""독스트링 언급: patch("nuri.core.db.query") 는 금지."""': 0,
        }
        for body, expected in forms.items():
            f = tmp_path / "test_canary.py"
            f.write_text(
                "from unittest.mock import patch\n"
                "import nuri.core.db as dbmod\n"
                "import nuri.collectors.base as other\n"
                "def test_x(monkeypatch, tmp):\n"
                f"    {body}\n",
                encoding="utf-8",
            )
            assert _live_occurrences(f) == expected, f"{body!r} → {_live_occurrences(f)} (기대 {expected})"

    def test_only_allowlisted_files_rebind_the_facade_readers(self):
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
