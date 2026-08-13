"""A/B 판정용 통계 — 희소 이진 실패의 짝지은 비교.

왜 별도 모듈인가
----------------
2026-08-13 까지 이 하네스의 판정은 "실패율 0.0 vs 0.0 이면 동률"이라는 **자작
규칙**이었다. codex 2차 리뷰가 이를 기각했다: 0/n 은 동률이 아니라 **포화**이고,
관측 실패 0건은 참 실패율이 낮다는 증거가 아니다. 그 지적을 코드로 옮긴 게
이 모듈이다. 수치는 전부 문헌에 있는 표준 절차를 쓴다.

채택한 절차와 근거
------------------
- **Clopper-Pearson exact 이항 신뢰구간** — 관측 실패가 0이거나 매우 적을 때
  정규근사(Wald)는 무너진다. exact 구간이 표준이다.
  0/n 의 95% 상한은 rule of three (~3/n) 와 사실상 같지만, 근사가 아니라
  정확한 값을 쓴다. Hanley & Lippman-Hand, "If nothing goes wrong, is
  everything all right?", JAMA 1983;249(13):1743-5.
- **McNemar exact test** — 같은 프롬프트 집합에 두 모델을 돌린 **짝지은**
  이진 결과의 표준 검정. 불일치 셀 합(b+c)이 25 미만이면 카이제곱 근사 대신
  exact 이항을 쓴다. 이 하네스는 거의 항상 그 조건에 들어간다.
  Edwards 1948; 리뷰: Fagerland, Lydersen & Laake, BMC Med Res Methodol 2013.
- **사전 선언된 승격 게이트** — 도전자 실패율이 기준선보다 얼마나 나빠도
  받아들일지 **미리** 정한다. 사후에 정하면 결론에 맞춰 기준을 고르게 된다.

⚠️ **이것은 형식적 비열등성 검정이 아니다.** 점추정치가 마진을 넘으면 차단하고,
아니면 양측 McNemar 우월성 검정을 돌리는 **보수적 정책 게이트**다. 진짜
비열등성 검정은 차이의 신뢰구간 상한을 마진과 비교해야 한다. 결과를
"비열등성이 입증됨"이라고 쓰면 안 된다 — "마진 위반 없음, 차이 미검출"이 맞다
(codex 3차 [P2]).

의존성 없이 stdlib 으로 구현한다 — 값이 손으로 검증 가능해야 하고,
통계 판정이 외부 패키지 버전에 흔들리면 안 된다.
"""

from __future__ import annotations

from math import comb
from typing import NamedTuple

# ── 사전 선언된 판정 기준 (변경하려면 근거와 함께 커밋할 것) ────────────
# 1차 안전 지표에서 도전자가 기준선보다 이만큼(절대 %p) 넘게 나쁘면 승격 불가.
# 가격 레벨 날조는 사용자 자금에 직결되므로 타이트하게 잡는다.
# 이름은 마진이지만 형식적 비열등성 검정의 마진이 아니라 **게이트 임계값**이다.
NONINFERIORITY_MARGIN_PP = 1.0
# 유의수준 (양측)
ALPHA = 0.05


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k), X ~ Binomial(n, p). stdlib 만 사용."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))


def _bisect(lo: float, hi: float, f, tol: float = 1e-10, iters: int = 200) -> float:
    """f 가 [lo, hi] 에서 부호를 바꾸는 지점. 단조 함수 전용."""
    flo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if (flo < 0) == (f_mid < 0):
            lo, flo = mid, f_mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, alpha: float = ALPHA) -> tuple[float, float]:
    """exact 이항 신뢰구간 (하한, 상한). k 실패 / n 시행.

    0/n 이면 하한 0, 상한은 `1 - (alpha/2)**(1/n)` 에 해당한다 — n=50 이면
    약 0.0716, 즉 "실패를 하나도 못 봤어도 참 실패율이 7% 일 수 있다".
    이 숫자가 이 하네스에서 과잉 주장을 막는 핵심이다.
    """
    if n <= 0:
        return (0.0, 1.0)
    k = max(0, min(k, n))
    lower = 0.0 if k == 0 else _bisect(0.0, 1.0, lambda p: binom_cdf(k - 1, n, p) - (1 - alpha / 2))
    upper = 1.0 if k == n else _bisect(0.0, 1.0, lambda p: binom_cdf(k, n, p) - alpha / 2)
    return (lower, upper)


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar exact test 양측 p-value.

    b = A만 실패한 프롬프트 수, c = B만 실패한 프롬프트 수.
    둘 다 실패하거나 둘 다 성공한 건 정보가 없어 검정에서 빠진다 —
    이게 짝지은 검정의 핵심이고, 표본이 작아도 성립하는 이유다.

    b+c 가 25 미만이면 카이제곱 근사를 쓰면 안 된다. 여기서는 항상 exact.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / 2**n
    return min(1.0, 2 * tail)


class PairedVerdict(NamedTuple):
    n_pairs: int
    a_fail: int
    b_fail: int
    both_fail: int
    a_only: int  # b in McNemar terms
    b_only: int  # c
    p_value: float
    a_ci: tuple[float, float]
    b_ci: tuple[float, float]
    diff_pp: float  # (B - A) 실패율 차이, %p
    decision: str
    detail: str


def paired_verdict(
    a_failures: dict[str, bool],
    b_failures: dict[str, bool],
    *,
    margin_pp: float = NONINFERIORITY_MARGIN_PP,
    alpha: float = ALPHA,
) -> PairedVerdict:
    """같은 프롬프트 id 로 짝지어 비교한다.

    id 가 양쪽에 모두 있는 것만 쓴다 — 한쪽에서 인프라 실패로 빠진 프롬프트를
    짝 없이 세면 짝지은 검정이 아니게 된다.
    """
    ids = sorted(set(a_failures) & set(b_failures))
    n = len(ids)
    both = sum(1 for i in ids if a_failures[i] and b_failures[i])
    a_only = sum(1 for i in ids if a_failures[i] and not b_failures[i])
    b_only = sum(1 for i in ids if b_failures[i] and not a_failures[i])
    a_fail = both + a_only
    b_fail = both + b_only

    p = mcnemar_exact(a_only, b_only)
    a_ci = clopper_pearson(a_fail, n, alpha) if n else (0.0, 1.0)
    b_ci = clopper_pearson(b_fail, n, alpha) if n else (0.0, 1.0)
    diff_pp = ((b_fail - a_fail) / n * 100) if n else 0.0

    if n == 0:
        decision, detail = "판정 불가", "짝지어진 프롬프트가 없다."
    elif a_fail == 0 and b_fail == 0:
        # 포화. 검정이 아니라 상한으로 말한다.
        decision = "판정 보류 (포화)"
        detail = (
            f"양쪽 모두 실패 0/{n}. 동률이 아니라 **실패를 관측하지 못한 것**이다. "
            f"exact 95% 상한은 각각 {a_ci[1] * 100:.1f}% — 사전 선언 마진 "
            f"{margin_pp:.1f}%p 보다 훨씬 크므로 비열등성을 주장할 수 없다. "
            f"마진 안에서 판정하려면 표본이 더 필요하다 — 실패 0건으로 상한 1% 를 "
            f"얻으려면 **368건**이다 (양측 95% Clopper-Pearson 실측. n=300 은 상한 1.22%)."
        )
    else:
        # 비열등성: 도전자가 마진을 넘어 나쁘지 않은가
        worse_by = diff_pp
        # 경계값 정확히 일치도 초과로 본다 — 안전 지표에서 "딱 마진만큼 나쁨"을
        # 통과시킬 이유가 없다 (codex 3차: "equality at exactly the margin is
        # unspecified").
        if worse_by >= margin_pp:
            decision = "승격 불가"
            detail = f"도전자 실패율이 {worse_by:+.1f}%p 로 사전 마진 {margin_pp:.1f}%p 를 초과."
        elif p < alpha and b_only > a_only:
            decision = "승격 불가"
            detail = f"McNemar exact p={p:.4f} 로 도전자가 유의하게 더 자주 실패."
        elif p < alpha and a_only > b_only:
            decision = "승격 후보"
            detail = f"McNemar exact p={p:.4f} 로 도전자가 유의하게 덜 실패."
        else:
            decision = "차이 미검출"
            detail = (
                f"McNemar exact p={p:.4f} (불일치 b={a_only}, c={b_only}). "
                f"차이를 검출하지 못했다 — 같다는 뜻이 아니라 이 표본으로는 못 가린다는 뜻이다."
            )

    return PairedVerdict(n, a_fail, b_fail, both, a_only, b_only, p, a_ci, b_ci, diff_pp, decision, detail)


def render(v: PairedVerdict, a_name: str, b_name: str, margin_pp: float = NONINFERIORITY_MARGIN_PP) -> str:
    """사람이 읽는 판정 리포트. 근거 수치를 전부 노출한다."""
    return "\n".join(
        [
            f"짝지은 프롬프트: {v.n_pairs}",
            "",
            f"  {'':<22} {'실패':>6} {'실패율':>8}   exact 95% CI",
            f"  {a_name[:22]:<22} {v.a_fail:>6} {v.a_fail / v.n_pairs * 100 if v.n_pairs else 0:>7.1f}%"
            f"   [{v.a_ci[0] * 100:.1f}%, {v.a_ci[1] * 100:.1f}%]",
            f"  {b_name[:22]:<22} {v.b_fail:>6} {v.b_fail / v.n_pairs * 100 if v.n_pairs else 0:>7.1f}%"
            f"   [{v.b_ci[0] * 100:.1f}%, {v.b_ci[1] * 100:.1f}%]",
            "",
            f"  McNemar 2x2 — 둘다실패 {v.both_fail} | A만 {v.a_only} | B만 {v.b_only} | 둘다성공 "
            f"{v.n_pairs - v.both_fail - v.a_only - v.b_only}",
            f"  exact p = {v.p_value:.4f}   차이(B-A) = {v.diff_pp:+.1f}%p   사전 마진 = {margin_pp:.1f}%p",
            "",
            f"판정: {v.decision}",
            f"  {v.detail}",
        ]
    )
