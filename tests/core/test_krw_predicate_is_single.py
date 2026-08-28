"""원화 표시 여부를 묻는 술어는 **하나뿐이다** (#1286).

## 무엇이 잘못됐었나

"이 보유가 원화인가" 라는 판정이 **5곳에 인라인 복사**돼 있었고, 그중 2곳은 통화를
보지 않고 **접미사만** 봤다:

- `analysis/portfolio.py` · `analysis/sector.py` · `alerts/risk_signals.py` — `currency == "KRW" or is_kr_ticker(...)`
- `recommend/holdings_monitor.py` — 같은 판정을 `if` 두 개로 펼쳐 씀 (게다가 `.upper()`)
- `recommend/price_targets.py` · `alerts/premarket_brief.py` — **`is_kr_ticker()` 단독** ← 결함

접미사만 보면 `currency="KRW"` 인데 `.KS`/`.KQ` 가 없는 보유가 **달러로 취급**된다.
환율이 정상일 때도 틀리고, 오차가 1,380배다. `premarket_brief` 에서는 #1284 가 넣은
가드(정본 술어)와 환산 루프(접미사 단독)가 **서로 어긋나** 있어서, 가드는 "환산 불가"
라고 판정하는데 루프는 달러로 계산하는 모순이 있었다.

## ⚠️ 왜 단순 스윕이 아닌가

`is_kr_ticker()` 는 **두 가지 다른 질문**에 쓰인다:

1. **통화** — "이 보유가 원화 표시인가" → `currency` 도 봐야 한다 (이 파일의 대상)
2. **시장/세션/유니버스** — "이게 한국 시장 종목인가" → **접미사 단독이 맞다**
   (`collectors/base.py` 의 market 필터, `risk_signals.py` 의 session 게이트,
   `sector.py:54` 의 `region`, `forward_outcome_tracker.py` 의 `market`)

`analysis/sector.py` 는 두 질문을 **나란히** 쓴다 — 52행은 통화(환산), 54행은 지역.
그래서 "`is_kr_ticker` 를 전부 바꿔라" 식의 스윕은 **정상 코드를 오탐**한다. 여기서는
대신 **인라인 사본이 다시 생기는 것**을 막는다: 그게 실제 재발 경로였다.
"""

import ast
import re
from pathlib import Path

import pytest

from nuri.core.fx import is_krw_holding

NURI = Path(__file__).resolve().parents[2] / "nuri"
#: 술어의 유일한 정의처. 여기 말고 어디에도 같은 식이 다시 나타나면 안 된다.
HOME = "core/fx.py"


class TestThePredicateItself:
    @pytest.mark.parametrize(
        ("ticker", "currency", "expected"),
        [
            ("999999.KS", "KRW", True),  # 둘 다
            ("888888.KQ", None, True),  # 접미사만 — 코스닥
            ("YYYY", "KRW", True),  # 통화만 (접미사 없음) ← 결함이던 축
            ("YYYY", "krw", True),  # 대소문자 무시 (holdings_monitor 가 하던 것)
            ("999999.KS", "USD", True),  # 통화가 틀려도 접미사가 KR
            ("ZZZZ", "USD", False),
            ("ZZZZ", None, False),
            ("ZZZZ", "", False),
        ],
    )
    def test_currency_or_suffix(self, ticker, currency, expected):
        assert is_krw_holding(ticker, currency) is expected

    def test_none_currency_never_raises(self):
        """`.get("currency")` 가 None 을 주는 호출자가 있다 — 터지면 안 된다."""
        assert is_krw_holding("ZZZZ", None) is False


class TestNoInlineCopyRemains:
    """구조 스윕 — 사본이 다시 생기는 걸 막는다.

    동작 잠금은 지금 있는 소비자만 덮는다. 이 결함이 5곳으로 번진 방식이 바로
    "새 곳에서 같은 식을 다시 쓰기" 였다.
    """

    #: 인라인 사본의 형태 — 같은 줄에서 `currency` 와 `is_kr_ticker` 를 함께 보는 것.
    INLINE = re.compile(r'currency.*==.*["\']KRW["\'].*is_kr_ticker|is_kr_ticker.*currency.*==.*["\']KRW["\']')

    @classmethod
    def _copies(cls) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for f in sorted(NURI.rglob("*.py")):
            rel = str(f.relative_to(NURI))
            if rel == HOME:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#")[0]
                if cls.INLINE.search(code):
                    out.setdefault(rel, []).append(i)
        return out

    def test_no_module_reimplements_the_predicate(self):
        found = self._copies()
        assert not found, f"원화 판정을 인라인으로 다시 구현한 곳: {found}"

    def test_the_sweep_has_eyes(self):
        """카나리아 — 양방향. 옛 사본 형태를 잡고, 정상 코드를 오탐하지 않아야 한다."""
        bad = '        is_krw = currency == "KRW" or is_kr_ticker(ticker)'
        bad2 = '        cur = "KRW" if (r.get("currency") == "KRW" or is_kr_ticker(t)) else "USD"'
        # 시장 질문 — 접미사 단독은 **정상**이다. 오탐하면 안 된다.
        ok1 = '        region = "KR" if is_kr_ticker(row["ticker"]) else "US"'
        ok2 = '        if session == "kr" and not is_kr_ticker(ticker):'
        ok3 = '        market = "kr" if is_kr_ticker(ticker) else "us"'
        assert self.INLINE.search(bad), "옛 사본 형태를 못 잡는다"
        assert self.INLINE.search(bad2), "괄호 낀 변종을 못 잡는다"
        for ok in (ok1, ok2, ok3):
            assert not self.INLINE.search(ok), f"시장 질문을 오탐한다: {ok.strip()}"


def _calls_in(rel: str, func: str | None = None) -> dict[str, int]:
    """`rel` 안에서 술어 호출 수를 센다. `func` 를 주면 **그 함수 본문만** 본다.

    ⚠️ 텍스트 카운트가 아니라 AST **Call 노드**를 센다. 처음엔 `src.count(...)` 로 셌다가
    같은 파일 **주석**에 `is_krw_holding()` 이 있어 카운트가 부풀었고, 루프를 되돌리는
    뮤테이션이 통과했다 (실측). 이 레포가 이미 아는 함정이다
    (`test_no_facade_query_patch.py`: "독스트링/주석 언급은 오탐").

    ⚠️ 그리고 **함수 단위**로 센다. 파일 전체를 세면, 대상 분기가 접미사 단독으로
    회귀해도 파일 어딘가에 무관한 호출이 하나 더 생기면 잠금이 헐거워진다
    (codex 리뷰 P3).
    """
    tree = ast.parse((NURI / rel).read_text(encoding="utf-8"))
    scope: ast.AST = tree
    if func is not None:
        found = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func]
        assert found, f"{rel}: 함수 {func} 를 찾지 못했다 — 이름이 바뀌면 잠금이 공허해진다"
        scope = found[0]
    out = {"is_krw_holding": 0, "is_kr_ticker": 0}
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in out:
            out[n.func.id] += 1
    return out


class TestCurrencySitesUseThePredicate:
    """환산하는 곳은 **정본 술어**를 실제로 **호출**한다.

    codex 리뷰 P3: 예전에는 파일에 문자열이 있기만 하면 통과해서, import 나 주석만
    남고 정작 환산 분기가 접미사 단독으로 회귀해도 초록이었다.
    """

    #: (파일, 환산 함수) — 함수 단위로 확인한다. `None` 은 **같은 함수 안에서 시장
    #: 질문도 하는 곳**이라 "접미사 단독 호출 0개" 규칙을 적용할 수 없다는 뜻이다:
    #:   - `sector.analyze_sector` — 53행 통화(환산), 55행 `region`(시장). 두 줄 간격.
    #:   - `risk_signals` — session 게이트가 접미사 단독으로 판정하는 게 **맞다**.
    #: 이 둘은 술어 **호출 여부**만 확인하고, 접미사 금지는 걸지 않는다.
    CONVERSION_SITES = (
        ("analysis/portfolio.py", "analyze_portfolio"),
        ("analysis/sector.py", None),
        ("alerts/risk_signals.py", None),
        ("alerts/premarket_brief.py", "_collect_context"),
        ("trading/recommend/price_targets.py", "check_portfolio_mdd"),
        ("trading/recommend/holdings_monitor.py", "_classify_asset_class"),
    )

    @pytest.mark.parametrize(("rel", "func"), CONVERSION_SITES)
    def test_site_calls_the_predicate(self, rel, func):
        counts = _calls_in(rel, func)
        where = f"{rel}::{func}" if func else rel
        assert counts["is_krw_holding"] >= 1, f"{where}: 정본 술어를 호출하지 않는다"

    @pytest.mark.parametrize(("rel", "func"), CONVERSION_SITES)
    def test_no_conversion_site_still_asks_only_the_suffix(self, rel, func):
        """환산 함수 안에 `is_kr_ticker` 직접 호출이 남아 있으면 술어가 갈린 것이다.

        Mutation lock: 어느 환산 분기든 `is_kr_ticker(...)` 로 되돌리면 FAIL — 파일
        어딘가의 무관한 호출로는 우회되지 않는다 (함수 스코프).
        """
        if func is None:
            pytest.skip("같은 함수 안에서 시장 질문도 하는 곳 — 위 CONVERSION_SITES 주석 참조")
        counts = _calls_in(rel, func)
        assert counts["is_kr_ticker"] == 0, (
            f"{rel}::{func}: 환산 함수 안에서 접미사 단독 판정을 쓴다 "
            f"({counts['is_kr_ticker']}회) — 통화 질문에는 `is_krw_holding` 을 쓴다"
        )

    def test_every_listed_site_exists(self):
        """양방향 — 파일이 사라지거나 이름이 바뀌면 위 검사가 조용히 공허해진다."""
        missing = [r for r, _ in self.CONVERSION_SITES if not (NURI / r).exists()]
        assert not missing, f"목록이 낡았다 (파일 없음): {missing}"


class TestGuardAndLoopAgree:
    """가드와 환산 루프가 **같은 술어**를 쓴다 (#1286 의 핵심 모순).

    `premarket_brief` 에서 가드는 정본, 루프는 접미사 단독이었다 — 가드가 "환산 불가"
    로 판정한 보유를 같은 함수의 루프가 달러로 계산했다.
    """

    def test_premarket_brief_guard_and_loop(self):
        c = _calls_in("alerts/premarket_brief.py", "_collect_context")
        assert c["is_krw_holding"] >= 2, "가드와 루프 중 한쪽이 접미사 단독으로 돌아갔다"

    def test_price_targets_guard_and_loop(self):
        c = _calls_in("trading/recommend/price_targets.py", "check_portfolio_mdd")
        assert c["is_krw_holding"] >= 2, "MDD 가드와 환산 루프의 술어가 갈렸다"

    def test_the_counter_is_function_scoped(self):
        """카나리아 — 파일 전체를 세면 무관한 호출이 잠금을 헐겁게 한다 (codex P3)."""
        whole = _calls_in("trading/recommend/price_targets.py")
        scoped = _calls_in("trading/recommend/price_targets.py", "check_portfolio_mdd")
        assert scoped["is_krw_holding"] <= whole["is_krw_holding"], "스코프가 파일보다 넓다"
        assert scoped["is_krw_holding"] >= 2

    def test_the_counter_ignores_comments(self):
        """카나리아 — 주석 속 언급을 세면 잠금이 조용히 헐거워진다 (실제로 그랬다)."""
        src = "# is_krw_holding() 를 쓴다\nx = is_krw_holding(a, b)\n"
        tree = ast.parse(src)
        n = sum(
            1
            for x in ast.walk(tree)
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "is_krw_holding"
        )
        assert n == 1, f"주석을 호출로 셌다: {n}"
        assert src.count("is_krw_holding(") == 2, "텍스트 카운트는 실제로 부풀어야 한다(대조)"
