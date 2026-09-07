"""`build_frontend.sh` 를 **실행해서** 본다 — 판정 · npm ci 선행 · 백업/복원 · dashboard 재기동 (#1462).

grep 이 아니라 실행인 이유는 `test_autopull_restarts_daemons.py` 와 같다: 재기동 hook 이 주석
안에만 있어도 문자열 테스트는 통과했다. 여기서는 stub PATH(npm · launchctl · curl)를 깔고
스크립트를 돌려 **무엇이 호출됐고 디스크에 무엇이 남았는지** 를 본다.

npm stub 은 Next 의 `cleanDistDir` 를 흉내낸다 — `run build` 가 **먼저 .next 를 비우고** 성공
시에만 BUILD_ID 를 쓴다 (next 16.3.3 `dist/build/index.js:623`). 실패 픽스처가 이 순서를 안
지키면 백업/복원 분기는 영영 안 밟힌다.

커밋 시각은 `GIT_COMMITTER_DATE` 로 고정한다 — 같은 초에 찍힌 두 커밋은 `%ct` 로 순서를 못
가르고, 그러면 "lock 이 빌드보다 새롭다" 가 실행 속도에 따라 참·거짓이 갈린다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "build_frontend.sh"
DASHBOARD = "com.nuri-quant.dashboard"

T0 = 1_700_000_000  # 고정 epoch — 커밋 시각의 기준점


def _git(cwd: Path, *args: str, when: int | None = None) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{when} +0000"
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture()
def world(tmp_path: Path):
    """frontend/ 를 가진 로컬 레포 + npm/launchctl/curl stub PATH."""
    work, binz, calls = tmp_path / "work", tmp_path / "bin", tmp_path / "calls.txt"
    binz.mkdir()

    (binz / "npm").write_text(
        "#!/bin/sh\n"
        f'echo "npm $*" >> "{calls}"\n'
        'if [ "$1" = "ci" ]; then exit "${NPM_CI_RC:-0}"; fi\n'
        'if [ "$1" = "run" ] && [ "$2" = "build" ]; then\n'
        "    rm -rf .next; mkdir -p .next/cache\n"  # cleanDistDir — 실패해도 이미 비워진 뒤다
        '    [ "${NPM_STUB_RC:-0}" = "0" ] || exit "$NPM_STUB_RC"\n'
        '    [ "${NPM_STUB_NO_BUILD_ID:-0}" = "1" ] || echo "stub-build-$$" > .next/BUILD_ID\n'
        "fi\n"
        "exit 0\n"
    )
    (binz / "launchctl").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "list" ]; then [ "${{LAUNCHCTL_HAS_DASHBOARD:-1}}" = "1" ] && echo "1 0 {DASHBOARD}"; exit 0; fi\n'
        f'echo "launchctl $*" >> "{calls}"\nexit 0\n'
    )
    (binz / "curl").write_text(f'#!/bin/sh\necho "curl $*" >> "{calls}"\nexit "${{CURL_STUB_RC:-0}}"\n')
    for f in ("npm", "launchctl", "curl"):
        (binz / f).chmod(0o755)

    work.mkdir()
    _git(work, "init", "-b", "main")
    fe = work / "frontend"
    (fe / "app").mkdir(parents=True)
    (fe / "package-lock.json").write_text("{}\n")
    (fe / "app" / "page.tsx").write_text("export default () => null;\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed", when=T0)

    def commit(rel: str, body: str, *, when: int) -> None:
        p = work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        _git(work, "add", "-A")
        _git(work, "commit", "-m", f"touch {rel}", when=when)

    def set_build(mtime: int, content: str = "old-build") -> Path:
        d = fe / ".next"
        d.mkdir(exist_ok=True)
        bid = d / "BUILD_ID"
        bid.write_text(content)
        os.utime(bid, (mtime, mtime))
        return bid

    def run(**env_extra: str):
        env = {
            **os.environ,
            "PATH": f"{binz}:{os.environ['PATH']}",
            "NURI_REPO": str(work),
            "DASH_WAIT_SECS": "1",
            **env_extra,
        }
        proc = subprocess.run(["bash", str(SCRIPT)], env=env, check=False, capture_output=True, text=True, timeout=60)
        return proc, (calls.read_text() if calls.exists() else "")

    return type(
        "W",
        (),
        {
            "work": work,
            "fe": fe,
            "commit": staticmethod(commit),
            "set_build": staticmethod(set_build),
            "run": staticmethod(run),
        },
    )


class TestVerdict:
    def test_up_to_date_build_does_nothing_and_says_nothing(self, world):
        """autopull 이 5분마다 부른다 — 최신이면 npm 도 로그도 없어야 한다."""
        world.set_build(T0 + 100)
        proc, calls = world.run()
        assert proc.returncode == 0
        assert proc.stdout == "" and "npm" not in calls, f"최신인데 움직였다:\nstdout={proc.stdout}\ncalls={calls}"

    def test_stale_build_is_rebuilt_and_the_dashboard_bounced(self, world):
        bid = world.set_build(T0 - 100)
        proc, calls = world.run()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "npm run build" in calls
        assert f"launchctl kickstart -k gui/{os.getuid()}/{DASHBOARD}" in calls, (
            f"대시보드를 재기동하지 않았다:\n{calls}"
        )
        assert bid.read_text().startswith("stub-build-"), "BUILD_ID 가 새 빌드가 아니다"
        assert not (world.fe / ".next.bak").exists(), "성공했는데 백업이 남았다 — 커밋마다 1.3GB 씩 쌓인다"

    def test_a_build_from_the_same_second_as_the_commit_is_current(self, world):
        """경계 — 커밋 시각 == 빌드 시각이면 최신이다 (`-le`). `-lt` 로 조이면 매 주기 재빌드한다."""
        world.set_build(T0)
        proc, calls = world.run()
        assert proc.returncode == 0 and proc.stdout == "" and "npm" not in calls, (
            f"같은 초의 빌드를 낡았다고 봤다 — 5분마다 대시보드를 흔든다:\n{calls}"
        )

    def test_missing_build_counts_as_stale(self, world):
        """BUILD_ID 가 없으면 0 이라 어떤 커밋보다 오래됐다 — 첫 배포·지워진 빌드 모두 여기로."""
        assert not (world.fe / ".next").exists()
        proc, calls = world.run()
        assert proc.returncode == 0 and "npm run build" in calls

    def test_a_repo_with_no_frontend_commits_is_left_alone(self, tmp_path, world):
        """frontend/ 커밋이 없으면 LAST=0 — 빌드가 없어도(0) 0>0 은 거짓이라 아무것도 안 한다.

        autopull 테스트 월드처럼 frontend/ 자체가 없는 레포에서 매 주기 npm 을 부르면 안 된다.
        """
        bare = tmp_path / "bare"
        bare.mkdir()
        _git(bare, "init", "-b", "main")
        (bare / "seed.txt").write_text("x\n")
        _git(bare, "add", "-A")
        _git(bare, "commit", "-m", "seed", when=T0)
        proc, calls = world.run(NURI_REPO=str(bare))
        assert proc.returncode == 0 and proc.stdout == "" and "npm" not in calls


class TestNpmCiGate:
    def test_lock_newer_than_build_runs_npm_ci_before_build(self, world):
        world.commit("frontend/package-lock.json", '{"bumped": 1}\n', when=T0 + 300)
        world.set_build(T0 + 100)
        proc, calls = world.run()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "npm ci" in calls and calls.index("npm ci") < calls.index("npm run build"), (
            f"npm ci 가 빌드보다 앞에 오지 않았다:\n{calls}"
        )

    def test_lock_older_than_build_skips_npm_ci(self, world):
        """소스만 바뀐 커밋 — 의존성 재설치는 수십 초라 필요할 때만."""
        world.commit("frontend/app/page.tsx", "export default () => 1;\n", when=T0 + 200)
        world.set_build(T0 + 100)  # lock(T0) 보다는 새롭고 page(T0+200) 보다는 오래됐다
        proc, calls = world.run()
        assert proc.returncode == 0 and "npm run build" in calls
        assert "npm ci" not in calls, f"lock 이 안 바뀌었는데 npm ci 를 돌렸다:\n{calls}"

    def test_lock_from_the_same_second_as_the_build_does_not_reinstall(self, world):
        """경계 — lock 커밋 시각 == 빌드 시각이면 그 lock 으로 만든 빌드다 (`-gt`). `-ge` 면 매번 npm ci."""
        world.commit("frontend/app/page.tsx", "export default () => 1;\n", when=T0 + 200)
        world.set_build(T0)  # lock 커밋(T0)과 같은 초, page(T0+200) 보다는 오래됐다 → 재빌드만
        proc, calls = world.run()
        assert proc.returncode == 0 and "npm run build" in calls
        assert "npm ci" not in calls, f"lock 과 같은 초의 빌드인데 재설치했다:\n{calls}"

    def test_failed_npm_ci_leaves_the_build_untouched(self, world):
        """의존성이 반쯤 깨진 상태에서 빌드하면 실패 뒤 복원까지 두 번 흔든다 — 아예 안 간다."""
        world.commit("frontend/package-lock.json", '{"bumped": 1}\n', when=T0 + 300)
        bid = world.set_build(T0 + 100)
        proc, calls = world.run(NPM_CI_RC="1")
        assert proc.returncode == 1
        assert "npm run build" not in calls and "kickstart" not in calls
        assert bid.read_text() == "old-build"


class TestRollback:
    def test_failed_build_restores_the_previous_build(self, world):
        """Next 는 빌드 시작 때 .next 를 비운다 — 백업이 없으면 실패가 빈 디렉터리를 남긴다."""
        bid = world.set_build(T0 - 100)
        proc, calls = world.run(NPM_STUB_RC="1")
        assert proc.returncode == 1
        assert "npm run build" in calls, "빌드를 시도조차 안 했다"
        assert bid.read_text() == "old-build", "이전 빌드가 복원되지 않았다 — 재기동·재부팅 때 빈 대시보드가 뜬다"
        assert "kickstart" not in calls, "실패했는데 대시보드를 재기동했다"
        assert not (world.fe / ".next.bak").exists()
        assert "복원" in proc.stdout

    def test_exit_zero_without_a_build_id_is_a_failure(self, world):
        """rc 0 이어도 BUILD_ID 가 없으면 서빙할 게 없다 — 성공으로 치면 빈 .next 로 대시보드를 재기동한다."""
        bid = world.set_build(T0 - 100)
        proc, calls = world.run(NPM_STUB_NO_BUILD_ID="1")
        assert proc.returncode == 1
        assert bid.read_text() == "old-build", "이전 빌드가 복원되지 않았다"
        assert "kickstart" not in calls

    def test_a_previous_run_that_died_mid_build_still_has_a_rollback(self, world):
        """재부팅 등으로 빌드 도중 죽으면 백업은 있고 .next 는 반쪽이다 — 그 백업이 롤백 대상이다."""
        bak = world.fe / ".next.bak"
        bak.mkdir(parents=True)
        (bak / "BUILD_ID").write_text("build-before-crash")
        (world.fe / ".next" / "cache").mkdir(parents=True)  # BUILD_ID 없는 반쪽
        proc, _ = world.run(NPM_STUB_RC="1")
        assert proc.returncode == 1
        assert (world.fe / ".next" / "BUILD_ID").read_text() == "build-before-crash"
        assert not bak.exists()


class TestDashboard:
    def test_dashboard_not_installed_skips_the_restart(self, world):
        """dev 머신에는 launchd 등재가 없다 — 빌드만 하고 끝낸다."""
        world.set_build(T0 - 100)
        proc, calls = world.run(LAUNCHCTL_HAS_DASHBOARD="0")
        assert proc.returncode == 0 and "npm run build" in calls
        assert "kickstart" not in calls
        assert "skip restart" in proc.stdout

    def test_unresponsive_dashboard_after_restart_is_a_failure(self, world):
        """빌드는 됐지만 :3000 이 안 뜨면 성공이 아니다 — 수동 경로의 7단계와 같은 기준."""
        world.set_build(T0 - 100)
        proc, calls = world.run(CURL_STUB_RC="22")
        assert proc.returncode == 1
        assert "kickstart" in calls and "curl" in calls
        assert "무응답" in proc.stdout


class TestNonInteractiveEnvironment:
    def test_npm_falls_back_to_homebrew_when_not_on_path(self):
        """launchd 는 로그인 셸 PATH 를 안 준다 — uv 와 같은 이유 (`test_uv_is_called_by_absolute_path_not_bare_name`)."""
        src = SCRIPT.read_text(encoding="utf-8")
        # homebrew 는 **뒤에** 붙는 폴백이다. 앞에 붙이면 로그인 PATH(dev 의 fnm)와 stub 을 가린다 —
        # 첫 판에서 이 파일의 실행 테스트 전부가 stub 대신 진짜 npm 을 돌렸다. 순서의 동작 잠금은
        # 위 실행 테스트들 자체다(stub 이 호출됐다는 것이 곧 증거). 여기는 문구만 본다.
        assert "command -v npm" in src and "/opt/homebrew/bin/npm" in src
        assert 'export PATH="$PATH:/opt/homebrew/bin"' in src
        assert 'export PATH="/opt/homebrew/bin:$PATH"' not in src, "homebrew 가 PATH 앞으로 갔다 — stub·fnm 을 가린다"

    def test_mtime_is_portable_to_linux(self):
        """CI(ubuntu) 가 이 파일의 실행 테스트를 돌린다 — `stat -f` 만 있으면 거기서 전부 0 이 된다."""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "stat -f %m" in src and "stat -c %Y" in src
