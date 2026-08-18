"""논지 원장 CLI — YAML 한 장을 읽어 `theses` 에 기록한다 (#1083).

**왜 CLI 가 필요한가**: `upsert_thesis` 만 있으면 원장은 파이썬을 여는 사람만 쓸 수 있고,
그러면 이 레포가 반복해 온 "배선은 됐는데 아무도 도달 못 하는" 상태가 된다
(`held_add_shadow` 테스트 통과 / 프로덕션 0행, `/api/alpha` 소비자 0).

**왜 플래그가 아니라 파일인가**: bull/bear 는 여러 문단이고 근거는 리스트다. 셸 인자로
받으면 줄바꿈이 죽고 따옴표 지옥이 된다.

```bash
python -m nuri.core.thesis_cli write docs/theses/nvda.yaml
python -m nuri.core.thesis_cli show NVDA
```

기본은 `status: draft` 다. `active` 승격은 파일에 명시할 때만 — LLM 초안이 사람 손을
거치지 않고 결정 화면에 사실처럼 실리면 안 된다 (STRATEGY §7.1).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import yaml

from nuri.core.db import (
    ThesisValidationError,
    add_criteria,
    get_active_thesis,
    get_thesis_history,
    upsert_thesis,
)


def _delete_thesis(thesis_id: int, db_path: Optional[Path]) -> None:
    """기준 등록 실패 시 논지를 되돌린다 — 반증 없는 논지를 남기지 않기 위해."""
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        conn.execute("DELETE FROM theses WHERE id = ?", (thesis_id,))


#: 파일에 반드시 있어야 하는 키. 없으면 어떤 것이 빠졌는지 한 번에 말한다 —
#: KeyError 하나씩 뱉으면 사용자가 파일을 여러 번 고쳐야 한다.
REQUIRED = ("ticker", "author", "stance", "bull_case", "bear_case", "evidence", "criteria")


def load_thesis_file(path: Path) -> dict:
    """YAML → `upsert_thesis` kwargs. 누락 키는 전부 모아서 한 번에 보고."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 최상위가 매핑이 아니다")
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f"{path}: 필수 키 누락 — {', '.join(missing)}")
    return {
        "ticker": str(data["ticker"]).upper(),
        "author": str(data["author"]),
        "stance": str(data["stance"]),
        "bull_case": str(data["bull_case"]),
        "bear_case": str(data["bear_case"]),
        "evidence": list(data["evidence"]),
        "criteria": list(data["criteria"]),
        "effective_date": data.get("effective_date"),
        "status": str(data.get("status", "draft")),
    }


def _cmd_write(path: Path, db_path: Optional[Path]) -> int:
    try:
        kwargs = load_thesis_file(path)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    criteria = kwargs.pop("criteria")
    try:
        thesis_id = upsert_thesis(db_path=db_path, **kwargs)
        # 기준 등록이 실패하면 **반증 없는 논지**가 남는다 — 그건 이 시스템이 막으려는
        # 상태 자체라, 논지를 되돌리고 통째로 거부한다.
        try:
            n_criteria = add_criteria(thesis_id, criteria, db_path=db_path)
        except ThesisValidationError:
            _delete_thesis(thesis_id, db_path)
            raise
    except ThesisValidationError as e:
        # 검증 실패는 사용자 입력 문제지 버그가 아니다 — traceback 없이 이유만.
        print(f"✗ 논지 거부: {e}", file=sys.stderr)
        return 1
    print(f"✓ {kwargs['ticker']} 논지 기록 — id={thesis_id} status={kwargs['status']} 반증기준 {n_criteria}건")
    if kwargs["status"] == "draft":
        print("  draft 는 결정 화면에 붙지 않는다. 승격하려면 파일에 status: active 로 다시 기록.")
    return 0


def _cmd_show(ticker: str, db_path: Optional[Path]) -> int:
    active = get_active_thesis(ticker, db_path=db_path)
    history = get_thesis_history(ticker, db_path=db_path)
    if not history:
        print(f"{ticker}: 기록된 논지 없음")
        return 0
    print(f"{ticker} — {len(history)}개 버전")
    for h in history:
        mark = "→" if active and h["id"] == active["id"] else " "
        print(f" {mark} v{h['version']} {h['effective_date']} {h['status']:<10} {h['author']}")
    if active:
        print(f"\n상승: {active['bull_case']}")
        print(f"하락: {active['bear_case']}")
        print(f"근거 {len(active['evidence'])}건")
        criteria = active.get("criteria") or []
        print(f"반증 기준 {len(criteria)}건 — 이게 사실이면 이 판단은 틀린 것:")
        for c in criteria:
            state = c["last_result"] or "미점검"
            expr = f"{c['metric']} {c['op']} {c['threshold']:g}" if c["kind"] == "machine" else "사람 판정"
            print(f"  [{state:11s}] {c['statement']}  ({expr})")
    else:
        print("\n현재 유효한 논지 없음 (draft 만 있거나 effective_date 가 미래)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="논지 원장 (#1083)")
    parser.add_argument("--db-path", type=Path, default=None, help="DB 경로 (기본: 프로덕션)")
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("write", help="YAML 파일에서 논지 기록")
    w.add_argument("path", type=Path)

    s = sub.add_parser("show", help="티커의 논지 이력 + 현재 유효 논지")
    s.add_argument("ticker")

    args = parser.parse_args(argv)
    if args.command == "write":
        return _cmd_write(args.path, args.db_path)
    return _cmd_show(args.ticker.upper(), args.db_path)


if __name__ == "__main__":
    sys.exit(main())
