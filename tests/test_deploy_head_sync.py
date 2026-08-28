"""배포 검증의 HEAD 비교를 **실행해서** 잠근다 (Gotcha-Test Pair, #1277).

## 무엇이 잘못됐었나

`deploy_to_mini.sh` step 7 이 `git log -1 --oneline` **문자열**을 비교했다. 그 축약 SHA
길이는 저장소마다 다르다 — git 의 auto-abbrev 가 오브젝트 수에서 파생되기 때문이다.
2026-08-29 실측: 같은 커밋이 MBP 에서 8자, Mac mini 에서 7자로 찍혀 **완벽히 동기화된
배포마다** "git HEAD 불일치" 경고가 났다 (그날 두 번의 배포에서 모두 재현).

이건 dead gate 가 아니라 **false-red** 다. 배포 검증은 상주 데몬이 구코드를 들고 도는
사고(#1024, 7일 잠복)를 잡는 마지막 관문인데, 매번 뜨는 경고는 진짜 불일치가 났을 때
그 한 줄을 무시하게 만든다.

## 왜 grep 이 아니라 실행인가

`tests/test_pre_push_hook.py` · `tests/test_hook_guard_execution.py` 의 전례 그대로다.
"축약을 안 쓴다" 를 소스에서 grep 하면 *다른 방식으로 축약하는* 회귀를 놓친다. 여기서는
**축약 길이가 실제로 다른 두 저장소**를 만들어 스크립트를 돌리고 종료 코드만 믿는다.

세 축:
- 같은 커밋 + 다른 `core.abbrev` → **일치 판정** (결함 그 자체)
- 다른 커밋 → **불일치 판정** (항상 초록인 가짜 게이트가 아님)
- 카나리아: 그 두 저장소에서 `--oneline` 출력이 실제로 **다름** — 이게 없으면 첫 축이
  공허하게 통과할 수 있다 (abbrev 설정이 안 먹었을 경우)
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "scripts" / "deploy" / "verify_head_sync.sh"
DEPLOY = REPO_ROOT / "scripts" / "deploy" / "deploy_to_mini.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")


def _git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0900",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0900",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(cwd),
    }
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _make_repo(path: Path, *, abbrev: int, content: str = "one") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "core.abbrev", str(abbrev))
    (path / "f.txt").write_text(content, encoding="utf-8")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "initial commit for head-sync test")
    return path


def _fake_ssh(tmp_path: Path) -> Path:
    """`ssh <host> <cmd>` 흉내 — 호스트를 무시하고 명령을 로컬 셸로 실행한다.

    스크립트가 원격에 보내는 문자열(`cd <path> && git ...`)을 그대로 받으므로,
    **실제 배포가 타는 코드 경로**를 그대로 돌린다.
    """
    p = tmp_path / "fake_ssh.sh"
    p.write_text('#!/usr/bin/env bash\nshift\nexec bash -c "$*"\n', encoding="utf-8")
    p.chmod(0o755)
    return p


def _broken_ssh(tmp_path: Path, *, rc: int = 255, stdout: str = "") -> Path:
    """전송 실패 흉내 — 실제 ssh 는 도달 불가 시 255 를 낸다."""
    p = tmp_path / f"broken_ssh_{rc}_{len(stdout)}.sh"
    p.write_text(f"#!/usr/bin/env bash\nprintf %s {stdout!r}\nexit {rc}\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def _garbage_ssh(tmp_path: Path) -> Path:
    """rc 0 인데 SHA 가 아닌 것을 뱉는 경우 (배너·경고문 등)."""
    p = tmp_path / "garbage_ssh.sh"
    p.write_text(
        '#!/usr/bin/env bash\nprintf "Warning: Permanently added host\\nnot-a-sha\\n"\nexit 0\n',
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def _run_verifier(local_repo: Path, ssh: Path, remote_repo: Path):
    return subprocess.run(
        ["bash", str(VERIFIER), str(ssh), "ignored-host", str(remote_repo)],
        cwd=local_repo,
        capture_output=True,
        text=True,
    )


class TestHeadSyncIsAbbreviationIndependent:
    def test_same_commit_different_abbrev_reports_match(self, tmp_path):
        """결함 그 자체 — 같은 커밋인데 축약 길이만 달라 불일치로 오판했다.

        Mutation lock: `verify_head_sync.sh` 를 `git log -1 --oneline` 비교로 되돌리면 FAIL.
        """
        a = _make_repo(tmp_path / "local", abbrev=7)
        b = _make_repo(tmp_path / "remote", abbrev=12)
        # 같은 내용·같은 author/committer·같은 날짜 → 같은 커밋 SHA
        assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD"), "전제 실패: 같은 커밋이 아니다"

        r = _run_verifier(a, _fake_ssh(tmp_path), b)
        assert r.returncode == 0, f"동기화된 배포를 불일치로 판정했다\nstdout={r.stdout}\nstderr={r.stderr}"

    def test_abbrev_settings_actually_differ(self, tmp_path):
        """카나리아 — 위 테스트가 공허하지 않은지 확인한다.

        `core.abbrev` 가 안 먹으면 두 저장소의 `--oneline` 이 같아져, 축약을 비교하도록
        되돌려도 첫 테스트가 **통과**한다. 그러면 잠금이 아니라 장식이다.
        """
        a = _make_repo(tmp_path / "local", abbrev=7)
        b = _make_repo(tmp_path / "remote", abbrev=12)
        assert _git(a, "log", "-1", "--oneline") != _git(b, "log", "-1", "--oneline"), (
            "축약 길이가 같아 이 테스트 환경은 #1277 을 재현하지 못한다"
        )

    def test_genuinely_different_commits_report_mismatch(self, tmp_path):
        """항상 초록인 가짜 게이트가 아님 — 진짜 불일치는 잡아야 한다.

        Mutation lock: 판정을 `true` 로 바꾸면 FAIL.
        """
        a = _make_repo(tmp_path / "local", abbrev=7, content="one")
        b = _make_repo(tmp_path / "remote", abbrev=7, content="two")
        assert _git(a, "rev-parse", "HEAD") != _git(b, "rev-parse", "HEAD")

        r = _run_verifier(a, _fake_ssh(tmp_path), b)
        assert r.returncode == 1, f"서로 다른 커밋을 일치로 판정했다\nstdout={r.stdout}"

    def test_output_carries_both_shas_and_labels(self, tmp_path):
        """호출자(deploy 스크립트)가 표시용 라벨을 3·4행에서 읽는다 — 그 계약을 잠근다."""
        a = _make_repo(tmp_path / "local", abbrev=7)
        b = _make_repo(tmp_path / "remote", abbrev=12)
        r = _run_verifier(a, _fake_ssh(tmp_path), b)
        lines = r.stdout.strip().splitlines()
        assert len(lines) == 4, f"4행이어야 한다: {lines}"
        assert len(lines[0]) == 40 and len(lines[1]) == 40, "1·2행은 전체 SHA(40자)여야 한다"
        assert "initial commit" in lines[2] and "initial commit" in lines[3], "3·4행은 표시용 라벨"


class TestFailureIsNotDisguisedAsMismatch:
    """**검증 실패**(rc 2)와 **검증 결과 불일치**(rc 1)를 나눈다 (codex 리뷰 P1).

    둘을 뭉뚱그리면 "검사 실패" 가 "검사 결과" 로 둔갑한다 — 이 레포가 이미 겪은 형태다
    (#910/#911: rc=127 이 실패와 구분되지 않아 게이트가 3.5개월 no-op).
    배포 쪽에서는 더 나쁘다: 마지막 안전 게이트가 **안 돌았는데** "deploy 완료" 가 찍힌다.
    """

    def test_transport_failure_is_undetermined_not_mismatch(self, tmp_path):
        """Mutation lock: `undetermined` 를 지우고 실패를 흘리면 rc 가 1 이 되어 FAIL."""
        a = _make_repo(tmp_path / "local", abbrev=7)
        r = _run_verifier(a, _broken_ssh(tmp_path, rc=255), tmp_path / "nowhere")
        assert r.returncode == 2, f"전송 실패를 rc {r.returncode} 로 보고했다 (2 여야 함)\n{r.stderr}"
        assert r.stderr.strip(), "판정 불가인데 이유를 남기지 않았다"

    def test_remote_exiting_one_is_still_undetermined(self, tmp_path):
        """가장 위험한 축 — 원격이 rc 1 로 죽으면 '불일치' 와 **정확히 같은 코드**다.

        스크립트가 하위 rc 를 그대로 흘리면(예: `set -e`) 여기서 1 이 나와 배포는
        '경고' 만 찍고 계속 간다. 반드시 2 로 승격돼야 한다.
        """
        a = _make_repo(tmp_path / "local", abbrev=7)
        r = _run_verifier(a, _broken_ssh(tmp_path, rc=1), tmp_path / "nowhere")
        assert r.returncode == 2, f"원격 rc 1 을 '불일치'({r.returncode}) 로 흘렸다"

    def test_non_sha_output_is_undetermined(self, tmp_path):
        """rc 0 인데 SHA 가 아닌 응답 — 그걸 믿으면 **틀린 이유**(불일치)를 보고한다."""
        a = _make_repo(tmp_path / "local", abbrev=7)
        r = _run_verifier(a, _garbage_ssh(tmp_path), tmp_path / "nowhere")
        assert r.returncode == 2, f"SHA 가 아닌 응답을 rc {r.returncode} 로 판정했다"

    def test_real_mismatch_still_reports_one(self, tmp_path):
        """대조군 — 2 로 다 밀어버리면 진짜 불일치를 놓친다."""
        a = _make_repo(tmp_path / "local", abbrev=7, content="one")
        b = _make_repo(tmp_path / "remote", abbrev=7, content="two")
        r = _run_verifier(a, _fake_ssh(tmp_path), b)
        assert r.returncode == 1, f"진짜 불일치가 {r.returncode} 로 나왔다"


class TestDeployScriptUsesTheVerifier:
    """배선 — 검증기가 있어도 배포가 안 부르면 소용없다 (#1180 계열 wiring 축).

    ⚠️ 여기는 **구조 검사**다. step 7 만 떼어 실행하려면 배포 스크립트에 테스트 전용
    모드를 넣어야 하는데, 프로덕션 배포 경로의 제어 흐름을 테스트를 위해 바꾸는 건
    비용이 더 크다고 판단했다. 대신 판정 로직 자체는 위에서 **실행으로** 잠갔다.
    """

    def test_verifier_exists_and_is_executable(self):
        assert VERIFIER.exists(), "검증기 파일이 없다"
        assert VERIFIER.stat().st_mode & 0o111, "실행 권한이 없다 — 배포가 부를 수 없다"

    @staticmethod
    def _remote_abbrev_lines(src: str) -> list[str]:
        """**원격** HEAD 를 축약 문자열로 가져오는 줄 — #1277 의 회귀 형태.

        `--oneline` 자체는 금지하지 않는다. 55행의 `echo "  local HEAD: ..."` 처럼
        표시용은 정상이고, 그걸 막으면 오탐이 된다. 문제는 그 축약을 **원격에서 받아
        비교면에 올리는 것**이라, SSH 호출과 축약이 같은 줄에 있는 경우만 본다.
        """
        return [ln for ln in src.splitlines() if "${SSH}" in ln and ("--oneline" in ln or "--abbrev" in ln)]

    def test_deploy_delegates_instead_of_comparing_inline(self):
        src = DEPLOY.read_text(encoding="utf-8")
        assert "verify_head_sync.sh" in src, "배포가 검증기를 부르지 않는다"
        offenders = self._remote_abbrev_lines(src)
        assert not offenders, f"원격 HEAD 를 축약으로 받고 있다 (#1277 회귀): {offenders}"

    def test_deploy_aborts_when_verification_is_undetermined(self):
        """rc 2 는 경고가 아니라 **중단**이어야 한다 (codex P1).

        `if cmd; then ... else warn` 로 감싸면 모든 비정상 종료가 경고로 강등된다 —
        그 형태가 소스에 없는지, 그리고 rc 갈래에 `fail` 이 있는지 본다.
        """
        src = DEPLOY.read_text(encoding="utf-8")
        assert "if HEAD_OUT=$(" not in src, "if 래핑이 되살아났다 — 모든 실패가 경고로 강등된다"
        assert "HEAD_RC" in src, "rc 를 받지 않는다"
        # rc 갈래(case) 안에 중단 경로가 있어야 한다.
        case_block = src.split('case "${HEAD_RC}"', 1)
        assert len(case_block) == 2, "rc 갈래(case)가 없다"
        branch = case_block[1].split("esac", 1)[0]
        assert "fail " in branch, "판정 불가에서 배포를 중단하지 않는다"
        assert "warn " in branch and "ok " in branch, "일치/불일치 갈래가 없다"

    def test_the_sweep_has_eyes(self):
        """카나리아 — sweep 이 조용히 아무것도 안 보는 상태로 썩지 않게.

        위 predicate 가 **옛 코드를 실제로 잡는지**, 그리고 표시용 줄은 **안 잡는지**
        둘 다 확인한다. 한쪽만 보면 "전부 통과" 와 "전부 차단" 을 구분 못 한다.
        """
        old_code = 'REMOTE_HEAD=$("${SSH}" "${REMOTE}" "cd ${REMOTE_PATH} && git log -1 --oneline")'
        display_only = 'echo "  local HEAD: $(git log -1 --oneline)"'
        assert self._remote_abbrev_lines(old_code) == [old_code], "옛 결함을 못 잡는다"
        assert self._remote_abbrev_lines(display_only) == [], "표시용 줄을 오탐한다"
