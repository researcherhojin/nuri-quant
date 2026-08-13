"""Tests for scripts/dev/llm_ab_stats.py — A/B 판정 통계.

**핵심 설계**: 자작 구현을 자작 기대값으로만 검증하지 않는다. Clopper-Pearson 과
McNemar exact 는 `scipy` / `statsmodels` 와 **직접 대조**한다. 이 하네스에서
반복된 실패 패턴이 "내가 상상한 기대값으로 테스트를 짜서 통과시키는 것"이었다.
표준 라이브러리와 값이 어긋나면 즉시 FAIL 해야 한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "llm_ab_stats", Path(__file__).resolve().parents[2] / "scripts" / "dev" / "llm_ab_stats.py"
)
assert _SPEC and _SPEC.loader
st = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st)


class TestClopperPearsonAgainstScipy:
    """exact 이항 CI — scipy 와 소수점 6자리까지 일치해야 한다."""

    CASES = [(0, 10), (0, 50), (0, 300), (1, 50), (3, 50), (5, 32), (25, 50), (50, 50), (2, 7)]

    @pytest.mark.parametrize("k,n", CASES)
    def test_matches_scipy(self, k: int, n: int) -> None:
        sp = pytest.importorskip("scipy.stats")
        lo, hi = st.clopper_pearson(k, n)
        ref = sp.binomtest(k, n).proportion_ci(confidence_level=0.95, method="exact")
        assert abs(lo - ref.low) < 1e-6
        assert abs(hi - ref.high) < 1e-6

    def test_zero_failures_upper_bound_is_not_zero(self) -> None:
        """0/n 이 "실패율 0" 을 뜻하지 않는다는 게 이 도구의 핵심 방어선이다."""
        lo, hi = st.clopper_pearson(0, 50)
        assert lo == 0.0
        assert hi > 0.07, "0/50 의 95% 상한은 7% 대여야 한다"

    def test_rule_of_three_is_an_approximation_not_the_value(self) -> None:
        """3/n 근사는 exact 보다 상한을 **과소평가**한다. 근사를 값으로 쓰면 안 된다."""
        for n in (10, 50, 100, 300):
            exact_hi = st.clopper_pearson(0, n)[1]
            assert exact_hi > 3.0 / n, f"n={n}: exact({exact_hi:.4f}) 가 3/n({3 / n:.4f}) 보다 커야 한다"

    def test_degenerate_n(self) -> None:
        assert st.clopper_pearson(0, 0) == (0.0, 1.0)


class TestMcNemarAgainstReference:
    CASES = [(0, 0), (1, 0), (0, 3), (2, 5), (3, 3), (1, 8), (10, 2), (4, 4), (0, 12)]

    @pytest.mark.parametrize("b,c", CASES)
    def test_matches_scipy_binomtest(self, b: int, c: int) -> None:
        sp = pytest.importorskip("scipy.stats")
        mine = st.mcnemar_exact(b, c)
        ref = sp.binomtest(min(b, c), b + c, 0.5).pvalue if b + c else 1.0
        assert abs(mine - ref) < 1e-9

    @pytest.mark.parametrize("b,c", [(1, 0), (0, 3), (2, 5), (1, 8), (10, 2)])
    def test_matches_statsmodels(self, b: int, c: int) -> None:
        sm = pytest.importorskip("statsmodels.stats.contingency_tables")
        assert abs(st.mcnemar_exact(b, c) - sm.mcnemar([[0, b], [c, 0]], exact=True).pvalue) < 1e-9

    def test_no_discordant_pairs_is_p_one(self) -> None:
        """둘 다 같은 결과만 나오면 짝지은 검정은 정보가 없다."""
        assert st.mcnemar_exact(0, 0) == 1.0

    def test_symmetric(self) -> None:
        assert st.mcnemar_exact(3, 9) == st.mcnemar_exact(9, 3)


class TestPairedVerdict:
    @staticmethod
    def _mk(a_fail_ids: set[str], b_fail_ids: set[str], n: int = 50):
        ids = [f"p{i:02d}" for i in range(n)]
        return (
            {i: (i in a_fail_ids) for i in ids},
            {i: (i in b_fail_ids) for i in ids},
        )

    def test_double_zero_is_saturation_not_a_tie(self) -> None:
        """이 하네스가 가장 자주 저지른 과잉 주장."""
        a, b = self._mk(set(), set())
        v = st.paired_verdict(a, b)
        assert v.decision == "판정 보류 (포화)"
        assert "동률이 아니라" in v.detail
        assert "7.1%" in v.detail or "7.0%" in v.detail  # exact 상한이 문구에 들어가야 한다
        assert "동률" not in v.decision

    def test_challenger_clearly_worse_blocks_promotion(self) -> None:
        a, b = self._mk(set(), {f"p{i:02d}" for i in range(9)})
        v = st.paired_verdict(a, b)
        assert v.decision == "승격 불가"
        assert v.b_only == 9 and v.a_only == 0

    def test_challenger_clearly_better_is_candidate(self) -> None:
        a, b = self._mk({f"p{i:02d}" for i in range(9)}, set())
        assert st.paired_verdict(a, b).decision == "승격 후보"

    def test_small_symmetric_difference_is_undetected_not_equal(self) -> None:
        """차이 미검출은 '같다'가 아니다 — 문구가 그렇게 말해야 한다."""
        a, b = self._mk({"p01"}, {"p02"})
        v = st.paired_verdict(a, b)
        assert v.decision == "차이 미검출"
        assert "같다는 뜻이 아니라" in v.detail

    def test_margin_violation_blocks_even_without_significance(self) -> None:
        """사전 마진 초과는 p-value 와 무관하게 승격 불가여야 한다."""
        a, b = self._mk(set(), {"p01", "p02"}, n=50)  # +4%p > 1%p 마진
        v = st.paired_verdict(a, b)
        assert v.decision == "승격 불가"
        assert "마진" in v.detail

    def test_only_paired_ids_are_used(self) -> None:
        """한쪽에만 있는 프롬프트를 세면 짝지은 검정이 아니게 된다."""
        a = {"x": False, "y": False, "z": True}
        b = {"x": False, "y": False}
        v = st.paired_verdict(a, b)
        assert v.n_pairs == 2
        assert v.a_fail == 0

    def test_empty_intersection(self) -> None:
        v = st.paired_verdict({"a": False}, {"b": False})
        assert v.n_pairs == 0
        assert v.decision == "판정 불가"

    def test_render_exposes_the_numbers(self) -> None:
        a, b = self._mk(set(), set())
        out = st.render(st.paired_verdict(a, b), "incumbent", "challenger")
        for token in ("McNemar", "exact p", "95% CI", "사전 마진", "판정"):
            assert token in out


class TestPredeclaredMargin:
    def test_margin_is_declared_and_tight(self) -> None:
        """사후에 정하면 결론에 맞춰 기준을 고르게 된다 — 상수로 고정한다."""
        assert st.NONINFERIORITY_MARGIN_PP == 1.0
        assert st.ALPHA == 0.05
