"""ForwardOutcomeTracker tests (#529 Phase 2 closed-loop — actor #11, canonical).

검증 (Codex Round 5 Layer B closed-loop):
- Layer B (deterministic, ZERO LLM)
- 3 actions: scan / track_one / last_outcome
- Closed-loop: emit → measure → auto-validate/reject HypothesisRegistry
- Anti-pattern lock-tests:
    1. lookahead bias — as_of + window > today → insufficient (false validation 차단)
    2. price 데이터 missing → insufficient_data
    3. 이미 validated/rejected/expired hypothesis → silently skip (status machine 보존)
    4. HOLD action → tracking skip
    5. invalid window (5/21/60 등) → BLOCK
- Discord publish: pass/reject auto-trigger 시 ROLLOUT (mock)
- Closed-loop integration: DecisionCompiler emit → 시간 경과 → Tracker → Hypothesis auto-validated
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.forward_outcome_tracker import (
    SUPPORTED_WINDOWS,
    WINDOW_THRESHOLDS,
    ForwardOutcomeTracker,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import (
    init_db,
    log_decision,
    log_decision_outcome,
    query,
    register_hypothesis,
)

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "fot.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.forward_outcome_tracker.log_decision_outcome",
            side_effect=make_redirect(db_module.log_decision_outcome),
        ),
        patch(
            "nuri.agents.actors.forward_outcome_tracker.query",
            side_effect=make_redirect(db_module.query),
        ),
        patch(
            "nuri.agents.actors.forward_outcome_tracker.validate_hypothesis",
            side_effect=make_redirect(db_module.validate_hypothesis),
        ),
        patch(
            "nuri.agents.actors.forward_outcome_tracker.reject_hypothesis",
            side_effect=make_redirect(db_module.reject_hypothesis),
        ),
        patch(
            "nuri.agents.actors.forward_outcome_tracker.log_decision",
            side_effect=make_redirect(db_module.log_decision),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


def _seed_decision(
    db_path,
    *,
    decision_id: str,
    ticker: str,
    as_of_date: str = "2026-04-20",
    action: str = "BUY",
    hypothesis_id: str | None = "h1",
):
    """agent_decisions row 시드 (FK + valid input)."""
    inputs = {
        "regime_run_id": "r1",
        "hypothesis_id": hypothesis_id or "h1",
        "causal_audit_id": "c1",
    }
    log_decision(
        decision_id=decision_id,
        ticker=ticker,
        as_of_date=as_of_date,
        action=action,
        conviction=0.85,
        inputs=inputs,
        rationale={},
        status="emitted",
        db_path=db_path,
    )


def _seed_hypothesis(db_path, hypothesis_id: str, claim: str):
    """open hypothesis 시드 — claim 다르면 새 row."""
    register_hypothesis(
        hypothesis_id=hypothesis_id,
        name=hypothesis_id,
        version="1.0.0",
        producer_actor="regime-posterior",
        claim_text=claim,
        evidence={},
        expiry_date="2026-12-31",
        db_path=db_path,
    )


def _seed_prices(db_path, rows: list[tuple[str, str, float]]):
    """[(ticker, date, close), ...] 직접 INSERT."""
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        for t, d, c in rows:
            conn.execute(
                "INSERT OR IGNORE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                (t, d, c),
            )


# ═══════════════════════════════════════════════════════
# Layer B invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert ForwardOutcomeTracker.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(ForwardOutcomeTracker, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("forward-outcome-tracker") is ForwardOutcomeTracker


# ═══════════════════════════════════════════════════════
# recommendations -> agent_decisions backfill (keystone: alpha 측정 켜기)
# ═══════════════════════════════════════════════════════


def _seed_recommendation(db_path, *, ticker, action="BUY", date="2026-04-20", confidence=80.0):
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, entry_price) VALUES (?, ?, ?, ?, ?)",
            (date, ticker, action, confidence, 100.0),
        )
        return conn.execute("SELECT id FROM recommendations WHERE ticker = ? AND date = ?", (ticker, date)).fetchone()[
            0
        ]


class TestRecommendationBackfill:
    """Root-cause 가드: decision_outcomes 가 영구 0행이던 이유 = tracker 가 빈
    agent_decisions 를 읽음. 실제 추천(recommendations)을 ledger 로 백필해 측정.
    이 클래스가 깨지면 alpha 측정 파이프라인이 다시 죽은 것."""

    def test_scan_backfills_and_measures_recommendation_alpha(self, patched_db):
        rec_id = _seed_recommendation(patched_db, ticker="TESTBB", action="BUY")
        _seed_prices(
            patched_db,
            [
                ("TESTBB", "2026-04-20", 100.0),
                ("TESTBB", "2026-04-27", 110.0),  # +10%
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 510.0),  # +2%
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        assert result.outcome == Outcome.PASS
        assert result.output["synced_from_recommendations"] >= 1

        # canonical ledger 에 백필됨 (FK 충족)
        ad = query(f"SELECT * FROM agent_decisions WHERE decision_id = 'rec_{rec_id}'", db_path=patched_db)
        assert len(ad) == 1 and ad[0]["status"] == "emitted"

        # decision_outcomes 에 benchmark-relative alpha row 생성
        out = query(
            f"SELECT * FROM decision_outcomes WHERE decision_id = 'rec_{rec_id}' AND observation_window = 7",
            db_path=patched_db,
        )
        assert len(out) == 1
        assert out[0]["realized_return"] == pytest.approx(0.10, abs=1e-6)
        assert out[0]["benchmark_return"] == pytest.approx(0.02, abs=1e-6)
        assert out[0]["alpha"] == pytest.approx(0.08, abs=1e-6)  # 10% - 2%

    def test_sell_recommendation_alpha_sign_flips(self, patched_db):
        """SELL 추천: 종목이 오르면 realized/alpha 는 음수 (short proxy)."""
        rec_id = _seed_recommendation(patched_db, ticker="TESTSS", action="SELL")
        _seed_prices(
            patched_db,
            [
                ("TESTSS", "2026-04-20", 100.0),
                ("TESTSS", "2026-04-27", 110.0),  # 종목 +10% → SELL 관점 -10%
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 510.0),  # +2% → SELL 관점 -2%
            ],
        )
        ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        out = query(
            f"SELECT * FROM decision_outcomes WHERE decision_id = 'rec_{rec_id}' AND observation_window = 7",
            db_path=patched_db,
        )
        assert len(out) == 1
        assert out[0]["realized_return"] == pytest.approx(-0.10, abs=1e-6)
        assert out[0]["alpha"] == pytest.approx(-0.08, abs=1e-6)

    def test_scan_backfill_is_idempotent(self, patched_db):
        """scan 2회 → agent_decisions rec row 중복 없음."""
        _seed_recommendation(patched_db, ticker="TESTCC", action="BUY")
        _seed_prices(
            patched_db,
            [
                ("TESTCC", "2026-04-20", 100.0),
                ("TESTCC", "2026-04-27", 105.0),
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 505.0),
            ],
        )
        ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        cnt = query("SELECT COUNT(*) AS c FROM agent_decisions WHERE ticker = 'TESTCC'", db_path=patched_db)
        assert cnt[0]["c"] == 1


# ═══════════════════════════════════════════════════════
# Action: track_one — happy paths
# ═══════════════════════════════════════════════════════


class TestPerMarketBenchmark:
    """KR 결정은 KOSPI, US 결정은 SPY 로 잰다 (#833).

    KR 종목을 SPY 로 재면 alpha 에 환율과 시장 스타일 차이가 통째로 섞여 부호까지
    뒤집힌다. 아래 첫 테스트가 그 상황을 그대로 만든다 — 두 벤치마크가 반대로
    움직여서, 잘못된 쪽을 쓰면 alpha 가 +0.02 가 아니라 +0.13 이 된다.
    """

    def _outcome_row(self, db_path, decision_id):
        rows = query(
            "SELECT alpha, benchmark_return, benchmark_ticker FROM decision_outcomes WHERE decision_id=?",
            (decision_id,),
            db_path=db_path,
        )
        return dict(rows[0])

    def test_kr_decision_is_measured_against_kospi(self, patched_db):
        """Gotcha-Test Pair: `benchmark_for(ticker)` 를 상수로 되돌리면 alpha 가
        0.13 이 되어 FAIL."""
        _seed_decision(patched_db, decision_id="dc-kr", ticker="TESTKR.KS", hypothesis_id=None)
        _seed_prices(
            patched_db,
            [
                ("TESTKR.KS", "2026-04-20", 100.0),
                ("TESTKR.KS", "2026-04-27", 108.0),  # +8%
                ("KOSPI", "2026-04-20", 2500.0),
                ("KOSPI", "2026-04-27", 2650.0),  # +6%
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 475.0),  # -5% — 반대 방향
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-kr", "observation_window": 7})

        assert result.output["alpha"] == pytest.approx(0.02, abs=1e-6), "KR alpha 가 SPY 기준으로 계산됨"
        row = self._outcome_row(patched_db, "dc-kr")
        assert row["benchmark_ticker"] == "KOSPI"
        assert row["benchmark_return"] == pytest.approx(0.06, abs=1e-6)

    def test_us_decision_still_uses_spy(self, patched_db):
        """회귀 방지 — US 경로는 §3.11 사전등록 기준 그대로여야 한다."""
        _seed_decision(patched_db, decision_id="dc-us", ticker="TESTAA", hypothesis_id=None)
        _seed_prices(
            patched_db,
            [
                ("TESTAA", "2026-04-20", 100.0),
                ("TESTAA", "2026-04-27", 108.0),
                ("KOSPI", "2026-04-20", 2500.0),
                ("KOSPI", "2026-04-27", 2650.0),
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 505.0),  # +1%
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-us", "observation_window": 7})

        assert result.output["alpha"] == pytest.approx(0.07, abs=1e-6)
        assert self._outcome_row(patched_db, "dc-us")["benchmark_ticker"] == "SPY"

    def test_kosdaq_routes_to_the_kr_benchmark(self):
        """`.KQ` 도 KR — `.KS` 만 보면 KOSDAQ 종목이 US 벤치마크로 새어나간다 (#764)."""
        from nuri.agents.actors.forward_outcome_tracker import benchmark_for

        assert benchmark_for("TESTKR.KQ") == benchmark_for("TESTKR.KS") == "KOSPI"
        assert benchmark_for("TESTAA") == "SPY"

    def test_unmapped_market_falls_back_to_the_us_benchmark(self):
        """map 이 비어도 죽지 않고 US 기준으로 폴백한다 — 단 그 사실이 행에 남는다."""
        from nuri.agents.actors import forward_outcome_tracker as fot

        with patch.dict(fot.RULES["measurement_mode"], {"benchmark_by_market": {}}):
            assert fot.benchmark_for("TESTKR.KS") == fot.DEFAULT_BENCHMARK_TICKER


class TestTrackOnePass:
    def test_pass_validation_8pct_return(self, patched_db):
        """7d window, +8% realized → pass + hypothesis auto-validated."""
        _seed_hypothesis(patched_db, "h-pass", "claim-pass")
        _seed_decision(patched_db, decision_id="dc-pass", ticker="TESTAA", hypothesis_id="h-pass")
        _seed_prices(
            patched_db,
            [
                ("TESTAA", "2026-04-20", 100.0),
                ("TESTAA", "2026-04-27", 108.0),
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 505.0),
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-pass", "observation_window": 7})
        assert result.outcome == Outcome.PASS
        assert result.output["validation"] == "pass"
        assert result.output["realized_return"] == pytest.approx(0.08)
        assert result.output["alpha"] == pytest.approx(0.08 - 0.01)

        # hypothesis 자동 validated
        rows = query(
            "SELECT status, validation_metrics_json FROM hypotheses WHERE hypothesis_id=?",
            ("h-pass",),
            db_path=patched_db,
        )
        assert dict(rows[0])["status"] == "validated"

    def test_reject_validation_negative_return(self, patched_db):
        """7d window, -8% realized → reject + hypothesis auto-rejected."""
        _seed_hypothesis(patched_db, "h-rej", "claim-rej")
        _seed_decision(patched_db, decision_id="dc-rej", ticker="TESTBB", hypothesis_id="h-rej")
        _seed_prices(
            patched_db,
            [
                ("TESTBB", "2026-04-20", 100.0),
                ("TESTBB", "2026-04-27", 92.0),
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 505.0),
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-rej", "observation_window": 7})
        assert result.outcome == Outcome.PASS  # measurement 자체는 성공
        assert result.output["validation"] == "reject"
        assert result.output["realized_return"] == pytest.approx(-0.08)

        rows = query(
            "SELECT status, rejection_reason FROM hypotheses WHERE hypothesis_id=?",
            ("h-rej",),
            db_path=patched_db,
        )
        r = dict(rows[0])
        assert r["status"] == "rejected"
        assert "forward outcome reject" in r["rejection_reason"]

    def test_sell_action_inverts_return(self, patched_db):
        """SELL action: 가격 하락 → positive return (short proxy)."""
        _seed_hypothesis(patched_db, "h-sell", "claim-sell")
        _seed_decision(patched_db, decision_id="dc-sell", ticker="TESTCC", action="SELL", hypothesis_id="h-sell")
        _seed_prices(
            patched_db,
            [
                ("TESTCC", "2026-04-20", 100.0),
                ("TESTCC", "2026-04-27", 92.0),
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-sell", "observation_window": 7})
        # SELL + 가격 -8% → realized = +0.08 → pass
        assert result.output["validation"] == "pass"
        assert result.output["realized_return"] == pytest.approx(0.08)


class TestWeekendEntryLockTest:
    """LOCK-TEST: 주말/휴장 as_of_date 진입은 직전 거래일 close 로 흡수 (on_or_before).

    시스템이 매일(주말 포함) 스캔하며 BUY 를 재발행하므로 as_of 가 토/일인 결정이
    다수 생긴다. entry 를 exact-date 로 조회하면 그날 시세가 없어 insufficient_data →
    prod 원장에서 성숙 US BUY 결정의 34% 결측(전부 주말) 발생 → §3.11 결측 게이트(15%)
    초과로 판정 무효 위험. Regression: entry 가 exact-date 로 되돌아가면 이 테스트 FAIL.
    """

    def test_weekend_entry_uses_prior_trading_close(self, patched_db):
        _seed_hypothesis(patched_db, "h-wk", "claim-wk")
        # as_of = 2026-05-09(토). 당일 시세 없음(주말) — 직전 금(05-08)만 seed.
        _seed_decision(patched_db, decision_id="dc-wk", ticker="TESTWK", as_of_date="2026-05-09", hypothesis_id="h-wk")
        _seed_prices(
            patched_db,
            [
                ("TESTWK", "2026-05-08", 100.0),  # 금 — entry on_or_before 흡수
                ("TESTWK", "2026-05-18", 108.0),  # 월 — target(05-16) 이후 첫 거래일, exit on_or_after
                ("SPY", "2026-05-08", 500.0),
                ("SPY", "2026-05-18", 505.0),
            ],
        )
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-wk", "observation_window": 7})
        # insufficient 아님 — entry=100(금 close), exit=108 → +8%
        assert result.output["validation"] == "pass"
        assert result.output["realized_return"] == pytest.approx(0.08)
        out = query(
            "SELECT realized_return, benchmark_return FROM decision_outcomes "
            "WHERE decision_id='dc-wk' AND observation_window=7",
            db_path=patched_db,
        )
        assert out[0]["realized_return"] is not None
        assert out[0]["benchmark_return"] is not None


# ═══════════════════════════════════════════════════════
# Anti-pattern lock-tests
# ═══════════════════════════════════════════════════════


class TestLookaheadBiasLockTest:
    """LOCK-TEST: as_of_date + window > today → insufficient (false validation 차단)."""

    def test_future_as_of_blocks_with_insufficient(self, patched_db):
        _seed_hypothesis(patched_db, "h-future", "claim-future")
        _seed_decision(
            patched_db,
            decision_id="dc-future",
            ticker="TESTFF",
            as_of_date="2027-01-01",
            hypothesis_id="h-future",
        )
        result = ForwardOutcomeTracker().run(
            {"action": "track_one", "decision_id": "dc-future", "observation_window": 7}
        )
        assert result.outcome == Outcome.WARN
        assert result.output["validation"] == "insufficient_data"
        assert "lookahead" in result.output["reason"].lower()

        # hypothesis status 변동 X
        rows = query(
            "SELECT status FROM hypotheses WHERE hypothesis_id=?",
            ("h-future",),
            db_path=patched_db,
        )
        assert dict(rows[0])["status"] == "open"

    def test_outcome_row_persisted_with_insufficient(self, patched_db):
        _seed_hypothesis(patched_db, "h-future2", "claim-future2")
        _seed_decision(
            patched_db,
            decision_id="dc-future2",
            ticker="TESTFG",
            as_of_date="2027-01-01",
            hypothesis_id="h-future2",
        )
        ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-future2", "observation_window": 7})
        rows = query(
            "SELECT hypothesis_validation, notes FROM decision_outcomes WHERE decision_id=?",
            ("dc-future2",),
            db_path=patched_db,
        )
        r = dict(rows[0])
        assert r["hypothesis_validation"] == "insufficient_data"
        assert "lookahead" in r["notes"].lower()


class TestMissingPriceDataLockTest:
    """LOCK-TEST: price 데이터 없음 → insufficient_data, hypothesis 상태 변동 X."""

    def test_no_entry_price_returns_insufficient(self, patched_db):
        _seed_hypothesis(patched_db, "h-noprice", "claim-np")
        _seed_decision(patched_db, decision_id="dc-np", ticker="MISSING", hypothesis_id="h-noprice")
        # no prices seeded
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-np", "observation_window": 7})
        assert result.output["validation"] == "insufficient_data"
        assert "price" in result.output["reason"].lower()

    def test_no_exit_price_returns_insufficient(self, patched_db):
        _seed_hypothesis(patched_db, "h-noexit", "claim-ne")
        _seed_decision(patched_db, decision_id="dc-ne", ticker="TESTNE", hypothesis_id="h-noexit")
        _seed_prices(patched_db, [("TESTNE", "2026-04-20", 100.0)])  # only entry
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-ne", "observation_window": 7})
        assert result.output["validation"] == "insufficient_data"


class TestStatusMachineLockTest:
    """LOCK-TEST: 이미 종결된 hypothesis 의 update 시도는 silently skip (status machine 보존)."""

    def test_validated_hypothesis_not_re_updated(self, patched_db):
        from nuri.core.db import validate_hypothesis

        _seed_hypothesis(patched_db, "h-already", "claim-already")
        validate_hypothesis("h-already", {"realized_brier": 0.1}, db_path=patched_db)
        # status: validated

        _seed_decision(patched_db, decision_id="dc-already", ticker="TESTAL", hypothesis_id="h-already")
        _seed_prices(
            patched_db,
            [
                ("TESTAL", "2026-04-20", 100.0),
                ("TESTAL", "2026-04-27", 92.0),  # would normally trigger reject
            ],
        )
        result = ForwardOutcomeTracker().run(
            {"action": "track_one", "decision_id": "dc-already", "observation_window": 7}
        )
        # outcome row 는 기록되지만 hypothesis status 그대로
        assert result.output["validation"] == "reject"
        rows = query(
            "SELECT status FROM hypotheses WHERE hypothesis_id=?",
            ("h-already",),
            db_path=patched_db,
        )
        assert dict(rows[0])["status"] == "validated"  # 변동 X

    def test_rejected_hypothesis_not_re_updated(self, patched_db):
        from nuri.core.db import reject_hypothesis

        _seed_hypothesis(patched_db, "h-rejected", "claim-rejected")
        reject_hypothesis("h-rejected", "manual reject", db_path=patched_db)

        _seed_decision(patched_db, decision_id="dc-rejected", ticker="TESTRJ", hypothesis_id="h-rejected")
        _seed_prices(
            patched_db,
            [("TESTRJ", "2026-04-20", 100.0), ("TESTRJ", "2026-04-27", 110.0)],
        )
        ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-rejected", "observation_window": 7})
        rows = query(
            "SELECT status FROM hypotheses WHERE hypothesis_id=?",
            ("h-rejected",),
            db_path=patched_db,
        )
        assert dict(rows[0])["status"] == "rejected"  # 변동 X

    def test_non_pass_reject_validation_is_noop(self, patched_db):
        """468->exit 방어 분기: validation ∉ {pass, reject} (예: insufficient_data) 면
        if/elif 둘 다 미매치 → fall-through, open hypothesis 미변경.

        공개 경로(_trigger_forward_validation L380 guard)는 pass/reject 만 이 메서드에
        넘기므로 도달 불가한 방어 분기 — staticmethod 직접 호출로 커버.
        Regression: 예상 밖 validation 값에 else 를 잘못 달면 open hypothesis 를 오변경.
        """
        _seed_hypothesis(patched_db, "h-insuf", "claim-insuf")
        ForwardOutcomeTracker._trigger_hypothesis_update("h-insuf", "insufficient_data", 7, 0.01, None, "run-insuf")
        rows = query(
            "SELECT status FROM hypotheses WHERE hypothesis_id=?",
            ("h-insuf",),
            db_path=patched_db,
        )
        assert dict(rows[0])["status"] == "open"  # pass/reject 아님 → 변동 없음


class TestHoldSkipLockTest:
    """LOCK-TEST: HOLD action → tracking skip (의미 없음)."""

    def test_hold_action_skipped(self, patched_db):
        _seed_hypothesis(patched_db, "h-hold", "claim-hold")
        _seed_decision(patched_db, decision_id="dc-hold", ticker="TESTHO", action="HOLD", hypothesis_id="h-hold")
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-hold", "observation_window": 7})
        assert result.outcome == Outcome.WARN
        assert "HOLD" in result.output.get("skipped", "")

    def test_hold_skipped_in_scan(self, patched_db):
        _seed_hypothesis(patched_db, "h-h2", "claim-h2")
        _seed_decision(patched_db, decision_id="dc-h2", ticker="TESTHX", action="HOLD", hypothesis_id="h-h2")
        result = ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        # scan 은 status='emitted' AND action IN ('BUY','SELL') 만 포함
        # HOLD 는 emitted 라도 query 단계 제외
        assert result.output["scanned"] == 0


# ═══════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════


class TestInputValidation:
    def test_invalid_action_blocked(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_track_one_missing_decision_id_blocked(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "track_one"})
        assert result.outcome == Outcome.BLOCK

    def test_track_one_unknown_decision_blocked(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "nonexistent"})
        assert result.outcome == Outcome.BLOCK
        assert "not found" in result.output["error"]

    def test_track_one_invalid_window_blocked(self, patched_db):
        _seed_hypothesis(patched_db, "h-w", "claim-w")
        _seed_decision(patched_db, decision_id="dc-w", ticker="TESTWW", hypothesis_id="h-w")
        result = ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-w", "observation_window": 21})
        assert result.outcome == Outcome.BLOCK

    def test_scan_invalid_window_blocked(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "scan", "windows": [60]})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Action: scan
# ═══════════════════════════════════════════════════════


class TestActionScan:
    def test_scan_empty_db(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "scan"})
        assert result.outcome == Outcome.PASS
        assert result.output["scanned"] == 0
        assert result.output["n_measurements"] == 0

    def test_scan_aggregates_pass_reject_insuf(self, patched_db):
        # pass
        _seed_hypothesis(patched_db, "h-p", "p-claim")
        _seed_decision(patched_db, decision_id="dc-p", ticker="TESTP", hypothesis_id="h-p")
        _seed_prices(
            patched_db,
            [("TESTP", "2026-04-20", 100.0), ("TESTP", "2026-04-27", 110.0)],
        )
        # reject
        _seed_hypothesis(patched_db, "h-r", "r-claim")
        _seed_decision(patched_db, decision_id="dc-r", ticker="TESTR", hypothesis_id="h-r")
        _seed_prices(
            patched_db,
            [("TESTR", "2026-04-20", 100.0), ("TESTR", "2026-04-27", 90.0)],
        )
        # insufficient (no prices)
        _seed_hypothesis(patched_db, "h-i", "i-claim")
        _seed_decision(patched_db, decision_id="dc-i", ticker="TESTI", hypothesis_id="h-i")

        result = ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        assert result.outcome == Outcome.PASS
        assert result.output["n_pass"] == 1
        assert result.output["n_reject"] == 1
        assert result.output["n_insufficient"] == 1

    def test_scan_default_windows(self, patched_db):
        _seed_hypothesis(patched_db, "h-d", "d-claim")
        _seed_decision(patched_db, decision_id="dc-d", ticker="TESTD", hypothesis_id="h-d")
        result = ForwardOutcomeTracker().run({"action": "scan"})
        # default = all 3 windows
        assert result.output["windows"] == list(SUPPORTED_WINDOWS)


# ═══════════════════════════════════════════════════════
# Action: last_outcome
# ═══════════════════════════════════════════════════════


class TestLastOutcome:
    def test_no_data_warn(self, patched_db):
        result = ForwardOutcomeTracker().run({"action": "last_outcome"})
        assert result.outcome == Outcome.WARN

    def test_returns_latest_for_decision(self, patched_db):
        _seed_hypothesis(patched_db, "h-l", "l-claim")
        _seed_decision(patched_db, decision_id="dc-l", ticker="TESTL", hypothesis_id="h-l")
        # manually log 7d + 14d outcomes
        log_decision_outcome(
            decision_id="dc-l",
            observation_window=7,
            tracked_as_of_date="2026-04-27",
            hypothesis_validation="insufficient_data",
            db_path=patched_db,
        )
        log_decision_outcome(
            decision_id="dc-l",
            observation_window=14,
            tracked_as_of_date="2026-05-04",
            hypothesis_validation="pass",
            db_path=patched_db,
        )
        result = ForwardOutcomeTracker().run({"action": "last_outcome", "decision_id": "dc-l"})
        assert result.outcome == Outcome.PASS
        # ORDER BY observation_window DESC → 14 returned
        assert result.output["observation_window"] == 14


# ═══════════════════════════════════════════════════════
# Discord publish
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    """PR3 Codex Round 6: validate/reject → outbox stage_rollout."""

    def test_validate_stages_to_rollout(self, patched_db):
        _seed_hypothesis(patched_db, "h-pub", "pub-claim")
        _seed_decision(patched_db, decision_id="dc-pub", ticker="TESTPB", hypothesis_id="h-pub")
        _seed_prices(
            patched_db,
            [("TESTPB", "2026-04-20", 100.0), ("TESTPB", "2026-04-27", 110.0)],
        )
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-pub", "observation_window": 7})
            mock_stage.assert_called_once()
            kw = mock_stage.call_args.kwargs
            assert kw["actor_name"] == "forward-outcome-tracker"
            assert kw["payload"]["kind"] == "hypothesis_validated"

    def test_reject_stages_to_rollout(self, patched_db):
        _seed_hypothesis(patched_db, "h-pub2", "pub2-claim")
        _seed_decision(patched_db, decision_id="dc-pub2", ticker="TESTPC", hypothesis_id="h-pub2")
        _seed_prices(
            patched_db,
            [("TESTPC", "2026-04-20", 100.0), ("TESTPC", "2026-04-27", 90.0)],
        )
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-pub2", "observation_window": 7})
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "hypothesis_rejected"

    def test_insufficient_does_not_stage(self, patched_db):
        _seed_hypothesis(patched_db, "h-np", "np-claim")
        _seed_decision(patched_db, decision_id="dc-np", ticker="MISSING2", hypothesis_id="h-np")
        with patch("nuri.agents.discord.outbox.stage_rollout") as mock_stage:
            ForwardOutcomeTracker().run({"action": "track_one", "decision_id": "dc-np", "observation_window": 7})
            mock_stage.assert_not_called()

    def test_publish_failure_does_not_block_actor(self, patched_db):
        _seed_hypothesis(patched_db, "h-pf", "pf-claim")
        _seed_decision(patched_db, decision_id="dc-pf", ticker="TESTPF", hypothesis_id="h-pf")
        _seed_prices(
            patched_db,
            [("TESTPF", "2026-04-20", 100.0), ("TESTPF", "2026-04-27", 110.0)],
        )
        with patch(
            "nuri.agents.discord.outbox.stage_rollout",
            side_effect=RuntimeError("outbox down"),
        ):
            result = ForwardOutcomeTracker().run(
                {"action": "track_one", "decision_id": "dc-pf", "observation_window": 7}
            )
            assert result.outcome == Outcome.PASS
            assert result.output["validation"] == "pass"


# ═══════════════════════════════════════════════════════
# Helper direct lock-tests
# ═══════════════════════════════════════════════════════


class TestHelperLockTests:
    def test_invalid_window_rejected(self, db_path):
        # 부모 row 시드
        _seed_hypothesis(db_path, "hx", "cx")
        _seed_decision(db_path, decision_id="dx", ticker="TX", hypothesis_id="hx")
        with pytest.raises(ValueError, match="observation_window must be"):
            log_decision_outcome(
                decision_id="dx",
                observation_window=21,
                tracked_as_of_date="2026-05-08",
                hypothesis_validation="pass",
                db_path=db_path,
            )

    def test_invalid_validation_rejected(self, db_path):
        _seed_hypothesis(db_path, "hy", "cy")
        _seed_decision(db_path, decision_id="dy", ticker="TY", hypothesis_id="hy")
        with pytest.raises(ValueError, match="hypothesis_validation must be"):
            log_decision_outcome(
                decision_id="dy",
                observation_window=7,
                tracked_as_of_date="2026-05-08",
                hypothesis_validation="maybe",
                db_path=db_path,
            )

    def test_idempotent_upsert(self, db_path):
        _seed_hypothesis(db_path, "hz", "cz")
        _seed_decision(db_path, decision_id="dz", ticker="TZ", hypothesis_id="hz")
        for ret in (0.05, 0.10):
            log_decision_outcome(
                decision_id="dz",
                observation_window=7,
                tracked_as_of_date="2026-05-08",
                realized_return=ret,
                hypothesis_validation="pass",
                db_path=db_path,
            )
        rows = query(
            "SELECT COUNT(*) AS c, realized_return FROM decision_outcomes WHERE decision_id=?",
            ("dz",),
            db_path=db_path,
        )
        r = dict(rows[0])
        assert r["c"] == 1
        assert r["realized_return"] == 0.10  # 두 번째 값으로 update


# ═══════════════════════════════════════════════════════
# Constants smoke
# ═══════════════════════════════════════════════════════


class TestConstants:
    def test_supported_windows_match_thresholds(self):
        assert set(WINDOW_THRESHOLDS.keys()) == set(SUPPORTED_WINDOWS)

    def test_thresholds_symmetric(self):
        for w, (up, down) in WINDOW_THRESHOLDS.items():
            assert up > 0
            assert down < 0
            assert abs(up + down) < 1e-9  # symmetric ±


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_scan_empty(self, patched_db, capsys):
        from nuri.agents.actors.forward_outcome_tracker import main

        rc = main(["scan"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "scanned" in out

    def test_cli_last_outcome_empty(self, patched_db, capsys):
        from nuri.agents.actors.forward_outcome_tracker import main

        rc = main(["last_outcome"])
        assert rc == 0


# ═══════════════════════════════════════════════════════
# Closed-loop integration — DecisionCompiler emit → Tracker → Hypothesis auto-validated
# ═══════════════════════════════════════════════════════


class TestClosedLoopIntegration:
    """Phase 2 closed-loop 의 진짜 가치 — 4-actor chain 의 outcome attribution."""

    def test_decision_compiler_emit_then_tracker_validates(self, patched_db, monkeypatch):
        # 1) Hypothesis register + validate (DecisionCompiler 가 통과시키려면)
        _seed_hypothesis(patched_db, "h-loop", "loop-claim")
        from nuri.core.db import validate_hypothesis

        # validate manually (실제로는 다른 mechanism — register 직후엔 open)
        # 그래서 새 hypothesis 만들고 그 자체로 closed-loop test 만 검증
        # 여기선 decision 만 있고 tracker 가 hypothesis 종결시키는 흐름

        _seed_decision(
            patched_db,
            decision_id="dc-loop",
            ticker="TESTLP",
            as_of_date="2026-04-20",
            hypothesis_id="h-loop",  # open status
        )
        _seed_prices(
            patched_db,
            [
                ("TESTLP", "2026-04-20", 100.0),
                ("TESTLP", "2026-04-27", 115.0),  # +15% strong pass
                ("SPY", "2026-04-20", 500.0),
                ("SPY", "2026-04-27", 505.0),
            ],
        )

        # 2) Tracker scan → validates h-loop automatically
        result = ForwardOutcomeTracker().run({"action": "scan", "windows": [7]})
        assert result.outcome == Outcome.PASS
        assert result.output["n_pass"] >= 1

        # 3) Verify hypothesis auto-transitioned open → validated
        rows = query(
            "SELECT status, validation_metrics_json FROM hypotheses WHERE hypothesis_id=?",
            ("h-loop",),
            db_path=patched_db,
        )
        r = dict(rows[0])
        assert r["status"] == "validated"
        # metrics 에 auto_trigger 표식
        import json

        metrics = json.loads(r["validation_metrics_json"])
        assert metrics["auto_trigger"] == "forward-outcome-tracker"
        assert metrics["realized_return"] == pytest.approx(0.15)
