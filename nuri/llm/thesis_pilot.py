"""thesis 파일럿 러너 — 밤마다 시드 고정 표본으로 채점 배치를 돌린다 (#1964).

파일럿은 확증이 아니다 — E 의 숫자(종목당 시간 · 실패율 · 일별 ΔIC 분산)를 정한다. 표본은 E 이후 쓰지 않는다.

- **꺼진 채 출하** — `config/thesis_pilot.yaml` 의 `experiment: null` 이면 아무것도 하지 않는다.
- **기간 = 동결 창** — `config/thesis_freeze.yaml` 에 같은 실험의 창이 오늘(KST)을 덮고, 지문이 그대로일 때만 돈다
  (#1990). 그래서 파일럿이 도는 날은 언제나 팔 정의가 얼어 있다.
- **세션 다음 날만** — 전날(미국 날짜)이 NYSE 거래일이었던 밤. 진입은 다음 개장이다(#1966).
- **Ollama 를 혼자 쓴다** — 미장 마감 브리프 창(16:30 ET ± 15분, 같은 DST 처리) 근처에는 시작하지 않는다. 동시
  클라이언트는 차가운 호출 검사에 걸린다. 대시보드의 즉석 리포트는 막을 수 없다 — 겹치면 원장에 `review_call` 로
  남는다(버려지지 않는다).
- **한 실험 · 한 날짜에 배치 하나** — 원장 확인 + 파일 잠금. 잠금 fd 는 배치 · 정산 자식에게 물려줘, 러너가 먼저
  죽어도 자식이 사는 동안 잠금이 남는다. 중복 실행은 #1991 이 거부한다.
- **추첨** — 시드 = SHA-256(실험, 코호트, 정렬된 유니버스 해시). `hash()` 는 프로세스마다 달라 쓰지 않는다.
  추첨 기록(시드 · 유니버스 해시 · 종목)은 비공개 보관소에 남긴다 — 유니버스는 `universe_sync` 로 바뀔 수 있다.
- **고정된 코드에서** — 배치는 HEAD 에 고정한 `git worktree` 에서 돈다. 팔 지문은 실행마다 디스크의 파일을 읽으므로,
  배치 도중 배포(autopull 은 막지만 `make deploy-mini` 는 안 막는다)가 한 배치 안에 정의를 섞는다(#1963 첫 측정).
  동결 확인도 그 트리 안에서 그 트리의 코드로 다시 한다 — 사전 점검과 트리 생성 사이의 배포까지 막는다. 돌릴 모든
  팔이 그 실험의 창에 얼려 있어야 한다.
- **분리 실행** — 스케줄러는 `launch` 만 하고, 배치는 새 세션(`start_new_session=True`)에서 돈다. launchd 는 job 이
  죽을 때 **같은 프로세스 그룹**만 정리한다(`man launchd.plist`, AbandonProcessGroup) — 스케줄러 재기동이 배치를
  죽이지 않는다. 정산 · reflection(`thesis_memory`)은 같은 프로세스에서 배치 뒤에 차례로(둘 다 Ollama 를 쓴다).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import yaml

from nuri.core.db import query
from nuri.core.market_calendar import nyse_holidays
from nuri.core.timezone import KST, kst_now
from nuri.llm import local_client as lc
from nuri.llm import thesis_freeze

PILOT_PATH = Path("config/thesis_pilot.yaml")
UNIVERSE_PATH = Path("config/universe.yaml")
US_SECTIONS = ("us_core", "us_sp500_extended")
WORK_DIR = Path("data/thesis_pilot")
ARMS = {"A", "B", "S"}
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Pilot:
    experiment: str
    tickers_per_night: int
    arms: tuple[str, ...]
    brief_quiet_minutes: int


def load_pilot(path: Path = PILOT_PATH) -> Optional[Pilot]:
    """`experiment: null` 이면 None(꺼짐). 잘못 쓴 설정은 거부한다 — 조용히 다른 표본을 돌리지 않게."""
    with path.open() as f:
        doc = yaml.safe_load(f) or {}
    if doc.get("experiment") is None:
        return None
    exp, k, arms, quiet = doc["experiment"], doc["tickers_per_night"], doc["arms"], doc["brief_quiet_minutes"]
    if not isinstance(exp, str) or not exp.strip():
        raise ValueError("experiment must be a non-empty string")
    if not isinstance(k, int) or k < 2:
        raise ValueError("tickers_per_night must be an integer of at least 2")
    if not isinstance(arms, list) or not arms or not set(arms) <= ARMS or len(set(arms)) != len(arms):
        raise ValueError(f"arms must be distinct values from {sorted(ARMS)}")
    if "S" in arms and "B" not in arms:
        raise ValueError("arm S consumes arm B")
    if not isinstance(quiet, int) or quiet < 0:
        raise ValueError("brief_quiet_minutes must be a non-negative integer")
    return Pilot(exp.strip(), k, tuple(arms), quiet)


def us_universe(path: Path = UNIVERSE_PATH) -> list[str]:
    with path.open() as f:
        doc = yaml.safe_load(f) or {}
    return sorted({t for s in US_SECTIONS for t in ((doc.get(s) or {}).get("tickers") or [])})


def draw(experiment: str, cohort: date, universe: list[str], k: int) -> dict[str, Any]:
    """시드 고정 추출 — 같은 (실험, 코호트, 유니버스) 면 언제 어디서 돌려도 같은 종목 · 같은 순서."""
    if k > len(universe):
        raise ValueError(f"cannot draw {k} tickers from a universe of {len(universe)}")
    universe_hash = hashlib.sha256("\n".join(universe).encode()).hexdigest()
    seed = hashlib.sha256(f"{experiment}\n{cohort.isoformat()}\n{universe_hash}".encode()).hexdigest()
    tickers = random.Random(int(seed, 16)).sample(universe, k)  # 순서도 시드 셔플
    return {
        "experiment": experiment,
        "cohort": cohort.isoformat(),
        "seed": seed,
        "universe_hash": universe_hash,
        "universe_size": len(universe),
        "tickers": tickers,
    }


def after_session(cohort: date) -> bool:
    """전날(미국 날짜)이 NYSE 거래일이었나 — KST 아침은 미국의 전날 밤이다."""
    prev = cohort - timedelta(days=1)
    return prev.weekday() < 5 and prev not in nyse_holidays(prev, prev)


def brief_busy(now: datetime, quiet_minutes: int) -> bool:
    """미장 마감 브리프가 Ollama 를 쓸 수 있는 구간 — 16:30 ET 의 15분 전부터 `quiet_minutes` 뒤까지(DST 는 NY 시각으로)."""
    ny = now.astimezone(NY)
    minutes = (ny.hour - 16) * 60 + ny.minute - 30
    return -15 <= minutes <= quiet_minutes


def batch_exists(experiment: str, cohort: date, db_path: Optional[Path] = None) -> bool:
    rows = query("SELECT started_at FROM thesis_batches WHERE experiment = ?", (experiment,), db_path=db_path)
    return any(datetime.fromisoformat(r["started_at"]).astimezone(KST).date() == cohort for r in rows)


def freeze_status(
    freezes: list[thesis_freeze.Freeze], pilot: Pilot, cohort: date, hashes: dict[str, str]
) -> Optional[str]:
    """이 실험의 창이 오늘을 덮고, 돌릴 **모든 팔**이 그 창에 얼려 있고, 지문이 그대로인가 — A 만 얼린 창으로 B 를
    돌리면 B 가 움직여도 막지 못한다 (Codex 리뷰)."""
    if thesis_freeze.violations(freezes, cohort, hashes):
        return "freeze_violation"
    covered = {a for f in freezes if f.experiment == pilot.experiment and f.start <= cohort <= f.end for a in f.arms}
    if not set(pilot.arms) <= covered:
        return "not_frozen"
    return None


def preflight(
    pilot: Pilot,
    now: datetime,
    *,
    freeze_path: Path = thesis_freeze.FREEZE_PATH,
    config_path: Path = lc.CONFIG_PATH,
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """돌면 안 되는 이유(없으면 None)."""
    cohort = now.astimezone(KST).date()
    if not after_session(cohort):
        return "no_session"
    hashes = thesis_freeze.current_hashes(lc.load_config(config_path))
    reason = freeze_status(thesis_freeze.load(freeze_path), pilot, cohort, hashes)
    if reason is not None:
        return reason
    if brief_busy(now, pilot.brief_quiet_minutes):
        return "ollama_busy"
    if batch_exists(pilot.experiment, cohort, db_path=db_path):
        return "already_ran"
    return None


def commands(pilot: Pilot, tickers: list[str], python: str, db_path: Optional[Path] = None) -> list[list[str]]:
    """배치 → 정산 · reflection, 차례로 — 둘 다 Ollama 를 쓴다. 사전 점검이 본 DB 를 자식도 쓴다 (Codex 리뷰)."""
    db = ["--db", str(db_path)] if db_path is not None else []
    return [
        [
            python,
            "-m",
            "nuri.llm.thesis_arm",
            "--tickers",
            ",".join(tickers),
            "--arms",
            ",".join(pilot.arms),
            "--scored",
            "--experiment",
            pilot.experiment,
            *db,
        ],
        [python, "-m", "nuri.llm.thesis_memory", *db],
    ]


def freeze_command(python: str) -> list[str]:
    """고정 트리 안에서 그 트리의 코드 · 설정으로 지문을 계산한다 — 이 프로세스가 import 한 코드가 아니라."""
    return [python, "-m", "nuri.llm.thesis_freeze"]


def exit_code(code: int) -> int:
    """신호로 죽은 자식(음수)도 실패로 — max() 에서 0 에 묻히지 않게 (Codex 리뷰)."""
    return code if code >= 0 else 128 - code


def pinned_worktree(repo: Path, path: Path) -> Path:
    """HEAD 에 고정한 작업 트리 — `data` 는 저장소의 것을 가리킨다(원장 · 보관소는 하나)."""
    if path.exists():
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], check=False)
        shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(path), "HEAD"], check=True, capture_output=True
    )
    (path / "data").symlink_to((repo / "data").resolve(), target_is_directory=True)
    return path


def run_night(
    pilot: Pilot,
    now: datetime,
    *,
    repo: Path,
    python: str,
    db_path: Optional[Path] = None,
) -> int:
    """배치 프로세스 본체 — 잠금 · 사전 점검 · 추첨 · 고정 트리에서 배치와 정산 · 정리."""
    cohort = now.astimezone(KST).date()
    # 자식은 고정 트리에서 돈다 — 상대 경로면 다른 DB 를 가리킨다 (Codex 리뷰)
    db_path = Path(os.path.abspath(db_path)) if db_path is not None else None
    work = repo / WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    with (work / f"{pilot.experiment}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("refused: locked", file=sys.stderr)
            return 4
        reason = preflight(
            pilot,
            now,
            freeze_path=repo / thesis_freeze.FREEZE_PATH,
            config_path=repo / lc.CONFIG_PATH,
            db_path=db_path,
        )
        if reason is not None:
            print(f"refused: {reason}", file=sys.stderr)
            return 0 if reason == "no_session" else 5
        record = draw(pilot.experiment, cohort, us_universe(repo / UNIVERSE_PATH), pilot.tickers_per_night)
        draws = work / "draws"
        draws.mkdir(exist_ok=True)
        (draws / f"{pilot.experiment}-{cohort.isoformat()}.json").write_text(json.dumps(record))
        tree = pinned_worktree(repo, work / f"wt-{pilot.experiment}-{cohort.isoformat()}")
        # 자식들이 잠금 fd 를 물려받는다 — flock 은 열린 파일에 걸리므로, 이 프로세스가 죽어도 배치가 사는 동안
        # 잠금이 남는다. 그 사이 다음 실행이 트리를 지우고 두 번째 배치를 띄우지 못한다 (Codex 리뷰).
        fds = (lock.fileno(),)
        try:
            # 실행할 바로 그 코드로 다시 확인한다 — 위 사전 점검과 트리 생성 사이에 배포가 끼어들 수 있다
            out = subprocess.run(freeze_command(python), cwd=tree, capture_output=True, text=True, pass_fds=fds)
            reason = (
                freeze_status(
                    thesis_freeze.load(tree / thesis_freeze.FREEZE_PATH), pilot, cohort, json.loads(out.stdout)
                )
                if out.returncode == 0
                else "freeze_unreadable"
            )
            if reason is not None:
                print(f"refused: {reason} in the pinned tree", file=sys.stderr)
                return 5
            rcs = [
                exit_code(subprocess.run(cmd, cwd=tree, check=False, pass_fds=fds).returncode)
                for cmd in commands(pilot, record["tickers"], python, db_path=db_path)
            ]
        finally:
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=False)
        return max(rcs)


def launch(argv: list[str], log_path: Path, cwd: Path) -> subprocess.Popen:
    """새 세션으로 띄우고 돌아온다 — 부모(스케줄러)가 죽거나 재기동돼도 자식은 산다."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 자식은 자기 사본을 갖는다 — 부모 쪽은 닫는다(스케줄러에 밤마다 fd 가 쌓이지 않게)
    with log_path.open("a") as log:
        return subprocess.Popen(
            argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True
        )


def launch_night(repo: Optional[Path] = None, python: str = sys.executable) -> Optional[int]:
    """스케줄러 진입점 — 꺼져 있으면 아무것도 하지 않는다. 띄운 배치 프로세스의 PID."""
    repo = repo if repo is not None else Path.cwd()
    if load_pilot(repo / PILOT_PATH) is None:
        return None
    log = repo / "data" / "logs" / f"thesis_pilot-{kst_now().date().isoformat()}.log"
    return launch([python, "-m", "nuri.llm.thesis_pilot", "run"], log, cwd=repo).pid


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Thesis pilot runner (#1964). Disabled while experiment is null.")
    p.add_argument("command", choices=["launch", "run"])
    args = p.parse_args(argv)
    repo = Path.cwd()
    if args.command == "launch":
        pid = launch_night(repo)
        print("disabled" if pid is None else f"launched {pid}")
        return 0
    pilot = load_pilot(repo / PILOT_PATH)
    if pilot is None:
        print("disabled")
        return 0
    return run_night(pilot, kst_now(), repo=repo, python=sys.executable)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
