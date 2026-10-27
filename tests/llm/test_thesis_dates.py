"""확증 날짜 수 분석 (#1991)."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pytest
from scipy.stats import spearmanr

from nuri.core.db import get_db, init_db
from nuri.llm import thesis_dates as td


def scipy_ic(x, y) -> float:
    """기준값 — scipy 의 결과 객체는 타입 스텁이 튜플로만 알려 속성 접근을 못 한다."""
    r: Any = spearmanr(x, y)
    return float(r.statistic)


ARMS = ("B", "A")
TICKERS = [f"T{i}" for i in range(6)]


def run(day, arm, ticker, rating, alpha=0.01, status="ok", arm_hash=None):
    return {
        "cohort_date": day,
        "arm": arm,
        "arm_hash": arm_hash or f"h{arm}",
        "ticker": ticker,
        "cutoff": f"{day}C",
        "rating": rating,
        "ret_status": status,
        "alpha": alpha if status == "ok" else None,
    }


def day_rows(day, b, a, alphas):
    return [run(day, "B", t, rb, al) for t, rb, al in zip(TICKERS, b, alphas)] + [
        run(day, "A", t, ra, al) for t, ra, al in zip(TICKERS, a, alphas)
    ]


GOOD_B = ["Buy", "Overweight", "Hold", "Underweight", "Sell", "Hold"]
GOOD_A = ["Sell", "Hold", "Buy", "Hold", "Overweight", "Underweight"]
ALPHAS = [0.05, 0.02, 0.0, -0.01, -0.04, 0.01]


class TestInformationCoefficient:
    @pytest.mark.parametrize(
        ("x", "y"),
        [
            ([2, 1, 0, -1, -2, 0], [0.05, 0.02, 0.0, -0.01, -0.04, 0.01]),
            ([1, 1, 0, 0, -1, 2], [0.3, -0.1, 0.3, 0.2, -0.5, 0.0]),  # 동순위 양쪽
        ],
    )
    def test_matches_scipy_spearman(self, x, y):
        assert td.spearman(x, y) == pytest.approx(scipy_ic(x, y))

    def test_delta_is_first_arm_minus_second_on_one_day(self):
        _, d, counts = td.daily_delta(day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS), ARMS, min_tickers=5)
        b = [td.SCORE[r] for r in GOOD_B]
        a = [td.SCORE[r] for r in GOOD_A]
        assert d.tolist() == [pytest.approx(scipy_ic(b, ALPHAS) - scipy_ic(a, ALPHAS))]
        assert counts["defined_days"] == counts["days"] == 1


class TestUndefinedDays:
    @pytest.mark.parametrize(
        ("b", "alphas", "reason"),
        [
            (["Hold"] * 6, ALPHAS, "constant_rating"),
            (GOOD_B, [0.01] * 6, "constant_alpha"),
        ],
    )
    def test_constant_days_are_skipped_and_counted(self, b, alphas, reason):
        rows = day_rows("2026-11-02", b, GOOD_A, alphas) + day_rows("2026-11-03", GOOD_B, GOOD_A, ALPHAS)
        dates, d, counts = td.daily_delta(rows, ARMS, min_tickers=5)
        assert dates == ["2026-11-03"] and len(d) == 1
        assert counts["undefined_reasons"] == {reason: 1} and counts["days"] == 2

    def test_a_day_with_fewer_settled_tickers_than_k_is_skipped(self):
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        for r in rows:
            if r["ticker"] in ("T0", "T1"):
                r["ret_status"], r["alpha"] = "missing", None
        dates, _, counts = td.daily_delta(rows, ARMS, min_tickers=5)
        assert dates == [] and counts["undefined_reasons"] == {"few_tickers": 1}
        assert counts["paired_returns"] == {"missing": 2, "ok": 4}

    def test_each_reason_is_counted_even_on_one_day(self):
        """한 날에 이유가 둘 이상이면 각각 센다 — 정의되지 않은 날 수는 days − defined_days."""
        _, _, counts = td.daily_delta(day_rows("2026-11-02", ["Hold"] * 6, GOOD_A, [0.01] * 6), ARMS, min_tickers=5)
        assert counts["undefined_reasons"] == {"constant_alpha": 1, "constant_rating": 1}
        assert counts["days"] - counts["defined_days"] == 1

    def test_only_tickers_both_arms_ran_count(self):
        """한 팔만 실행한 종목은 그날의 IC 에 들어가지 않는다 — 들어가면 차이가 범위를 잰다."""
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS) + [run("2026-11-02", "B", "T9", "Buy", 0.9)]
        _, d, counts = td.daily_delta(rows, ARMS, min_tickers=5)
        _, base, _ = td.daily_delta(day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS), ARMS, min_tickers=5)
        assert d.tolist() == base.tolist() and counts["paired_returns"] == {"ok": 6}

    def test_unsettled_rows_are_counted_as_pending(self):
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        for r in rows:
            r["ret_status"], r["alpha"] = None, None
        _, _, counts = td.daily_delta(rows, ARMS, min_tickers=5)
        assert counts["paired_returns"] == {"pending": 6}


class TestReview:
    def test_review_maps_to_neutral_and_is_counted(self):
        review_b = ["REVIEW" if r == "Hold" else r for r in GOOD_B]
        _, d_review, counts = td.daily_delta(day_rows("2026-11-02", review_b, GOOD_A, ALPHAS), ARMS, min_tickers=5)
        _, d_hold, _ = td.daily_delta(day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS), ARMS, min_tickers=5)
        assert d_review.tolist() == d_hold.tolist()
        assert counts["review_runs"] == {"B": 2, "A": 0}


class TestFailClosed:
    def test_two_definitions_of_one_arm_are_refused(self):
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        rows[0]["arm_hash"] = "other"
        with pytest.raises(ValueError, match="arm B has 2 definitions"):
            td.daily_delta(rows, ARMS, min_tickers=5)

    def test_an_arm_with_no_runs_is_refused(self):
        rows = [r for r in day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS) if r["arm"] == "B"]
        with pytest.raises(ValueError, match="arm A has 0 definitions"):
            td.daily_delta(rows, ARMS, min_tickers=5)

    def test_a_duplicate_run_is_refused(self):
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        with pytest.raises(ValueError, match="more than one run"):
            td.daily_delta([*rows, dict(rows[0])], ARMS, min_tickers=5)

    def test_arms_settled_on_different_cutoffs_are_refused(self):
        """정산은 (종목, cutoff) 단위 — 다른 창의 수익을 한 IC 에 섞지 않는다 (Codex 리뷰)."""
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        rows[-1]["cutoff"] = "other"
        with pytest.raises(ValueError, match="different cutoffs"):
            td.daily_delta(rows, ARMS, min_tickers=5)

    def test_a_non_finite_alpha_is_refused(self):
        """무한대 alpha 도 순위는 매겨져 정상 날이 된다 — 손상된 정산은 거부한다 (Codex 리뷰)."""
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        for r in rows:
            if r["ticker"] == "T0":
                r["alpha"] = math.inf
        with pytest.raises(ValueError, match="not finite"):
            td.daily_delta(rows, ARMS, min_tickers=5)

    def test_an_unknown_rating_is_refused(self):
        rows = day_rows("2026-11-02", GOOD_B, GOOD_A, ALPHAS)
        rows[0]["rating"] = "Strong Buy"
        with pytest.raises(ValueError, match="unknown rating"):
            td.daily_delta(rows, ARMS, min_tickers=5)


def series(phi, n=300, seed=1):
    """AR(1) — 같은 표본 표준편차 0.1 로 맞춘다(다른 것은 의존뿐)."""
    e = np.random.default_rng(seed).standard_normal(n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return (x - x.mean()) / x.std(ddof=1) * 0.1


def overlapping(n, seed):
    """보유 5세션이 겹친 일별 값 — 5개 충격의 이동합, 이론 σ_LR = 5 × 0.02 = 0.1."""
    e = np.random.default_rng(seed).standard_normal(n + 4) * 0.02
    return np.convolve(e, np.ones(5), "valid")


def finite_truth(n, reps=4000):
    """그 길이에서 평균의 실제 표준편차 × √n."""
    return float(np.std([overlapping(n, s).mean() * np.sqrt(n) for s in range(reps)]))


KW = {"targets": [0.02, 0.05], "alpha": 0.05, "power": 0.8, "holding": 5, "n_boot": 300, "n_outer": 50}


class TestRequiredDates:
    def test_autocorrelated_input_needs_more_dates_than_iid_of_the_same_variance(self):
        ar = td.required_dates(series(0.9), seed=0, **KW)
        iid = td.required_dates(series(0.0), seed=0, **KW)
        assert ar["required"]["0.05"]["dates"] > iid["required"]["0.05"]["dates"]
        assert ar["sigma_bootstrap"] > 3 * iid["sigma_bootstrap"]

    def test_iid_input_is_planned_from_the_overlap_model(self):
        """의존이 없는 자료에도 겹침 모델 √(H·γ₀) 가 정한다 — 날짜를 더 잡는 쪽(교과서 공식 ≈ 31 의 H 배)."""
        out = td.required_dates(series(0.0, n=2000), seed=0, **KW)
        assert 0.085 < out["sigma_bootstrap"] < 0.115
        assert out["sigma_overlap_model"] == pytest.approx(np.sqrt(5) * 0.1)
        assert out["sigma_source"] == "overlap_model" and out["sigma_lr"] == out["sigma_overlap_model"]
        assert out["required"]["0.05"]["dates"] == math.ceil((2.8016 * np.sqrt(5) * 0.1 / 0.05) ** 2)

    def test_a_pilot_length_series_is_not_planned_low(self):
        """20일 겹친 보유: 블록 부트스트랩만으로는 참값의 약 2/3 — 계획 값은 0.85 배 아래로 떨어지지 않는다."""
        truth = finite_truth(20)
        sigmas = [td.planning_sd(overlapping(20, s), 5, 300, np.random.default_rng(s))["sigma"] for s in range(150)]
        assert np.mean(sigmas) >= 0.85 * truth

    def test_a_long_series_is_not_planned_wildly_high(self):
        sigmas = [td.planning_sd(overlapping(300, s), 5, 300, np.random.default_rng(s))["sigma"] for s in range(30)]
        assert np.mean(sigmas) <= 1.2 * finite_truth(300, reps=1000)

    def test_longer_blocks_are_tried(self):
        out = td.required_dates(series(0.9, n=60), seed=0, **KW)
        assert list(out["sigma_bootstrap_by_block"]) == [str(b) for b in range(5, 21)]
        assert out["sigma_bootstrap"] == max(out["sigma_bootstrap_by_block"].values())

    def test_the_bootstrap_is_deterministic_under_a_seed(self):
        x = series(0.9, n=40)
        assert td.required_dates(x, seed=7, **KW) == td.required_dates(x, seed=7, **KW)
        assert (
            td.required_dates(x, seed=7, **KW)["sigma_lr_range"] != td.required_dates(x, seed=8, **KW)["sigma_lr_range"]
        )

    def test_the_answer_is_an_uncalibrated_range(self):
        out = td.required_dates(series(0.9, n=40), seed=0, **KW)
        lo, hi = out["required"]["0.05"]["range"]
        assert lo <= out["required"]["0.05"]["dates"] <= hi and lo < hi
        assert out["range_calibrated"] is False
        assert "20 sessions" in out["assumption"]

    def test_a_sparse_pilot_reports_degenerate_replicates_not_zero_dates(self):
        """한 날만 다른 표본 — 바깥 재표본이 모두 0 이 될 수 있다. 0 일 대신 1 일 하한과 그 수를 낸다 (Codex 리뷰)."""
        x = np.r_[np.zeros(19), 0.1]
        out = td.required_dates(x, seed=0, **{**KW, "targets": [0.005, 1.0], "alpha": 0.2, "power": 0.5})
        assert out["degenerate_outer_replicates"] > 0
        assert all(v >= 1 for r in out["required"].values() for v in (r["dates"], *r["range"]))

    def test_block_indices_are_contiguous_runs(self):
        idx = td.block_indices(12, 5, 3, np.random.default_rng(0))
        assert idx.shape == (3, 12)
        for row in idx:
            for start in (0, 5, 10):
                seg = row[start : start + 5]
                assert np.all(np.diff(seg) == 1)

    @pytest.mark.parametrize(
        ("x", "over", "match"),
        [
            (series(0.0, n=40), {"holding": 0}, "at least 1"),
            (series(0.0, n=9), {}, "at least 10 are needed"),
            (series(0.0, n=40), {"targets": [0.0]}, "finite and positive"),
            (series(0.0, n=40), {"targets": [math.inf]}, "finite and positive"),
            (series(0.0, n=40), {"targets": []}, "finite and positive"),
            (series(0.0, n=40), {"n_outer": 1}, "replicates"),
            (series(0.0, n=40), {"n_boot": 10}, "replicates"),
            (series(0.0, n=40), {"power": 0.4}, "power"),
            (series(0.0, n=40), {"alpha": 1.0}, "alpha"),
            (np.full(40, 0.1), {}, "no variance"),
            (np.r_[series(0.0, n=39), np.nan], {}, "no variance"),
            (np.tile([-0.1, 0.1], (40, 1)), {}, "one series"),
            (np.tile([1e-200, -1e-200], 20), {}, "no variance"),  # 분산이 언더플로
            (np.tile([1.0, np.nextafter(1.0, 2.0)], 20), {}, "no variance"),  # 부동소수 오차만큼의 차이
        ],
    )
    def test_degenerate_inputs_are_refused_not_answered(self, x, over, match):
        with pytest.raises(ValueError, match=match):
            td.required_dates(x, seed=0, **{**KW, **over})


# ── 원장 ──

DAYS = [f"2026-11-{d:02d}" for d in range(2, 14)]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


def seed(db, experiment, *, days=DAYS, batch_status="ok", late=0, scored=1, ret_status="ok"):
    rng = np.random.default_rng(len(experiment))
    ratings = list(td.SCORE)[:5]
    with get_db(db) as conn:
        bid = f"{experiment}-b"
        conn.execute(
            "INSERT OR IGNORE INTO thesis_batches VALUES (?, ?, 's', 'c', 'e', 'c', ?)", (bid, experiment, batch_status)
        )
        for day in days:
            for t in TICKERS:
                cutoff = f"{day}T{experiment}"
                conn.execute(
                    "INSERT INTO thesis_returns VALUES (?, ?, ?, 'e', 'x', 'c', 0.1, 'SPY', 0.0, ?, '{}', 'f')",
                    (t, cutoff, ret_status, float(rng.normal())),
                )
                for arm in ARMS:
                    conn.execute(
                        "INSERT INTO thesis_runs (experiment, batch_id, cohort_date, arm, arm_hash, ticker, cutoff, "
                        "late, scored, run_hash, packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, "
                        "budget_tokens, rating, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'r', '[]', 'v', '[]', "
                        "'[]', '{}', 14000, ?, 'verdict')",
                        (experiment, bid, day, arm, f"h{arm}", t, cutoff, late, scored, str(rng.choice(ratings))),
                    )


class TestLedger:
    def test_a_confirmatory_tag_never_sees_pilot_rows(self, db):
        seed(db, "pilot-1")
        seed(db, "confirm-1", days=DAYS[:3])
        rows = td.ledger_rows(experiment="confirm-1", arms=ARMS, db_path=db)
        assert len(rows) == 3 * len(TICKERS) * 2
        assert {r["cohort_date"] for r in rows} == set(DAYS[:3])
        assert td.ledger_rows(experiment="confirm-2", arms=ARMS, db_path=db) == []

    @pytest.mark.parametrize("over", [{"batch_status": "canary_changed"}, {"late": 1}, {"scored": 0}])
    def test_unverified_late_or_unscored_runs_are_left_out(self, db, over):
        seed(db, "pilot-1", **over)
        assert td.ledger_rows(experiment="pilot-1", arms=ARMS, db_path=db) == []

    def test_other_arms_are_left_out(self, db):
        seed(db, "pilot-1")
        assert {r["arm"] for r in td.ledger_rows(experiment="pilot-1", arms=("B", "S"), db_path=db)} == {"B"}

    def test_the_cli_prints_aggregates_only(self, db, capsys):
        seed(db, "pilot-1")
        rc = td.main(["--experiment", "pilot-1", "--db", str(db), "--boot", "200", "--outer", "50"])
        out = capsys.readouterr().out
        assert rc == 0
        report = json.loads(out)
        assert report["days"] == len(DAYS) and report["params"]["seed"] == 0
        assert set(report["required"]) == {"0.02", "0.05", "0.1"}
        assert all(r["calendar_dates"] >= r["dates"] for r in report["required"].values())
        assert not any(t in out for t in TICKERS), "종목이 출력에 나왔다"
        assert "mean" not in out, "관측된 효과를 내면 목표를 거기 맞춰 고르게 된다"

    def test_calendar_dates_scale_by_the_defined_day_rate(self, db):
        """정의되지 않는 날만큼 달력 날짜를 더 잡는다 — 아니면 E 가 확증 날짜를 덜 잡는다."""
        seed(db, "pilot-1")
        seed(db, "pilot-1", days=["2026-11-20", "2026-11-23", "2026-11-24"], ret_status="missing")
        out = td.analyze(experiment="pilot-1", arms=ARMS, db_path=db, min_tickers=5, seed=0, **{**KW, "n_boot": 200})
        assert out["days"] == 15 and out["undefined_reasons"].get("few_tickers") == 3
        for r in out["required"].values():
            assert r["calendar_dates"] == math.ceil(r["dates"] * 15 / out["defined_days"])
            assert r["calendar_range"] == [math.ceil(v * 15 / out["defined_days"]) for v in r["range"]]

    def test_the_cli_refuses_with_a_reason(self, db, capsys):
        seed(db, "pilot-1", days=DAYS[:3])
        assert td.main(["--experiment", "pilot-1", "--db", str(db)]) == 2
        assert "refused:" in capsys.readouterr().err

    def test_the_cli_needs_two_different_arms(self, db):
        with pytest.raises(SystemExit):
            td.main(["--experiment", "x", "--arms", "B,B", "--db", str(db)])
