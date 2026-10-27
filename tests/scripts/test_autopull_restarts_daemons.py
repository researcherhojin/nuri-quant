"""autopull 이 코드를 당긴 뒤 **상주 데몬을 실제로 재기동하는지** — 스크립트를 실행해서 본다.

**왜 grep 이 아니라 실행인가**: `scripts/deploy/autopull_receiver.sh` 의 재기동 hook 은
"24/7 서비스가 등록되어 있지 않아 no-op" 이라는 주석과 함께 **주석 처리된 예시**로만
존재했다. 문자열만 보는 테스트였다면 `launchctl kickstart` 가 주석 안에 있어도 통과했다.
`test_deploy_bounces_resident_services.py` 도 같은 함정을 밟은 적이 있다(성공 메시지 안의
URL 때문에 curl 을 지워도 통과) — 그래서 여기선 **stub PATH 를 깔고 스크립트를 돌려**
`launchctl` 이 진짜로 호출됐는지 기록을 본다.

**막으려는 사고** (2026-08-10 프로덕션 실측): 수동 경로(`deploy_to_mini.sh`)는 #940 이후
상주 서비스를 bounce 하는데 **자동 경로(autopull)는 안 했다**. 사용자는 머지마다 수동
배포를 돌리지 않으므로 데몬이 7일간 구코드로 돌았고, #1017 이 `nuri/core/rules.py` 에
심볼을 추가한 날 밤 `premarket_brief` 가 ImportError 로 죽어 산출물 3개가 사라졌다.
APScheduler 는 `executed successfully` 를 찍었다 — 실패 신호가 아예 없었다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPULL = REPO_ROOT / "scripts" / "deploy" / "autopull_receiver.sh"

RESIDENT = ["com.nuri-quant.scheduler", "com.nuri-quant.api", "com.nuri-quant.discord-bot"]
DASHBOARD = "com.nuri-quant.dashboard"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


@pytest.fixture()
def world(tmp_path: Path):
    """origin 이 한 커밋 앞선 로컬 레포 + launchctl/uv stub PATH."""
    origin, work, binz = tmp_path / "origin", tmp_path / "work", tmp_path / "bin"
    binz.mkdir()
    calls = tmp_path / "calls.txt"

    # launchctl stub — `list` 는 서비스가 설치된 것처럼 답하고, 나머지는 인자를 기록.
    (binz / "launchctl").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "list" ]; then for l in {" ".join([*RESIDENT, DASHBOARD])}; do echo "1 0 $l"; done; exit 0; fi\n'
        f'echo "launchctl $*" >> "{calls}"\nexit 0\n'
    )
    # UV_STUB_RC 로 sync 실패를 흉내낸다 (기본 0 — 기존 테스트 무영향).
    (binz / "uv").write_text(f'#!/bin/sh\necho "uv $*" >> "{calls}"\nexit ${{UV_STUB_RC:-0}}\n')
    # npm stub — build_frontend.sh (#1462) 가 부른다. Next 처럼 .next 를 비운 뒤 성공 시만 BUILD_ID.
    (binz / "npm").write_text(
        "#!/bin/sh\n"
        f'echo "npm $*" >> "{calls}"\n'
        'if [ "$1" = "run" ] && [ "$2" = "build" ]; then\n'
        "    rm -rf .next; mkdir -p .next/cache\n"
        '    [ "${NPM_STUB_RC:-0}" = "0" ] || exit "$NPM_STUB_RC"\n'
        '    echo "stub-build-$$" > .next/BUILD_ID\n'
        "fi\n"
        "exit 0\n"
    )
    # curl stub — GitHub runs API 에는 CI 판정 JSON 을, 그 밖(대시보드 헬스체크)에는 성공만 돌려준다.
    # 기본 판정은 success (기존 테스트 무영향). CI_STUB_JSON 으로 본문을, CI_STUB_RC 로 본문 **뒤** 종료 코드를 정한다 (#1808).
    green = (
        '{"workflow_runs": [{"event": "push", "head_branch": "main", "status": "completed", "conclusion": "success"}]}'
    )
    (binz / "curl").write_text(
        "#!/bin/sh\n"
        f'echo "curl $*" >> "{calls}"\n'
        'case "$*" in *api.github.com*)\n'
        f"    if [ -n \"$CI_STUB_JSON\" ]; then printf '%s' \"$CI_STUB_JSON\"; else printf '%s' '{green}'; fi\n"
        '    exit "${CI_STUB_RC:-0}" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    for f in ("launchctl", "uv", "npm", "curl"):
        (binz / f).chmod(0o755)

    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))
    (work / "seed.txt").write_text("seed\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "-q", "origin", "main")

    def land(files: dict[str, str]) -> None:
        """origin/main 에 커밋 하나를 올린다 (autopull 이 당겨갈 것)."""
        side = tmp_path / "side"
        if not side.exists():
            _git(tmp_path, "clone", "-q", str(origin), str(side))
        for rel, body in files.items():
            p = side / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        _git(side, "add", "-A")
        _git(side, "commit", "-m", "change")
        _git(side, "push", "-q", "origin", "main")

    def run(**env_extra: str) -> str:
        env = {
            **os.environ,
            "PATH": f"{binz}:{os.environ['PATH']}",
            "NURI_REPO": str(work),
            "HOME": str(tmp_path),
            "DASH_WAIT_SECS": "1",
            **env_extra,
        }
        subprocess.run(["bash", str(AUTOPULL)], env=env, check=False, capture_output=True, timeout=120)
        return calls.read_text() if calls.exists() else ""

    def autopull_log() -> str:
        p = tmp_path / "Library" / "Logs" / "nuri-quant-autopull.log"
        return p.read_text() if p.exists() else ""

    return type(
        "W",
        (),
        {
            "land": staticmethod(land),
            "run": staticmethod(run),
            "work": work,
            "origin": origin,
            "autopull_log": staticmethod(autopull_log),
        },
    )


class TestAutopullBouncesDaemons:
    def test_python_change_restarts_every_resident_service(self, world):
        world.land({"nuri/core/rules.py": "VIX_MAX_AGE_BUSINESS_DAYS = 2\n"})
        out = world.run()
        assert "Already up to date" not in out
        for label in RESIDENT:
            assert re.search(rf"launchctl kickstart -k \S*{re.escape(label)}", out), (
                f"{label} 을 재기동하지 않았다 — 데몬이 구코드를 들고 계속 돈다.\n기록:\n{out}"
            )

    def test_it_actually_pulled(self, world):
        """카나리아 — ff-merge 가 실패했는데 '재기동 안 함' 을 정상으로 읽으면 안 된다."""
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run()
        assert (world.work / "nuri" / "core" / "rules.py").exists(), "ff-merge 가 안 됐다 — 이 픽스처가 고장난 것"

    def test_docs_only_change_does_not_restart(self, world):
        """문서만 바뀌면 재기동하지 않는다 — 5분마다 데몬을 흔들면 잡이 죽는다."""
        world.land({"docs/whatever.md": "# hi\n"})
        out = world.run()
        assert "kickstart" not in out, f"문서 변경으로 재기동했다:\n{out}"

    def test_dep_change_syncs_venv_before_restarting(self, world):
        """`uv sync` 는 재기동 **앞**에 와야 한다 — 뒤면 새 프로세스가 옛 venv 로 뜬다."""
        world.land({"uv.lock": "# bumped\n"})
        out = world.run()
        assert "uv sync" in out, f"deps 가 바뀌었는데 sync 하지 않았다:\n{out}"
        assert out.index("uv sync") < out.index("kickstart"), f"sync 가 재기동보다 뒤에 있다:\n{out}"

    def test_dep_change_syncs_with_locked(self, world):
        """`uv sync` 는 `--locked` 로 불러야 한다 (#1350).

        플래그가 없으면 sync 가 tracked `uv.lock` 을 **다시 쓴다**. 그러면 워킹트리가
        dirty 가 되고, 다음 5분 주기가 `ABORT: uncommitted local changes` 에 걸려
        **exit 0** 으로 멈춘다 — 실패로도 안 보이는 영구 배포 동결. `--frozen` 도
        오답이다(트리는 지키지만 구 버전을 무신호로 설치). 위
        `test_dep_change_syncs_venv_before_restarting` 의 `"uv sync" in out` 은
        어느 플래그든 통과하므로 이 축을 잠그지 못한다.
        """
        world.land({"pyproject.toml": '[project]\nname = "x"\n'})
        out = world.run()
        syncs = [ln for ln in out.splitlines() if ln.startswith("uv sync")]
        assert syncs, f"pyproject 가 바뀌었는데 uv sync 를 부르지 않았다:\n{out}"
        assert all("--locked" in ln for ln in syncs), (
            "uv sync 에 --locked 가 없다 — 플래그 없는 sync 는 tracked uv.lock 을 "
            "재작성해 autopull 을 영구 정지시킨다:\n" + "\n".join(syncs)
        )

    def test_daemons_still_restart_when_sync_fails(self, world):
        """sync 가 실패해도 재기동은 한다 — 실수가 아니라 의도된 선택이다.

        `--locked` 는 lock 불일치 시 non-zero 로 죽으므로 이 경로의 발화 빈도가
        올라간다. 그때 "구 venv + 새 코드" 가 되는 것은 사실이고 ImportError 위험이
        있지만, 대안(재기동 보류)은 이 파일 상단이 기록한 **#1017 사고 그대로**다 —
        autopull 이 데몬을 bounce 하지 않아 7일간 구코드로 돌았고 아무 신호가 없었다.
        크래시는 launchd KeepAlive 와 watchdog 이 표면화하지만 침묵은 아무도 못 본다.
        재기동을 sync 성공에 게이트하려는 변경은 이 테스트에서 막힌다 — 되돌리기
        전에 위 사고를 먼저 읽으라는 뜻이다.
        """
        world.land({"nuri/core/rules.py": "X = 1\n", "pyproject.toml": '[project]\nname = "x"\n'})
        out = world.run(UV_STUB_RC="1")
        assert "uv sync" in out, f"sync 를 시도조차 안 했다:\n{out}"
        for label in RESIDENT:
            assert re.search(rf"launchctl kickstart -k \S*{re.escape(label)}", out), (
                f"sync 실패를 이유로 {label} 재기동을 건너뛰었다 — 구코드로 계속 돈다 (#1017):\n{out}"
            )

    def test_uv_is_called_by_absolute_path_not_bare_name(self):
        """launchd 는 로그인 셸 PATH 를 안 물려준다 — 이름으로 부르면 조용히 건너뛴다.

        2026-08-10 수동 조치에서 실제로 `uv: command not found` 로 sync 가 통째로 스킵됐다.
        """
        src = AUTOPULL.read_text(encoding="utf-8")
        assert "command -v uv" in src and "/opt/homebrew/bin/uv" in src, (
            "uv 를 PATH 이름만으로 부르면 launchd 컨텍스트에서 조용히 실패한다"
        )


class TestAutopullBuildsTheFrontend:
    """자동 경로도 프론트를 빌드한다 (#1462) — 데몬 재기동(#1023)과 같은 비대칭의 재발.

    2026-07-27 에 수동 경로(deploy_to_mini.sh 4단계)에만 재빌드를 넣고 자동 경로는 WARN 로그로
    사람에게 넘겼다. 그 WARN 은 8/30 이후 17번 찍혔고 아무도 안 받았다 — 프로덕션이 9일 된
    빌드(frontend/ 커밋 25건 · 취약 패키지 3개 미반영)를 서빙했고, 소스만 바뀐 커밋은 WARN 조차
    없었다. 빌드 스크립트 자체의 동작(백업·복원·npm ci 게이트)은 `test_build_frontend.py` 가 잠그고,
    여기서는 **autopull 이 그걸 부르는지** 를 본다.
    """

    def _last_frontend_commit(self, work: Path) -> int:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", "frontend/"],
            cwd=work,
            check=True,
            capture_output=True,
            text=True,
        )
        return int(out.stdout.strip())

    def test_frontend_change_rebuilds_and_bounces_only_the_dashboard(self, world):
        world.land({"frontend/app/page.tsx": "export default () => null;\n"})
        out = world.run()
        assert "npm run build" in out, f"프론트가 바뀌었는데 빌드하지 않았다:\n{out}"
        assert re.search(rf"launchctl kickstart -k \S*{re.escape(DASHBOARD)}", out), (
            f"대시보드를 재기동하지 않았다:\n{out}"
        )
        for label in RESIDENT:
            assert label not in out, f"python 이 안 바뀌었는데 {label} 을 재기동했다:\n{out}"

    def test_a_stale_build_is_healed_even_when_nothing_new_landed(self, world):
        """판정이 커밋 vs 빌드 시각이라, 지난 주기에 실패했거나 밀린 빌드를 새 커밋 없이도 따라잡는다.

        이게 없으면 실패한 빌드는 다음 프론트 커밋까지 영영 재시도되지 않는다 — 조용한 실패의 형태.
        """
        world.land({"frontend/app/page.tsx": "export default () => null;\n"})
        world.run()
        bid = world.work / "frontend" / ".next" / "BUILD_ID"
        assert bid.exists()
        old = self._last_frontend_commit(world.work) - 1000
        os.utime(bid, (old, old))  # 빌드가 코드보다 오래된 것처럼

        out = world.run()  # origin 에 새 커밋 없음
        assert out.count("npm run build") == 2, f"새 커밋이 없다고 밀린 빌드를 두었다:\n{out}"

    def test_backend_only_change_does_not_rebuild_a_current_frontend(self, world):
        """빌드는 수십 초고 대시보드 재기동은 세션을 끊는다 — 프론트가 안 바뀌면 건드리지 않는다."""
        world.land({"frontend/app/page.tsx": "export default () => null;\n"})
        world.run()
        world.land({"nuri/core/rules.py": "X = 1\n"})
        out = world.run()
        assert out.count("npm run build") == 1, f"백엔드만 바뀌었는데 프론트를 다시 빌드했다:\n{out}"
        assert out.count(DASHBOARD) == 1

    def test_failed_frontend_build_is_logged_and_python_daemons_still_restart(self, world):
        """프론트 빌드 실패가 python 재기동을 막으면 안 된다 — 두 축은 독립이다 (#1017 과 같은 원칙)."""
        world.land({"nuri/core/rules.py": "X = 1\n", "frontend/app/page.tsx": "export default () => null;\n"})
        out = world.run(NPM_STUB_RC="1")
        for label in RESIDENT:
            assert re.search(rf"launchctl kickstart -k \S*{re.escape(label)}", out), f"{label} 재기동이 빠졌다:\n{out}"
        assert DASHBOARD not in out, "빌드가 실패했는데 대시보드를 재기동했다"
        assert "ERROR: frontend 빌드 실패" in world.autopull_log(), (
            "실패가 로그에 없다 — 침묵은 이 이슈가 막으려는 바로 그 형태다\n" + world.autopull_log()
        )


def _runs(*runs: dict) -> str:
    """runs API 응답 — 각 런은 기본으로 main 의 push 런이다."""
    return json.dumps({"workflow_runs": [{"event": "push", "head_branch": "main", **r} for r in runs]})


def _rev(repo: Path, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


class TestAutopullWaitsForGreenCi:
    """main CI 가 success 인 커밋만 배포한다 (#1808).

    branch protection 의 `strict` 가 켜져 있던 동안은 PR CI 가 머지 뒤 트리를 그대로 검사해서
    그게 사실상 배포 게이트였다. `strict` 를 끄면 각자 초록인 두 PR 이 합쳐진 트리는 main push
    CI 만 검사한다 — 이 게이트가 없으면 그 트리가 결과와 무관하게 5분 안에 production 에 깔린다.
    """

    @staticmethod
    def _held(world, **env: str) -> str:
        before = _rev(world.work)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        out = world.run(**env)
        assert _rev(world.work) == before, f"CI 가 초록이 아닌데 배포했다:\n{world.autopull_log()}"
        assert "kickstart" not in out, f"배포를 보류했는데 데몬을 재기동했다:\n{out}"
        return world.autopull_log()

    def test_green_ci_deploys_and_asks_about_the_fetched_commit(self, world):
        world.land({"nuri/core/rules.py": "X = 1\n"})
        target = _rev(world.origin, "main")
        out = world.run()
        assert _rev(world.work) == target, "CI 가 초록인데 배포하지 않았다"
        assert f"head_sha={target}&branch=main" in out, f"당겨올 커밋의 main 런이 아닌 것을 물었다:\n{out}"

    def test_running_ci_holds(self, world):
        log = self._held(world, CI_STUB_JSON=_runs({"status": "in_progress", "conclusion": None}))
        assert "main CI = ('push', 'in_progress', None)" in log

    def test_red_ci_holds(self, world):
        log = self._held(world, CI_STUB_JSON=_runs({"status": "completed", "conclusion": "failure"}))
        assert "main CI = ('push', 'completed', 'failure')" in log

    def test_no_run_yet_holds(self, world):
        log = self._held(world, CI_STUB_JSON='{"workflow_runs": []}')
        assert "main CI = no-run" in log

    def test_unreadable_api_holds(self, world):
        """판정을 못 읽으면 배포하지 않는다 — API 실패를 초록으로 읽으면 게이트가 없는 것과 같다."""
        log = self._held(world, CI_STUB_JSON=" ", CI_STUB_RC="22")
        assert "main CI = unreadable" in log

    def test_a_transfer_that_fails_after_a_green_body_holds(self, world):
        """curl 이 성공 본문을 내보낸 뒤 실패해도(exit 18) 보류한다 — 파이프로 넘기면 본문대로 success 였다."""
        log = self._held(world, CI_STUB_RC="18")
        assert "main CI = unreadable" in log

    def test_success_only_counts_as_a_completed_runs_conclusion(self, world):
        """status 가 success 여도 completed 가 아니면 보류한다 — conclusion 대신 status 를 읽던 판에서 통과했다."""
        log = self._held(world, CI_STUB_JSON=_runs({"status": "success", "conclusion": None}))
        assert "main CI = ('push', 'success', None)" in log

    def test_a_conclusion_with_trailing_newlines_is_not_success(self, world):
        """conclusion 이 `success` 뒤에 줄바꿈을 달고 오면 success 가 아니다 — bash 의 $(...) 가 끝 줄바꿈을 지우던 비교에서는 통과했다."""
        log = self._held(world, CI_STUB_JSON=_runs({"status": "completed", "conclusion": "success\n\n"}))
        assert "main CI = ('push', 'completed', 'success\\n\\n')" in log

    def test_a_status_padded_to_look_green_holds(self, world):
        """응답 값이 출력 앞머리가 되면 잘림과 NUL 제거로 "green" 을 만들 수 있었다 — 접두사는 응답과 무관해야 한다."""
        log = self._held(world, CI_STUB_JSON=_runs({"status": "green" + "\u0000" * 55, "conclusion": "failure"}))
        assert "main CI = ('push', 'green" in log

    def test_a_held_commit_deploys_once_ci_turns_green(self, world):
        self._held(world, CI_STUB_JSON=_runs({"status": "queued", "conclusion": None}))
        out = world.run()
        assert _rev(world.work) == _rev(world.origin, "main"), "초록이 된 뒤에도 배포하지 않았다"
        assert "kickstart" in out

    def test_a_dispatch_run_counts_even_after_a_cancelled_push_run(self, world):
        """GITHUB_TOKEN 머지에는 push 런이 없고 catch-up 이 띄운 dispatch 런만 있다 (#1812).

        가장 최근 런 하나만 보면 취소된 push 런과 성공한 dispatch 런이 같이 있을 때 영원히 보류한다.
        """
        world.land({"nuri/core/rules.py": "X = 1\n"})
        runs = _runs(
            {"status": "completed", "conclusion": "cancelled"},
            {"event": "workflow_dispatch", "status": "completed", "conclusion": "success"},
        )
        world.run(CI_STUB_JSON=runs)
        assert _rev(world.work) == _rev(world.origin, "main"), (
            f"성공한 dispatch 런을 인정하지 않았다:\n{world.autopull_log()}"
        )

    def test_a_pull_request_run_does_not_count(self, world):
        """PR 런은 머지 뒤 트리를 검사한 게 아니다 — `strict` 없이 합쳐진 트리는 main 런만 검사한다."""
        log = self._held(
            world, CI_STUB_JSON=_runs({"event": "pull_request", "status": "completed", "conclusion": "success"})
        )
        assert "main CI = ('pull_request', 'completed', 'success')" in log

    def test_a_run_on_another_branch_does_not_count(self, world):
        self._held(
            world, CI_STUB_JSON=_runs({"head_branch": "feature", "status": "completed", "conclusion": "success"})
        )


class TestAutopullDefersForAnOpenThesisBatch:
    """채점 배치가 도는 동안 autopull 은 주기를 건너뛴다 (#1989) — pull 도 재기동도 없다.

    재기동은 배치를 죽이고, pull 만 해도 늦게 import 되는 모듈 · 디스크에서 읽는 팔 정의 해시가 새 코드로 바뀐다.
    """

    @staticmethod
    def _db(world, status: str | None, hours_ago: float = 0.5) -> None:
        from datetime import timedelta, timezone

        from nuri.core.db import get_db, init_db
        from nuri.core.timezone import kst_now

        path = world.work / "data" / "portfolio.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(path)
        if status is None:
            return
        # start_batch 의 _utc_now 와 같은 형식 (UTC ISO, 마이크로초 · +00:00)
        started = (kst_now() - timedelta(hours=hours_ago)).astimezone(timezone.utc).isoformat()
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO thesis_batches (batch_id, experiment, started_at, canary_start, status) "
                "VALUES ('b', 'pilot', ?, 'c', ?)",
                (started, status),
            )

    def test_an_open_recent_batch_defers_pull_and_restart(self, world):
        self._db(world, "open")
        world.land({"nuri/core/rules.py": "X = 1\n"})
        out = world.run()
        assert "kickstart" not in out
        assert not (world.work / "nuri" / "core" / "rules.py").exists(), "열린 배치 중에 pull 했다"
        assert "thesis batch open" in world.autopull_log()

    @pytest.mark.parametrize(("status", "hours_ago"), [("open", 7.0), ("ok", 0.5), ("canary_changed", 0.5), (None, 0)])
    def test_a_stale_or_finished_batch_or_no_table_does_not_block(self, world, status, hours_ago):
        """6시간 넘게 열린 배치는 멈춘 것 — 배포를 영원히 막지 않는다. 끝난 배치 · 빈 표도 막지 않는다."""
        self._db(world, status, hours_ago)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        out = world.run()
        assert (world.work / "nuri" / "core" / "rules.py").exists()
        assert "kickstart" in out

    def test_the_cap_is_configurable(self, world):
        self._db(world, "open", hours_ago=2.0)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run(THESIS_DEFER_HOURS="1")
        assert (world.work / "nuri" / "core" / "rules.py").exists()

    def test_an_empty_db_file_does_not_block(self, world):
        (world.work / "data").mkdir(parents=True, exist_ok=True)
        (world.work / "data" / "portfolio.db").write_bytes(b"")
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run()
        assert (world.work / "nuri" / "core" / "rules.py").exists()

    def test_an_unreadable_db_defers_instead_of_reading_as_zero(self, world):
        """읽지 못한 표를 0 건으로 치면 열린 배치가 있어도 배포한다 — 보류하고 이유를 남긴다."""
        (world.work / "data").mkdir(parents=True, exist_ok=True)
        (world.work / "data" / "portfolio.db").write_bytes(b"not a database" * 100)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        out = world.run()
        assert "kickstart" not in out
        assert not (world.work / "nuri" / "core" / "rules.py").exists()
        assert "thesis_batches unreadable" in world.autopull_log()

    def test_a_failing_sqlite_cli_defers(self, world):
        self._db(world, "ok")
        stub = world.work.parent / "bin" / "sqlite3"
        stub.write_text("#!/bin/sh\necho 'Error: database is locked' >&2\nexit 5\n")
        stub.chmod(0o755)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run()
        assert not (world.work / "nuri" / "core" / "rules.py").exists()
        assert "database is locked" in world.autopull_log()

    @staticmethod
    def _mini_sqlite(world) -> Path:
        """mini 의 Apple sqlite3 3.51 처럼 — -wal/-shm 이 없을 때 읽기 전용 열기는 code 14 로 실패한다 (#1995).
        그 밖에는 진짜 CLI 로 넘기고, 받은 인자를 한 줄씩 남긴다."""
        real = shutil.which("sqlite3")
        assert real, "sqlite3 CLI 가 없다"
        stub = world.work.parent / "bin" / "sqlite3"
        argv_log = world.work.parent / "sqlite3_argv"
        stub.write_text(
            "#!/bin/bash\n"
            f'printf "%s\\0" "$@" >> "{argv_log}"; printf "\\n" >> "{argv_log}"\n'
            'for a in "$@"; do case "$a" in -readonly|*mode=ro*) ro=1 ;; *.db) db="$a" ;; esac; done\n'
            'if [ -n "$ro" ] && [ ! -e "$db-shm" ]; then\n'
            '  echo "Error: in prepare, unable to open database file (14)" >&2; exit 1\n'
            "fi\n"
            f'exec "{real}" "$@"\n'
        )
        stub.chmod(0o755)
        return argv_log

    @pytest.mark.parametrize(("status", "deploys"), [("open", False), ("ok", True)])
    def test_a_wal_db_with_no_open_connection_is_still_read(self, world, status, deploys):
        """연결이 모두 닫혀 -wal/-shm 이 없는 WAL DB — 읽지 못한다고 보류하면 배포가 무작위로 막힌다 (#1995)."""
        self._db(world, status)
        db = world.work / "data" / "portfolio.db"
        # conftest 가 테스트 DB 를 MEMORY 저널로 만든다 — 운영처럼 WAL 로 바꾸고, 연결이 닫혀 사이드카가 없는 상태로
        sqlite3 = shutil.which("sqlite3")
        assert sqlite3
        mode = subprocess.run([sqlite3, str(db), "PRAGMA journal_mode=WAL;"], capture_output=True, text=True)
        assert mode.stdout.strip() == "wal"
        assert not Path(f"{db}-shm").exists() and not Path(f"{db}-wal").exists()
        self._mini_sqlite(world)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run()
        assert (world.work / "nuri" / "core" / "rules.py").exists() is deploys
        assert "unreadable" not in world.autopull_log()

    def test_the_guard_connection_refuses_writes(self, world):
        """읽기 전용 플래그 대신 query_only — 가드가 쓴 그대로의 인자로 INSERT 를 보내면 거부돼야 한다."""
        self._db(world, "ok")
        argv_log = self._mini_sqlite(world)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run()
        argv = argv_log.read_text().splitlines()[0].split("\0")[:-1]
        argv[-1] = (
            "INSERT INTO thesis_batches (batch_id, experiment, started_at, canary_start, status) "
            "VALUES ('x', 'p', 's', 'c', 'open');"
        )
        sqlite3 = shutil.which("sqlite3")
        assert sqlite3
        r = subprocess.run([sqlite3, *argv], capture_output=True, text=True)
        assert r.returncode != 0 and "readonly" in r.stderr, r.stderr

    @pytest.mark.parametrize("hours", ["oops", "-1", "0", "100", "6 hours')) OR 1=1; --"])
    def test_an_invalid_cap_falls_back_to_six_hours(self, world, hours):
        """시간 값은 SQL 에 들어간다 — 무효 값은 수정자 오류로 0 건이 되거나 질의를 바꾼다. 6 으로 본다."""
        self._db(world, "open", hours_ago=2.0)
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run(THESIS_DEFER_HOURS=hours)
        assert not (world.work / "nuri" / "core" / "rules.py").exists()
        assert "THESIS_DEFER_HOURS" in world.autopull_log()

    def test_an_injected_cap_cannot_turn_finished_batches_into_a_block(self, world):
        self._db(world, "ok")
        world.land({"nuri/core/rules.py": "X = 1\n"})
        world.run(THESIS_DEFER_HOURS="6 hours')) OR 1=1 OR ('")
        assert (world.work / "nuri" / "core" / "rules.py").exists()
