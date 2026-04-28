"""
Q1 Recovery state machine lock-tests — STRATEGY §5.3.1 Gotcha-Test Pair.

Locks invariants from `docs/plans/E3_symmetric_amplifier_design.md`:
    1. Recovery requires prior_stress (panic 없이 그냥 상승은 회복 아님)
    2. Single-day bounce 차단 — 3 consecutive repair days 필수
    3. F&G 데이터 부족 시 graceful — VIX/SPY 만으로 동작

Test data is fully synthetic (tmp_path DB) — no network, no real prices.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices
from nuri.quant.regime.recovery_detector import (
    REPAIR_PERSIST_DAYS,
    detect_prior_stress,
    evaluate_recovery,
    evaluate_repair_day,
)


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "recovery.db"
    init_db(path)
    return path


def _bdates(start: str, n: int) -> list[str]:
    """Business-day strings."""
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=n)]


def _seed_spy(db_path, dates: list[str], closes: list[float]) -> None:
    df = pd.DataFrame(
        {
            "ticker": "SPY",
            "date": dates,
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [50_000_000] * len(closes),
            "adj_close": closes,
        }
    )
    upsert_prices(df, db_path)


def _seed_vix(db_path, dates: list[str], values: list[float]) -> None:
    rows = [{"indicator": "vix", "date": d, "value": v, "source": "test"} for d, v in zip(dates, values)]
    upsert_macro(rows, db_path)


# ════════════════════════════════════════════════════════════
# Lock-test 1 (Q1 invariant 1): no recovery without prior_stress
# ════════════════════════════════════════════════════════════
class TestRecoveryRequiresPriorStress:
    """STRATEGY §2.6 — amplifier 1번째 mandatory 조건은 prior_stress 가 있을 때만 회복 인정.

    Why this lock matters: panic 없는 평상시 상승장에서 amplifier 가 발동하면
    revenge trading 함정. 사용자 -₩7M 회복 욕구를 코드 레벨에서 차단.
    """

    def test_calm_uptrend_no_prior_stress_no_recovery(self, db_path):
        # 90일 평온한 상승장: VIX 14-16 만, SPY 100→130 꾸준히 상승
        dates = _bdates("2024-01-02", 90)
        closes = [100.0 + i * 0.3 for i in range(90)]
        vix_vals = [14.0 + (i % 3) * 0.5 for i in range(90)]
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, vix_vals)

        as_of = dates[-1]
        prior_stress, reasons = detect_prior_stress(as_of, db_path=db_path)
        assert prior_stress is False, f"calm uptrend triggered prior_stress: {reasons}"

        result = evaluate_recovery(as_of, db_path=db_path)
        assert result.prior_stress is False
        assert result.recovery_confirmed is False, "recovery fired without prior stress (revenge-trading risk)"

    def test_vix_spike_creates_prior_stress(self, db_path):
        # VIX 가 직전 20일에 27 까지 spike → prior_stress trigger
        dates = _bdates("2024-01-02", 90)
        closes = [100.0] * 90
        vix_vals = [16.0] * 90
        # 직전 20일 안에 VIX 27 발생
        vix_vals[-15] = 27.5
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, vix_vals)

        prior_stress, reasons = detect_prior_stress(dates[-1], db_path=db_path)
        assert prior_stress is True
        assert any("vix_peak" in r for r in reasons)

    def test_spy_drawdown_creates_prior_stress(self, db_path):
        # 63일 안에 시장 지수 10% drawdown
        dates = _bdates("2024-01-02", 90)
        closes = [100.0] * 30 + [100.0 - i * 0.5 for i in range(30)] + [85.0 + i * 0.1 for i in range(30)]
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, [16.0] * 90)

        prior_stress, reasons = detect_prior_stress(dates[-1], db_path=db_path)
        assert prior_stress is True
        assert any("spy_max_dd" in r or "spy_dd" in r for r in reasons)

    def test_recovered_after_stress_still_detects_prior_stress(self, db_path):
        """SPY 100 → 82 (-18%) → 96 path. 오늘 가격은 -8% 임계값 위로 회복했으나
        window 내 drawdown 흔적이 있으므로 prior_stress=True 여야 한다.

        Why this lock matters (codex Round 1 P1): 회복된 후엔 stress 흔적을 잊어
        recovery_confirmed 가 영영 발동 못 하던 bug. 회복 path 자체를 차단하던
        critical bug — 본 테스트가 fix 를 lock.
        """
        dates = _bdates("2024-01-02", 90)
        # 30일 평탄 100 → 30일 -18% 하락 (100→82) → 30일 회복 (82→96.7)
        closes = [100.0] * 30 + [100.0 - i * 0.6 for i in range(30)] + [82.0 + i * 0.51 for i in range(30)]
        # closes[-1] ≈ 96.79 (peak 100 대비 -3.2%, -8% 임계값 위로 회복)
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, [16.0] * 90)

        prior_stress, reasons = detect_prior_stress(dates[-1], db_path=db_path)
        assert prior_stress is True, f"recovered-after-stress 시나리오에서 prior_stress 망각 (codex P1 회귀): {reasons}"
        assert any("spy_max_dd" in r for r in reasons), reasons


# ════════════════════════════════════════════════════════════
# Lock-test 2 (Q1 invariant 2): 1-day bounce 차단, 3 consecutive 필요
# ════════════════════════════════════════════════════════════
class TestRecoveryRequiresThreeDayRepair:
    """단일 일 bounce 만으로 recovery 인정하면 false dawn (dead cat bounce) 위험.
    Codex Q1 권고: REPAIR_PERSIST_DAYS = 3.

    Why this lock matters: 04-09 시점 같이 panic 직후 1일 bounce 에 amplifier
    발동하면 추가 leg-down 에 그대로 노출.

    Implementation note: data fixture 로 4-component repair_day 를 deterministic 하게
    조립하기 어려워 monkeypatch 로 evaluate_repair_day + detect_prior_stress 를 stub.
    이 테스트의 대상 invariant 는 evaluate_recovery() 의 consecutive count 로직 자체.
    """

    def test_one_day_bounce_does_not_confirm_recovery(self, db_path, monkeypatch):
        # 가장 최근 1 일만 repair_day=True, 이전 모두 False 로 stub
        from nuri.quant.regime import recovery_detector as rd

        # 마지막 1 일만 True
        seen_dates: list[str] = []

        def fake_repair(as_of, db_path=None):  # noqa: ARG001
            seen_dates.append(as_of)
            # 첫 번째 호출 (current as_of) 만 True, 그 이후는 모두 False
            return (len(seen_dates) == 1, {"stub": True})

        def fake_stress(as_of, db_path=None):  # noqa: ARG001
            return (True, ["stub_stress"])

        monkeypatch.setattr(rd, "evaluate_repair_day", fake_repair)
        monkeypatch.setattr(rd, "detect_prior_stress", fake_stress)

        # SPY 시계열만 seed (consecutive lookup 시 trading day 목록 사용)
        dates = _bdates("2024-01-02", 90)
        _seed_spy(db_path, dates, [100.0] * 90)
        _seed_vix(db_path, dates, [16.0] * 90)  # exit_recovery 평가용

        result = evaluate_recovery(dates[-1], db_path=db_path)
        assert result.prior_stress is True, "stress stub must be applied"
        assert result.repair_day is True, "today repair_day stub"
        # 1일만 True → consecutive 1 → < REPAIR_PERSIST_DAYS
        assert result.consecutive_repair_days < REPAIR_PERSIST_DAYS
        assert result.recovery_confirmed is False, "single-day bounce confirmed recovery (false dawn risk)"

    def test_three_day_repair_confirms_recovery(self, db_path, monkeypatch):
        """positive case — 3 연속 repair + prior_stress 면 recovery_confirmed=True."""
        from nuri.quant.regime import recovery_detector as rd

        def fake_repair_always_true(as_of, db_path=None):  # noqa: ARG001
            return (True, {"stub": True})

        def fake_stress(as_of, db_path=None):  # noqa: ARG001
            return (True, ["stub_stress"])

        monkeypatch.setattr(rd, "evaluate_repair_day", fake_repair_always_true)
        monkeypatch.setattr(rd, "detect_prior_stress", fake_stress)

        dates = _bdates("2024-01-02", 90)
        _seed_spy(db_path, dates, [100.0] * 90)
        _seed_vix(db_path, dates, [16.0] * 90)

        result = evaluate_recovery(dates[-1], db_path=db_path)
        assert result.consecutive_repair_days >= REPAIR_PERSIST_DAYS
        assert result.recovery_confirmed is True

    def test_repair_persist_constant_blocks_single_day(self):
        # config 변조 방지 — REPAIR_PERSIST_DAYS 가 임의로 1 로 내려가면 invariant 깨짐
        assert REPAIR_PERSIST_DAYS >= 3, "REPAIR_PERSIST_DAYS must be ≥ 3 — false-dawn protection"

    def test_broken_streak_resets_consecutive_count(self, db_path, monkeypatch):
        """T=True, T-1=False, T-2=True 패턴 → consecutive=1 (T-1 에서 streak break).

        Why this lock matters (codex Round 1 P3): consecutive count 가 break 무시하고
        running total 만 누적하면 false dawn detection 실효. T-1 단 1 일 break 도
        streak reset 보장.
        """
        from nuri.quant.regime import recovery_detector as rd

        # date 별 deterministic stub — call order 의존 안 함
        # 호출 순서: today → T-1 → T-2 (evaluate_recovery 내부 reversed loop)
        dates = _bdates("2024-01-02", 90)
        today = dates[-1]
        t_minus_1 = dates[-2]
        t_minus_2 = dates[-3]
        repair_map = {today: True, t_minus_1: False, t_minus_2: True}

        def fake_repair(as_of, db_path=None):  # noqa: ARG001
            return (repair_map.get(as_of, False), {"stub": True})

        def fake_stress(as_of, db_path=None):  # noqa: ARG001
            return (True, ["stub_stress"])

        monkeypatch.setattr(rd, "evaluate_repair_day", fake_repair)
        monkeypatch.setattr(rd, "detect_prior_stress", fake_stress)

        _seed_spy(db_path, dates, [100.0] * 90)
        _seed_vix(db_path, dates, [16.0] * 90)

        result = evaluate_recovery(today, db_path=db_path)
        assert result.consecutive_repair_days == 1, (
            f"broken streak at T-1 must reset, got {result.consecutive_repair_days}"
        )
        assert result.recovery_confirmed is False


# ════════════════════════════════════════════════════════════
# Lock-test 4 (Q1 invariant 3): exit hysteresis — 2 consecutive fails OR VIX≥25
# ════════════════════════════════════════════════════════════
class TestExitHysteresisTwoConsecutiveFails:
    """Codex Round 1 P2 — file header 가 "2 consecutive repair fails OR VIX≥25" 명세.
    기존 구현은 VIX path 만 surface 했음. 두 path 모두 lock 필요.

    Why this lock matters: recovery 확정 후 회복 끝났는지 판정 기준. VIX 가 정상이라도
    repair condition 이 2일 연속 깨지면 dead-cat-bounce 가능성 — exit 신호 필수.
    """

    def test_two_consecutive_fails_triggers_exit_even_with_low_vix(self, db_path, monkeypatch):
        from nuri.quant.regime import recovery_detector as rd

        dates = _bdates("2024-01-02", 90)
        today = dates[-1]
        t_minus_1 = dates[-2]
        # today + T-1 모두 repair=False, 그 외 dates 는 호출 안 됨 (today=False 라 consecutive loop 진입 안 함)
        repair_map = {today: False, t_minus_1: False}

        def fake_repair(as_of, db_path=None):  # noqa: ARG001
            return (repair_map.get(as_of, False), {"stub": True})

        def fake_stress(as_of, db_path=None):  # noqa: ARG001
            return (True, ["stub_stress"])

        monkeypatch.setattr(rd, "evaluate_repair_day", fake_repair)
        monkeypatch.setattr(rd, "detect_prior_stress", fake_stress)

        _seed_spy(db_path, dates, [100.0] * 90)
        _seed_vix(db_path, dates, [16.0] * 90)  # well below EXIT_VIX_THRESHOLD=25

        result = evaluate_recovery(today, db_path=db_path)
        assert result.exit_recovery is True, (
            "2 consecutive repair fails 만으로 exit 안 발동 — VIX 가 낮아도 차단되어야 함"
        )

    def test_single_fail_does_not_trigger_exit(self, db_path, monkeypatch):
        from nuri.quant.regime import recovery_detector as rd

        dates = _bdates("2024-01-02", 90)
        today = dates[-1]
        t_minus_1 = dates[-2]
        repair_map = {today: False, t_minus_1: True}  # 단 1일 break

        def fake_repair(as_of, db_path=None):  # noqa: ARG001
            return (repair_map.get(as_of, False), {"stub": True})

        def fake_stress(as_of, db_path=None):  # noqa: ARG001
            return (True, ["stub_stress"])

        monkeypatch.setattr(rd, "evaluate_repair_day", fake_repair)
        monkeypatch.setattr(rd, "detect_prior_stress", fake_stress)

        _seed_spy(db_path, dates, [100.0] * 90)
        _seed_vix(db_path, dates, [16.0] * 90)

        result = evaluate_recovery(today, db_path=db_path)
        assert result.exit_recovery is False, "single-day repair miss 만으로 exit 발동 안 됨"


# ════════════════════════════════════════════════════════════
# Lock-test 3: F&G 데이터 부족 시 graceful fallback
# ════════════════════════════════════════════════════════════
class TestRecoveryGracefulFallbackWithoutFG:
    """F&G data 가 DB 에 14 rows only — Codex consult 발견.
    F&G 없이도 SPY+VIX 만으로 recovery detection 동작해야 함 (data sovereignty §2.5).
    """

    def test_no_fear_greed_data_does_not_crash(self, db_path):
        dates = _bdates("2024-01-02", 90)
        closes = [100.0] * 90
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, [16.0] * 90)
        # F&G 의도적으로 안 seed

        # 예외 발생 안 해야 함
        result = evaluate_recovery(dates[-1], db_path=db_path)
        assert result is not None
        # F&G 가 trigger 한 reason 은 없어야 함
        assert not any("fg_min" in r for r in result.prior_stress_reasons)

    def test_repair_components_independent_of_fg(self, db_path):
        dates = _bdates("2024-01-02", 90)
        # Repair 4 components 가 모두 PASS 가능한 가격 시나리오
        closes = [100.0] * 60 + [98.0 + i * 0.5 for i in range(30)]  # 마지막 30일 우상향
        vix_vals = [22.0] * 60 + [22.0 - i * 0.2 for i in range(30)]  # 마지막 30일 VIX 하락
        _seed_spy(db_path, dates, closes)
        _seed_vix(db_path, dates, vix_vals)

        repair_day, components = evaluate_repair_day(dates[-1], db_path=db_path)
        # 4 components 모두 boolean (None/missing 아님)
        assert all(isinstance(v, bool) for v in components.values())
        assert "spy_above_20dma" in components
        assert "vix_3d_slope_negative" in components
