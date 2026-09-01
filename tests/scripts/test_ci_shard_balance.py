"""CI 의 fast-shard 분할이 **시간 기반**으로 도는지 잠근다.

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
import re
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
            f"{DURATIONS.name} 이 없다 — CI fast shard 가 개수 균형으로 degrade 한다.\n"
            "`make sync-test-durations` 로 재생성할 것."
        )
        data = json.loads(DURATIONS.read_text())
        assert isinstance(data, dict) and data, "durations 파일이 비었거나 dict 가 아니다"
        assert len(data) >= _MIN_ENTRIES, (
            f"durations 항목이 {len(data)}개뿐 (하한 {_MIN_ENTRIES}) — 잘렸거나 오래됐다.\n"
            "`make sync-test-durations` 로 재생성할 것."
        )


class TestPrecisionStaysBounded:
    """Gotcha-Test Pair: full-precision float 로 되돌리면 FAIL.

    pytest-split 원본은 `0.0016861240146681666` 같은 값을 쓴다. privacy 스캐너는 민감 키가
    있는 줄에서 `\\b\\d{7,}\\b` 를 찾는데 소수점이 word boundary 라 그 19자리가 통째로 잡힌다 —
    `cash_balance` 가 이름에 든 테스트 3개 때문에 CI 가 막혔다 (2026-08-10).
    `make sync-test-durations` 가 `scripts/doc/round_test_durations.py` 를 이어 돌려 막는데,
    그 단계를 빼면 다음 재생성이 같은 실패를 되살린다. 그걸 여기서 잡는다.
    """

    def test_no_value_exceeds_four_decimals(self):
        data = json.loads(DURATIONS.read_text())
        # 원본 텍스트에서 봐야 한다 — 파싱된 float 은 자릿수 정보를 잃는다.
        long_runs = re.findall(r"\d+\.\d{5,}", DURATIONS.read_text())
        assert not long_runs, (
            f"소수 5자리 이상 값 {len(long_runs)}건 (예: {long_runs[:3]}) — "
            "privacy 스캐너에 걸린다. `scripts/doc/round_test_durations.py` 를 돌릴 것."
        )
        assert data, "durations 가 비었다"

    def test_the_regeneration_path_rounds(self):
        """카나리아 — Makefile 이 반올림 단계를 빠뜨리면 다음 재생성이 회귀한다."""
        makefile = (REPO_ROOT / "Makefile").read_text()
        target = makefile.split("sync-test-durations:", 1)[1].split("\n\n", 1)[0]
        assert "round_test_durations.py" in target, (
            "`sync-test-durations` 타깃이 반올림 단계를 안 부른다 — 재생성 시 CI 가 다시 막힌다"
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


WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml"


class TestShardTopology:
    """matrix.shard 와 pytest `--splits` 의 정합을 잠근다 (#1156 codex P2).

    matrix 를 [1..4] 로 줄이면서 `--splits 6` 을 두면 group 5/6 의 테스트는
    **어느 shard 에서도 안 돌지만 CI 는 초록**이다 — 실행 누락이 침묵한다.
    """

    def test_matrix_matches_splits(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        # 워크플로 구조상 각 테스트 job 은 matrix 선언 뒤에 자기 pytest 커맨드가
        # 온다 — 등장 순서 쌍(fast, slow)으로 대조한다.
        matrices = re.findall(r"shard: \[([0-9, ]+)\]", text)
        splits = re.findall(r"--splits (\d+)", text)
        assert len(matrices) == len(splits) >= 2, (
            f"테스트 job 의 matrix/--splits 쌍을 못 찾았다 (matrix {len(matrices)} / splits {len(splits)})"
        )
        for m, s in zip(matrices, splits):
            shard_list = [int(x) for x in m.split(",")]
            assert shard_list == list(range(1, int(s) + 1)), (
                f"matrix {shard_list} ≠ --splits {s} — 빠진 group 의 테스트는 어느 shard 에서도 안 돈다"
            )


class TestShardAlgorithm:
    """Fast lane 이 serial 연속 구간 분배로 돌아가는 회귀를 막는다 (#1393)."""

    def test_fast_shards_use_least_duration(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        fast_job = text.split("  backend-tests-shard:", 1)[1].split("  backend-tests-slow:", 1)[0]
        assert "--splitting-algorithm least_duration" in fast_job, (
            "fast shard 가 pytest-split 기본 duration_based_chunks 로 돌아갔다 — "
            "xdist 비선형 비용이 한 shard 에 몰려 8분 timeout 을 재현한다"
        )
