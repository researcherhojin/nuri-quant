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
    (binz / "uv").write_text(f'#!/bin/sh\necho "uv $*" >> "{calls}"\nexit 0\n')
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

    def run() -> str:
        env = {
            **os.environ,
            "PATH": f"{binz}:{os.environ['PATH']}",
            "NURI_REPO": str(work),
            "HOME": str(tmp_path),
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

    def test_uv_is_called_by_absolute_path_not_bare_name(self):
        """launchd 는 로그인 셸 PATH 를 안 물려준다 — 이름으로 부르면 조용히 건너뛴다.

        2026-08-10 수동 조치에서 실제로 `uv: command not found` 로 sync 가 통째로 스킵됐다.
        """
        src = AUTOPULL.read_text(encoding="utf-8")
        assert "command -v uv" in src and "/opt/homebrew/bin/uv" in src, (
            "uv 를 PATH 이름만으로 부르면 launchd 컨텍스트에서 조용히 실패한다"
        )
