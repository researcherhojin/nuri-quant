"""의사결정 임계값은 코드가 아니라 `config/rules.yaml` 에 있다 (carry-over audit N1/N2).

왜 값 비교로는 안 되는가
------------------------
"config 값과 상수가 같다"는 테스트는 **부분 되돌림을 못 잡는다**. 누가 액터에
`CONVICTION_EMIT_CUTOFF = 0.70` 을 다시 인라인하면서 YAML 블록을 그대로 두면,
두 값이 같으므로 그 테스트는 초록으로 통과한다. 그 순간 config 는 아무도 안 읽는
장식이 되고, 튜닝은 조용히 무효가 된다.

그래서 **값이 아니라 구조**를 본다: 액터 모듈에 그 이름으로 module-level 대입이
없어야 하고, 그 이름이 `nuri.core.rules` 에서 import 돼야 한다. 문자열 grep 이
아니라 AST 를 쓰는 이유는 주석·docstring 안의 같은 문구를 오탐하지 않기 위해서다
(`tests/core/test_sqlite3_sole_importer.py` 와 같은 형태).

⚠️ 이 잠금은 **일부러 깐깐하다.** `from nuri.core import rules` +
`rules.CONVICTION_EMIT_CUTOFF` 형태도 거부한다. 그건 버그가 아니라 의도다 —
잠금이 허용하는 형태가 넓어질수록 되돌림을 놓칠 여지가 커진다. 이 테스트가
터졌다면 우회로를 찾지 말고, 정말 import 형태를 바꿀 이유가 있는지부터 볼 것.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nuri.core.rules import (
    CONVICTION_EMIT_CUTOFF,
    CONVICTION_HOLD_CUTOFF,
    OUTCOME_WINDOW_THRESHOLDS,
    REGIME_FAVOR_PROB,
    RULES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_MODULE = "nuri.core.rules"

# (액터 경로, config 에서 와야 하는 이름들)
CONFIG_BACKED: list[tuple[str, tuple[str, ...]]] = [
    (
        "nuri/agents/actors/decision_compiler.py",
        ("CONVICTION_EMIT_CUTOFF", "CONVICTION_HOLD_CUTOFF", "REGIME_FAVOR_PROB"),
    ),
    ("nuri/agents/actors/forward_outcome_tracker.py", ("OUTCOME_WINDOW_THRESHOLDS",)),
]


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)


def _module_level_assignments(tree: ast.Module) -> set[str]:
    """모듈 최상위에서 대입되는 이름. 함수/클래스 안쪽은 보지 않는다."""
    return {n for n, _ in _module_scope_assignments(tree)}


def _bound_names(tree: ast.Module):
    """(이름, 대입식) — 파일 **어디서든** 그 이름에 값을 묶는 모든 자리.

    스코프를 구분하지 않는다. 첫 판은 모듈 스코프만 봤는데, 적대적 감사가
    **함수 지역 shadow** 가 가장 현실적인 되돌림이라고 지적했다 (2026-08-14):
    `_compile()` 첫 줄에 `CONVICTION_EMIT_CUTOFF = 0.70` 한 줄이면 config 가
    무력해지고, 모듈 스코프만 보는 스윕은 초록이다. 액터가 이 이름들을 다시
    묶을 정당한 이유가 없으므로 스코프를 나눌 이유도 없다.

    `ctx=Store` 인 `Name` 만 센다. 이걸 안 보면 `labels[CONVICTION_EMIT_CUTOFF] = x`
    처럼 **읽기로 쓰는 자리**까지 거부하는 오탐이 난다(같은 감사에서 확인).
    Store 로 좁히면 `for X in ...` / `with ... as X` / walrus / AugAssign 도 함께
    잡힌다 — 전부 바인딩이기 때문이다.
    """
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.id, None
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            yield node.target.id, value
        # `globals()["X"] = ...` / `vars()["X"] = ...` — 이름을 문자열 뒤에 숨기는 우회
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Call)
                    and getattr(t.value.func, "id", "") in ("globals", "vars")
                    and isinstance(t.slice, ast.Constant)
                    and isinstance(t.slice.value, str)
                ):
                    yield t.slice.value, node.value


def _module_scope_assignments(tree: ast.Module):
    return _bound_names(tree)


def _module_level_value(tree: ast.Module, name: str) -> ast.expr | None:
    """`name` 에 대입된 식. AnnAssign/Assign 만 — 값이 필요한 검사용."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    return None


def _references(expr: ast.expr | None, names: set[str]) -> bool:
    """식이 주어진 이름 중 하나라도 참조하는가."""
    if expr is None:
        return False
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(expr))


def _imported_from_rules(tree: ast.Module) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == RULES_MODULE
        for alias in node.names
    }


class TestThresholdsComeFromConfig:
    @pytest.mark.parametrize("rel,names", CONFIG_BACKED, ids=lambda v: v if isinstance(v, str) else "")
    def test_no_module_level_literal_reassignment(self, rel: str, names: tuple[str, ...]) -> None:
        """액터가 그 이름을 스스로 정의하면 config 는 장식이 된다."""
        assigned = _module_level_assignments(_tree(rel)) & set(names)
        assert not assigned, f"{rel} 이 {sorted(assigned)} 을(를) 모듈 최상위에서 다시 정의한다 — config 가 무시된다"

    @pytest.mark.parametrize("rel,names", CONFIG_BACKED, ids=lambda v: v if isinstance(v, str) else "")
    def test_names_are_imported_from_the_rules_loader(self, rel: str, names: tuple[str, ...]) -> None:
        missing = set(names) - _imported_from_rules(_tree(rel))
        assert not missing, f"{rel} 이 {sorted(missing)} 을(를) {RULES_MODULE} 에서 import 하지 않는다"

    def test_the_sweep_actually_sees_something(self) -> None:
        """스윕이 0건을 훑고도 통과하면, 통과가 아무 의미가 없다.

        경로 오타나 파일 이동으로 대상이 사라지면 위 두 테스트는 조용히 초록이
        된다 — 카나리아를 둔다.
        """
        for rel, names in CONFIG_BACKED:
            assert (REPO_ROOT / rel).exists(), f"{rel} 이 없다 — CONFIG_BACKED 를 갱신할 것"
            assert names, f"{rel} 의 이름 목록이 비어 있다"
            assert _imported_from_rules(_tree(rel)), f"{rel} 이 {RULES_MODULE} 를 아예 import 하지 않는다"


class TestConfigBlocksExist:
    """로더 기본값이 YAML 부재를 가려주므로, 블록 자체의 존재를 따로 잠근다.

    `nuri/core/rules.py` 의 `.get(..., 0.70)` 기본값은 **옮기기 전 리터럴과 같은
    값**이다. 그래서 YAML 블록을 지우면 런타임은 아무 소리 없이 예전 동작으로
    돌아간다 (2026-08-14 실측). 기본값을 없애면 config 파일 하나가 깨졌을 때
    import 자체가 죽으므로, 기본값은 두되 **블록의 존재를 테스트로 강제**하는 쪽을
    택했다. 이 클래스가 그 역할이고, 지우면 위 트레이드오프가 무너진다.
    """

    def test_decision_compiler_block_is_present_and_complete(self) -> None:
        dc = RULES.get("decision_compiler")
        assert dc, "config/rules.yaml 에 decision_compiler 블록이 없다"
        assert set(dc) == {"conviction_emit_cutoff", "conviction_hold_cutoff", "regime_favor_prob"}

    def test_outcome_tracking_block_is_present(self) -> None:
        wt = (RULES.get("outcome_tracking") or {}).get("window_thresholds")
        assert wt, "config/rules.yaml 에 outcome_tracking.window_thresholds 가 없다"

    def test_loaded_values_match_the_config_file(self) -> None:
        """로더가 YAML 을 실제로 읽는지 — 기본값으로만 살아 있으면 안 된다."""
        dc = RULES["decision_compiler"]
        assert CONVICTION_EMIT_CUTOFF == dc["conviction_emit_cutoff"]
        assert CONVICTION_HOLD_CUTOFF == dc["conviction_hold_cutoff"]
        assert REGIME_FAVOR_PROB == dc["regime_favor_prob"]

    def test_window_keys_are_ints_and_values_are_tuples(self) -> None:
        """YAML 에서 키를 `"7":` 로 인용하면 str 이 되어 소비처가 KeyError 를 낸다.

        정규화는 로더 책임이다 — 소비자마다 방어하게 만들면 하나가 빠진다.
        """
        assert all(isinstance(k, int) for k in OUTCOME_WINDOW_THRESHOLDS)
        assert all(isinstance(v, tuple) and len(v) == 2 for v in OUTCOME_WINDOW_THRESHOLDS.values())


class TestPreRegisteredCriteriaStayInCode:
    """§3.11 사전등록 기준은 **config 로 옮기면 안 된다** — 잠금이 약해진다.

    `DEFAULT_BENCHMARK_TICKER` 를 config 에서 파생시키면
    `tests/core/test_rules.py::test_benchmark_matches_tracker_constant` 가
    `x == x` 자기비교로 무너진다. 지금은 코드 리터럴 ↔ config 대조라서 둘 중
    하나만 바꾸면 CI 가 잡는다. 그 이중 게이트가 사전등록의 실질이다.
    """

    # config 로 새는 경로는 두 가지다: 로더에서 import 하거나, 로더가 만든 이름을
    # 참조하는 식으로 유도하거나. 두 번째가 더 조용하다 — `= tuple(sorted(...))` 는
    # 여전히 module-level 대입이라 "대입이 있는가" 만 보는 검사를 통과한다.
    # (2026-08-14 실측: 이 테스트의 첫 판이 정확히 그 뮤테이션을 놓쳤다.)
    _CONFIG_NAMES = {"OUTCOME_WINDOW_THRESHOLDS", "RULES"}

    def _assert_literal(self, name: str, why: str) -> None:
        tree = _tree("nuri/agents/actors/forward_outcome_tracker.py")
        value = _module_level_value(tree, name)
        assert value is not None, f"{name} 이 모듈 최상위에 없다 — {why}"
        assert name not in _imported_from_rules(tree), f"{name} 을 로더에서 import 한다 — {why}"
        assert not _references(value, self._CONFIG_NAMES), f"{name} 이 config 파생 식이다 — {why}"

    def test_benchmark_ticker_is_still_a_code_literal(self) -> None:
        self._assert_literal(
            "DEFAULT_BENCHMARK_TICKER",
            "§3.11 사전등록 기준의 이중 게이트(코드 리터럴 ↔ config 대조)가 사라진다",
        )

    def test_supported_windows_is_still_a_code_literal(self) -> None:
        self._assert_literal(
            "SUPPORTED_WINDOWS",
            "YAML 한 줄로 사전등록 window 30 을 조용히 끌 수 있게 된다",
        )

    def test_window_key_set_still_matches_supported_windows(self) -> None:
        """config 로 옮긴 쪽(키 집합)과 코드에 남은 쪽이 갈라지면 KeyError 가 난다."""
        from nuri.agents.actors.forward_outcome_tracker import SUPPORTED_WINDOWS, WINDOW_THRESHOLDS

        assert set(WINDOW_THRESHOLDS) == set(SUPPORTED_WINDOWS)


class TestTrackerHoldsACopyNotAnAlias:
    def test_patching_the_actor_does_not_mutate_the_loader(self) -> None:
        """별칭이면 테스트의 patch.dict 가 `nuri.core.rules` 원본을 오염시킨다."""
        import nuri.agents.actors.forward_outcome_tracker as fot
        import nuri.core.rules as rules

        assert fot.WINDOW_THRESHOLDS is not rules.OUTCOME_WINDOW_THRESHOLDS
        assert fot.WINDOW_THRESHOLDS == rules.OUTCOME_WINDOW_THRESHOLDS


class TestLoaderReadsTheKeysThatExist:
    """로더가 **실제로 있는 키**를 읽는지. 없는 키는 조용히 기본값이 된다.

    스윕은 액터 두 파일만 본다. 로더(`nuri/core/rules.py`)에 하드코딩을 넣거나
    키 이름을 틀리면 스윕은 초록인 채로 config 가 무력해진다 (2026-08-14 적대적
    감사 지적). 특히 **키 오타는 사고로 일어난다** — YAML 키를 이름만 바꾸고
    로더를 안 고치면 `.get("없는키", 0.70)` 이 기본값을 돌려주고 아무도 모른다.
    """

    _LOADER = REPO_ROOT / "nuri" / "core" / "rules.py"

    def _get_calls(self, receiver: str) -> set[str]:
        """`_dc.get("x", ...)` 형태에서 읽는 키 이름들."""
        tree = ast.parse(self._LOADER.read_text(encoding="utf-8"), filename=str(self._LOADER))
        keys = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == receiver
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
        return keys

    def test_decision_compiler_keys_exist_in_yaml(self) -> None:
        read = self._get_calls("_dc")
        assert read, "로더가 _dc 에서 아무 키도 안 읽는다 — 변수명이 바뀌었는지 확인"
        missing = read - set(RULES.get("decision_compiler") or {})
        assert not missing, f"로더가 YAML 에 없는 키를 읽는다(조용히 기본값): {sorted(missing)}"

    def test_outcome_tracking_keys_exist_in_yaml(self) -> None:
        read = self._get_calls("_ot")
        assert read, "로더가 _ot 에서 아무 키도 안 읽는다"
        missing = read - set(RULES.get("outcome_tracking") or {})
        assert not missing, f"로더가 YAML 에 없는 키를 읽는다(조용히 기본값): {sorted(missing)}"
