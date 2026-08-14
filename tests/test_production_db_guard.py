"""`tests/conftest.py` 의 프로덕션 DB 접근 금지 가드가 **실제로 무는지** 검증한다.

⚠️ 이 테스트들은 원래 `tests/conftest.py` 안에 있었다. **pytest 는 conftest.py 를
테스트 모듈로 수집하지 않는다** — `python_files` 기본값이 `test_*.py` 라서, 파일을
인자로 명시할 때만 수집된다. 그래서 "돌려서 확인했다"던 게 사실은 `pytest
tests/conftest.py` 명시 실행이었고, `make test-fast` 와 CI 는 이 3개를 **한 번도
실행한 적이 없었다** (2026-08-14 Codex 리뷰 지적, `pytest tests/ --collect-only`
로 0건 실측).

가드를 검증하는 테스트가 조용히 안 돌면 가드가 죽어도 초록이다 — 이 레포는 훅 2개가
3.5개월간 무력했던 전례가 있다(`.claude/rules/enforcement.md`). 그래서 여기,
수집되는 파일에 둔다.

conftest 에서 `_ProductionDBTouched` / `_REAL_DB` 를 import 하지 않는다 (`tests/` 는
패키지가 아니라 import 경로가 실행 방식에 따라 달라진다). 대신 **성질**을 직접
단언한다 — 어차피 중요한 건 클래스 이름이 아니라 "`except Exception` 을 통과한다" 다.
"""

import sqlite3
from pathlib import Path

import pytest

# conftest 의 `_REAL_DB` 와 같은 경로. 한쪽만 바뀌면 가드가 안 물어 이 테스트가
# FAIL 한다 — 드리프트가 조용히 넘어가지 않는 방향이다.
REAL_DB = Path(__file__).resolve().parents[1] / "data" / "portfolio.db"


class TestProductionDBGuard:
    def test_the_guard_actually_bites(self):
        """가드가 등록만 되고 안 무는 상태를 막는다."""
        with pytest.raises(BaseException, match="프로덕션 DB") as exc_info:
            sqlite3.connect(str(REAL_DB))

        assert not isinstance(exc_info.value, Exception), (
            "가드 예외가 `Exception` 하위다 — 프로덕션의 광범위 `except Exception` 에 "
            "삼켜진다. `BaseException` 을 직접 상속해야 한다."
        )

    def test_the_guard_leaves_other_paths_alone(self, tmp_path):
        """tmp DB 는 막지 않는다 — 막으면 전 스위트가 죽는다."""
        p = tmp_path / "ok.db"
        sqlite3.connect(str(p)).close()
        assert p.exists()

    def test_the_guard_survives_a_broad_except(self):
        """광범위 `except Exception` 이 가드를 삼키면 안 된다.

        프로덕션 코드는 섹션마다 `except Exception` 으로 감싸는 곳이 많다
        (`nuri/llm/report.py::gather_context`). 가드가 `AssertionError` 였을 때
        실제로 삼켜져서, 격리를 꺼도 테스트 5개가 초록이었다 (2026-08-14 실측).
        """
        swallowed = False
        try:
            try:
                sqlite3.connect(str(REAL_DB))
            except Exception:  # noqa: BLE001 — 프로덕션 코드의 실제 패턴을 재현
                swallowed = True
        except BaseException:  # noqa: BLE001 — 가드가 여기까지 올라와야 정상
            pass
        assert not swallowed, "가드가 `except Exception` 에 삼켜졌다 — 백스톱이 아니다"


class TestIsolationFixture:
    def test_db_path_points_away_from_production(self):
        """autouse 격리가 `nuri.core.db.DB_PATH` 를 실제로 갈아끼웠는지."""
        import nuri.core.db as db_mod

        assert Path(db_mod.DB_PATH).resolve() != REAL_DB.resolve()

    def test_isolated_db_has_the_schema(self):
        """세션 템플릿 복사본이 빈 파일이 아니라 스키마를 갖고 있는지.

        복사가 조용히 실패하면 모든 테스트가 "테이블 없음" 으로 죽는 대신
        빈 결과를 받아 통과할 수 있다.
        """
        from nuri.core.db import query

        rows = query("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio'")
        assert rows, "격리 DB 에 portfolio 테이블이 없다 — 스키마 템플릿 복사 실패"
