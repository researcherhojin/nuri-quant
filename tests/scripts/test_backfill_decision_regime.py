"""Tests for scripts/ops/backfill_decision_regime.py — decisions.regime 백필 (#1264).

Gotcha-Test Pair: 이 백필의 위험은 "채우는 것" 이 아니라 **채우면 안 되는 행을 채우는
것**이다. 소스가 없거나 어휘 밖이면 NULL 이 정답이고, 그 규칙이 지워지면 원장에
사후 추정값이 들어간다.

tmp_path DB 격리 (tests/CLAUDE.md), 티커는 전부 합성 placeholder (privacy).
"""

from __future__ import annotations

import json

import pytest

from nuri.core.db import get_db, init_db, query
from scripts.ops.backfill_decision_regime import backfill_decision_regime


def _verdicts(regime) -> str:
    """실 writer 형태를 복사한다 — 10-agent 배열이고 macro 만 regime 을 담는다.

    잘못된 형태의 mock 은 버그를 잠근다(#1180). 배열 안에서 macro 의 **위치도 고정하지
    않는다** — 스크립트가 인덱스가 아니라 `json_each` 로 찾는다는 계약을 같이 지킨다.
    """
    macro = {
        "agent_name": "macro",
        "ticker": "TST_A",
        "action": "HOLD",
        "confidence": 60.0,
        "reasoning": "합성",
        "data_points": {"macro_score": 55.0, "confidence_pct": 60.0},
    }
    if regime is not None:
        macro["data_points"]["regime"] = regime
    other = {
        "agent_name": "technical",
        "ticker": "TST_A",
        "action": "HOLD",
        "confidence": 50.0,
        "reasoning": "합성",
        "data_points": {"rsi": 50.0},
    }
    return json.dumps([other, macro, other], ensure_ascii=False)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed(db_path, ticker, *, regime_col, verdicts, date="2026-05-01"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO decisions (date, ticker, action, confidence, regime, agent_verdicts)"
            " VALUES (?, ?, 'HOLD', 50.0, ?, ?)",
            (date, ticker, regime_col, verdicts),
        )


def _regime_of(db_path, ticker):
    return query("SELECT regime FROM decisions WHERE ticker = ?", (ticker,), db_path=db_path)[0]["regime"]


def test_backfills_canonical_value_from_the_row(db_path):
    """행 안의 macro verdict 가 canonical 이면 컬럼으로 복사된다."""
    _seed(db_path, "TST_A", regime_col=None, verdicts=_verdicts("bull_low_vol"))

    stats = backfill_decision_regime(db_path=db_path)

    assert stats["backfilled"] == 1
    assert _regime_of(db_path, "TST_A") == "bull_low_vol"


def test_missing_macro_regime_stays_null(db_path):
    """macro verdict 에 regime 이 없는 행은 백필 후에도 NULL 이다.

    lossy retrofit 금지 잠금 (`db_migrations.py` 의 forward-only NULL 정책과 같은 축).
    소스가 없을 때 무엇이든 지어내면 원장이 사후 추정값을 사실처럼 담게 된다.

    Mutation lock: `src is None` 분기를 지우고 기본값을 넣으면 FAIL.
    """
    _seed(db_path, "TST_A", regime_col=None, verdicts=_verdicts(None))
    _seed(db_path, "TST_B", regime_col=None, verdicts=None)  # agent_verdicts 자체가 없는 행

    stats = backfill_decision_regime(db_path=db_path)

    assert stats["backfilled"] == 0
    assert stats["no_source"] == 2
    assert _regime_of(db_path, "TST_A") is None
    assert _regime_of(db_path, "TST_B") is None


def test_non_canonical_value_is_not_written(db_path):
    """free-text / 빈 문자열은 기록하지 않는다 — 어휘 밖 값은 NULL 로 둔다.

    `recommendations.regime` 이 '' 와 '[recovery] 비중 축소' 를 실제로 담고 있었다(#832).
    같은 오염을 `decisions` 로 옮기지 않는다.

    Mutation lock: `src in ALL_REGIMES` 검사를 지우면 FAIL.
    """
    _seed(db_path, "TST_A", regime_col=None, verdicts=_verdicts("[recovery] 비중 축소"))
    _seed(db_path, "TST_B", regime_col=None, verdicts=_verdicts(""))

    stats = backfill_decision_regime(db_path=db_path)

    assert stats["backfilled"] == 0
    assert stats["non_canonical"] == 2
    assert _regime_of(db_path, "TST_A") is None
    assert _regime_of(db_path, "TST_B") is None


def test_one_malformed_row_does_not_abort_the_backfill(db_path):
    """깨진 `agent_verdicts` 한 행이 백필 전체를 죽이면 안 된다.

    `json_each` 는 깨진 JSON 을 만나면 그 행을 건너뛰는 게 아니라
    `OperationalError: malformed JSON` 으로 **쿼리째** 죽인다 — 가드가 없으면 행 하나가
    나머지 386행의 백필을 막는다. `pipeline_events.payload` 가 같은 모양으로 당했고
    (`nuri/core/CLAUDE.md`), 이 컬럼은 프로덕션 읽기 경로도 이미 깨진 JSON 을 방어한다
    (`test_decisions.py::test_regime_malformed_json_swallowed`) — 실재하는 입력이다.

    Mutation lock: `_EXTRACT_REGIME` 의 `CASE WHEN json_valid(...)` 가드를 걷어내면
    OperationalError 로 FAIL.
    """
    _seed(db_path, "TST_OK", regime_col=None, verdicts=_verdicts("bull_low_vol"))
    _seed(db_path, "TST_BAD", regime_col=None, verdicts="이건 JSON 이 아니다")
    _seed(db_path, "TST_OBJ", regime_col=None, verdicts='{"agent_name": "macro"}')  # 배열 아닌 객체
    # 스칼라 JSON — `isinstance(parsed, list)` 검사가 없으면 `for item in 5` 가 TypeError 로
    # 백필 전체를 죽인다. 객체/문자열로는 이 축이 안 잡힌다(순회는 되고 결과가 같다).
    _seed(db_path, "TST_NUM", regime_col=None, verdicts="5")

    stats = backfill_decision_regime(db_path=db_path)

    # 멀쩡한 행은 그대로 채워진다 — 깨진 이웃이 막지 않는다.
    assert _regime_of(db_path, "TST_OK") == "bull_low_vol"
    assert stats["backfilled"] == 1
    assert stats["malformed"] == 1
    assert stats["no_source"] == 2  # 객체 + 스칼라
    assert _regime_of(db_path, "TST_BAD") is None
    assert _regime_of(db_path, "TST_OBJ") is None
    assert _regime_of(db_path, "TST_NUM") is None


def test_only_the_macro_agent_supplies_the_regime(db_path):
    """다른 에이전트가 `data_points.regime` 을 담아도 그 값을 쓰지 않는다 (Codex P2).

    "regime 을 담은 첫 verdict" 로 두면 어느 에이전트의 값인지가 **데이터 모양에 달린
    가정**이 된다. 다른 에이전트가 같은 키를 쓰기 시작하면 조용히 그쪽 값이 원장에 박힌다.
    provenance 는 가정이 아니라 이름으로 강제한다.

    Mutation lock: `item.get("agent_name") != _REGIME_AGENT` 검사를 지우면 배열 앞쪽의
    non-macro 값이 채택돼 FAIL.
    """
    verdicts = json.dumps(
        [
            # macro 보다 **앞에** 있고 같은 키를 담는다 — 순서로 이기지 못하게 한다.
            {"agent_name": "technical", "data_points": {"regime": "bear_high_vol"}},
            {"agent_name": "macro", "data_points": {"regime": "bull_low_vol"}},
        ],
        ensure_ascii=False,
    )
    _seed(db_path, "TST_A", regime_col=None, verdicts=verdicts)

    backfill_decision_regime(db_path=db_path)

    assert _regime_of(db_path, "TST_A") == "bull_low_vol"


def test_regime_from_a_non_macro_agent_alone_is_not_used(db_path):
    """macro 가 없고 다른 에이전트만 regime 을 담은 행은 NULL 을 유지한다."""
    verdicts = json.dumps([{"agent_name": "technical", "data_points": {"regime": "bull_low_vol"}}])
    _seed(db_path, "TST_A", regime_col=None, verdicts=verdicts)

    stats = backfill_decision_regime(db_path=db_path)

    assert stats["backfilled"] == 0
    assert stats["no_source"] == 1
    assert _regime_of(db_path, "TST_A") is None


def test_idempotent_rerun_skips_existing(db_path):
    """재실행은 write 0 — 이미 canonical 인 행은 후보가 아니다.

    Mutation lock: 후보 쿼리에서 `WHERE d.regime IS NULL` 을 지우면 2회차 candidates 가
    0 이 아니게 되어 FAIL.
    """
    _seed(db_path, "TST_A", regime_col=None, verdicts=_verdicts("bull_low_vol"))

    first = backfill_decision_regime(db_path=db_path)
    second = backfill_decision_regime(db_path=db_path)

    assert first["backfilled"] == 1
    assert second["candidates"] == 0
    assert second["backfilled"] == 0
    assert _regime_of(db_path, "TST_A") == "bull_low_vol"


def test_existing_canonical_value_is_never_overwritten(db_path):
    """이미 라벨된 행은 소스와 달라도 건드리지 않는다 — 백필은 채우기지 재작성이 아니다."""
    _seed(db_path, "TST_A", regime_col="sideways_low_vol", verdicts=_verdicts("bull_low_vol"))

    backfill_decision_regime(db_path=db_path)

    assert _regime_of(db_path, "TST_A") == "sideways_low_vol"


def test_dry_run_writes_nothing(db_path):
    """--dry-run 은 카운트만 낸다."""
    _seed(db_path, "TST_A", regime_col=None, verdicts=_verdicts("bull_low_vol"))

    stats = backfill_decision_regime(db_path=db_path, dry_run=True)

    assert stats["backfilled"] == 1  # 예정 건수는 보고한다
    assert _regime_of(db_path, "TST_A") is None  # 그러나 원장은 그대로
    assert "dry-run" in stats["coverage_after"]
