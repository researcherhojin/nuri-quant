"""`nuri/core/db/connection.py` 단독 sqlite3 importer 불변조건 (STRATEGY §2.2).

PreToolUse 훅(`.claude/settings.json`)이 `import sqlite3` 를 막지만 **편집 시점에만**
동작한다 — 훅 도입 이전에 들어온 코드, 훅을 안 쓰는 편집기, 사람이 직접 넣은 커밋은
전부 통과한다. 실제로 `nuri/trading/engine/certification.py` 가 그렇게 통과해 있었고
(연결은 안 열고 `except sqlite3.OperationalError` 한 줄 때문에 import), 2026-07-28
문서 감사에서야 발견됐다 — 그때까지 `invariants.md` 는 "유일한 importer" 라고 단언하고
있었다.

이 테스트가 그 갭을 메운다: 편집 경로와 무관하게 CI 가 매번 전수 검사한다.

정당한 필요(좁은 DB 예외만 잡기)는 `nuri.core.db` 가 re-export 하는 `OperationalError`
/ `DatabaseError` 로 해결한다. `except Exception` 으로 넓히는 건 진짜 버그를 삼키므로
더 나쁜 우회다.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NURI = REPO_ROOT / "nuri"
SOLE_IMPORTER = NURI / "core" / "db" / "connection.py"


def _modules_importing_sqlite3() -> list[str]:
    """`nuri/` 전 모듈 AST 파싱 → sqlite3 를 import 하는 파일 목록.

    문자열 grep 이 아니라 AST 를 쓴다 — 주석·docstring·문자열 리터럴 안의
    'import sqlite3' 를 오탐하지 않기 위해서다 (이 파일 자체가 docstring 에서
    그 문구를 여러 번 쓴다).
    """
    offenders: list[str] = []
    for path in sorted(NURI.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "sqlite3" for a in node.names):
                offenders.append(str(path.relative_to(REPO_ROOT)))
                break
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offenders.append(str(path.relative_to(REPO_ROOT)))
                break
    return offenders


class TestSqlite3SoleImporter:
    def test_only_connection_module_imports_sqlite3(self):
        """`nuri/` 안에서 sqlite3 를 import 하는 파일은 정확히 1개다.

        Gotcha-Test Pair: 다른 모듈에 `import sqlite3` 를 넣으면 이 테스트가 FAIL 한다.
        실패 메시지가 대안(`from nuri.core.db import OperationalError`)까지 알려준다.
        """
        offenders = _modules_importing_sqlite3()
        expected = [str(SOLE_IMPORTER.relative_to(REPO_ROOT))]
        assert offenders == expected, (
            f"sqlite3 를 import 하는 모듈이 {len(offenders)}개 — 기대 1개.\n"
            f"  발견: {offenders}\n"
            f"  DB 예외를 잡으려던 것이라면 `from nuri.core.db import OperationalError` 를 쓸 것.\n"
            f"  연결이 필요하면 query() / query_df() / upsert_*() / get_db() 를 쓸 것."
        )

    def test_facade_reexports_db_exception_types(self):
        """`nuri.core.db` 가 예외 타입을 노출한다 — 이게 규칙 준수의 탈출구다.

        이 re-export 가 사라지면 좁은 예외 처리를 원하는 호출자는 sqlite3 를 직접
        import 하거나 `except Exception` 으로 넓히는 수밖에 없다. 둘 다 나쁘다.
        """
        import sqlite3

        from nuri.core.db import DatabaseError, OperationalError

        assert OperationalError is sqlite3.OperationalError
        assert DatabaseError is sqlite3.DatabaseError

    def test_certification_catches_db_errors_without_importing_sqlite3(self):
        """#904 후속 회귀 — certification 이 예외를 여전히 좁게 잡는다.

        `import sqlite3` 만 지우고 `except Exception` 으로 넓히면 이 테스트가 FAIL 한다.
        """
        from nuri.core.db import OperationalError
        from nuri.trading.engine import certification

        src = (REPO_ROOT / "nuri/trading/engine/certification.py").read_text(encoding="utf-8")
        assert "except OperationalError" in src, "좁은 DB 예외 처리가 사라졌다"
        assert certification.OperationalError is OperationalError
