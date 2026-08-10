"""SIEGE 변동성 게이트 ↔ 수집기 계약 (#1022).

**왜 이 파일이 있나**: `config/rules.yaml siege_gates` 가 선언한 변동성 지표 중
`kospi` 와 `yield` 는 **`macro` 테이블에 한 행도 없다** (2026-08-10 프로덕션 실측
n=0). 그런데 게이트는 값이 없으면 `passed=True, "데이터 없음 — 스킵"` 을 돌려줬다.
결과: `volatility_gate_kr_index` 와 `volatility_gate_bond` 가 도입(#248) 이래
**한 번도 평가된 적 없이 매 인증서에 초록으로 찍혔다**.

⚠️ "미수집"이 아니다 — `prices.KOSPI` 는 419행, `prices.TLT` 는 46행 있다.
`_get_indicator_value` 가 **`macro` 만 읽어서** 못 보는 것이다. 그래서 이 계약의
대조 대상은 "수집 여부"가 아니라 **macro 에 쓰는 수집기 레지스트리**다.

게이트 semantics 는 고쳤지만(값 없음 → FAIL/warning) 그것만으로는 **다음 dangling
포인터를 못 막는다**. 그래서 config 를 그 레지스트리와 대조한다.

allowlist 는 양방향으로 잠근다 (`test_cross_stage_imports.py` 와 같은 관용):
새 dangling 포인터도 실패하고, 해소된 항목을 안 지워도 실패한다.

⚠️ **이 테스트가 증명하지 않는 것** (Codex 리뷰 2026-08-10): 선언한 지표를
`_get_indicator_value` 가 **런타임에 실제로 읽을 수 있는지**는 증명하지 못한다.
수집기가 등록돼 있어도 ingest 가 깨지거나 다른 이름으로 쓰면 이 테스트는 통과한다.
그 층은 게이트 자신이 맡는다 — 이제 값이 없으면 인증서에 `평가 불가` 로 표면화되므로
런타임 검출기는 인증서다. 여기 계약의 범위는 **PR 시점의 오타·dangling 포인터**다.

레지스트리는 손으로 적지 않고 **소스에서 유도**한다 (#1015 fixer 가드와 같은 방식) —
손 목록을 두면 그 목록이 다음 드리프트 지점이 된다는 게 Codex P1 지적이었다.
"""

import ast
import re
from pathlib import Path

import yaml

from nuri.trading.engine.certification import _check_volatility_for_class

REPO_ROOT = Path(__file__).resolve().parents[3]
_COLLECTORS = REPO_ROOT / "nuri" / "collectors"


def _macro_writer_indicators() -> set[str]:
    """수집기 소스에서 macro.indicator 로 들어가는 이름을 **AST 로 유도**한다.

    두 가지 형태만 본다 — 실제로 그 두 가지가 전부다:
      1. `{"indicator": "<literal>", ...}` — collector 가 직접 dict 를 만드는 경우
      2. 모듈 레벨 `*_SERIES` / `*_SYMBOLS` dict 의 **키** — macro.py 가 이걸 순회하며 씀

    이름을 손으로 복사하지 않으므로 지표 rename 을 자동으로 따라간다. 담는 그릇
    자체(`_SERIES`/`_SYMBOLS`)의 이름이 바뀌면 아래 카나리아가 터진다.
    """
    found: set[str] = set()
    containers = 0
    for path in sorted(_COLLECTORS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # (1) {"indicator": "vix", ...}
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "indicator"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    ):
                        found.add(v.value)
            # (2) FRED_SERIES = {...} / YFINANCE_SYMBOLS = {...}
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(n.endswith(("_SERIES", "_SYMBOLS")) for n in names):
                    containers += 1
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            found.add(k.value)
    if containers == 0:
        raise RuntimeError(
            "`*_SERIES` / `*_SYMBOLS` 컨테이너를 하나도 못 찾았다 — 수집기 레지스트리 유도가 "
            "소스와 어긋났다. 이 계약은 지금 아무것도 검사하지 않는다."
        )
    return found


# ── 선언은 됐지만 macro 에 안 들어오는 지표 ──
# 값은 "왜 아직 없는가 + 해소 조건 + 추적 이슈". 비워두지 말 것 — 이유 없는 항목은
# 그냥 잊혀진 dangling 포인터다.
#
# **allowlist 가 무기한 면죄부가 되지 않는 이유** (Codex P2): 항목이 남아 있는 동안
# 해당 게이트는 매 인증서에 `평가 불가` warning 으로 찍히고 score 를 깎는다. 압력은
# 이 테스트가 아니라 **매일 나가는 인증서**가 만든다. 이 테스트가 강제하는 건
# "이유와 추적 이슈가 붙어 있을 것" 까지다.
KNOWN_MISSING_FROM_MACRO = {
    "kospi": (
        "#1020 — 시계열 자체는 있다: `prices.KOSPI` 419행 (freshness 게이트가 이미 쓴다). "
        "`_get_indicator_value` 가 macro 만 읽어서 못 볼 뿐. prices 폴백을 붙이면 "
        "해소되지만 게이트 입력 경로 변경이라 별도 PR. threshold 5.0 은 "
        "pct-change 의미로 이미 정합이라 재도출 불필요."
    ),
    "yield": (
        "#1021 — bond 클래스 primary. `macro.us_10y_yield`(335행) / `prices.TLT`(46행) 둘 다 "
        "후보지만 threshold 0.3 이 `_compute_3d_change` 의 pct 의미와 안 맞는다 "
        "(0.3% ≈ 1.3bp → 상시 발화). 포인터만 바꾸면 죽은 게이트가 시끄러운 게이트로 "
        "바뀔 뿐 — threshold 재도출은 매매 룰 변경이라 STRATEGY PR 대상."
    ),
}
_ISSUE_REF = re.compile(r"#\d{2,}")


def _collected_indicators() -> set[str]:
    return _macro_writer_indicators()


def _declared_indicators() -> dict[str, list[str]]:
    """rules.yaml 이 선언한 변동성 지표 → 선언 위치 **전부**. `_3d_change` 는 base 로 환원.

    `setdefault` 로 첫 선언만 남기면 같은 dangling 입력에 여러 asset class 가
    물려 있는 걸 숨긴다 (Codex P2).
    """
    rules = yaml.safe_load((REPO_ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for cls, policy in (rules.get("siege_gates", {}).get("asset_classes", {}) or {}).items():
        names = [policy.get("volatility_primary")] + list(policy.get("volatility_secondary") or [])
        for name in names:
            if not name:
                continue
            base = name[: -len("_3d_change")] if name.endswith("_3d_change") else name
            out.setdefault(base, []).append(f"{cls}.{name}")
    return out


class TestVolatilityGateContract:
    def test_every_declared_indicator_is_collected_or_allowlisted(self):
        declared = _declared_indicators()
        collected = _collected_indicators()
        dangling = {b: w for b, w in declared.items() if b not in collected and b not in KNOWN_MISSING_FROM_MACRO}
        assert not dangling, (
            "macro 에 안 들어오는 변동성 지표를 게이트에 선언했다 — 그 게이트는 영원히 평가되지 않는다:\n"
            + "\n".join(f"  {b}  (선언: {', '.join(w)})" for b, w in sorted(dangling.items()))
            + "\nmacro 수집을 붙이거나, 못 하면 KNOWN_MISSING_FROM_MACRO 에 사유와 함께 등록할 것."
        )

    def test_registry_is_derived_not_hand_written(self):
        """유도가 살아 있는지 — 알려진 지표가 잡혀야 한다 (카나리아).

        AST 유도가 조용히 빈 집합을 돌려주면 위 계약이 전부 vacuous-pass 로 바뀐다.
        이 파일이 고치려는 결함과 정확히 같은 형태라 카나리아를 따로 둔다.
        """
        collected = _collected_indicators()
        for known in ("vix", "usd_krw", "gold", "fear_greed", "put_call_ratio"):
            assert known in collected, f"수집기 레지스트리 유도가 `{known}` 를 놓쳤다 — 계약이 무력하다"

    def test_allowlist_has_no_stale_entries(self):
        """macro 에 들어오게 됐거나 config 에서 사라진 항목은 allowlist 에서 빼야 한다."""
        declared, collected = _declared_indicators(), _collected_indicators()
        resolved = sorted(b for b in KNOWN_MISSING_FROM_MACRO if b in collected)
        assert not resolved, f"이제 macro 에 들어온다 — KNOWN_MISSING_FROM_MACRO 에서 제거할 것: {resolved}"
        unused = sorted(b for b in KNOWN_MISSING_FROM_MACRO if b not in declared)
        assert not unused, f"config 가 더는 선언하지 않는다 — KNOWN_MISSING_FROM_MACRO 에서 제거할 것: {unused}"

    def test_allowlist_reasons_are_substantive(self):
        thin = sorted(b for b, why in KNOWN_MISSING_FROM_MACRO.items() if len(why.strip()) < 40)
        assert not thin, f"사유가 너무 짧다 (해소 조건까지 적을 것): {thin}"

    def test_allowlist_entries_cite_a_tracking_issue(self):
        """면죄부가 아니라 부채 — 항목마다 추적 이슈가 붙어 있어야 한다 (Codex P2)."""
        untracked = sorted(b for b, why in KNOWN_MISSING_FROM_MACRO.items() if not _ISSUE_REF.search(why))
        assert not untracked, f"추적 이슈(#NNNN) 없는 allowlist 항목 — 영구 방치 경로다: {untracked}"


class TestUnknownIndicatorFailsTheGate:
    """게이트 semantics 잠금 — 미상은 PASS 가 아니다."""

    def test_missing_primary_fails_as_warning(self, db_path):
        conds = _check_volatility_for_class(
            "bond", {"volatility_primary": "yield_3d_change", "volatility_primary_threshold": 0.3}, db_path=db_path
        )
        assert len(conds) == 1
        assert conds[0].passed is False, "값 없는 지표가 PASS 로 찍히면 죽은 게이트가 초록으로 보인다"
        assert conds[0].severity == "warning", "certified 를 막으면 안 된다 — Surface rung"
        assert "평가 불가" in conds[0].detail

    def test_present_primary_still_passes_when_calm(self, db_path):
        from nuri.core.db import upsert_macro
        from nuri.core.timezone import today_kst

        upsert_macro([{"indicator": "vix", "date": today_kst(), "value": 15.0, "source": "test"}], db_path)
        conds = _check_volatility_for_class(
            "us_equity", {"volatility_primary": "vix", "volatility_primary_threshold": 30}, db_path=db_path
        )
        assert conds[0].passed is True
        assert "정상" in conds[0].detail

    def test_breach_still_fails_as_warning(self, db_path):
        from nuri.core.db import upsert_macro
        from nuri.core.timezone import today_kst

        upsert_macro([{"indicator": "vix", "date": today_kst(), "value": 35.0, "source": "test"}], db_path)
        conds = _check_volatility_for_class(
            "us_equity", {"volatility_primary": "vix", "volatility_primary_threshold": 30}, db_path=db_path
        )
        assert conds[0].passed is False
        assert conds[0].severity == "warning"
