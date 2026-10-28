"""대화형 B 팔: 진행 이벤트와 허용 목록 최종 카드만 stdout 으로 보낸다 (#1965). 원장은 쓰지 않는다."""

import argparse
import json
import re
import sys
import traceback
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import yaml

from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_contract as tc
from nuri.llm.thesis_events import PREFIX, public_event

INTERACTIVE_RUNTIME_PATH = Path("config/llm_interactive.yaml")


def interactive_config(cfg: dict, path: Path = INTERACTIVE_RUNTIME_PATH) -> dict:
    """채점 설정은 보존하고 대화형 실행의 검증된 버전만 따로 고정한다."""
    with path.open() as stream:
        override = yaml.safe_load(stream)
    if (
        not isinstance(override, dict)
        or set(override) != {"version"}
        or not isinstance(override["version"], str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", override["version"]) is None
    ):
        raise ValueError("interactive runtime requires exactly one explicit version")
    result = deepcopy(cfg)
    result["expected"]["version"] = override["version"]
    return result


def emit(value: dict[str, str]) -> None:
    event = public_event(value)
    if event is not None:
        print(PREFIX + json.dumps(event), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unscored, local-only thesis stages; public event stream only.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Z]{1,6}", args.ticker):
        parser.error("ticker must contain one to six uppercase letters")
    cfg = lc.load_config()
    try:
        cfg = interactive_config(cfg)
        packets = tc.build_packets(args.ticker, db_path=args.db)
        run = arm.run_arm_b(args.ticker, packets, cfg=cfg, scored=False, progress=emit)
        tc.archive(run, packets, cfg)
        outcome = (
            "verdict" if run["outcome"] == "verdict" else "review" if run["outcome"].startswith("review") else "failed"
        )
        emit({"event": "result", "rating": run["rating"], "outcome": outcome, "run_hash": run["run_hash"]})
        return 1 if outcome == "failed" else 0
    except Exception:
        directory = Path(cfg["archive_dir"]) / "interactive"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{uuid4().hex}.log").write_text(traceback.format_exc())
        emit({"event": "error", "code": "run_failed"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
