"""환율이 없을 때 **숫자를 지어내지 않는다** (#1283).

## 무엇이 잘못됐었나

#1278 이 "최신 환율" 읽기를 `nuri/core/fx.py` 한 곳으로 모으면서 부재를 `None` 으로
정직하게 냈다 (STRATEGY §2.6). 그런데 그 `None` 을 받는 소비자가 전부 `or 1400` 으로
즉시 메웠다 — **단일 읽기 지점이 생겼을 뿐 fabrication 은 그대로**였다. 상수도 하나가
아니었다: 6곳이 1400, `print_summary` 만 1450 이라 같은 부재에 두 개의 답이 있었다.

프로덕션 환율은 1383.52(2026-08-29)라 1400 은 +1.2% 다. **오차 자체는 작다 — 문제는
부재가 숫자로 둔갑해 수집기가 죽어도 아무도 모른다는 것이다.** #1278 이 정확히 그
형태였다(미래 행이 노후 경고까지 죽여 이중으로 눈이 멀어 있었다).

## 왜 소비자별로 따로 잠그나

`tests/CLAUDE.md` Time-bomb 2차 발생의 교훈 그대로 — *"규칙 하나에 잠금이 한 경로만
걸려 있으면 나머지 경로는 무방비다."* 이 결함은 8곳에 흩어져 있었다.

## 대조군이 왜 필요한가

"환율 없으면 None" 만 잠그면 **전부 None 을 반환하는 가짜 수정**이 통과한다. 환율이
없어도 **US 전용 집계는 정확히 계산된다** — 일괄 포기는 과잉이고, 그 구분이 이 PR 의
설계다. 그래서 각 경로마다 대조군을 짝지어 둔다.

API/프론트 4곳(`actions.py` · `dashboard.py` ×2 · `page.tsx`)은 응답 형태가 바뀌어
프론트와 같이 움직여야 하므로 **#1284** 로 분리했다. 아래 `FABRICATION_EXEMPT` 가
그 4곳 중 Python 3곳을 사유와 함께 붙잡고 있고, #1284 가 랜딩하면 **stale 로 FAIL** 해서
제거를 강제한다.
"""

import ast
import logging
import re
from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db
from nuri.core.fx import latest_usd_krw, latest_usd_krw_value
from nuri.core.timezone import today_kst

TODAY = today_kst()

#: 합성 종목 — 실제 보유와 무관하다 (public repo, `tests/CLAUDE.md` privacy).
KR_TICKER = "999999.KS"
US_TICKER = "ZZZZ"
ACCOUNT = "Brokerage Alpha"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "fx.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _seed_fx(db_path, value, date=TODAY):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro (indicator, date, value, source) VALUES ('usd_krw', ?, ?, 'test')",
            (date, value),
        )


def _seed_holding(db_path, ticker, avg_price, quantity, close=None):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
            (ACCOUNT, ticker, quantity, avg_price),
        )
        if close is not None:
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                (ticker, TODAY, close),
            )


class TestARateIsPositiveOrAbsent:
    """0/음수는 환율이 아니라 손상된 행이다 — 부재로 접는다.

    이 불변식이 없으면 `0.0` 이 "값이 있다" 로 통과해 호출자마다 다르게 터진다:
    나눗셈 하는 쪽은 `ZeroDivisionError`, `or` 폴백을 둔 쪽은 조용히 지어낸 숫자.
    `portfolio.py` 의 죽은 폴백을 안전하게 지울 수 있는 근거이기도 하다.
    """

    def test_zero_is_treated_as_absent(self, db):
        """Mutation lock: `if value <= 0` 가드를 지우면 FAIL."""
        _seed_fx(db, 0.0)
        assert latest_usd_krw_value() is None, "0.0 을 환율로 냈다"

    def test_negative_is_treated_as_absent(self, db):
        _seed_fx(db, -1380.0)
        assert latest_usd_krw_value() is None

    def test_corrupt_row_is_logged(self, db, caplog):
        """조용히 버리면 손상 행이 영영 안 보인다."""
        _seed_fx(db, 0.0)
        with caplog.at_level(logging.WARNING, logger="nuri.core.fx"):
            latest_usd_krw_value()
        assert caplog.records, "손상된 환율 행을 발견하고도 경고하지 않았다"

    def test_positive_rate_still_returned(self, db):
        """대조군 — 정상 값까지 삼키는 가짜 수정을 막는다."""
        _seed_fx(db, 1380.0)
        got = latest_usd_krw()
        assert got is not None and got[0] == pytest.approx(1380.0)


class TestPortfolioStateHasNoFabricatedRate:
    """`rate = get_exchange_rate(...) or 1400.0` 이 여기 있었다 (도달 불가였다)."""

    def test_corrupt_rate_raises_instead_of_falling_back(self, db):
        """Mutation lock: `or 1400.0` 을 되살리면 예외 대신 1400 으로 진행해 FAIL."""
        from nuri.analysis.portfolio import StaleExchangeRateError, portfolio_state

        _seed_fx(db, 0.0)
        _seed_holding(db, US_TICKER, avg_price=100.0, quantity=10, close=100.0)
        with pytest.raises(StaleExchangeRateError):
            portfolio_state(db_path=db)

    def test_valid_rate_still_works(self, db):
        """대조군 — 정상 환율에서는 예전과 똑같이 동작한다."""
        from nuri.analysis.portfolio import portfolio_state

        _seed_fx(db, 1380.0)
        _seed_holding(db, US_TICKER, avg_price=100.0, quantity=10, close=100.0)
        assert isinstance(portfolio_state(db_path=db), dict)


class TestPrintSummaryDoesNotInventARate:
    """`df.attrs.get("usd_krw", 1450.0)` — 나머지가 전부 1400 인데 여기만 1450 이었다."""

    @staticmethod
    def _frame(rate):
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "account": ACCOUNT,
                    "ticker": US_TICKER,
                    "weight_pct": 100.0,
                    "current_price": 100.0,
                    "avg_price": 100.0,
                    "pnl_pct": 0.0,
                    "pnl_usd": 0.0,
                    "current_value_usd": 1000.0,
                }
            ]
        )
        df.attrs["total_value_usd"] = 1000.0
        if rate is not None:
            df.attrs["usd_krw"] = rate
        return df

    def test_missing_rate_says_so_instead_of_printing_1450(self, capsys):
        """Mutation lock: 기본값 1450.0 을 되살리면 FAIL."""
        from nuri.analysis.portfolio import print_summary

        print_summary(self._frame(None))
        out = capsys.readouterr().out
        assert "미수집" in out, "환율이 없는데 있는 것처럼 출력했다"
        assert "1,450" not in out and "1,400" not in out, f"환율을 지어냈다: {out}"
        assert "$1,000" in out, "USD 총액은 환율과 무관하므로 계속 나와야 한다"

    def test_present_rate_prints_krw_total(self, capsys):
        """대조군 — 환율이 있으면 예전처럼 KRW 환산을 낸다."""
        from nuri.analysis.portfolio import print_summary

        print_summary(self._frame(1380.0))
        out = capsys.readouterr().out
        assert "1,380" in out and "미수집" not in out


class TestPortfolioMddAbstainsRatherThanGuess:
    """`usd_krw = 1400.0  # 폴백` — 지어낸 환율로 손절선을 판정했다.

    혼합 포트폴리오에서 `total_value/total_cost` 는 rate 에 의존하므로
    (`cost_us + cost_kr/rate` 꼴) 그 숫자가 `PORTFOLIO_STOP` 발화 여부를 가른다.

    ⚠️ 이 축은 **대조군 없이는 공허하다.** 위반이 없어도 `None` 이라, "환율 없음 → None"
    만 단언하면 아무것도 잠그지 못한다. 그래서 같은 보유를 환율만 넣어 돌려 **위반이
    실제로 잡히는지** 먼저 확인한다.
    """

    @staticmethod
    def _seed_deeply_underwater_kr(db_path):
        # 원가 대비 -50% — `PORTFOLIO_STOP`(-10%) 를 확실히 넘긴다.
        _seed_holding(db_path, KR_TICKER, avg_price=100_000.0, quantity=10, close=50_000.0)

    def test_with_a_rate_the_violation_is_detected(self, db):
        """대조군 겸 전제 — 이게 없으면 아래 테스트가 공허하다."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        _seed_fx(db, 1380.0)
        self._seed_deeply_underwater_kr(db)
        result = check_portfolio_mdd(db_path=db)
        assert result is not None and result["severity"] == "critical"

    def test_without_a_rate_it_abstains(self, db, caplog):
        """Mutation lock: `usd_krw = 1400.0` 폴백을 되살리면 위반 dict 가 나와 FAIL."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        self._seed_deeply_underwater_kr(db)  # 환율 미시드
        with caplog.at_level(logging.WARNING, logger="nuri.trading.recommend.price_targets"):
            assert check_portfolio_mdd(db_path=db) is None, "지어낸 환율로 손절선을 판정했다"
        assert caplog.records, "판정을 포기하고도 조용했다 — 아무도 수집기 결함을 모른다"

    def test_us_only_portfolio_still_judged_without_a_rate(self, db):
        """대조군 — 환율이 없어도 US 전용은 정확히 계산된다. 일괄 None 은 과잉이다."""
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        _seed_holding(db, US_TICKER, avg_price=100.0, quantity=10, close=50.0)
        result = check_portfolio_mdd(db_path=db)
        assert result is not None, "환율과 무관한 US 전용 포트폴리오까지 판정을 포기했다"
        assert result["pnl_pct"] == pytest.approx(-50.0)


class TestBriefOmitsTotalsRatherThanInventingThem:
    """`rate = latest_usd_krw_value(...) or 1400.0` — 매일 아침 읽는 브리프였다."""

    def test_without_a_rate_totals_are_omitted_with_a_reason(self, db, caplog):
        """Mutation lock: `or 1400.0` 을 되살리면 totals 가 채워져 FAIL."""
        from nuri.alerts.premarket_brief import _collect_context

        _seed_holding(db, KR_TICKER, avg_price=100_000.0, quantity=10, close=100_000.0)
        with caplog.at_level(logging.WARNING, logger="nuri.alerts.premarket_brief"):
            ctx = _collect_context(db_path=db)
        assert ctx["portfolio_totals"] is None, "지어낸 환율로 총액을 실었다"
        assert ctx["portfolio_totals_blocked"], "섹션이 그냥 사라졌다 — 이유가 없으면 결함처럼 보인다"

    def test_the_reason_reaches_both_renderers(self, db):
        """로그로만 남기면 아침에 읽는 사람에게 도달하지 않는다."""
        from nuri.alerts.premarket_brief import (
            _collect_context,
            format_brief_embed,
            format_brief_markdown,
        )

        _seed_holding(db, KR_TICKER, avg_price=100_000.0, quantity=10, close=100_000.0)
        ctx = _collect_context(db_path=db)

        md = format_brief_markdown(ctx)
        assert "미수집" in md, "markdown 브리프가 이유를 말하지 않는다"

        embed_text = str(format_brief_embed(ctx))
        assert "미수집" in embed_text, "Discord embed 가 이유를 말하지 않는다"

    def test_with_a_rate_totals_are_computed(self, db):
        """대조군 — 환율이 있으면 예전과 똑같이 총액을 낸다."""
        from nuri.alerts.premarket_brief import _collect_context

        _seed_fx(db, 1380.0)
        _seed_holding(db, KR_TICKER, avg_price=100_000.0, quantity=10, close=100_000.0)
        ctx = _collect_context(db_path=db)
        assert ctx["portfolio_totals"], "환율이 있는데 총액을 못 냈다"
        assert ctx["portfolio_totals_blocked"] is None

    def test_us_only_totals_computed_without_a_rate(self, db):
        """대조군 — 환율이 없어도 US 전용 보유는 환산이 필요 없다."""
        from nuri.alerts.premarket_brief import _collect_context

        _seed_holding(db, US_TICKER, avg_price=100.0, quantity=10, close=100.0)
        ctx = _collect_context(db_path=db)
        assert ctx["portfolio_totals"], "환율과 무관한 US 전용까지 총액을 포기했다"
        assert ctx["portfolio_totals"]["total_usd"] == pytest.approx(1000.0)


#: 환율 크기의 리터럴을 **일부러** 들고 있는 곳. 사유를 반드시 함께 적는다.
#: 양방향 검사라 낡은 항목(이미 정리된 파일)도 FAIL 한다 — allowlist 가 조용히 커지는 걸
#: 막는 것이 이 목록의 존재 이유다 (`test_cross_stage_imports.py` 와 같은 규율).
FABRICATION_EXEMPT: dict[str, str] = {
    "api/routes/actions.py": (
        "#1284 — 비중% 산정의 `or 1400`. 응답 형태가 바뀌어(집계가 null 이 된다) "
        "프론트(`page.tsx` · `holdings-summary.ts`)와 한 PR 에서 같이 움직여야 한다. "
        "백엔드만 먼저 정직해지면 `_compute_actual_allocation` 의 sum 이 TypeError 로 죽는다."
    ),
    "api/routes/dashboard.py": (
        "#1284 — `account_values[].value` 와 `cash_summary` 의 `or 1400` 2곳. "
        "위와 같은 이유로 프론트와 동시에 움직여야 한다. `/api/dashboard` 는 이미 "
        "`exchange_rate: number | null` 을 정직하게 내보내는데 프론트가 그 신호를 버린다."
    ),
    "trading/agents/korean_market.py": (
        "**성격이 다르다 — 지어낸 값이 아니다.** `fx_weak_default` / `fx_weak_floor` / "
        "`fx_strong_ceil` 은 `config/agents.yaml` 이 정본인 **정책 임계값**의 코드 기본값이고, "
        "무엇을 '원화 약세' 로 볼지의 선택이지 환율 **측정치**가 아니다. 측정 부재를 숫자로 "
        "메우는 것과 정책 기본값을 두는 것은 다른 일이다 (Config over code 준수)."
    ),
}


class TestNoNewFabricatedRateAppears:
    """구조 스윕 — 새 소비자가 또 `or 1400` 을 붙이는 걸 막는다.

    동작 잠금은 **지금 존재하는** 경로만 덮는다. 이 결함이 8곳으로 번진 방식이 바로
    "새 곳에서 같은 폴백을 다시 쓰기" 였다.

    ⚠️ **텍스트 스윕은 기각했다.** 처음에 정규식으로 짰더니 `core/fx.py` 의 독스트링
    ("**1417.4** 를 반환했다") 과 `dashboard.py` 의 독스트링("환율 누락 시 1400 기본값")을
    걸었다 — 코드가 아니라 *설명*이다. 이 레포가 이미 내린 판정과 같다
    (`test_no_facade_query_patch.py`: "독스트링/주석 언급은 오탐이라 텍스트 sweep 기각").
    그래서 **숫자 리터럴은 AST 로** 집고(문자열·주석·독스트링이 구조적으로 배제된다),
    식별자만 같은 물리 행에서 본다.
    """

    #: 좁게 시작했다가 넓혔다. `usd_krw|exchange_rate|fx_` 만 보면 **지금 있는 철자만**
    #: 잡고 `rate = fx or 1400` · `FALLBACK_RATE = 1400` · `rate = get_rate() or 1400`
    #: 은 전부 빠져나간다 — 백스톱이 현재 코드만 덮으면 백스톱이 아니다.
    #:
    #: ⚠️ 경계는 `\b` 가 아니라 **글자 경계**여야 한다. `_` 는 단어 문자라
    #: `\brate\b` 가 `FALLBACK_RATE` 를 못 잡고, 반대로 맨 `rate` 부분일치는
    #: `gene`**`rate`**`` · `sepa`**`rate`** 를 잡는다. `(?<![a-z])rate(?![a-z])` 가
    #: 양쪽을 동시에 만족한다.
    #:
    #: 넓힌 뒤에도 `nuri/` 실측은 **동일(7 hits / 3 files)** — 오탐 비용 0 이었다.
    IDENT = re.compile(r"usd_krw|usdkrw|krw|환율|(?<![a-z])fx(?![a-z])|(?<![a-z])rate(?![a-z])", re.I)

    @classmethod
    def _scan(cls, src: str) -> list[int]:
        """한 소스에서 '환율 크기 리터럴 + 같은 행의 FX 식별자' 행번호.

        카나리아와 실제 스윕이 **같은 함수**를 타야 한다. 로직을 복사해 두면 카나리아는
        복사본만 검증하고, 정작 스윕이 눈이 멀어도 초록으로 통과한다.
        """
        lines = src.splitlines()
        out: list[int] = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Constant):
                continue
            v = node.value
            # bool 은 int 의 서브클래스라 명시 제외.
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            # 환율 크기 — KRW/USD 는 네 자리다.
            if not (1000 <= v < 2000):
                continue
            if cls.IDENT.search(lines[node.lineno - 1]):
                out.append(node.lineno)
        return sorted(out)

    @classmethod
    def _fabrications(cls) -> dict[str, list[int]]:
        root = Path(__file__).resolve().parents[2] / "nuri"
        out: dict[str, list[int]] = {}
        for f in sorted(root.rglob("*.py")):
            found = cls._scan(f.read_text(encoding="utf-8"))
            if found:
                out[str(f.relative_to(root))] = found
        return out

    def test_no_unlisted_file_fabricates_a_rate(self):
        found = self._fabrications()
        unlisted = {k: v for k, v in found.items() if k not in FABRICATION_EXEMPT}
        assert not unlisted, f"환율을 지어내는 곳이 새로 생겼다: {unlisted}"

    def test_every_exemption_is_still_needed(self):
        """양방향 — #1284 가 랜딩하면 그 항목들이 여기서 FAIL 해 제거를 강제한다."""
        found = self._fabrications()
        stale = [k for k in FABRICATION_EXEMPT if k not in found]
        assert not stale, f"낡은 예외 항목(이미 정리됨): {stale}"

    def test_every_exemption_states_a_reason(self):
        for path, why in FABRICATION_EXEMPT.items():
            assert len(why) > 40, f"{path}: 사유가 너무 짧다 — 다음 사람이 판단할 수 없다"

    def test_the_fixed_sites_are_actually_clean(self):
        """이 PR 이 고친 4곳이 스윕에 안 잡히는지 — 수정이 실제로 먹었다는 증거."""
        found = self._fabrications()
        for path in (
            "analysis/portfolio.py",
            "alerts/premarket_brief.py",
            "trading/recommend/price_targets.py",
            "core/fx.py",
        ):
            assert path not in found, f"{path} 에 아직 지어낸 환율이 있다: {found[path]}"

    def test_the_sweep_has_eyes(self):
        """카나리아 — 스윕이 조용히 아무것도 안 잡으면 위 테스트는 영원히 초록이다.

        **양방향**이다: 옛 결함 형태를 잡는지 + 독스트링을 오탐하지 않는지. 후자가 없으면
        "전부 통과" 와 "전부 차단" 을 구분할 수 없다 (텍스트 스윕이 실제로 밟은 함정).
        """
        doc = '"""환율 누락 시 1400 기본값 — 설명일 뿐 코드가 아니다."""\n'
        assert self._scan(doc) == [], "독스트링을 코드로 오탐한다 — 텍스트 스윕의 실패를 반복한다"

        # 옛 결함의 **철자 변종**들. 좁은 IDENT 는 아래 3·4·5번을 전부 놓쳤다 —
        # 실제로 그래서 넓혔다. 변종을 함께 잠가야 "지금 코드만 덮는 백스톱" 으로
        # 되돌아가는 걸 막는다.
        for src in (
            "rate = exchange_rate or 1400\n",
            "usd_krw = x or 1400\n",
            "rate = fx or 1400\n",
            "FALLBACK_RATE = 1400\n",
            "rate = get_rate() or 1400\n",
        ):
            assert self._scan(src) == [1], f"이 형태를 못 잡는다 — 스윕에 눈이 없다: {src!r}"

        # 반대편 — 넓힌 경계가 무관한 단어를 잡으면 오탐이 쌓여 스윕이 무시당한다.
        # `rate` 를 부분일치로 두면 아래가 전부 걸린다.
        for src in (
            "count = generate(1400)\n",
            "x = separate_thing(1500)\n",
            "duration_ms = 1500\n",
            "iterations = 1200\n",
            "accurate_total = 1100\n",
        ):
            assert self._scan(src) == [], f"무관한 단어를 환율로 오탐한다: {src!r}"

    def test_the_magnitude_window_brackets_a_real_rate(self):
        """1000~2000 창이 실제 환율을 포함하는지 — 창이 빗나가면 스윕은 늘 0건이다.

        프로덕션 실측 1383.52 (2026-08-29), 옛 폴백 1400/1450 이 모두 안에 있다.
        """
        for v in (1383.52, 1400, 1450.0):
            assert self._scan(f"usd_krw = {v}\n") == [1], f"{v} 를 환율 크기로 안 본다"
        for v in (7.0, 999, 2000, 130_000):
            assert self._scan(f"usd_krw = {v}\n") == [], f"{v} 는 환율 크기가 아닌데 잡았다"
