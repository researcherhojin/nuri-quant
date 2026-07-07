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
