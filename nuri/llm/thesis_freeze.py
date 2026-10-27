"""실험 창 동안 팔 정의를 얼린다 (#1990).

팔 지문(`arm_hash`)은 동작 파일 · 런타임 설정이 바뀌면 움직인다. 매일 여러 세션이 main 에 머지하므로, 파일럿 ·
확증 창 도중의 합법적인 머지 하나가 수집 중인 실험을 조용히 새 실험으로 바꾼다 — 원장에 지문이 섞인 뒤에야 보인다.

- **선언** — `config/thesis_freeze.yaml` 에 실험 · 창(KST 날짜, 양 끝 포함) · 기대 지문. 해제도 그 파일 편집이다.
- **검사** — fast 테스트가 지금 지문을 다시 계산해, 오늘이 창 안이고 지문이 다르면 실패한다. 네트워크 · DB 없음.
- **같은 지문** — A · B · S 가 원장에 쓰는 것과 같은 계산이어야 한다. A · S 는 실행 안에서 바로 계산하므로 여기서
  같은 식을 쓰고, 각 팔 테스트가 `run["arm_hash"] == current_hashes(cfg)[arm]` 로 묶는다.
- **잘못 쓴 선언은 실패** — 오타 하나로 가드가 꺼지지 않게, 모르는 키 · 팔, 중복 키, 64자 hex 가 아닌 지문,
  따옴표 날짜, start > end 를 모두 거부한다.

현재 지문은 `python -m nuri.llm.thesis_freeze` 로 출력한다(창 선언용).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from nuri.core.timezone import kst_now
from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_contract as tc
from nuri.llm import thesis_sim as sim

FREEZE_PATH = Path("config/thesis_freeze.yaml")
ARMS = ("A", "B", "S")
_HASH = re.compile(r"[0-9a-f]{64}")
_KEYS = {"experiment", "start", "end", "arms"}


@dataclass(frozen=True)
class Freeze:
    experiment: str
    start: date
    end: date
    arms: dict[str, str]


def current_hashes(cfg: dict[str, Any]) -> dict[str, str]:
    """원장에 기록되는 팔별 지문 — A 는 `run_baseline`, B 는 `arm_b_hash`, S 는 `run_arm_s` 와 같은 식."""
    return {
        "A": tc.definition_hash(tc.ARM_A_FILES, cfg, tc.ARM_A_TEXTS),
        "B": arm.arm_b_hash(cfg),
        "S": tc.definition_hash(
            sim.ARM_S_FILES, cfg, (tc._canonical(cfg.get("memory")), tc._canonical(cfg.get("sim")))
        ),
    }


def _date(value: Any, where: str) -> date:
    # 따옴표 날짜는 str, 시각까지 쓰면 datetime(date 의 하위형) — 둘 다 창 경계가 모호하다
    if type(value) is not date:
        raise ValueError(f"{where}: an unquoted YYYY-MM-DD date is required, got {type(value).__name__}")
    return value


def parse(doc: Any) -> list[Freeze]:
    if not isinstance(doc, dict) or set(doc) != {"freezes"} or not isinstance(doc["freezes"], list):
        raise ValueError("the freeze file holds exactly one key, 'freezes', a list")
    out: list[Freeze] = []
    for n, e in enumerate(doc["freezes"]):
        where = f"freezes[{n}]"
        if not isinstance(e, dict) or set(e) != _KEYS:
            raise ValueError(f"{where}: keys must be exactly {sorted(_KEYS)}")
        if not isinstance(e["experiment"], str) or not e["experiment"]:
            raise ValueError(f"{where}: experiment must be a non-empty string")
        start, end = _date(e["start"], f"{where}.start"), _date(e["end"], f"{where}.end")
        if start > end:
            raise ValueError(f"{where}: start is after end")
        arms = e["arms"]
        if not isinstance(arms, dict) or not arms or not set(arms) <= set(ARMS):
            raise ValueError(f"{where}: arms maps a non-empty subset of {list(ARMS)} to hashes")
        for k, h in arms.items():
            if not isinstance(h, str) or not _HASH.fullmatch(h):
                raise ValueError(f"{where}.arms.{k}: a 64-character lowercase hex hash is required")
        out.append(Freeze(e["experiment"], start, end, dict(arms)))
    return out


class _UniqueKeyLoader(yaml.SafeLoader):
    """중복 키를 거부한다 — `safe_load` 는 뒤 값으로 덮어써, 끝에 붙은 `freezes: []` 하나가 앞의 창을 지운다."""

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        dup = sorted({str(k) for k in keys if keys.count(k) > 1})
        if dup:
            raise ValueError(f"duplicate keys {dup} at line {node.start_mark.line + 1}")
        return super().construct_mapping(node, deep=deep)


def load(path: Path = FREEZE_PATH) -> list[Freeze]:
    with path.open() as f:
        return parse(yaml.load(f, Loader=_UniqueKeyLoader))


def violations(freezes: list[Freeze], today: date, hashes: dict[str, str]) -> list[str]:
    """오늘이 창 안(양 끝 포함)인 선언 중 지문이 달라진 팔."""
    return [
        f"{f.experiment} ({f.start}..{f.end}) arm {k}: frozen {h[:12]}, now {hashes[k][:12]}"
        for f in freezes
        if f.start <= today <= f.end
        for k, h in sorted(f.arms.items())
        if hashes[k] != h
    ]


def check(freeze_path: Path = FREEZE_PATH, config_path: Path = lc.CONFIG_PATH) -> list[str]:
    """오늘(KST 날짜) 기준 위반 — fast 테스트가 실제 파일로 부른다. `today_kst()` 는 문자열이라 쓰지 않는다."""
    return violations(load(freeze_path), kst_now().date(), current_hashes(lc.load_config(config_path)))


def main() -> int:
    print(json.dumps(current_hashes(lc.load_config()), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
