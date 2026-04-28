"""Recent SIEGE certification runs — 반복 작업 중 이전 verdict 와 비교용.

E4-0a 이후 `certifications` 테이블에 매 실행이 persist. 이 스크립트가 조회 +
diff 하이라이트. 사용:

    make certify-history              # 최근 10건
    make certify-history N=20         # 최근 20건
    python scripts/siege_history.py --detail  # 각 row 의 conditions JSON 전체
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nuri.core.db import query


def _fmt_bool(b: int) -> str:
    return "✅ CERTIFIED" if b else "❌ REJECTED"


def _fmt_timestamp(ts: str) -> str:
    # 2026-04-20T17:11:03.115012+09:00 → 04-20 17:11:03
    return ts[5:19].replace("T", " ")


def _failing_gates(conditions_json: str) -> list[str]:
    conds = json.loads(conditions_json or "[]")
    return [c["id"] for c in conds if not c.get("passed")]


def _error_gates(conditions_json: str) -> list[str]:
    conds = json.loads(conditions_json or "[]")
    return [c["id"] for c in conds if not c.get("passed") and c.get("severity") == "error"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", "-n", type=int, default=10, help="최근 N건 (default 10)")
    parser.add_argument("--detail", action="store_true", help="각 row 의 조건 전체 출력")
    parser.add_argument("--caller", help="caller 필터 (예: cli, api:actions:health)")
    args = parser.parse_args()

    sql = """
        SELECT id, timestamp, certified, score, total_conditions, passed, failed, warnings,
               regime, portfolio_hash, conditions_json, caller
        FROM certifications
    """
    params: list = []
    if args.caller:
        sql += " WHERE caller = ?"
        params.append(args.caller)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(args.limit)

    rows = query(sql, tuple(params))

    if not rows:
        print("certifications 테이블 비어있음. `make certify` 1회 실행 후 재시도.")
        return 0

    print(f"최근 {len(rows)}건 SIEGE certification:")
    print(f"{'─' * 80}")
    print(f"{'id':>4}  {'time':<14}  {'verdict':<14}  {'score':>5}  {'P/F/W':<10}  {'regime':<20}  caller")
    print(f"{'─' * 80}")

    prev_hash = None
    for row in rows:
        hash_short = (row["portfolio_hash"] or "")[:8]
        hash_tag = "" if prev_hash is None or prev_hash == row["portfolio_hash"] else " *"
        prev_hash = row["portfolio_hash"]

        print(
            f"{row['id']:>4}  "
            f"{_fmt_timestamp(row['timestamp']):<14}  "
            f"{_fmt_bool(row['certified']):<14}  "
            f"{row['score']:>5}  "
            f"{row['passed']}/{row['failed']}/{row['warnings']:<6}  "
            f"{(row['regime'] or '-'):<20}  "
            f"{row['caller'] or '-'}"
            f"{hash_tag}"
        )

        errors = _error_gates(row["conditions_json"])
        if errors:
            print(f"      ❌ error gates: {', '.join(errors)}")
        if args.detail:
            failing = _failing_gates(row["conditions_json"])
            if failing:
                print(f"      ⚠  failing: {', '.join(failing)}")
            print(f"      hash: {hash_short}...")

    print(f"{'─' * 80}")
    print("범례: * = 이전 row 와 portfolio_hash 다름 (portfolio state 변경 감지)")
    print(f"전체 rows: {query('SELECT COUNT(*) AS c FROM certifications')[0]['c']}")
    print("반복 작업: `make certify` 실행 후 이 명령으로 변화 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
