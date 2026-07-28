"""단계 간 import 를 고정한다 (#920).

`.claude/rules/invariants.md` 의 **Cross-stage isolation** 은 오래 "convention —
review-enforced" 였고, 실제로는 지켜지지 않고 있었다 — 19건이 경계를 넘고 있었다.
문제는 위반 자체보다 **검증할 수 없었다는 점**이다: 불변식은 다섯 단계를 이름으로
부르는데 어느 디렉터리가 어느 단계인지 아무 문서도 말하지 않았다. 매핑이 없으면
같은 코드베이스에서 19건도 38건도 "맞는" 답이 된다.

여기서 두 가지를 고정한다:

1. **module-level 금지** — 교차 import 는 반드시 함수 본문 안(deferred)이어야 한다.
   이게 실제로 성립하는 성질이고, `engine/conflicts.py` ↔ `recommend/candidates.py`
   상호 의존이 ImportError 없이 버티는 유일한 이유다. 하나라도 최상위로 올리면
   즉시 순환이 터진다.
2. **집합 동결** — 아래 ALLOWED 와 정확히 일치해야 한다. 새 교차 의존은 의도적으로
   등재해야만 통과한다. 줄어들 때도 FAIL 시켜 목록이 낡지 않게 한다.

Gotcha-Test Pair: 교차 import 를 하나 추가하면 FAIL, 최상위로 올려도 FAIL.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 단계 → 디렉터리. 불변식이 빠뜨린 매핑이며, `.claude/rules/invariants.md` 와 짝이다.
# `nuri/quant` 는 의도적으로 제외 — 여러 단계가 공유하는 라이브러리이지 한 단계가
# 아니다. `nuri/core` 도 마찬가지(공용 어휘·DB·시간).
STAGES = {
    "collect": "nuri/collectors",
    "analyze": "nuri/analysis",
    "consensus": "nuri/trading/agents",
    "certify": "nuri/trading/engine",
    "track": "nuri/trading/recommend",
}

# (소스 파일, 대상 모듈) → 왜 허용하는가.
# 줄 번호로 키를 잡지 않는다 — 무관한 편집에도 깨진다.
ALLOWED: dict[tuple[str, str], str] = {
    (
        "nuri/analysis/evidence_charts.py",
        "nuri.trading.engine.memory",
    ): "증거 차트가 strategy memory 를 읽어 렌더 — 읽기 전용",
    (
        "nuri/trading/agents/consensus/__main__.py",
        "nuri.trading.engine.decisions",
    ): "CLI 가 합의 직후 결정을 기록 — README 가 명시한 in-memory hand-off",
    ("nuri/trading/agents/consensus/presentation.py", "nuri.trading.recommend.price_targets"): "stdout 렌더링 전용",
    ("nuri/trading/agents/consensus/presentation.py", "nuri.collectors.external"): "stdout 렌더링 전용",
    ("nuri/trading/engine/certification.py", "nuri.analysis.portfolio"): "게이트가 현재 포트폴리오 상태를 봐야 함",
    ("nuri/trading/engine/certification.py", "nuri.collectors.external"): "외부 분석 요약을 증거로 첨부",
    ("nuri/trading/engine/conflicts.py", "nuri.trading.recommend.candidates"): (
        "detect_conflicts(candidates=None) 의 auto-fetch. candidates.py 와 상호 의존을 이루는 "
        "나머지 한쪽 — 제거하려면 프로덕션 호출 5곳과 이 파일의 CLI 를 함께 옮겨야 하고, "
        "그래도 CLI 가 다시 이 방향을 만든다. 실효 방어선은 위의 module-level 금지다."
    ),
    ("nuri/trading/engine/decisions.py", "nuri.trading.recommend.price_targets"): "결정 기록 시 가격 레벨 계산",
    (
        "nuri/trading/engine/remediation.py",
        "nuri.analysis.rebalance_advisor",
    ): "위반 해소 제안이 리밸런스 리포트를 재사용",
    ("nuri/trading/recommend/candidates.py", "nuri.trading.engine.memory"): "후보 점수에 drift 상태 반영",
    (
        "nuri/trading/recommend/candidates.py",
        "nuri.trading.engine.conflicts",
    ): "후보에 방향 충돌 annotate — 위 auto-fetch 와 짝",
    (
        "nuri/trading/recommend/holdings_monitor.py",
        "nuri.trading.agents.consensus",
    ): "보유 종목 재평가에 10-agent 합의 재사용",
    ("nuri/trading/recommend/rebalance.py", "nuri.analysis.rebalance"): "MVO/RP 최적화 결과를 입력으로",
    ("nuri/trading/recommend/rebalance.py", "nuri.trading.engine.gate"): "리밸런스 액션에 게이트 적용",
    ("nuri/trading/recommend/rebalance.py", "nuri.trading.engine.conflicts"): "리밸런스 전 충돌 확인",
}


def _stage_of_path(p: str) -> str | None:
    best = None
    for name, d in STAGES.items():
        if p == d or p.startswith(d + "/"):
            if best is None or len(d) > len(STAGES[best]):
                best = name
    return best


def _stage_of_module(m: str) -> str | None:
    return _stage_of_path(m.replace(".", "/"))


def _sweep() -> list[dict]:
    """(source, target, module, lineno, module_level) 목록."""
    out: list[dict] = []
    for f in sorted((REPO_ROOT / "nuri").rglob("*.py")):
        rel = str(f.relative_to(REPO_ROOT))
        src = _stage_of_path(str(f.parent.relative_to(REPO_ROOT)))
        if not src:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        toplevel = {id(n) for n in tree.body}
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                tgt = _stage_of_module(m)
                if tgt and tgt != src:
                    out.append(
                        {
                            "file": rel,
                            "module": m,
                            "src": src,
                            "tgt": tgt,
                            "lineno": node.lineno,
                            "module_level": id(node) in toplevel,
                        }
                    )
    return out


class TestSweepIsAlive:
    def test_sweep_finds_the_stage_directories(self):
        """매핑된 디렉터리가 전부 실존하는지 — 리팩터로 조용히 눈이 머는 것 방지."""
        for stage, d in STAGES.items():
            assert (REPO_ROOT / d).is_dir(), f"{stage} 디렉터리 없음: {d}"

    def test_sweep_returns_something(self):
        """0건이면 정규식/매핑이 깨진 것이지 위반이 사라진 게 아니다."""
        assert _sweep(), "교차 import 를 하나도 못 찾음 — sweep 이 무력화됨"


class TestNoModuleLevelCrossStageImport:
    def test_every_cross_stage_import_is_deferred(self):
        """교차 import 는 전부 함수 본문 안에 있어야 한다.

        `engine/conflicts.py` ↔ `recommend/candidates.py` 는 상호 의존이라,
        어느 한쪽을 최상위로 올리는 순간 import 시점에 순환이 터진다.

        Gotcha-Test Pair: 아무 교차 import 나 모듈 최상위로 옮기면 FAIL.
        """
        hoisted = [f"{h['file']}:{h['lineno']} -> {h['module']}" for h in _sweep() if h["module_level"]]
        assert not hoisted, "교차 단계 import 가 module-level 로 올라옴 (순환 위험):\n  " + "\n  ".join(hoisted)


class TestAllowlistIsExact:
    def test_no_undeclared_cross_stage_import(self):
        """새 교차 의존은 ALLOWED 에 사유와 함께 등재해야 통과한다."""
        found = {(h["file"], h["module"]) for h in _sweep()}
        new = sorted(found - set(ALLOWED))
        assert not new, (
            "등재되지 않은 교차 단계 import:\n  "
            + "\n  ".join(f"{f} -> {m}" for f, m in new)
            + "\n\ntests/core/test_cross_stage_imports.py 의 ALLOWED 에 사유와 함께 추가하거나, "
            "의존을 없앨 것."
        )

    def test_allowlist_has_no_stale_entries(self):
        """의존이 사라졌으면 목록에서도 빼야 한다 — 낡은 허용목록은 거짓 안심을 준다."""
        found = {(h["file"], h["module"]) for h in _sweep()}
        stale = sorted(set(ALLOWED) - found)
        assert not stale, "ALLOWED 에 있으나 코드에 없는 항목 (제거할 것):\n  " + "\n  ".join(
            f"{f} -> {m}" for f, m in stale
        )

    def test_every_allowlist_entry_states_a_reason(self):
        blank = [k for k, v in ALLOWED.items() if not v.strip()]
        assert not blank, f"사유 없는 허용 항목: {blank}"
