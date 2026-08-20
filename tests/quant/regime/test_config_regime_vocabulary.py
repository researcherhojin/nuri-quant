"""레짐 어휘 잠금 — config 키와 게이트 코드가 분류기가 내는 값과 같은 우주에 있을 것.

`classify_regime()` 이 낼 수 있는 값은 `ALL_REGIMES` 10개뿐인데, BUY 게이트는 오랫동안
다른 어휘(`bear` · `crash` · `extreme_fear` · `neutral` · `momentum_*` · `extreme_greed`)를
조회했다. 파이썬 딕셔너리의 `.get(key, default)` 는 키가 안 맞아도 예외를 던지지 않으므로
불일치가 **정상 동작으로 읽혔다** — 로그도 경고도 실패도 없이 방어 게이트 3건이
도입(2026-04-30) 이래 한 번도 발화하지 못했다 (#1130).

`.claude/rules/enforcement.md` 가 부르는 "green dead gate" 계열이고, 이 파일이 그 계열의
재발을 막는 짝이다 (STRATEGY §5.3.1 Gotcha-Test Pair).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from nuri.quant.regime.classifier import ALL_REGIMES, UNKNOWN_REGIME

REPO = Path(__file__).resolve().parents[3]
BUY_SIGNALS = REPO / "config" / "buy_signals.yaml"
RULES = REPO / "config" / "rules.yaml"


def _avg_down_trigger(c: dict) -> dict:
    modes = (c.get("held_add_mode") or {}).get("modes") or {}
    return (modes.get("average_down") or {}).get("trigger") or {}


#: 출하 config 에서 레짐 문자열을 담는 자리. (설명, 값 추출) 쌍.
#: 새 자리를 추가하면 여기에도 등재한다 — 등재를 잊으면 그 자리는 검사되지 않는다.
_REGIME_SITES = [
    ("quality_bar.per_regime", lambda c: (c.get("quality_bar") or {}).get("per_regime") or {}),
    ("gates.blocking_regimes", lambda c: (c.get("gates") or {}).get("blocking_regimes") or []),
    (
        "allocation.total_pct_by_regime",
        lambda c: (c.get("allocation") or {}).get("total_pct_by_regime") or {},
    ),
    (
        "held_add_mode.modes.average_down.trigger.macro_veto_regimes",
        lambda c: _avg_down_trigger(c).get("macro_veto_regimes") or [],
    ),
    # rules.yaml 쪽 — 현재는 canonical 이지만 잠겨 있지 않았다. 같은 결함이 재발할
    # 자리이므로 함께 본다 (#1131 Codex P2).
    (
        "rules.yaml siege_gates.regime_overrides",
        lambda c: ((c.get("_rules") or {}).get("siege_gates") or {}).get("regime_overrides") or {},
    ),
]

#: 값이 **비어 있어도 키는 존재해야 하는** 자리. 키를 통째로 지우면 소비 코드의
#: `.get(...) or []` 가 빈 목록으로 폴백해 게이트가 조용히 사라진다 — 값이 비어 있는
#: 것(의도된 soft-penalty 운용)과 키가 없는 것(사고)은 구분돼야 한다.
_REQUIRED_KEYS = [
    ("gates.blocking_regimes", lambda c: c.get("gates") or {}, "blocking_regimes"),
    ("held_add_mode...macro_veto_regimes", _avg_down_trigger, "macro_veto_regimes"),
]

#: 비면 어휘 검사가 공허해지는 자리 — 채점 표는 항상 값을 갖는다.
_SCORING_SITES = {
    "quality_bar.per_regime",
    "allocation.total_pct_by_regime",
    "rules.yaml siege_gates.regime_overrides",
}


def _is_regime_expr(node: ast.expr) -> bool:
    """`regime` · `state.regime` · `_get_regime()[0]` 처럼 레짐을 담는 표현인가.

    이름만 보던 이전 판은 `state.regime in {...}` 과 `_get_regime()[0] in {...}` 를
    통째로 놓쳤다 (#1131 Codex P2).
    """
    if isinstance(node, ast.Name):
        return "regime" in node.id
    if isinstance(node, ast.Attribute):
        return "regime" in node.attr
    if isinstance(node, ast.Subscript):
        return _is_regime_expr(node.value)
    if isinstance(node, ast.Call):
        return _is_regime_expr(node.func)
    return False


def _string_literals(node: ast.expr) -> list[str]:
    """비교 대상이 담은 문자열 리터럴 — 단일 상수와 리터럴 컬렉션 둘 다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


#: 레짐을 게이팅에 쓰는 모듈. 여기서 레짐 문자열을 **코드에** 박으면 config 가 SSoT 가
#: 아니게 되고, 오타/어휘 불일치가 다시 조용해진다.
_GATE_MODULES = [
    REPO / "nuri" / "trading" / "recommend" / "buy_candidate_emitter.py",
    REPO / "nuri" / "trading" / "recommend" / "held_add.py",
]


@pytest.fixture(scope="module")
def shipped() -> dict:
    """두 config 를 한 매핑으로 — 사이트 추출기가 최상위 키로 갈라 본다."""
    return {
        **yaml.safe_load(BUY_SIGNALS.read_text()),
        "_rules": yaml.safe_load(RULES.read_text()),
    }


class TestConfigSpeaksTheClassifiersLanguage:
    @pytest.mark.parametrize("label,extract", _REGIME_SITES, ids=[s[0] for s in _REGIME_SITES])
    def test_every_regime_key_is_canonical(self, shipped, label, extract):
        """비정식 키는 `.get()` 이 조용히 삼키므로, 존재 자체가 결함이다."""
        keys = set(extract(shipped))
        unreachable = sorted(keys - set(ALL_REGIMES))
        assert not unreachable, (
            f"{label} 에 `classify_regime()` 이 절대 내지 않는 키가 있다: {unreachable}. "
            f"허용 어휘는 ALL_REGIMES 10개뿐이다 — 이 키들은 조용히 무시된다 (#1130)."
        )

    @pytest.mark.parametrize("label", sorted(_SCORING_SITES))
    def test_the_scoring_sites_are_populated(self, shipped, label):
        """전 사이트가 비면 위 검사는 공허하게 통과한다 — 카나리아.

        `any()` 로는 판별이 안 된다: veto 사이트 둘이 비어 있어도 채점 사이트만으로
        통과해 버린다 (#1131 Codex P2). 채점 사이트는 **비면 안 되는** 쪽이므로 각각을
        직접 본다. veto 사이트가 비어 있는 것은 의도된 운용이라 여기서 요구하지 않고,
        대신 `test_veto_keys_exist_even_when_empty` 가 키의 존재를 잠근다.
        """
        extract = next(e for lbl, e in _REGIME_SITES if lbl == label)
        assert extract(shipped), f"{label} 이 비었다 — 어휘 검사가 공허해진다"

    @pytest.mark.parametrize("label,parent,key", _REQUIRED_KEYS, ids=[r[0] for r in _REQUIRED_KEYS])
    def test_veto_keys_exist_even_when_empty(self, shipped, label, parent, key):
        """빈 목록과 없는 키는 다르다 — 소비 코드가 둘을 구분 못 하므로 여기서 잠근다."""
        assert key in parent(shipped), (
            f"{label} 키가 사라졌다. 소비 코드는 `.get(...) or []` 로 빈 목록에 폴백하므로 "
            f"게이트가 조용히 없어진다 — 비활성이면 빈 목록을 **명시**할 것."
        )

    def test_unknown_label_can_never_match_a_regime_table(self):
        """미상이 `ALL_REGIMES` 에 들어오면 조정 표에 매치될 수 있게 된다.

        그러면 "모른다" 가 완화나 강화를 받는다 — 미상을 별도 키로 분리한 이유가 사라진다.
        """
        assert UNKNOWN_REGIME not in ALL_REGIMES

    def test_the_allocation_table_declares_its_own_default(self, shipped):
        """표에 없는 정식 레짐이 **선언되지 않은** 상수로 떨어지면 안 된다."""
        alloc = shipped.get("allocation") or {}
        assert "default_pct" in alloc
        assert "unknown_regime_pct" in alloc


class TestGateCodeDoesNotHardcodeRegimes:
    @pytest.mark.parametrize("path", _GATE_MODULES, ids=lambda p: p.name)
    def test_no_literal_regime_set_is_compared_against(self, path):
        """`if regime in {"bear", "crash"}` 와 `regime == "bear"` 의 재발을 막는다.

        문자열 grep 이 아니라 AST 로 본다 — 주석과 docstring 이 그 문자열을 **설명하기
        위해** 담고 있어서(이 커밋이 그렇다) grep 은 오탐만 낸다. 여기서 보는 것은
        레짐 표현을 문자열 리터럴과 비교하는 노드뿐이고, 상수 이름(`UNKNOWN_REGIME`)
        과의 비교는 리터럴이 아니므로 통과한다.
        """
        tree = ast.parse(path.read_text())
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or not _is_regime_expr(node.left):
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if not isinstance(op, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)):
                    continue
                literals = _string_literals(comparator)
                if literals:
                    offenders.append((node.lineno, literals))
        assert not offenders, (
            f"{path.name} 이 레짐을 문자열 리터럴과 비교한다: {offenders}. "
            f"config 로 옮길 것 — 코드에 박으면 어휘 불일치가 다시 조용해진다 (#1130)."
        )
