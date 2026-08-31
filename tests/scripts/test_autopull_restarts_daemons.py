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

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPULL = REPO_ROOT / "scripts" / "deploy" / "autopull_receiver.sh"

RESIDENT = ["com.nuri-quant.scheduler", "com.nuri-quant.api", "com.nuri-quant.discord-bot"]


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
        f'if [ "$1" = "list" ]; then for l in {" ".join(RESIDENT)}; do echo "1 0 $l"; done; exit 0; fi\n'
        f'echo "launchctl $*" >> "{calls}"\nexit 0\n'
    )
    # UV_STUB_RC 로 sync 실패를 흉내낸다 (기본 0 — 기존 테스트 무영향).
    (binz / "uv").write_text(f'#!/bin/sh\necho "uv $*" >> "{calls}"\nexit ${{UV_STUB_RC:-0}}\n')
    for f in ("launchctl", "uv"):
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
            **env_extra,
        }
        subprocess.run(["bash", str(AUTOPULL)], env=env, check=False, capture_output=True, timeout=120)
        return calls.read_text() if calls.exists() else ""

    return type("W", (), {"land": staticmethod(land), "run": staticmethod(run), "work": work})


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
