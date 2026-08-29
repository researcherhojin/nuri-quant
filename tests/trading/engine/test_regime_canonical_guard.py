"""`decisions.regime` 도 canonical 어휘만 받는다 — 형제 writer 2곳과 대칭 (#1268).

## 무엇이 잘못됐었나

같은 값을 쓰는 writer 3곳 중 **한 곳만** 정규화 가드를 안 통과했다:

| writer | 가드 |
|---|---|
| `recommend/tracker.py` · `agents/consensus/persistence.py` | `canonical_regime_or_none()` ✅ |
| `engine/decisions.py` | raw ❌ |

그리고 이슈가 지목한 것보다 **경로가 하나 더 있었다.** `_snapshot_market_context` 는
regime 을 두 곳에서 채운다:

1. `pipeline_events` 의 `regime_changed` payload — **다른 생산자가 쓴 임의 JSON**
2. `classify_regime()` fallback (#1256) — 분류기가 canonical 을 돌려주므로 낮은 위험

이슈는 2번만 적었는데 **1번이 더 위험하다**: `#832` 가 `canonical_regime_or_none` 을
만든 이유가 정확히 그 free-text 유입이었다 (`"" / "[recovery] 비중 축소"` 가 실제 사례).

## 왜 어휘 밖 문자열이 위험한가

`UNKNOWN_REGIME = "unknown"` 은 **의도적으로 `ALL_REGIMES` 밖**이다. 어휘 밖 값이
미상을 뜻하는 게 아니라 **표에 존재하는 다른 이름**으로 새면, 배분 조회의
`.get(key, default)` 가 조용히 값을 준다 — #1131 에서 미상이 `"neutral"` 로 표기돼
`buy_signals.yaml` 의 `total_pct_by_regime` 에서 **가장 공격적인 0.40 배분**을 받았다.

## 이 결함의 증거는 레포 안에 있었다

기존 테스트 픽스처가 `"risk_on"` / `"risk_off"` 를 썼다 — 둘 다 `ALL_REGIMES` 에 없는,
그럴듯하게 들리는 **지어낸 이름**이다. 무가드 동작을 테스트가 잠그고 있었던 셈이고,
사람이 어휘 밖 이름을 자연스럽게 만들어낸다는 증거이기도 하다.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.regime.classifier import ALL_REGIMES

NURI = Path(__file__).resolve().parents[3] / "nuri"

#: 어휘 밖이지만 **그럴듯한** 이름들. 사람이 실제로 만들어내는 형태다.
PLAUSIBLE_BUT_WRONG = ["risk_on", "risk_off", "neutral", "bull", "bear", "", "[recovery] 비중 축소"]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "d.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _seed_regime_event(db_path, value):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (timestamp, event_type, payload) VALUES (?, ?, ?)",
            ("2026-08-29T10:00:00", "regime_changed", json.dumps({"regime": value})),
        )


class TestFreeTextNeverReachesTheColumn:
    """이슈가 안 적은 경로 — `pipeline_events` payload 는 임의 JSON 이다."""

    @pytest.mark.parametrize("value", PLAUSIBLE_BUT_WRONG)
    def test_non_canonical_payload_is_dropped(self, db, value, monkeypatch):
        """Mutation lock: 정규화를 지우면 이 값들이 그대로 컬럼에 들어가 FAIL."""
        import nuri.quant.regime.classifier as classifier
        from nuri.trading.engine.decisions import _snapshot_market_context

        # fallback 분류기를 죽여 **payload 경로만** 본다 — 안 그러면 빈 DB 의 분류기
        # 결과에 따라 결과가 흔들린다 (주변 상태 의존, 기존 테스트가 밟은 함정).
        monkeypatch.setattr(classifier, "classify_regime", lambda db_path=None: None)
        _seed_regime_event(db, value)
        ctx = _snapshot_market_context(db_path=db)
        assert ctx.get("regime") is None, f"어휘 밖 값이 통과했다: {value!r}"

    @pytest.mark.parametrize("value", sorted(ALL_REGIMES))
    def test_canonical_payload_survives(self, db, value, monkeypatch):
        """대조군 — 정상 값까지 떨구는 가짜 수정을 막는다.

        `ALL_REGIMES` **전부**를 돈다: 일부만 통과시키는 구현도 잡는다.
        """
        import nuri.quant.regime.classifier as classifier
        from nuri.trading.engine.decisions import _snapshot_market_context

        monkeypatch.setattr(classifier, "classify_regime", lambda db_path=None: None)
        _seed_regime_event(db, value)
        ctx = _snapshot_market_context(db_path=db)
        assert ctx["regime"] == value

    def test_absent_regime_leaves_the_key_unset(self, db, monkeypatch):
        """계약 유지 — "모르면 키 자체가 없다". 소비자가 `"regime" not in ctx` 로 본다.

        `None` 을 넣는 구현으로 바꾸면 이 단언이 FAIL 한다. 기능은 같지만 계약이 다르다.
        """
        import nuri.quant.regime.classifier as classifier
        from nuri.trading.engine.decisions import _snapshot_market_context

        monkeypatch.setattr(classifier, "classify_regime", lambda db_path=None: None)
        _seed_regime_event(db, "risk_on")
        ctx = _snapshot_market_context(db_path=db)
        assert "regime" not in ctx


#: **어휘가 `ALL_REGIMES` 인 컬럼**의 writer 만 대상이다.
#:
#: "모든 regime writer 에 가드" 는 **틀린 원칙**이다 — `candidate_runs.regime` 은
#: `UNKNOWN_REGIME`("unknown") 을 정당하게 저장하는데, 그 값은 **의도적으로**
#: `ALL_REGIMES` 밖이다 (미상을 어휘 안 이름으로 표기하지 않으려고 그렇게 만들었다).
#: 그 컬럼까지 가드를 걸면 미상을 표현할 방법이 사라진다.
#:
#: 값의 `functions` 는 **가드를 부르는 함수 이름**이다. 파일 단위로만 세면 같은 파일
#: 어딘가의 죽은 호출 하나로 검사가 만족되고 정작 쓰기 경로는 무가드일 수 있다
#: (Codex P3, PR #1294). 이 레포가 반복해서 밟는 "눈 없는 스윕" 이라 함수까지 내린다.
CANONICAL_VOCAB_WRITERS: dict[str, dict] = {
    "trading/recommend/tracker.py": {
        "column": "recommendations.regime",
        "functions": ("save_buy_candidates", "save_recommendations"),
    },
    "trading/agents/consensus/persistence.py": {
        "column": "recommendations.regime",
        "functions": ("save_to_recommendations",),
    },
    "trading/engine/decisions.py": {
        "column": "decisions.regime",
        "functions": ("_snapshot_market_context",),
    },
    # #1293 — 여기가 셋 중 위험이 가장 컸다: 행수가 decisions 의 12배(4,525)이고, 값이
    # `regime_overrides.get(regime, {})` 라는 **조용한 기본값** 경로로 간다.
    "trading/engine/certification.py": {
        "column": "certifications.regime",
        "functions": ("_classify_regime_fresh",),
    },
}

#: 같은 어휘를 쓰는데 **아직 가드가 없는** writer. 사유와 추적 이슈를 함께 적는다.
#: 양방향 검사라 고치고 나면 stale 로 FAIL 해서 목록 정리를 강제한다.
#: 같은 어휘를 쓰는데 **아직 가드가 없는** writer. 사유와 추적 이슈를 함께 적는다.
#: 양방향 검사라 고치고 나면 stale 로 FAIL 해서 목록 정리를 강제한다.
#: 현재 비어 있다 — #1293 이 마지막 항목(`certification.py`)을 닫았다.
KNOWN_UNGUARDED: dict[str, str] = {}


class TestCanonicalVocabColumnsAreGuarded:
    """어휘가 `ALL_REGIMES` 인 컬럼의 writer 는 **같은** 가드를 통과한다.

    비대칭 자체가 결함이었다: 두 곳은 통과하고 한 곳만 안 하는 상태는, 다음에
    classifier 반환이 바뀌거나 소비자가 늘 때 조용히 깨질 자리다.
    """

    @staticmethod
    def _guard_calls(rel: str) -> int:
        tree = ast.parse((NURI / rel).read_text(encoding="utf-8"))
        return sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "canonical_regime_or_none"
        )

    @staticmethod
    def _guard_call_functions(rel: str) -> set[str]:
        """가드를 **호출하는 함수 이름** 집합. 중첩 함수는 가장 안쪽 이름으로 잡힌다."""
        tree = ast.parse((NURI / rel).read_text(encoding="utf-8"))
        found = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "canonical_regime_or_none"
                for n in ast.walk(fn)
            ):
                found.add(fn.name)
        return found

    @pytest.mark.parametrize("rel", sorted(CANONICAL_VOCAB_WRITERS))
    def test_writer_calls_the_guard(self, rel):
        """AST 로 **실호출**만 센다 — import 나 주석 언급으로는 통과하지 않는다.

        파일이 아니라 **함수** 단위다: 같은 파일 어딘가의 죽은 호출로는 통과하지 않는다.
        """
        entry = CANONICAL_VOCAB_WRITERS[rel]
        actual = self._guard_call_functions(rel)
        for func in entry["functions"]:
            assert func in actual, f"{rel}::{func} ({entry['column']}): 정규화 가드를 호출하지 않는다"

    def test_guard_call_sites_match_the_code(self):
        """양방향 — 가드 호출이 **다른 함수로 새면** 인벤토리와 어긋나 FAIL 한다.

        이게 없으면 쓰기 함수에서 가드를 빼고 같은 파일의 아무 함수에 하나 남겨두는
        변경이 조용히 통과한다 (Codex P3 가 지적한 구멍).
        """
        for rel, entry in sorted(CANONICAL_VOCAB_WRITERS.items()):
            assert self._guard_call_functions(rel) == set(entry["functions"]), (
                f"{rel}: 가드 호출 함수가 인벤토리와 다르다 — "
                f"코드={sorted(self._guard_call_functions(rel))}, 목록={sorted(entry['functions'])}"
            )

    def test_every_listed_writer_exists(self):
        """양방향 — 파일이 사라지거나 옮겨지면 위 검사가 조용히 공허해진다."""
        missing = [r for r in {**CANONICAL_VOCAB_WRITERS, **KNOWN_UNGUARDED} if not (NURI / r).exists()]
        assert not missing, f"목록이 낡았다: {missing}"

    def test_inventory_matches_the_code(self):
        """목록을 **줄여서** 스윕을 피할 수 없게 한다.

        뮤테이션 실측에서 발각: `CANONICAL_VOCAB_WRITERS` 에서 한 줄을 지우면
        parametrize 가 한 케이스 덜 돌 뿐 **그대로 통과**했다. 목록이 스스로를
        검증하지 못하면 allowlist 는 회피 수단이 된다.

        그래서 기대 집합을 리터럴이 아니라 **코드에서 유도**한다: 가드를 호출하는
        모든 모듈은 인벤토리에 있어야 하고, 그 역도 성립해야 한다.
        """
        callers = {
            str(f.relative_to(NURI)) for f in NURI.rglob("*.py") if self._guard_calls(str(f.relative_to(NURI))) > 0
        }
        listed = set(CANONICAL_VOCAB_WRITERS)
        assert callers == listed, (
            f"인벤토리와 실제 가드 호출자가 다르다.\n"
            f"  목록에만 있음(가드 호출 안 함): {sorted(listed - callers)}\n"
            f"  코드에만 있음(인벤토리 누락): {sorted(callers - listed)}"
        )

    def test_known_gap_is_still_a_gap(self):
        """양방향 — #1293 이 고치면 이 항목이 stale 로 FAIL 해서 목록 정리를 강제한다.

        이 축이 없으면 known-gap 목록이 영원히 남아 "알고도 안 고친 것" 과
        "이미 고쳤는데 목록만 낡은 것" 을 구분할 수 없다.
        """
        still_unguarded = [r for r in KNOWN_UNGUARDED if self._guard_calls(r) == 0]
        assert sorted(still_unguarded) == sorted(KNOWN_UNGUARDED), (
            f"known-gap 이 이미 가드를 갖췄다 — 목록에서 빼고 CANONICAL_VOCAB_WRITERS 로 옮길 것: "
            f"{sorted(set(KNOWN_UNGUARDED) - set(still_unguarded))}"
        )

    def test_every_known_gap_states_a_reason(self):
        for rel, why in KNOWN_UNGUARDED.items():
            assert len(why) > 40, f"{rel}: 사유가 너무 짧다 — 다음 사람이 판단할 수 없다"
            assert "#" in why, f"{rel}: 추적 이슈 번호가 없다"

    def test_the_counter_ignores_mentions(self):
        """카나리아 — 텍스트로 세면 import 줄과 주석이 통과시킨다."""
        src = "from x import canonical_regime_or_none  # canonical_regime_or_none() 참고\n"
        tree = ast.parse(src)
        calls = sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "canonical_regime_or_none"
        )
        assert calls == 0, "import/주석을 호출로 셌다"
        assert "canonical_regime_or_none" in src, "텍스트 검사라면 통과했을 형태(대조)"
