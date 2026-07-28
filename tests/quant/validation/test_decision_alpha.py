"""decision_alpha 판정 도구 테스트 (#831, STRATEGY §3.11).

Gotcha-Test Pair:
- ticker-block placebo 의 핵심 계약 = "같은 ticker 의 반복 emit 은 null 에서도
  같은 치환 ticker 를 공유" (의존 구조 상속). 이 계약이 깨지면 (iid 화) null
  분산이 과소평가돼 anti-conservative p — §3.11 이 지정한 P1 결함의 재유입.
- 결측 정의 = "창이 닫혔는데 alpha 미기록" — lookahead 미도래분을 결측으로
  세면 측정 기간 내내 INVALID_MISSING 오탐.
"""

from datetime import date, timedelta

import pytest

from nuri.core.db import get_db, init_db
from nuri.quant.validation import decision_alpha as da

# ─── 합성 원장 픽스처 ───────────────────────────────────
# declared_date(2026-07-08) 이후 emit + 판정창 30d 가 닫히도록 과거 날짜 사용 불가
# (declared_date 는 사전 고정) → emit 은 2026-07-10~, as_of 를 미래로 주입해
# 창을 닫는다 (adjudicate/fetch_sample 의 as_of 파라미터 — wall-clock 무의존,
# time-bomb fixture 방지).

EMIT_1 = "2026-07-10"
EMIT_2 = "2026-07-13"
EMIT_3 = "2026-07-15"  # recommendations UNIQUE(date, ticker) — 반복 emit 은 날짜가 달라야 함
AS_OF = "2026-09-01"  # 모든 emit 의 30d 창 닫힘


def _business_dates(start: str, days: int) -> list[str]:
    """주말 제외 date 시퀀스 (합성 가격용)."""
    out, d = [], date.fromisoformat(start)
    while len(out) < days:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "adjudicate.db"
    init_db(path)
    return path


def _seed_prices(db_path, ticker: str, start: str, days: int, base: float, drift: float):
    """일정 drift 의 합성 close 시계열."""
    dates = _business_dates(start, days)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                (ticker, d, base * (1 + drift) ** i),
            )
        conn.commit()


def _seed_decision(db_path, rec_id: int, ticker: str, emit: str, action: str = "BUY", alpha=None, window: int = 30):
    """recommendations + agent_decisions (+ optional decision_outcomes) 1건."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (id, date, ticker, action, confidence) VALUES (?, ?, ?, ?, 80.0)",
            (rec_id, emit, ticker, action),
        )
        conn.execute(
            """INSERT INTO agent_decisions
               (decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status)
               VALUES (?, ?, ?, ?, 0.8, '{}', '{}', 'emitted')""",
            (f"rec_{rec_id}", ticker, emit, action),
        )
        if alpha is not None:
            conn.execute(
                """INSERT INTO decision_outcomes
                   (decision_id, observation_window, tracked_as_of_date, realized_return,
                    benchmark_return, alpha, hit_threshold, hypothesis_validation)
                   VALUES (?, ?, ?, ?, 0.0, ?, 0, 'pass')""",
                (f"rec_{rec_id}", window, AS_OF, alpha, alpha),
            )
        conn.commit()


@pytest.fixture
def seeded(db_path):
    """SPY + 치환 universe 3종 + 실표본 2 ticker 4 decision."""
    # 가격: 7/1 부터 60 영업일 — 30d 창 + on_or_after 여유
    _seed_prices(db_path, "SPY", "2026-07-01", 60, 100.0, 0.001)
    _seed_prices(db_path, "AAA", "2026-07-01", 60, 50.0, 0.002)
    _seed_prices(db_path, "BBB", "2026-07-01", 60, 80.0, 0.000)
    _seed_prices(db_path, "CCC", "2026-07-01", 60, 30.0, 0.003)
    _seed_prices(db_path, "TSLA", "2026-07-01", 60, 200.0, 0.004)
    _seed_prices(db_path, "NVDA", "2026-07-01", 60, 150.0, 0.002)
    # 실표본: TSLA 3회 반복 (블록), NVDA 1회
    _seed_decision(db_path, 1, "TSLA", EMIT_1, alpha=0.05)
    _seed_decision(db_path, 2, "TSLA", EMIT_2, alpha=0.08)
    _seed_decision(db_path, 3, "TSLA", EMIT_3, alpha=0.03)
    _seed_decision(db_path, 4, "NVDA", EMIT_1, alpha=-0.01)
    return db_path


# ═══════════════════════════════════════════════════════
# 표본 규약 (§3.11)
# ═══════════════════════════════════════════════════════


class TestFetchSample:
    def test_us_buy_only(self, seeded):
        # KR / SELL / 기간 밖은 표본 제외
        _seed_decision(seeded, 10, "005930.KS", EMIT_1, alpha=0.5)  # KR
        _seed_decision(seeded, 11, "AAA", EMIT_1, action="SELL", alpha=0.5)  # SELL
        _seed_decision(seeded, 12, "BBB", "2026-07-01", alpha=0.5)  # declared_date 이전
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        assert s.n == 4
        assert all(not d["ticker"].endswith(".KS") for d in s.decisions)

    def test_missing_only_when_window_closed(self, seeded):
        # 창 닫힘 + alpha 없음 → 결측 / 창 미도래 → 결측 아님 (lookahead)
        _seed_decision(seeded, 20, "AAA", EMIT_1, alpha=None)  # closed, missing
        _seed_decision(seeded, 21, "BBB", "2026-08-25", alpha=None)  # 창 미도래 (as_of 9/1)
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        assert s.n_missing_closed == 1
        assert round(s.missing_rate_pct, 1) == round(1 / 5 * 100, 1)


# ═══════════════════════════════════════════════════════
# 순열 — ticker-block placebo 계약
# ═══════════════════════════════════════════════════════


class TestTickerBlockPlacebo:
    def test_block_shares_single_substitute(self, seeded):
        """Gotcha lock: 한 블록(반복 ticker)의 모든 emit 이 같은 치환 ticker 를 쓴다.

        이 계약이 깨지면 null 이 iid 화 → 분산 과소평가 → anti-conservative p.
        (구현상 치환 추첨은 블록당 1회 — `ticker_block_placebo` 의 per-ticker
        rng.integers 1회 호출. 블록 구조는 `_blocks`/`_eligible_substitutes` 로 고정.)
        """
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        blocks = da._blocks(s.decisions)
        assert blocks["TSLA"] == [EMIT_1, EMIT_2, EMIT_3]

        book = da.PriceBook(db_path=seeded)
        eligible = da._eligible_substitutes(book, blocks, 30, "SPY", db_path=seeded)
        # 치환 후보에 원 ticker 제외 + pseudo/benchmark 제외
        assert "TSLA" not in eligible["TSLA"]
        assert "SPY" not in eligible["TSLA"]
        assert set(eligible["TSLA"]) <= {"AAA", "BBB", "CCC", "NVDA"}

    def test_deterministic_p_with_same_seed(self, seeded):
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        r1 = da.ticker_block_placebo(s, n_perm=50, seed=828, db_path=seeded)
        r2 = da.ticker_block_placebo(s, n_perm=50, seed=828, db_path=seeded)
        assert r1.p_value == r2.p_value
        assert r1.null_means == r2.null_means

    def test_one_sided_p_bounds(self, seeded):
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        r = da.ticker_block_placebo(s, n_perm=50, seed=1, db_path=seeded)
        assert 1 / 51 <= r.p_value <= 1.0
        assert r.observed_mean == pytest.approx((0.05 + 0.08 + 0.03 - 0.01) / 4)


# ═══════════════════════════════════════════════════════
# 반기 분할 + 통합 판정
# ═══════════════════════════════════════════════════════


class TestAdjudicate:
    def test_median_split_balanced(self, seeded):
        s = da.fetch_sample(db_path=seeded, as_of=AS_OF)
        halves = da.median_split_means(s)
        assert halves["h1_n"] == 2 and halves["h2_n"] == 2

    def test_progress_report_before_evaluation_date(self, seeded):
        # as_of 가 evaluation_date (2027-06-30) 이전 → 조기 승격 금지
        report = da.adjudicate(db_path=seeded, n_perm=20, as_of=AS_OF)
        assert report["pre_evaluation"] is True
        assert report["verdict"] == "PROGRESS_REPORT"
        assert report["criteria_verdict_if_final"] == "INSUFFICIENT_N"  # n=4 < 200
        assert report["permutation"]["scheme"] == "ticker_block_placebo"

    def test_invalid_when_missing_exceeds_cap(self, seeded):
        # 결측 6건 추가 → 6/10 = 60% > 15% cap → 판정 무효 우선
        miss_dates = _business_dates("2026-07-16", 6)
        for i, d in enumerate(miss_dates):
            _seed_decision(seeded, 30 + i, "AAA", d, alpha=None)
        report = da.adjudicate(db_path=seeded, n_perm=20, as_of=AS_OF)
        assert report["missing_rate_pct"] > report["missing_max_pct"]
        assert report["criteria_verdict_if_final"] == "INVALID_MISSING"

    def test_no_sample(self, db_path):
        report = da.adjudicate(db_path=db_path, n_perm=20, as_of=AS_OF)
        assert report["verdict"] == "NO_SAMPLE"

    def test_cli_smoke(self, seeded, capsys):
        rc = da.main(["--db", str(seeded), "--n-perm", "20"])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"verdict"' in out


# ═══════════════════════════════════════════════════════
# 열화 경로 — 설정 부재 / 가격 결측 / 치환 불가
# ═══════════════════════════════════════════════════════


class TestCriteriaSource:
    def test_missing_measurement_mode_raises_instead_of_defaulting(self):
        """판정 파라미터가 없으면 **멈춘다** — 기본값으로 조용히 판정하지 않는다.

        §3.11 의 요체는 기준이 사전 고정돼 있다는 것이다. 설정이 사라졌는데
        코드 기본값으로 리포트를 내면 그 리포트는 무엇을 기준으로 한 판정인지
        아무도 모른다. 여기서 raise 하는 게 유일하게 정직한 동작이다.
        """
        from unittest.mock import patch

        with patch.dict(da.RULES, {}, clear=True), pytest.raises(RuntimeError, match="measurement_mode"):
            da._criteria()


class TestPriceBookMisses:
    """가격 조회는 없을 때 None 을 돌려줘야 한다 — 예외도, 이웃 값도 아니다."""

    def test_exact_date_miss_returns_none(self, seeded):
        book = da.PriceBook(db_path=seeded)
        assert book.close("AAA", "2020-01-01") is None, "시계열 시작 전인데 값이 나왔다"
        assert book.close("AAA", "2099-01-01") is None, "시계열 끝 이후인데 값이 나왔다"

    def test_on_or_after_past_the_end_returns_none(self, seeded):
        """창 끝이 시계열 밖 — 미래 창은 '아직 모른다' 이지 0 이 아니다."""
        book = da.PriceBook(db_path=seeded)
        assert book.close_on_or_after("AAA", "2099-01-01") is None

    def test_unknown_ticker_is_empty_not_an_error(self, seeded):
        book = da.PriceBook(db_path=seeded)
        assert book.close("NOPRICE", EMIT_1) is None
        assert book.close_on_or_after("NOPRICE", EMIT_1) is None


class TestPlaceboAlphaGuards:
    def test_missing_price_yields_none(self, seeded):
        """가격이 없으면 placebo alpha 는 None — 이게 치환 후보 필터의 근거다."""
        book = da.PriceBook(db_path=seeded)
        assert da._placebo_alpha(book, "NOPRICE", EMIT_1, 30, "SPY") is None

    def test_zero_entry_price_yields_none(self, seeded):
        """entry=0 은 수익률 정의 불가 — ZeroDivisionError 대신 None."""
        with get_db(seeded) as conn:
            for d in _business_dates(EMIT_1, 40):
                conn.execute("INSERT OR REPLACE INTO prices (ticker, date, close) VALUES ('ZEROP', ?, 0.0)", (d,))
            conn.commit()
        book = da.PriceBook(db_path=seeded)
        assert da._placebo_alpha(book, "ZEROP", EMIT_1, 30, "SPY") is None


class TestSkippedBlocks:
    def test_block_without_substitutes_keeps_observed_alpha(self, db_path):
        """라인 250-257: 치환 후보가 없는 블록은 null 에서도 실측 alpha 를 그대로 쓴다.

        치환할 종목이 없다고 그 블록을 표본에서 빼면 null 이 실측보다 유리해져
        p 가 anti-conservative 해진다. 실측을 그대로 넣으면 null 이 실측 쪽으로
        끌려가 p 가 **보수적** 으로 나온다 — 틀리더라도 엣지를 과대평가하지 않는
        방향으로 틀린다. 그리고 그 사실은 `skipped_blocks` 로 공시된다.

        Gotcha-Test Pair: `continue` 대신 블록을 건너뛰면 count 가 0 이 되어
        ZeroDivisionError, 실측 유지를 빼면 p 가 1.0 미만이 되어 FAIL.
        """
        _seed_prices(db_path, "SPY", "2026-07-01", 60, 100.0, 0.001)
        _seed_prices(db_path, "ONLY", "2026-07-01", 60, 50.0, 0.002)
        _seed_decision(db_path, 1, "ONLY", EMIT_1, alpha=0.05)
        _seed_decision(db_path, 2, "ONLY", EMIT_2, alpha=0.07)

        s = da.fetch_sample(db_path=db_path, as_of=AS_OF)
        r = da.ticker_block_placebo(s, n_perm=20, seed=828, db_path=db_path)

        assert r.skipped_blocks == ["ONLY"], "치환 불가 사실이 공시되지 않음"
        assert r.null_means == [pytest.approx(r.observed_mean)] * 20
        assert r.p_value == 1.0, "치환 불가 블록이 p 를 보수적으로 만들지 않았다"


class TestVerdictBranches:
    """라인 352-359: 판정 우선순위 — 결측 무효 > 표본 미달 > 3조건.

    n≥200 은 판정일(2027-06-30)에나 도달할 표본이라, 이 두 분기는 그때까지 한
    번도 실행되지 않는다. 판정 당일에 처음 돌아가는 코드를 남겨두지 않기 위해
    `min_n_us_buy_decisions` 만 낮춰 분기 자체를 미리 실행한다 — 낮추는 건 이
    테스트 안에서만이고, 실제 사전등록값은 `tests/core/test_rules.py` 의
    `test_adjudication_params_locked` 가 그대로 잠근다.
    """

    def _adjudicate_with_small_n(self, db_path, **kw):
        from unittest.mock import patch

        with patch.dict(da.RULES["measurement_mode"], {"min_n_us_buy_decisions": 2}):
            return da.adjudicate(db_path=db_path, n_perm=20, as_of=AS_OF, **kw)

    def test_criteria_not_met_when_permutation_is_insignificant(self, seeded):
        """평균 alpha 는 양수이고 반기 분할도 통과하지만 p 가 못 미친다.

        가장 흔할 결과이며 §3.11 이 경고한 함정이다 — "평균이 +니까 엣지가 있다"
        는 결론을 순열이 막는다.
        """
        report = self._adjudicate_with_small_n(seeded)

        assert report["criteria_verdict_if_final"] == "CRITERIA_NOT_MET"
        assert report["conditions"]["mean_alpha_positive"] is True
        assert report["conditions"]["both_halves_positive"] is True
        assert report["conditions"]["permutation_significant"] is False
        assert report["verdict"] == "PROGRESS_REPORT", "판정일 전인데 최종 판정이 표출됐다"

    def test_criteria_met_requires_all_three(self, db_path):
        """3조건 동시 충족 → CRITERIA_MET. 승격 경로가 실제로 존재하는지 확인.

        실측 alpha 를 모든 placebo 보다 크게 두어 p = 1/(20+1) = 0.0476 < 0.05.
        이 분기가 죽어 있으면 판정일에 '통과인데 통과가 안 나오는' 상태가 된다.
        """
        _seed_prices(db_path, "SPY", "2026-07-01", 60, 100.0, 0.001)
        for t, base, drift in (("AAA", 50.0, 0.002), ("BBB", 80.0, 0.0), ("TSLA", 200.0, 0.004)):
            _seed_prices(db_path, t, "2026-07-01", 60, base, drift)
        for rec_id, emit in ((1, EMIT_1), (2, EMIT_2), (3, EMIT_3)):
            _seed_decision(db_path, rec_id, "TSLA", emit, alpha=0.5)
        _seed_decision(db_path, 4, "AAA", EMIT_1, alpha=0.5)

        report = self._adjudicate_with_small_n(db_path)

        assert report["criteria_verdict_if_final"] == "CRITERIA_MET"
        assert all(report["conditions"].values())
        assert report["p_value"] < report["p_max"]
        # 통과해도 판정일 전이면 표출은 진행 리포트 — 조기 승격 금지 (§3.11 원안 4번)
        assert report["verdict"] == "PROGRESS_REPORT"
