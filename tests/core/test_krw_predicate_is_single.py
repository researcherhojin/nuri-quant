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


class TestCurrencySitesUseThePredicate:
    """환산하는 곳은 **정본 술어**를 경유한다 — 접미사 단독으로 돌아가면 FAIL.

    시장 질문(`region` / `session` / `market` / universe 필터)은 대상이 아니다.
    """

    #: 통화 환산을 하는 함수와, 그 안에서 술어를 부르는지 확인할 파일.
    CONVERSION_SITES = (
        "analysis/portfolio.py",
        "analysis/sector.py",
        "alerts/risk_signals.py",
        "alerts/premarket_brief.py",
        "trading/recommend/price_targets.py",
        "trading/recommend/holdings_monitor.py",
    )

    @pytest.mark.parametrize("rel", CONVERSION_SITES)
    def test_site_calls_the_predicate(self, rel):
        src = (NURI / rel).read_text(encoding="utf-8")
        assert "is_krw_holding(" in src, f"{rel}: 정본 술어를 쓰지 않는다"

    def test_every_listed_site_exists(self):
        """양방향 — 파일이 사라지거나 이름이 바뀌면 위 검사가 조용히 공허해진다."""
        missing = [r for r in self.CONVERSION_SITES if not (NURI / r).exists()]
        assert not missing, f"목록이 낡았다 (파일 없음): {missing}"


class TestGuardAndLoopAgree:
    """가드와 환산 루프가 **같은 술어**를 써야 한다 (#1286 의 핵심 모순).

    `premarket_brief` 에서 가드는 정본, 루프는 접미사 단독이었다. 그러면 가드가
    "환산 불가" 로 판정한 보유를 루프는 달러로 계산한다 — 한 함수 안에서 두 판정이
    서로 반대되는 상태다.

    ⚠️ **호출 수는 AST 로 센다.** 처음엔 `src.count("is_krw_holding(")` 로 셌는데,
    같은 파일의 **주석**에 `is_krw_holding()` 이 들어 있어 카운트가 하나 부풀었고,
    루프를 접미사 단독으로 되돌리는 뮤테이션이 **통과**했다 (실측). 이 레포가 이미
    아는 함정이다 — `test_no_facade_query_patch.py` 가 "독스트링/주석 언급은 오탐" 이라
    텍스트 스윕을 기각한 것과 같은 이유.
    """

    @staticmethod
    def _calls(rel: str) -> int:
        tree = ast.parse((NURI / rel).read_text(encoding="utf-8"))
        return sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "is_krw_holding"
        )

    def test_premarket_brief_uses_one_predicate(self):
        """Mutation lock: 가드나 루프 중 하나를 접미사 단독으로 되돌리면 FAIL."""
        assert self._calls("alerts/premarket_brief.py") >= 2, (
            "가드와 루프 중 한쪽이 접미사 단독으로 돌아갔다 — 같은 함수 안에서 판정이 갈린다"
        )

    def test_price_targets_uses_one_predicate(self):
        assert self._calls("trading/recommend/price_targets.py") >= 2, "MDD 가드와 환산 루프의 술어가 갈렸다"

    def test_the_counter_ignores_comments(self):
        """카나리아 — 주석 속 언급을 세면 위 두 잠금이 조용히 헐거워진다 (실제로 그랬다)."""
        import tempfile

        src = "# is_krw_holding() 를 쓴다\nx = is_krw_holding(a, b)\n"
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.py"
            f.write_text(src, encoding="utf-8")
            tree = ast.parse(f.read_text(encoding="utf-8"))
            n = sum(
                1
                for x in ast.walk(tree)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "is_krw_holding"
            )
        assert n == 1, f"주석을 호출로 셌다: {n}"
        assert src.count("is_krw_holding(") == 2, "텍스트 카운트는 실제로 부풀어야 한다(대조)"
