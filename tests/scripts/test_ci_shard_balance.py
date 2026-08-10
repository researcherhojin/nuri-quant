"""CI 의 4-shard 분할이 **시간 기반**으로 도는지 잠근다.

pytest-split 은 `.test_durations` 가 없으면 조용히 **개수 균형**으로 degrade 한다. 그게
graceful 하지 않다 — 2026-08-10 실측으로 shard 최대/최소가 3.75배 벌어졌고, 최악 shard 가
5분 timeout 을 넘겨 PR 2건(#1012·#1015)이 막혔다. degrade 는 로그 한 줄
(`[pytest-split] No test durations found`)만 남기고 job 은 초록으로 끝나므로, 파일이 사라지거나
이름이 틀려도 아무도 모른다.

실제로 이름이 틀려 있었다: CI 워크플로 주석과 `pyproject.toml` 이 둘 다 `.test-durations`
(하이픈)라고 적어놨는데 플러그인 기본값은 `.test_durations` (언더스코어)다. 그 이름으로 파일을
만들었다면 영영 안 읽혔다.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# pytest-split 의 `--durations-path` 기본값. 바꾸려면 CI 커맨드에 명시 전달해야 한다.
DURATIONS = REPO_ROOT / ".test_durations"

# 현재 6706 항목. 하한을 낮게 둬서 평소 증감에는 안 걸리고, 삭제·절단만 잡는다.
_MIN_ENTRIES = 5000


class TestDurationsFile:
    def test_exists_and_parses(self):
        """파일이 없으면 CI 가 count-split 으로 조용히 떨어진다."""
        assert DURATIONS.exists(), (
            f"{DURATIONS.name} 이 없다 — CI 4-shard 가 개수 균형으로 degrade 한다.\n"
            "`make sync-test-durations` 로 재생성할 것."
        )
        data = json.loads(DURATIONS.read_text())
        assert isinstance(data, dict) and data, "durations 파일이 비었거나 dict 가 아니다"
        assert len(data) >= _MIN_ENTRIES, (
            f"durations 항목이 {len(data)}개뿐 (하한 {_MIN_ENTRIES}) — 잘렸거나 오래됐다.\n"
            "`make sync-test-durations` 로 재생성할 것."
        )


class TestFilenameIsNotMisspelled:
    """Gotcha-Test Pair: 문서/워크플로에 하이픈 철자를 되살리면 FAIL.

    하이픈 철자는 **동작을 바꾸지 않으면서** 다음 사람을 잘못된 파일명으로 안내한다 —
    그 이름으로 만든 파일은 읽히지 않고 CI 는 계속 초록이다.
    """

    SITES = (".github/workflows/main-ci-cd.yml", "pyproject.toml", "Makefile")

    def test_no_site_spells_it_with_a_hyphen(self):
        offenders = [s for s in self.SITES if ".test-durations" in (REPO_ROOT / s).read_text()]
        assert not offenders, (
            "`.test-durations` (하이픈) 로 적힌 곳: "
            + ", ".join(offenders)
            + "\npytest-split 기본값은 `.test_durations` (언더스코어) 다."
        )

    def test_the_sites_actually_mention_the_file(self):
        """카나리아 — 세 곳이 전부 파일을 안 언급하면 위 테스트가 공허하게 통과한다."""
        mentioning = [s for s in self.SITES if ".test_durations" in (REPO_ROOT / s).read_text()]
        assert len(mentioning) == len(self.SITES), "durations 파일을 언급하지 않는 곳: " + ", ".join(
            set(self.SITES) - set(mentioning)
        )
