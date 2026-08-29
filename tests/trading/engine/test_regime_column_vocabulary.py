"""스키마의 모든 regime 계열 컬럼은 어휘가 분류돼 있어야 한다 (#1311, #1293 후속).

## 무엇이 사라졌었나

#1293 이 마지막 무가드 writer 를 닫으면서 `KNOWN_UNGUARDED` 가 비었다. 그 순간
"어휘가 `ALL_REGIMES` 인데 가드도 분류도 없는 **다음** writer 가 없다" 는 완결성
주장을 아무도 하지 않게 됐다 — 인벤토리 검사는 가드를 부르는 것들끼리의 정합성만
본다. 여기서 그 축을 복원한다: **스키마에서 regime 계열 컬럼을 기계적으로 유도**해
전부 분류를 요구한다. 새 컬럼이 생기면 분류 없이는 FAIL — 사람이 결정해야 한다.

## 분류는 writer 추적으로 정했다 — 테이블 내용이 아니라

빈 테이블은 계약을 알려주지 않는다 (`decisions.regime` 도 행 0인데 어휘 안).
미확정이던 5개 컬럼은 2026-08-29 writer 코드 추적(#1311)으로 확정했고, 각 항목의
근거는 인벤토리에 적었다. "모든 regime writer 에 가드" 는 여전히 틀린 원칙이다 —
`candidate_runs.regime` 은 `UNKNOWN_REGIME` 을, `strategy_memory.regime` 은 `'all'`
집계 sentinel 을 **의도적으로** 어휘 밖에서 쓴다. 목표는 전부 가드가 아니라
**전부 분류**다.

## enforcement 2종

- `guard`: writer 가 `canonical_regime_or_none()` 을 호출 —
  `test_regime_canonical_guard.py` 의 `CANONICAL_VOCAB_WRITERS` 가 함수 단위로 잠근다.
- `structural`: 값이 구조적으로 canonical — classifier 반환의 passthrough, 닫힌 dict,
  fail-closed 게이트. 가드 호출이 없으므로 여기의 canary 가 인용된 파일·심볼의
  실존을 검사해 인벤토리가 낡으면 FAIL 한다 (writer 를 못 찾았는데 "확정" 으로
  남는 상태를 금지 — Codex consult 지적).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.regime.classifier import ALL_REGIMES
from nuri.trading.strategy.longshort import REGIME_ALLOCATION
from tests.trading.engine.test_regime_canonical_guard import CANONICAL_VOCAB_WRITERS

NURI = Path(__file__).resolve().parents[3] / "nuri"

#: 스키마의 **모든** regime 계열 컬럼 분류. 키는 `table.column`.
#:
#: - `vocab="ALL_REGIMES"`: canonical 어휘(또는 NULL)만 도달 가능. `enforcement` 필수.
#: - `vocab="OUT_OF_VOCAB"`: 어휘 밖 값을 의도적으로 쓴다. `reason` 필수 (사유 + 이슈).
#: - `structural` 항목의 `writers`: {nuri 상대경로: (심볼, 근거)} — 심볼은 그 파일에서
#:   값의 canonical 성을 만드는 함수/dict 이름. canary 가 실존을 검사한다.
REGIME_COLUMN_VOCABULARY: dict[str, dict] = {
    "candidate_runs.regime": {
        "vocab": "OUT_OF_VOCAB",
        "reason": "UNKNOWN_REGIME('unknown') 을 정당하게 저장 — 미상을 어휘 안 이름으로 "
        "표기하면 배분 조회 .get() 이 조용히 값을 주는 사고(#1131)가 재발한다 (#1293 본문)",
    },
    "certifications.regime": {"vocab": "ALL_REGIMES", "enforcement": "guard"},
    "decisions.regime": {"vocab": "ALL_REGIMES", "enforcement": "guard"},
    "macro_events.regime_hint": {
        "vocab": "ALL_REGIMES",
        "enforcement": "structural",
        "writers": {
            "llm/event_classifier.py": (
                "REGIME_HINT_BY_CATEGORY",
                "값의 유일한 출처가 닫힌 dict — LLM 은 category 를 고를 뿐이고 미등록 "
                "category 는 neutral(NULL) 로 붕괴한다. NULL 은 '힌트 없음' (#1311 추적)",
            ),
        },
    },
    "market_postmortem.regime": {
        "vocab": "ALL_REGIMES",
        "enforcement": "structural",
        "writers": {
            "alerts/postmarket_brief.py": (
                "_persist_postmortem",
                "classify_regime() 반환의 passthrough — 분류 실패 경로는 NULL, free-text "
                "유입 경로 없음. 유일한 쓰기 경로 write_brief → upsert_postmortem (#1311 추적)",
            ),
        },
    },
    "positions.regime_at_entry": {
        "vocab": "ALL_REGIMES",
        "enforcement": "structural",
        "writers": {
            "trading/strategy/position.py": (
                "certify_position",
                "'unknown' fallback 이 코드에 있으나 INSERT 전 certify_position 의 "
                "REGIME_ALLOCATION fail-closed 게이트(미등록 레짐 차단)가 걸러낸다. "
                "REGIME_ALLOCATION 키 == ALL_REGIMES 는 아래 테스트가 잠근다 (#1311 추적)",
            ),
        },
    },
    "recommendations.regime": {"vocab": "ALL_REGIMES", "enforcement": "guard"},
    "regime_transitions.from_regime": {
        "vocab": "OUT_OF_VOCAB",
        "reason": "`prev_regime or 'unknown'` (strategy/monitor.py) — 최초 전환에서 직전 "
        "레짐 부재를 'unknown' 으로 기록한다. dev DB 실측 근거 있음 (#1311)",
    },
    "regime_transitions.to_regime": {
        "vocab": "ALL_REGIMES",
        "enforcement": "structural",
        "writers": {
            "trading/strategy/monitor.py": (
                "detect_regime_transition",
                "classify_regime() 반환의 passthrough — 분류기가 None 이면 전환 감지 전에 "
                "조기 반환해 INSERT 에 도달하지 않는다 (#1311 추적)",
            ),
        },
    },
    "strategy_memory.regime": {
        "vocab": "OUT_OF_VOCAB",
        "reason": "'all' 집계 sentinel (engine/decisions.py save_agent_accuracy_snapshot) — "
        "agent accuracy 행은 전 레짐 집계라 UNIQUE 키의 일부로 'all' 을 쓰고, 기간 rollup "
        "은 NULL, per-regime 행만 base regime 을 쓴다 (#1311 추적)",
    },
}


def _schema_regime_columns(tmp_path) -> set[str]:
    """라이브 스키마(전체 migration 적용)에서 regime 계열 컬럼을 유도한다."""
    path = tmp_path / "schema.db"
    init_db(path)
    found = set()
    with get_db(path) as conn:
        tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        for table in tables:
            for row in conn.execute(f"PRAGMA table_info({table})"):
                if "regime" in row[1].lower():
                    found.add(f"{table}.{row[1]}")
    return found


class TestEveryRegimeColumnIsClassified:
    def test_inventory_matches_the_schema(self, tmp_path):
        """양방향 — 새 regime 컬럼은 분류 없이는 FAIL, 사라진 컬럼은 stale 로 FAIL.

        기대 집합을 리터럴이 아니라 **스키마에서 유도**한다 — 목록을 줄여서 스윕을
        피할 수 없다 (`test_inventory_matches_the_code` 와 같은 원리).
        """
        schema = _schema_regime_columns(tmp_path)
        listed = set(REGIME_COLUMN_VOCABULARY)
        assert schema == listed, (
            f"regime 컬럼 분류가 스키마와 다르다.\n"
            f"  스키마에만 있음(미분류 — 사람이 결정할 것): {sorted(schema - listed)}\n"
            f"  목록에만 있음(stale): {sorted(listed - schema)}"
        )

    def test_every_entry_has_a_valid_shape(self):
        """ALL_REGIMES 는 enforcement 필수, OUT_OF_VOCAB 은 사유+이슈 필수."""
        for col, entry in sorted(REGIME_COLUMN_VOCABULARY.items()):
            vocab = entry["vocab"]
            assert vocab in ("ALL_REGIMES", "OUT_OF_VOCAB"), f"{col}: 미정의 vocab {vocab!r}"
            if vocab == "ALL_REGIMES":
                assert entry.get("enforcement") in ("guard", "structural"), (
                    f"{col}: ALL_REGIMES 인데 enforcement 가 없다 — 가드인지 구조인지 정할 것"
                )
            else:
                reason = entry.get("reason", "")
                assert len(reason) > 40, f"{col}: 사유가 너무 짧다 — 다음 사람이 판단할 수 없다"
                assert "#" in reason, f"{col}: 추적 이슈 번호가 없다"


class TestGuardEnforcedColumnsMatchTheGuardInventory:
    def test_two_inventories_agree(self):
        """enforcement='guard' 컬럼 집합 == `CANONICAL_VOCAB_WRITERS` 가 커버하는 컬럼 집합.

        양방향 — 가드 인벤토리에서 컬럼이 빠지면 여기가 FAIL 하고, 여기서 guard 로
        분류만 하고 가드 인벤토리에 안 올리면 역시 FAIL 한다. 두 목록이 서로를 잠근다.
        """
        declared = {
            col
            for col, e in REGIME_COLUMN_VOCABULARY.items()
            if e["vocab"] == "ALL_REGIMES" and e.get("enforcement") == "guard"
        }
        guarded = {e["column"] for e in CANONICAL_VOCAB_WRITERS.values()}
        assert declared == guarded, (
            f"guard 분류와 가드 인벤토리가 다르다.\n"
            f"  분류만 있음(가드 미등록): {sorted(declared - guarded)}\n"
            f"  가드만 있음(분류 누락/불일치): {sorted(guarded - declared)}"
        )


class TestStructuralWritersAreReal:
    """structural 주장의 canary — 인용한 파일·심볼이 실존하지 않으면 FAIL.

    writer 를 못 찾았는데 "확정" 으로 남는 인벤토리를 금지한다. 파일 이동/함수
    rename 시 여기가 깨져서 분류를 재검토하게 강제한다. 심볼 확인은 텍스트가 아니라
    AST — 주석/독스트링의 언급으로는 통과하지 않는다.
    """

    @staticmethod
    def _symbols(rel: str) -> set[str]:
        tree = ast.parse((NURI / rel).read_text(encoding="utf-8"))
        names: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
        return names

    @pytest.mark.parametrize(
        "col",
        sorted(c for c, e in REGIME_COLUMN_VOCABULARY.items() if e.get("enforcement") == "structural"),
    )
    def test_cited_file_and_symbol_exist(self, col):
        writers = REGIME_COLUMN_VOCABULARY[col].get("writers")
        assert writers, f"{col}: structural 인데 writer 인용이 없다"
        for rel, (symbol, why) in writers.items():
            assert (NURI / rel).exists(), f"{col}: 인용 파일이 없다 — {rel}"
            assert symbol in self._symbols(rel), (
                f"{col}: {rel} 에 심볼 {symbol!r} 이 없다 — writer 가 이동/rename 됐다면 분류를 재검토할 것"
            )
            assert len(why) > 40, f"{col}: 구조적 근거가 너무 짧다"

    def test_the_symbol_check_ignores_comments(self):
        """카나리아의 카나리아 — 텍스트 검사라면 주석 언급으로 통과했을 형태."""
        src = "# certify_position() 를 부른다\nx = 1\n"
        tree = ast.parse(src)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "certify_position" not in names
        assert "certify_position" in src  # 텍스트 검사라면 통과했을 대조군


class TestRegimeAllocationKeysAreExactlyAllRegimes:
    def test_key_sets_are_equal(self):
        """`positions.regime_at_entry` 의 structural 분류가 딛고 선 동치.

        certify_position 은 REGIME_ALLOCATION 에 없는 레짐을 fail-closed 로 차단한다 —
        그 게이트가 "canonical 만 통과" 를 뜻하려면 키 집합이 정확히 ALL_REGIMES 여야
        한다. 키가 하나라도 빠지면 canonical 레짐이 부당 차단되고(false-block), 어휘
        밖 키가 들어오면 그 이름이 컬럼까지 흘러든다(#1131 계열).
        """
        assert sorted(REGIME_ALLOCATION) == sorted(ALL_REGIMES), (
            f"REGIME_ALLOCATION 키가 ALL_REGIMES 와 다르다.\n"
            f"  배분에만 있음: {sorted(set(REGIME_ALLOCATION) - set(ALL_REGIMES))}\n"
            f"  어휘에만 있음: {sorted(set(ALL_REGIMES) - set(REGIME_ALLOCATION))}"
        )
