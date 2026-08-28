"""decisions.regime 백필 — 행 내부 `agent_verdicts` 에서 복사 (#1264).

#1258 이전 epoch 의 `decisions.regime` 은 NULL 이다 (그 시점 writer 가 컬럼을 채우지
않았다). 값은 **이미 같은 행 안에 있다** — 합의 배치가 `agent_verdicts` 에 macro
에이전트의 verdict 를 통째로 저장했고, 그 `data_points.regime` 이 그날 라이브로 쓰인
레짐이다. 이 스크립트는 그 값을 컬럼으로 옮긴다.

**왜 이 소스인가** (#1264 에서 후보 4개 중 3개 탈락):

- `reasoning` 정규식 → supporter-only 산문이라 커버리지가 action 에 상관 (SELL 76행 중 1행)
- `recommendations` join → 같은 run 이지만 **다른 함수의 별도 `classify_regime()` 호출**
- `classify_regime(date=...)` 재실행 → freshness 게이트가 `if date is None` 안에 있어
  날짜를 주면 우회되고, `prices`/`macro` 는 INSERT OR REPLACE 라 vintage 가 없다.
  **라이브가 내지 않기로 한 라벨을 제조**하게 된다

PIT 관점: 미래 데이터로 역추정하는 게 아니라 같은 결정 산출물 안에 이미 포착된 동시대
값을 **행 안에서 복사**하는 것이다. `db_migrations.py` 의 "legacy row 는 NULL 유지 —
lossy retrofit 금지" 는 신규 스키마를 휴리스틱 추정으로 채우지 말라는 규정이라, 행 내부
canonical 값의 결정론적 복사는 그 사정거리 밖이다.

⚠️ **비대칭을 남긴다 — 의도한 것이다.** post-#1258 행은 `decision_evidence` 에
`source_type='regime'` 뒷받침 행을 갖지만, 백필된 행은 갖지 않는다. evidence 행까지
만들면 사후 복사를 **라이브 증거로 위장**하게 되므로 만들지 않는다. 원장을 읽는 쪽은
"regime 은 있는데 evidence 가 없는 행 = 백필된 행" 으로 구분할 수 있다.

원장은 **prod(Mac mini) 단일 적용** — dev 는 read-replica 다 (STRATEGY §3.11).

사용법:
    .venv/bin/python scripts/ops/backfill_decision_regime.py --dry-run   # write 없음
    .venv/bin/python scripts/ops/backfill_decision_regime.py             # 실제 백필
"""

from __future__ import annotations

import argparse
import json
import logging

logger = logging.getLogger(__name__)


#: regime 을 내는 에이전트. **이름으로 강제한다** — "regime 을 담은 첫 verdict" 로 두면
#: 어느 에이전트의 값인지가 데이터 모양에 달린 가정이 되고, 다른 에이전트가 같은 키를
#: 쓰기 시작하면 조용히 그쪽 값을 백필한다 (Codex P2). dev 원장 실측: 두 방식의 결과가
#: 364행 전부 동일하고 regime 을 담은 에이전트는 macro 뿐이라, 강제해도 커버리지 손실 0.
_REGIME_AGENT = "macro"


def _regime_from_verdicts(parsed) -> str | None:
    """verdict 배열에서 **macro** 에이전트의 `data_points.regime`. 형태가 다르면 None.

    배열 인덱스를 고정하지 않는다 — 에이전트 순서는 계약이 아니라서 이름으로 찾는다.
    배열이 아니거나 원소가 dict 가 아니면 소스 없음으로 본다.

    ⚠️ **추출을 SQL 로 하지 않는다.** `json_each` 는 깨진 JSON 을 만나면 그 행을 건너뛰는
    게 아니라 `OperationalError: malformed JSON` 으로 **쿼리 전체를 죽인다** — 행 하나가
    백필 전체를 막는다. dev 원장에 실제로 그런 행이 1건 있다(id 20, `json_type` 은
    'array' 인데 `json_valid` 는 0). `CASE WHEN json_valid(...)` 로 감싸도 소용없다:
    최상위가 객체이거나 배열 원소에 문자열이 섞이면 가드를 통과한 뒤 `json_extract` 가
    같은 예외로 죽는다(실측). `pipeline_events.payload` 가 같은 모양으로 당했고
    (`nuri/core/CLAUDE.md`), 이 컬럼은 프로덕션 읽기 경로도 이미 깨진 JSON 을 방어한다
    (`test_decisions.py::test_regime_malformed_json_swallowed`) — 실재하는 입력이다.
    """
    if not isinstance(parsed, list):
        return None
    for item in parsed:
        if not isinstance(item, dict) or item.get("agent_name") != _REGIME_AGENT:
            continue
        data_points = item.get("data_points")
        if isinstance(data_points, dict) and data_points.get("regime") is not None:
            return data_points["regime"]
    return None


def _coverage(db_path=None) -> tuple[int, int]:
    """(regime 이 canonical 인 행 수, 전체 행 수)."""
    from nuri.core.db import query
    from nuri.quant.regime.classifier import ALL_REGIMES

    placeholders = ",".join("?" * len(ALL_REGIMES))
    total = query("SELECT COUNT(*) AS c FROM decisions", db_path=db_path)[0]["c"]
    labeled = query(
        f"SELECT COUNT(*) AS c FROM decisions WHERE regime IN ({placeholders})",
        tuple(ALL_REGIMES),
        db_path=db_path,
    )[0]["c"]
    return labeled, total


def backfill_decision_regime(db_path=None, dry_run: bool = False) -> dict:
    """NULL 인 `decisions.regime` 을 같은 행의 `agent_verdicts` 에서 복사.

    canonical 값이 이미 있는 행은 건드리지 않는다(멱등). 추출값이 `ALL_REGIMES` 멤버가
    아니면(free-text·빈문자열·부재) **NULL 을 유지한다** — 어휘 밖 값을 원장에 넣지 않는다.

    Returns:
        stats dict — candidates / backfilled / no_source / non_canonical / malformed /
        coverage_before / coverage_after
    """
    from nuri.core.db import get_db, query
    from nuri.quant.regime.classifier import ALL_REGIMES

    labeled_before, total = _coverage(db_path)

    # canonical 이 이미 있는 행은 후보가 아니다 — 재실행이 write 0 이 되는 지점.
    rows = query(
        "SELECT id, agent_verdicts FROM decisions WHERE regime IS NULL",
        db_path=db_path,
    )

    updates: list[tuple[str, int]] = []
    no_source = 0  # agent_verdicts 부재 또는 regime 을 담은 verdict 없음 → NULL 유지
    non_canonical = 0  # 값은 있는데 어휘 밖 → NULL 유지
    malformed = 0  # agent_verdicts 가 깨진 JSON → NULL 유지 (운영자에게 따로 보고한다)
    for r in rows:
        raw = r["agent_verdicts"]
        if raw is None:
            no_source += 1
            continue
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            malformed += 1
            continue

        src = _regime_from_verdicts(parsed)
        if src is None:
            no_source += 1
        elif src in ALL_REGIMES:
            updates.append((src, r["id"]))
        else:
            non_canonical += 1

    if updates and not dry_run:
        with get_db(db_path) as conn:
            conn.executemany("UPDATE decisions SET regime = ? WHERE id = ?", updates)

    labeled_after = labeled_before if dry_run else _coverage(db_path)[0]
    return {
        "candidates": len(rows),
        "backfilled": len(updates),
        "no_source": no_source,
        "non_canonical": non_canonical,
        "malformed": malformed,
        "coverage_before": f"{labeled_before}/{total}",
        "coverage_after": f"{labeled_after}/{total}" + (" (dry-run, write 없음)" if dry_run else ""),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="decisions.regime 백필 — agent_verdicts 에서 복사 (#1264)")
    parser.add_argument("--dry-run", action="store_true", help="DB write 없이 변경 예정 카운트만 출력")
    args = parser.parse_args(argv)

    stats = backfill_decision_regime(dry_run=args.dry_run)
    print(f"백필 대상 행 (regime IS NULL): {stats['candidates']}")
    print(f"  canonical 복사: {stats['backfilled']}")
    print(f"  소스 없음 → NULL 유지: {stats['no_source']}")
    print(f"  어휘 밖 값 → NULL 유지: {stats['non_canonical']}")
    print(f"  agent_verdicts 깨진 JSON → NULL 유지: {stats['malformed']}")
    print(f"커버리지: {stats['coverage_before']} → {stats['coverage_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
