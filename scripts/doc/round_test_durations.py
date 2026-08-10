#!/usr/bin/env python3
"""`.test_durations` 의 소수 자릿수를 4자리로 고정한다.

**왜 필요한가** — pytest-split 이 쓰는 원본은 `0.0016861240146681666` 같은 full-precision
float 이다. privacy 스캐너(`scripts/verify/check_privacy_leak.py`)는 민감 키가 있는 줄에서
`\\b\\d{7,}\\b` 를 찾는데, 소수점이 word boundary 라 `0016861240146681666` 이 19자리 런으로
잡힌다. `cash_balance` 가 이름에 든 테스트 3개가 정확히 그렇게 걸려 CI 를 막았다 (2026-08-10).

allowlist 로 파일을 통째 면제하는 대신 자릿수를 줄인다 — `ALLOWLIST_PATHS` 는 파일 **전체**를
빼버리는 알려진 맹점(#981)이고, 여기 넣으면 그 맹점을 넓히는 셈이다.

4자리면 최장 런이 4자리(정수부 최대 2자리 + 소수부 4자리, 소수점으로 분리)라 안전하고,
shard 균형에도 영향이 없다 — 실측 1.10x 로 반올림 전후 동일. 부수 효과로 파일이 작아진다
(804KB → 692KB).

`round()` 가 아니라 **문자열 포맷**을 쓴다: `round(0.2848, 4)` 가 float repr 을 거치며
`0.28480000000000005` 로 되살아나 다시 7자리를 넘길 수 있다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DECIMALS = 4


def round_file(path: Path) -> tuple[int, int, int]:
    """자릿수를 고정해 덮어쓴다. `(항목 수, 이전 바이트, 이후 바이트)` 를 돌려준다."""
    before = path.stat().st_size
    data = json.loads(path.read_text())
    body = ",\n ".join(f"{json.dumps(k)}: {v:.{DECIMALS}f}" for k, v in data.items())
    path.write_text("{\n " + body + "\n}\n")
    return len(data), before, path.stat().st_size


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(".test_durations")
    if not path.exists():
        print(f"✗ {path} 없음 — 먼저 `make sync-test-durations` 로 생성할 것", file=sys.stderr)
        return 1
    n, before, after = round_file(path)
    print(f"✓ {path}: {n} entries, {before / 1024:.0f}KB → {after / 1024:.0f}KB ({DECIMALS} decimals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
