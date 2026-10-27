"""thesis JSONL 스트림을 기다리는 봇 전용 실행기 (#1965). 원문은 로컬 로그에만 남긴다."""

# cspell:ignore killpg

import asyncio
import json
import os
import re
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from nuri.llm.local_client import load_config
from nuri.llm.thesis_events import PREFIX, public_event

REPO_ROOT = Path(__file__).resolve().parents[3]


async def run(
    target: str, ticker: str, on_stage: Callable[[dict[str, str]], Awaitable[None]]
) -> tuple[int, dict[str, str]]:
    if target != "thesis-remote" or not re.fullmatch(r"[A-Z]{1,6}", ticker):
        raise ValueError("invalid thesis invocation")
    cfg = load_config()
    directory = Path(cfg["archive_dir"]) / "interactive"
    directory.mkdir(parents=True, exist_ok=True)
    timeout = float(cfg["interactive"]["timeout_s"])
    with (directory / f"{uuid4().hex}.log").open("ab", buffering=0) as raw:
        proc = await asyncio.create_subprocess_exec(
            "make",
            target,
            f"ticker={ticker}",
            cwd=REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=raw,
            start_new_session=True,
        )

        async def consume() -> tuple[int, dict[str, str]]:
            result = None
            assert proc.stdout is not None
            while line := await proc.stdout.readline():
                raw.write(line)
                if not line.startswith(PREFIX.encode()):
                    continue
                try:
                    event = public_event(json.loads(line[len(PREFIX) :]))
                except (ValueError, UnicodeDecodeError):
                    continue
                if event is None:
                    continue
                if event["event"] == "stage":
                    await on_stage(event)
                else:
                    result = event
            rc = await proc.wait()
            if rc != 0:
                return rc, {"event": "error", "code": "run_failed"}
            if result is None or result["event"] != "result":
                return 2, {"event": "error", "code": "stream_failed"}
            return 0, result

        try:
            return await asyncio.wait_for(consume(), timeout=timeout)
        except TimeoutError:
            return 124, {"event": "error", "code": "timeout"}
        finally:
            # make 만 죽이면 SSH·원격 실행이 남는다. 시작한 프로세스 그룹을 함께 종료한다.
            if proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                await proc.wait()
