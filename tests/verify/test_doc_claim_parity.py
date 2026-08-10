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
    def test_sync_does_more_than_print_its_banner(self):
        """#916 의 고장 모드 그대로 — 배너만 찍고 종료하면 FAIL.

        Gotcha-Test Pair: `current=$(grep ... || true)` 의 `|| true` 를 지우면
        set -e 가 첫 클레임에서 스크립트를 죽여 이 테스트가 FAIL.
        """
        r = subprocess.run(["bash", str(SYNC)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, check=False)
        processed = [ln for ln in r.stdout.splitlines() if "already in sync" in ln or "→" in ln]
        assert len(processed) >= 15, (
            f"클레임을 {len(processed)}건만 처리했다 — 중간에 죽었을 가능성:\n{r.stdout}{r.stderr}"
        )
        assert r.returncode == 0, f"clean tree 인데 exit {r.returncode}:\n{r.stdout}{r.stderr}"


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


class TestRoundTrip:
    def test_corrupted_count_is_repaired_and_then_verifies(self, repo_copy):
        """망가뜨림 → sync → verify 통과. 게이트와 fixer 가 같은 걸 본다는 증명."""
        readme = repo_copy / "README.md"
        original = readme.read_text()
        assert "SQLite WAL · 51 tables" in original
        readme.write_text(original.replace("SQLite WAL · 51 tables", "SQLite WAL · 88 tables"))

        before = _run(VERIFY, repo_copy)
        assert "DRIFT" in before.stdout, f"손상시켰는데 verify 가 통과함:\n{before.stdout}"

        sync = _run(SYNC, repo_copy)
        assert sync.returncode == 0, sync.stdout + sync.stderr

        after = _run(VERIFY, repo_copy)
        assert "DRIFT" not in after.stdout, f"sync 후에도 drift 잔존:\n{after.stdout}"
        assert "SQLite WAL · 51 tables" in readme.read_text()

    def test_sync_leaves_neighbouring_numbers_alone(self, repo_copy):
        """Backend 행 동기화가 같은 표의 다른 숫자를 건드리지 않는다.

        Gotcha-Test Pair: STRATEGY 패턴을 'Backend tests.*[0-9,]+ tests' 로 넓히면
        첫 숫자 런인 "Codecov 1%" 가 파괴되고, 옛 패턴 '[0-9,]+ tests, [0-9]+ files \\|'
        로 되돌리면 바로 아래 Frontend 행이 백엔드 수치로 덮어써진다 — 둘 다 FAIL.
        """
        strategy = repo_copy / "docs" / "STRATEGY.md"
        strategy.write_text(
            re.sub(
                r"[0-9,]+ tests, 284 files \(statement",
                "9,999 tests, 284 files (statement",
                strategy.read_text(),
                count=1,
            )
        )

        sync = _run(SYNC, repo_copy)
        assert sync.returncode == 0, sync.stdout + sync.stderr

        after = strategy.read_text()
        assert "Codecov 1% relative" in after, "Backend 행의 1% 가 파괴됨"
        # 사본의 tests/ 는 비어 있어 **파일 수**는 0 으로 동기화된다(fixture 아티팩트).
        # 이 테스트가 지키는 건 그게 아니라 "이웃 숫자를 건드리지 않는가" 이므로
        # Frontend 행의 **테스트 수**(1449)만 본다 — 옛 패턴이 덮어썼던 바로 그 값.
        assert re.search(r"Frontend tests \|[^|]*\| 1449 tests,", after), "Frontend 테스트 수가 덮어써짐"
        assert "9,999" not in after, "손상된 값이 복구되지 않음"
