"""`scripts/deploy/thesis_remote.sh` — Discord /thesis 를 MBP 에서 돌리는 위임 스크립트.

스크립트 텍스트를 긁지 않고 **실행**한다 (`tests/CLAUDE.md` "워크플로 스텝은 실행하고"). 임시 디렉터리에
스크립트를 복사하고 옆에 가짜 `ssh_dev2.sh` 를 둔다 — 가짜는 받은 인자를 기록한 뒤 원격 명령을 가짜
HOME 에서 실제로 실행하고, PATH 앞의 가짜 `make` 가 받은 인자와 `NURI_DB_PATH` 를 찍는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "deploy" / "thesis_remote.sh"

FAKE_SSH = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_LOG"
# 마지막 인자가 원격 명령 — ssh 처럼 홈에서 시작해 실행한다
cd "$HOME" && exec bash -c "${@: -1}"
"""

FAKE_MAKE = """#!/usr/bin/env bash
echo "make-args: $*"
echo "db: ${NURI_DB_PATH:-<unset>}"
exit "${FAKE_MAKE_RC:-0}"
"""


@pytest.fixture
def rig(tmp_path: Path):
    bin_dir = tmp_path / "deploy"
    bin_dir.mkdir()
    shutil.copy(SCRIPT, bin_dir / "thesis_remote.sh")
    (bin_dir / "ssh_dev2.sh").write_text(FAKE_SSH, encoding="utf-8")
    fake_path = tmp_path / "fakebin"
    fake_path.mkdir()
    (fake_path / "make").write_text(FAKE_MAKE, encoding="utf-8")
    (fake_path / "make").chmod(0o755)
    home = tmp_path / "home"
    repo = home / "workspace" / "nuri-quant"
    (repo / "data" / "replicas").mkdir(parents=True)
    (home / ".zshrc").write_text("", encoding="utf-8")
    log = tmp_path / "ssh.log"

    def run(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{fake_path}:{os.environ['PATH']}",
            "HOME": str(home),
            "FAKE_LOG": str(log),
            "DEV2_HOST": "user@macbook.local",
            "DEV2_PATH": "~/workspace/nuri-quant",
        }
        env.update(env_extra or {})
        env = {k: v for k, v in env.items() if v is not None and v != "<drop>"}
        return subprocess.run(
            ["bash", str(bin_dir / "thesis_remote.sh"), *args], env=env, capture_output=True, text=True, check=False
        )

    return run, repo, log, home


class TestInputIsRefusedBeforeSsh:
    @pytest.mark.parametrize("ticker", ["", "msft", "TOOLONGX", "MS;rm", "A B", "$(id)"])
    def test_bad_ticker_exits_2_without_ssh(self, rig, ticker: str) -> None:
        run, _, log, _ = rig
        r = run(ticker)
        assert r.returncode == 2
        assert not log.exists(), "형태가 틀린 ticker 로는 원격에 접속하지 않는다"

    def test_missing_host_exits_2(self, rig) -> None:
        run, _, log, _ = rig
        r = run("MSFT", env_extra={"DEV2_HOST": "<drop>"})
        assert r.returncode == 2
        assert "DEV2_HOST" in r.stderr
        assert not log.exists()


class TestRemoteRun:
    def test_runs_make_thesis_on_the_newest_replica(self, rig) -> None:
        run, repo, log, _ = rig
        old = repo / "data" / "replicas" / "portfolio_old.db"
        new = repo / "data" / "replicas" / "portfolio_new.db"
        old.write_text("x")
        new.write_text("x")
        os.utime(old, (1_000_000, 1_000_000))
        r = run("MSFT")
        assert r.returncode == 0, r.stderr
        assert "make-args: thesis-progress ticker=MSFT" in r.stdout
        assert f"db: {repo}/data/replicas/portfolio_new.db" in r.stdout
        argv = log.read_text(encoding="utf-8").splitlines()
        assert argv[:5] == ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "user@macbook.local"]

    def test_tilde_path_is_made_home_relative(self, rig) -> None:
        """`~/` 를 못 벗기면 원격에서 리터럴 `~` 디렉터리로 cd 하다 실패한다 (#947 과 같은 함정)."""
        run, _, log, _ = rig
        assert run("MSFT").returncode == 0
        remote_cmd = log.read_text(encoding="utf-8").splitlines()[-1]
        assert remote_cmd.startswith("cd workspace/nuri-quant ")

    def test_without_a_replica_it_warns_and_uses_the_dev_db(self, rig) -> None:
        run, _, _, _ = rig
        r = run("MSFT")
        assert r.returncode == 0
        assert "db: <unset>" in r.stdout
        assert "no replica" in r.stderr

    def test_remote_exit_code_is_propagated(self, rig) -> None:
        """Discord embed 는 rc 로 성공을 판정한다 — 원격 실패가 0 으로 바뀌면 안 된다."""
        run, _, _, _ = rig
        assert run("MSFT", env_extra={"FAKE_MAKE_RC": "3"}).returncode == 3

    @pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh 없는 러너")
    def test_host_is_read_from_zshrc_when_the_env_lacks_it(self, rig) -> None:
        """봇 프로세스는 .env 만 읽는다 — DEV2_HOST 는 ~/.zshrc 에서 가져와야 한다."""
        run, _, log, home = rig
        (home / ".zshrc").write_text(
            "export DEV2_HOST=user@macbook.local\nexport DEV2_PATH=~/workspace/nuri-quant\n", encoding="utf-8"
        )
        r = run("MSFT", env_extra={"DEV2_HOST": "<drop>", "DEV2_PATH": "<drop>"})
        assert r.returncode == 0, r.stderr
        assert "user@macbook.local" in log.read_text(encoding="utf-8").splitlines()
