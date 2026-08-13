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
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _module_level_value(tree: ast.Module, name: str) -> ast.expr | None:
    """모듈 최상위에서 `name` 에 대입된 **식**. 없으면 None."""
    for node in tree.body:
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
    """로더 기본값이 YAML 부재를 가려주므로, 블록 자체의 존재를 따로 잠근다."""

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
