"""doc-count 게이트와 그 fixer 가 같은 클레임 목록을 본다 (#916).

`verify_doc_counts.sh` 는 검사하고 `sync_doc_counts.sh` 는 고친다. 두 목록이
갈라지면 **게이트가 잡은 drift 를 그 게이트가 안내하는 명령이 못 고치는** 상태가
된다 — verify 는 빨간불, sync 는 "할 일 없음". 실제로 `CLAUDE.md` 가
`.claude/rules/` 로 쪼개진 뒤 sync 가 첫 클레임에서 `set -e` 로 죽어 아무것도
고치지 않았고, 그동안 verify 는 계속 그 명령을 해결책으로 안내했다.

여기서 잠그는 것:
  1. sync 가 배너만 찍고 죽지 않는다 (실제 고장 모드의 직접 재현)
  2. verify 가 검사하는 (파일, 클레임) 을 sync 도 전부 다룬다
  3. round-trip — 숫자를 망가뜨리면 sync 가 고치고 verify 가 통과한다
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify" / "verify_doc_counts.sh"
SYNC = REPO_ROOT / "scripts" / "doc" / "sync_doc_counts.sh"

# `update_claim <live_fn> <file> '<pattern>'` / `check_claim "<label>" "$X" "<file>" '<pattern>'`
_SYNC_CALL = re.compile(r"^update_claim\s+(\S+)\s+(\S+)\s+'(.+)'\s*$", re.M)
_VERIFY_CALL = re.compile(r"""check_claim\s+"[^"]+"\s+"[^"]+"\s+"([^"]+)"\s+'(.+?)'\s*(?:\|\||$)""", re.M)


def _sync_targets() -> set[tuple[str, str]]:
    return {(f, pat) for _fn, f, pat in _SYNC_CALL.findall(SYNC.read_text())}


def _verify_targets() -> set[tuple[str, str]]:
    return {(f, pat) for f, pat in _VERIFY_CALL.findall(VERIFY.read_text())}


class TestSyncRuns:
    def test_sync_does_more_than_print_its_banner(self, repo_copy):
        """#916 의 고장 모드 그대로 — 배너만 찍고 종료하면 FAIL.

        Gotcha-Test Pair: `current=$(grep ... || true)` 의 `|| true` 를 지우면
        set -e 가 첫 클레임에서 스크립트를 죽여 이 테스트가 FAIL.

        `repo_copy` 필수 — sync 는 in-place fixer 다. 이 테스트만 `cwd=REPO_ROOT`
        로 돌아서 **백엔드 테스트를 돌릴 때마다 실제 README/ARCHITECTURE/STRATEGY 가
        조용히 재작성**됐다. 통과하면서 쓰기 때문에 아무 신호가 없었다.
        `conftest.py` 의 `_repo_docs_stay_untouched` 가 되돌림을 잡는다.
        """
        r = _run(SYNC, repo_copy)
        processed = [ln for ln in r.stdout.splitlines() if "already in sync" in ln or "→" in ln]
        assert len(processed) >= 15, (
            f"클레임을 {len(processed)}건만 처리했다 — 중간에 죽었을 가능성:\n{r.stdout}{r.stderr}"
        )
        assert r.returncode == 0, f"manifest 가 온전한 사본인데 exit {r.returncode}:\n{r.stdout}{r.stderr}"


class TestStaleTargetIsSurvivable:
    """대상 문구가 이사가도 스크립트가 죽지 않고 나머지를 계속 처리한다.

    건강한 레포에서는 모든 패턴이 존재하므로 `set -e` 가 발동할 일이 없다 — 즉
    이 방어선은 **미래의 stale** 에만 작동하고, 그 상황을 여기서 인위적으로 만들지
    않으면 `|| true` 를 지워도 아무 테스트가 반응하지 않는다. #916 이 정확히 그
    "아직 아무도 밟지 않은 지뢰" 였다.
    """

    def test_missing_pattern_warns_and_continues(self, repo_copy):
        """첫 클레임의 대상 문구를 지워도 나머지가 처리되고, 조용히 넘어가지 않는다.

        Gotcha-Test Pair: `grep ... | head -1 || true` 의 `|| true` 를 지우면
        set -e 가 첫 클레임에서 스크립트를 죽여 processed 가 0 이 되고 FAIL.
        """
        # 카나리아는 sync 목록의 **첫** 클레임 대상이어야 한다 — 첫 항목에서 죽는지가
        # 이 테스트가 잠그는 것이기 때문. `.claude/rules/architecture.md` 를 쓰다가
        # 그 파일이 사이트에서 빠지면서(always-loaded 파일의 카운트 제거) 카나리아가
        # 아무 것도 안 겨냥하게 돼 조용히 통과했다 — 사이트를 옮길 땐 여기도 옮긴다.
        target = repo_copy / "nuri" / "collectors" / "CLAUDE.md"
        target.write_text(target.read_text().replace("Data Collectors", "Data Thingies"))

        r = _run(SYNC, repo_copy)

        processed = [ln for ln in r.stdout.splitlines() if "already in sync" in ln or "→" in ln]
        assert len(processed) >= 10, f"stale 대상 하나에 스크립트가 멈췄다 ({len(processed)}건 처리):\n{r.stdout}"
        assert "pattern not found" in r.stdout, f"누락을 알리지 않음:\n{r.stdout}"
        assert r.returncode != 0, "manifest 가 깨졌는데 exit 0 — 조용히 넘어감"


class TestFixerGuard:
    """`conftest.py` 의 fixer 가드가 **무장돼 있는지** 실제로 위반을 시도해 확인한다.

    가드는 `subprocess.Popen` 을 감싸므로 argv 를 변수에 담든 `check_call` 을 쓰든
    헬퍼로 감싸든 전부 같은 관문을 지난다 — 소스 문자열이 아니라 **실행 시도**를 본다.
    """

    def test_launching_the_fixer_at_the_real_repo_is_blocked(self):
        """Gotcha-Test Pair: `_run(SYNC, repo_copy)` 를 `cwd=REPO_ROOT` 직접 실행으로
        되돌리면 그 테스트가 여기서 막혀 FAIL. 문서의 sync 상태와 무관하게 결정론적이다.
        """
        with pytest.raises(AssertionError, match="실제 리포에 겨눴다"):
            subprocess.run(["bash", str(SYNC)], cwd=REPO_ROOT, capture_output=True, check=False)

    def test_a_copy_override_is_accepted(self, fixer_guard, repo_copy):
        """정상 경로까지 막으면 사본 실행이 불가능해진다 — 과잉 차단 방지."""
        assert fixer_guard(["bash", str(SYNC)], {"REPO_ROOT": str(repo_copy)}) is None

    def test_read_only_checkers_are_not_blocked(self, fixer_guard):
        """`scripts/verify/` 의 검사기는 레포에서 돌아도 무해하다 — 대상 아님."""
        assert fixer_guard(["bash", str(VERIFY)], None) is None


class TestClaimListParity:
    def test_both_scripts_were_parsed(self):
        """정규식이 조용히 눈이 멀면 아래 포함관계 테스트가 공허하게 통과한다."""
        assert len(_sync_targets()) >= 15, _sync_targets()
        assert len(_verify_targets()) >= 15, _verify_targets()

    def test_every_verified_claim_is_also_syncable(self):
        """verify 가 하드 게이트하는 클레임은 sync 도 고칠 수 있어야 한다.

        Gotcha-Test Pair: verify 에 check_claim 을 추가하고 sync 에 대응 항목을
        빼면 FAIL — 그 조합이 "빨간불인데 고칠 수단이 없는" 상태다.
        """
        missing = sorted(_verify_targets() - _sync_targets())
        assert not missing, (
            "verify 는 검사하는데 sync 는 안 고치는 클레임:\n"
            + "\n".join(f"  {f}  {pat}" for f, pat in missing)
            + "\nscripts/doc/sync_doc_counts.sh 에 update_claim 을 추가할 것"
        )

    def test_sync_targets_all_exist_in_their_files(self):
        """sync 의 대상 문구가 실제로 그 파일에 있는가 — #916 의 직접 원인."""
        stale = []
        for f, pat in sorted(_sync_targets()):
            p = REPO_ROOT / f
            if not p.exists() or not re.search(pat, p.read_text()):
                stale.append((f, pat))
        assert not stale, "sync 대상이 이사갔거나 사라짐:\n" + "\n".join(f"  {f}  {pat}" for f, pat in stale)


#: `repo_copy` 가 심는 테스트 개수. 라이브 수치와 안 겹치는 작은 값이어야
#: "fixer 가 정말 다시 썼는가" 를 값으로 구분할 수 있다.
_SEEDED_TESTS = 3


@pytest.fixture
def repo_copy(tmp_path):
    """검사 대상 문서만 복사한 얕은 사본 + `.venv` 심볼릭 링크.

    round-trip 은 문서를 실제로 **쓰기** 때문에 레포에서 직접 돌리면 `-n auto`
    병렬 실행 중 다른 워커가 손상된 중간 상태를 읽는다. `_common.sh` 의 REPO_ROOT
    override 로 두 스크립트를 사본에 묶는다.
    """
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in (
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/STRATEGY.md",
        "config/CLAUDE.md",
        "config/rules.yaml",
        "nuri/api/CLAUDE.md",
        "nuri/collectors/CLAUDE.md",
        ".claude/rules/architecture.md",
        "nuri/core/db_migrations.py",
        "nuri/scheduler.py",
    ):
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, out)
    for pkg in ("nuri/collectors", "nuri/api/routes"):
        (dst / pkg).mkdir(parents=True, exist_ok=True)
        for f in (REPO_ROOT / pkg).glob("*.py"):
            shutil.copy2(f, dst / pkg / f.name)
    for sub in ("tests", "frontend/src", "frontend/e2e"):
        (dst / sub).mkdir(parents=True, exist_ok=True)
    # `tests/` 를 빈 채로 두면 `live_tests_be` 가 0 을 세고, 그러면
    # `sync_doc_counts.sh` 의 `if [ -n "$TESTS_BE" ]` 블록이 통째로 건너뛰어져
    # **테스트-수 규칙 3건이 이 fixture 에서 한 줄도 실행되지 않는다** — 그 규칙을
    # 겨눈 뮤테이션이 전부 무력했던 이유다 (#1084). 실제 파일을 심어 블록을 살린다.
    # 개수(_SEEDED_TESTS)는 아래 테스트가 복구된 값을 확인하는 데 쓴다.
    (dst / "tests" / "test_seeded.py").write_text(
        "".join(f"def test_seed_{i}():\n    pass\n\n" for i in range(_SEEDED_TESTS)),
        encoding="utf-8",
    )
    (dst / "pyproject.toml").write_text("")  # _common.sh 의 레포 루트 마커
    (dst / ".venv").symlink_to(REPO_ROOT / ".venv")
    return dst


def _run(script: Path, repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        env={**os.environ, "REPO_ROOT": str(repo)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _live_marker(text: str, pattern: str) -> str:
    """문서가 **지금** 말하는 문구를 뽑는다.

    수치를 리터럴로 박으면 마이그레이션·테스트 추가로 문서가 움직이는 순간 marker 가
    사라지고, 변조 `replace`/`re.sub` 가 아무것도 바꾸지 않아 **손상 없는 실행**이 된다.
    그러면 테스트는 통과하거나(공짜 초록) 게이트 회귀와 구분 안 되는 이유로 실패한다.
    실제로 `284 files` 가 낡아 이 파일의 이웃-숫자 테스트가 무증상으로 비어 있었다 (#1083).
    """
    m = re.search(pattern, text)
    assert m, f"문서에서 {pattern!r} 를 못 찾았다 — 이 테스트의 대조 대상이 사라졌다"
    return m.group(0)


class TestRoundTrip:
    def test_corrupted_count_is_repaired_and_then_verifies(self, repo_copy):
        """망가뜨림 → sync → verify 통과. 게이트와 fixer 가 같은 걸 본다는 증명."""
        readme = repo_copy / "README.md"
        original = readme.read_text()
        marker = _live_marker(original, r"SQLite WAL · \d+ tables")
        readme.write_text(original.replace(marker, "SQLite WAL · 88 tables"))
        assert "88 tables" in readme.read_text(), "손상이 안 걸렸다 — 아래 검증이 공짜로 통과한다"

        before = _run(VERIFY, repo_copy)
        assert "DRIFT" in before.stdout, f"손상시켰는데 verify 가 통과함:\n{before.stdout}"

        sync = _run(SYNC, repo_copy)
        assert sync.returncode == 0, sync.stdout + sync.stderr

        after = _run(VERIFY, repo_copy)
        assert "DRIFT" not in after.stdout, f"sync 후에도 drift 잔존:\n{after.stdout}"
        assert marker in readme.read_text()

    def test_the_test_count_rules_run_when_nothing_is_deselected(self, repo_copy):
        """수집 요약에 deselect 가 없어도 테스트-수 동기화가 돈다 (#1084).

        `live_tests_be` 는 pytest 요약을 긁는데, pytest 는 **deselect 가 있을 때만**
        `N/M tests collected` 를 찍는다. 0 건이면 `N tests collected` 다. 옛 정규식은
        앞 형식만 봐서 그 순간 빈 값을 돌려줬고, 호출부의 `if [ -n "$TESTS_BE" ]` 가
        테스트-수 claim 3건을 **통째로 건너뛰었다** — 종료코드 0 으로, 조용히.

        `verify_doc_counts.sh` 는 파일 수만 검사하고 테스트 수는 안 본다. 즉 fixer 가
        일을 멈춰도 그걸 잡을 게이트가 없다. 이 사본은 deselect 가 0 이므로 바로 그
        조건이고, 여기서 복구가 일어나야 정규식이 두 형식을 다 받는다는 증명이 된다.
        """
        strategy = repo_copy / "docs" / "STRATEGY.md"
        before = strategy.read_text()
        marker = _live_marker(before, r"[0-9,]+ tests, [0-9]+ files \(statement")

        corrupted = before.replace(marker, marker.replace(marker.split(" tests,")[0], "9,999", 1), 1)
        strategy.write_text(corrupted)
        assert "9,999 tests," in strategy.read_text(), "손상이 안 걸렸다 — 아래가 공짜로 통과한다"

        sync = _run(SYNC, repo_copy)
        assert sync.returncode == 0, sync.stdout + sync.stderr

        after = strategy.read_text()
        assert "9,999 tests," not in after, (
            "테스트 수가 복구되지 않았다 — deselect 0 인 수집 요약에서 블록이 건너뛰어졌다\n" + sync.stdout
        )
        assert f"{_SEEDED_TESTS} tests," in after, f"fixer 가 심은 개수({_SEEDED_TESTS})로 다시 쓰지 않았다"

    def test_sync_leaves_neighbouring_numbers_alone(self, repo_copy):
        """Backend **파일 수** 동기화가 같은 표의 다른 숫자를 건드리지 않는다.

        ⚠️ 여기 적혀 있던 Gotcha-Test Pair 주장(‘STRATEGY 패턴을 넓히면 Codecov 1% 가
        파괴되고, 옛 패턴으로 되돌리면 Frontend 행이 덮어써진다 — 둘 다 FAIL’)은
        **거짓이었다.** 2026-08-18 실측: 두 뮤테이션 다 이 테스트를 통과한다.

        이유는 `sync_doc_counts.sh` 의 **테스트 수** 블록 전체가
        `TESTS_BE=$(live_tests_be || echo "")` + `if [ -n "$TESTS_BE" ]` 로 감싸여
        있고, 얕은 사본은 `tests/` 가 비어 있어 그 값이 빈 문자열이 되기 때문이다.
        즉 `update_comma_number` 계열은 이 fixture 에서 **한 줄도 실행되지 않는다** —
        그 규칙을 겨눈 뮤테이션이 무력한 게 당연하다.

        그래서 이 테스트가 실제로 잠그는 것은 `update_claim live_test_files_be` 하나다:
        Backend 행의 파일 수를 고치면서 같은 줄의 ‘Codecov 1%’ 와 아래 Frontend 행의
        테스트 수를 건드리지 않는가. 테스트-수 규칙까지 덮으려면 fixture 가 실제 테스트
        파일을 심어야 한다 → #1084.
        """
        strategy = repo_copy / "docs" / "STRATEGY.md"
        before = strategy.read_text()
        frontend_row = _live_marker(before, r"Frontend tests \|[^|]*\| [0-9,]+ tests,")

        # Backend 행의 **파일 수**를 손상시킨다. 얕은 사본은 `tests/` 가 비어 있어 fixer 가
        # 실제로 다시 쓰는 값이 파일 수뿐이고, 테스트 수를 망가뜨리면 복구가 일어나지 않아
        # 복구 단언이 성립하지 않는다. 옛 버전은 낡은 `284 files` 를 겨눠 **손상 자체가 안
        # 걸린 채** 통과했다 — 게이트를 검사하는 테스트가 무증상으로 비어 있던 것이다.
        strategy.write_text(re.sub(r"([0-9,]+ tests, )\d+( files \(statement)", r"\g<1>777\g<2>", before, count=1))
        assert "777 files (statement" in strategy.read_text(), "손상이 안 걸렸다 — 아래 검증이 공짜로 통과한다"

        sync = _run(SYNC, repo_copy)
        assert sync.returncode == 0, sync.stdout + sync.stderr

        after = strategy.read_text()
        assert "Codecov 1% relative" in after, "Backend 행의 1% 가 파괴됨"
        # 이 테스트가 지키는 건 "이웃 숫자를 건드리지 않는가" 다 — Frontend 행의 **테스트
        # 수**가 옛 패턴이 백엔드 값으로 덮어쓰던 바로 그 자리다 (파일 수는 fixture 아티팩트로
        # 0 이 되므로 행 전체가 아니라 테스트 수까지만 본다).
        assert frontend_row in after, "Frontend 테스트 수가 덮어써짐"
        assert "777 files" not in after, "손상된 값이 복구되지 않음"
