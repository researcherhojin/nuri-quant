"""would-fire 전방 측정 잠금 (#1173 = #788 Stage 1).

세 축을 고정한다:
- **동치**: emit 루프의 "gates ∧ score ≥ 임계" 유도가 `select_held_mode` 와 갈라질 수 없다.
- **그리드 수학**: 절대/백분위/rank_floor variant 와 near-threshold 경계.
- **사전등록**: config grid + stage2_adjudication 값의 조용한 드리프트 = FAIL
  (변경은 STRATEGY §3.12 개정 PR 로만 — §3.6 사전등록 원칙).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from nuri.core.db import init_db, query
from nuri.trading.recommend import held_add as ha
from nuri.trading.recommend import held_add_would_fire as wf

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def cfg_modes() -> dict:
    """mode trigger 3종 — 출하 기본값과 같은 임계 (75/75/80)."""
    return {
        "modes": {
            "tp1_residual_add": {
                "trigger": {
                    "last_trim_age_days_min": 5,
                    "last_trim_age_days_max": 60,
                    "unrealized_pnl_min_factor": 1.2,
                    "composite_score_min": 75,
                    "require_breakout_above_last_trim_price": True,
                },
                "precedence": 1,
            },
            "ride_winner": {
                "trigger": {
                    "unrealized_pnl_min_factor": 2.5,
                    "days_held_min": 30,
                    "composite_score_min": 75,
                    "sector_momentum_min": 5,
                },
                "precedence": 2,
            },
            "average_down": {
                "trigger": {
                    "unrealized_pnl_min_factor": 0.3,
                    "unrealized_pnl_max_factor": 0.7,
                    "composite_score_min": 80,
                    "rsi_max": 35,
                    "days_held_min": 14,
                    "macro_veto": True,
                    "macro_veto_regimes": [],
                },
                "precedence": 3,
            },
        }
    }


@pytest.fixture
def stub_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nuri.trading.recommend.held_add._get_last_trim_age_days",
        lambda ticker, max_days=60, db_path=None: 10,
    )
    monkeypatch.setattr(
        "nuri.trading.recommend.held_add._get_account_strategy_profile",
        lambda account: {"stop_loss": -7, "max_single_position": 0.15, "tp1_pct": 20.0},
    )


WINNER_POS = {"ticker": "NVDA", "account": "acct_a", "pnl_pct": 60.0, "days_held": 40}
LOSER_POS = {"ticker": "MSFT", "account": "acct_a", "pnl_pct": -4.0, "days_held": 40}


# ─── 1. 동치 잠금 — 유도 경로 ≡ select_held_mode ───────────────────


class TestGatesEquivalence:
    """emit 루프의 유도(gates + score ≥ config 임계의 첫 precedence)가
    `select_held_mode` 와 완전히 같아야 한다 — 측정 축과 라이브 결정이 공유하는
    평가가 갈라지면 Stage 2 의 "current" variant 가 실주행과 다른 것을 잰다."""

    @pytest.mark.parametrize("score", [0.0, 50.0, 74.9, 75.0, 79.9, 80.0, 95.0])
    @pytest.mark.parametrize(
        ("pos", "rsi", "breakout", "sector_mom"),
        [
            (WINNER_POS, 50.0, True, 8.0),  # tp1 + ride 게이트 열림
            (WINNER_POS, 50.0, False, 8.0),  # ride 만
            (WINNER_POS, 50.0, False, 0.0),  # 게이트 전부 닫힘
            (LOSER_POS, 30.0, False, 0.0),  # average_down 만
        ],
    )
    def test_derived_mode_equals_select_held_mode(
        self, cfg_modes: dict, stub_readers: None, score: float, pos: dict, rsi, breakout: bool, sector_mom: float
    ) -> None:
        regime, vix = "bull_low_vol", 15.0
        gates = ha.evaluate_mode_gates(
            pos, cfg_modes, rsi, regime, vix, breakout_above_trim=breakout, sector_mom=sector_mom
        )
        thresholds = ha.current_mode_thresholds(cfg_modes)
        derived = next(
            (
                m
                for m in sorted(ha.MODE_PRECEDENCE.keys(), key=lambda m: ha.MODE_PRECEDENCE[m])
                if gates[m] and score >= thresholds[m]
            ),
            None,
        )
        canonical = ha.select_held_mode(
            pos, cfg_modes, score, rsi, regime, vix, breakout_above_trim=breakout, sector_mom=sector_mom
        )
        assert derived == canonical


# ─── 2. 그리드 수학 ────────────────────────────────────────────────


GRID_CFG = {"absolute": [55, 60, 65, 70], "percentiles": [70, 80, 90], "rank_floor": {"percentile": 70, "floor": 60}}
CURRENT = {"tp1_residual_add": 75.0, "ride_winner": 75.0, "average_down": 80.0}


class TestGridThresholds:
    def test_variant_set_and_values(self) -> None:
        scores = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        grid = wf.compute_grid_thresholds(scores, CURRENT, GRID_CFG)
        assert set(grid) == {"current", "abs_55", "abs_60", "abs_65", "abs_70", "p70", "p80", "p90", "rank_floor"}
        assert grid["current"]["average_down"] == 80.0 and grid["current"]["ride_winner"] == 75.0
        assert all(v == 55.0 for v in grid["abs_55"].values())
        # numpy linear interpolation: p70 of the 10-point ladder = 73.0
        assert grid["p70"]["ride_winner"] == pytest.approx(73.0)
        assert grid["rank_floor"]["ride_winner"] == pytest.approx(73.0)  # max(73, 60)

    def test_rank_floor_uses_the_floor_when_percentile_is_lower(self) -> None:
        grid = wf.compute_grid_thresholds([10.0, 20.0, 30.0], CURRENT, GRID_CFG)
        assert grid["rank_floor"]["ride_winner"] == 60.0  # p70=24 < floor 60

    def test_empty_scores_disable_percentile_variants(self) -> None:
        grid = wf.compute_grid_thresholds([], CURRENT, GRID_CFG)
        assert grid["p70"]["ride_winner"] is None and grid["rank_floor"]["ride_winner"] is None
        assert grid["abs_55"]["ride_winner"] == 55.0  # 절대 variant 는 분포 무관


class TestWouldFire:
    def test_relaxed_threshold_can_promote_a_higher_precedence_mode(self) -> None:
        """임계 완화가 current 와 **다른 상위 precedence mode** 를 고를 수 있다 —
        Stage 2 incremental 정의가 mode 무관인 이유 (STRATEGY §3.12 2항)."""
        gates = {"tp1_residual_add": True, "ride_winner": True, "average_down": False}
        grid = {
            "current": dict(CURRENT),
            "abs_60": dict.fromkeys(CURRENT, 60.0),
        }
        out = wf.compute_would_fire(70.0, gates, grid)
        assert out["current"] is None  # 70 < 75
        assert out["abs_60"] == "tp1_residual_add"  # 완화 시 precedence 1 이 먼저

    def test_gate_closed_mode_never_fires(self) -> None:
        gates = {"tp1_residual_add": False, "ride_winner": True, "average_down": False}
        out = wf.compute_would_fire(90.0, gates, {"abs_60": dict.fromkeys(CURRENT, 60.0)})
        assert out["abs_60"] == "ride_winner"

    def test_none_threshold_means_no_fire(self) -> None:
        gates = dict.fromkeys(CURRENT, True)
        out = wf.compute_would_fire(90.0, gates, {"p70": dict.fromkeys(CURRENT, None)})
        assert out["p70"] is None


class TestNearThreshold:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [(69.9, False), (70.0, True), (75.0, True), (80.0, True), (80.1, False)],
    )
    def test_band_boundaries(self, score: float, expected: bool) -> None:
        gates = {"tp1_residual_add": False, "ride_winner": True, "average_down": False}
        assert wf.compute_near_threshold(score, gates, CURRENT, near_band=5.0) is expected

    def test_needs_an_open_gate(self) -> None:
        gates = dict.fromkeys(CURRENT, False)
        assert wf.compute_near_threshold(75.0, gates, CURRENT, near_band=5.0) is False


# ─── 3. 원장 멱등성 + emit 통합 ────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "wf.db"
    init_db(path)
    return path


def _row(ticker: str = "NVDA", score: float = 70.0, blackout: bool = False) -> dict:
    if blackout:
        # emit 계약: blackout 은 provider 를 타기 전에 끊기므로 관측치가 없다 (NULL).
        return {
            "ticker": ticker,
            "account": "acct_a",
            "score": None,
            "pnl_pct": 60.0,
            "rsi": None,
            "sector_mom": None,
            "headroom_pct": 3.0,
            "gates": dict.fromkeys(CURRENT, False),
            "earnings_blackout": True,
        }
    return {
        "ticker": ticker,
        "account": "acct_a",
        "score": score,
        "pnl_pct": 60.0,
        "rsi": 50.0,
        "sector_mom": 8.0,
        "headroom_pct": 3.0,
        "gates": {"tp1_residual_add": False, "ride_winner": True, "average_down": False},
        "earnings_blackout": blackout,
    }


WF_CFG = {"enabled": True, "near_band": 5, "grid": GRID_CFG}


class TestLedgerIdempotency:
    def test_same_day_rerun_updates_one_row(self, db_path: Path) -> None:
        wf.log_would_fire_rows(
            [_row(score=70.0)], WF_CFG, CURRENT, as_of_date="2026-08-29", run_id="r1", db_path=db_path
        )
        wf.log_would_fire_rows(
            [_row(score=76.0)], WF_CFG, CURRENT, as_of_date="2026-08-29", run_id="r2", db_path=db_path
        )

        rows = query("SELECT * FROM held_add_would_fire", db_path=db_path)
        assert len(rows) == 1, "같은 (날짜, ticker, account) 재실행이 중복행을 만들었다"
        assert rows[0]["score"] == 76.0 and rows[0]["run_id"] == "r2"
        fired = json.loads(rows[0]["would_fire_json"])
        assert fired["current"] == "ride_winner"  # 76 ≥ 75 (당일 최신 평가가 canonical)

    def test_different_days_accumulate(self, db_path: Path) -> None:
        wf.log_would_fire_rows([_row()], WF_CFG, CURRENT, as_of_date="2026-08-28", db_path=db_path)
        wf.log_would_fire_rows([_row()], WF_CFG, CURRENT, as_of_date="2026-08-29", db_path=db_path)
        assert len(query("SELECT * FROM held_add_would_fire", db_path=db_path)) == 2

    def test_blackout_row_is_recorded_but_fires_nothing(self, db_path: Path) -> None:
        wf.log_would_fire_rows(
            [_row(blackout=True), _row(ticker="MSFT", score=90.0)],
            WF_CFG,
            CURRENT,
            as_of_date="2026-08-29",
            db_path=db_path,
        )
        rows = {r["ticker"]: r for r in query("SELECT * FROM held_add_would_fire", db_path=db_path)}
        assert rows["NVDA"]["earnings_blackout"] == 1
        assert rows["NVDA"]["score"] is None, "blackout 행에 관측치가 아닌 score 가 박혔다"
        assert all(v is None for v in json.loads(rows["NVDA"]["would_fire_json"]).values())
        assert rows["NVDA"]["near_threshold"] == 0
        # blackout 행은 백분위 모집단에서도 빠진다 — MSFT 단독 분포 (p70 = 90)
        grid = json.loads(rows["MSFT"]["grid_thresholds_json"])
        assert grid["p70"]["ride_winner"] == pytest.approx(90.0)

    def test_rerun_deletes_orphan_rows_of_the_day(self, db_path: Path) -> None:
        """당일 재실행에 없는 보유의 행은 삭제 — upsert 만으론 판 보유의 행과 낡은
        백분위 grid 가 남아 Stage 2 발화 카운트를 오염시킨다 (codex diff P2)."""
        wf.log_would_fire_rows(
            [_row(ticker="NVDA"), _row(ticker="MSFT", score=90.0)],
            WF_CFG,
            CURRENT,
            as_of_date="2026-08-29",
            db_path=db_path,
        )
        wf.log_would_fire_rows(
            [_row(ticker="MSFT", score=88.0)], WF_CFG, CURRENT, as_of_date="2026-08-29", db_path=db_path
        )

        rows = query("SELECT ticker FROM held_add_would_fire WHERE as_of_date='2026-08-29'", db_path=db_path)
        assert [r["ticker"] for r in rows] == ["MSFT"], "당일 고아 행이 남았다"
        # 다른 날짜의 행은 건드리지 않는다
        wf.log_would_fire_rows([_row(ticker="NVDA")], WF_CFG, CURRENT, as_of_date="2026-08-30", db_path=db_path)
        assert len(query("SELECT * FROM held_add_would_fire", db_path=db_path)) == 2


class TestEmitIntegration:
    """emit_held_add_shadow 가 라이브 emit 과 같은 스냅샷으로 원장을 채우고,
    기록 실패가 emit 을 죽이지 않는다 (#894 계열)."""

    @pytest.fixture
    def cfg_path(self, tmp_path: Path, cfg_modes: dict) -> Path:
        cfg = {
            "held_add_mode": {
                "enabled": True,
                "shadow_mode_until": "2099-12-31",
                "earnings_blackout_days": 5,
                **cfg_modes,
                "would_fire_logging": dict(WF_CFG),
            }
        }
        p = tmp_path / "buy_signals.yaml"
        p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        return p

    @pytest.fixture
    def positions(self, monkeypatch: pytest.MonkeyPatch, stub_readers: None) -> None:
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_held_positions",
            lambda db_path=None: [dict(WINNER_POS), dict(LOSER_POS)],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add.derive_position_cap",
            lambda t, a, db_path=None: {"current_pct": 5.0, "cap_max_pct": 15.0, "headroom_pct": 10.0},
        )

    def test_rows_logged_into_the_given_db_only(self, db_path: Path, cfg_path: Path, positions: None) -> None:
        result = ha.emit_held_add_shadow(
            config_path=cfg_path,
            score_provider=lambda t: 76.0,
            rsi_provider=lambda t: 30.0,
            regime_provider=lambda: ("bull_low_vol", 15.0),
            sector_mom_provider=lambda t: 8.0,
            breakout_above_trim_provider=lambda t: True,
            db_path=db_path,
        )
        rows = query("SELECT * FROM held_add_would_fire", db_path=db_path)
        assert len(rows) == 2, "보유 2건이 전부 원장에 기록돼야 한다"
        by_ticker = {r["ticker"]: r for r in rows}
        # 라이브 emit 과 같은 값: NVDA 는 tp1 발화 (76 ≥ 75, breakout ON)
        assert any(c.ticker == "NVDA" and c.mode == "tp1_residual_add" for c in result.candidates)
        assert json.loads(by_ticker["NVDA"]["would_fire_json"])["current"] == "tp1_residual_add"
        assert by_ticker["NVDA"]["near_threshold"] == 1  # |76-75| ≤ 5

    def test_logging_failure_does_not_kill_the_emit(
        self, db_path: Path, cfg_path: Path, positions: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nuri.trading.recommend.held_add_would_fire as wf_mod

        def _boom(*a, **kw):
            raise RuntimeError("ledger down")

        monkeypatch.setattr(wf_mod, "log_would_fire_rows", _boom)
        result = ha.emit_held_add_shadow(
            config_path=cfg_path,
            score_provider=lambda t: 76.0,
            rsi_provider=lambda t: 30.0,
            regime_provider=lambda: ("bull_low_vol", 15.0),
            sector_mom_provider=lambda t: 8.0,
            breakout_above_trim_provider=lambda t: True,
            db_path=db_path,
        )
        assert result.candidates, "관측 실패가 본 작업(emit)을 죽였다 (#894)"

    def test_blackout_short_circuits_before_providers(self, db_path: Path, cfg_path: Path, positions: None) -> None:
        """blackout 종목은 provider 를 **타지 않는다** (종전 short-circuit 유지 —
        codex diff P2: provider 예외가 run 전체를 죽이는 회귀 + 미평가 값의 관측치화).
        NVDA 를 blackout 으로 만들고 그 ticker 의 score provider 를 지뢰로 둔다."""
        from datetime import date
        from types import SimpleNamespace

        today = date(2026, 5, 4)

        def factory(ticker: str):
            if ticker == "NVDA":
                return SimpleNamespace(calendar={"Earnings Date": [date(2026, 5, 6)]})  # ±5d 안
            return SimpleNamespace(calendar={})

        def score_fn(ticker: str) -> float:
            if ticker == "NVDA":
                raise RuntimeError("blackout ticker 의 provider 가 호출됐다")
            return 76.0

        result = ha.emit_held_add_shadow(
            config_path=cfg_path,
            today=today,
            earnings_fetcher_factory=factory,
            score_provider=score_fn,
            rsi_provider=lambda t: 30.0,
            regime_provider=lambda: ("bull_low_vol", 15.0),
            sector_mom_provider=lambda t: 8.0,
            breakout_above_trim_provider=lambda t: True,
            db_path=db_path,
        )

        assert "NVDA@acct_a" in result.skipped
        rows = {r["ticker"]: r for r in query("SELECT * FROM held_add_would_fire", db_path=db_path)}
        assert rows["NVDA"]["earnings_blackout"] == 1 and rows["NVDA"]["score"] is None
        assert rows["MSFT"]["score"] == 76.0  # 나머지 보유는 정상 평가·기록

    def test_disabled_logging_writes_nothing(
        self, db_path: Path, tmp_path: Path, cfg_modes: dict, positions: None
    ) -> None:
        cfg = {
            "held_add_mode": {
                "enabled": True,
                "shadow_mode_until": "2099-12-31",
                "earnings_blackout_days": 5,
                **cfg_modes,
            }
        }
        p = tmp_path / "no_wf.yaml"
        p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        ha.emit_held_add_shadow(
            config_path=p,
            score_provider=lambda t: 76.0,
            rsi_provider=lambda t: 30.0,
            regime_provider=lambda: ("bull_low_vol", 15.0),
            sector_mom_provider=lambda t: 8.0,
            breakout_above_trim_provider=lambda t: True,
            db_path=db_path,
        )
        assert query("SELECT * FROM held_add_would_fire", db_path=db_path) == []


# ─── 4. 사전등록 잠금 (§3.6 / STRATEGY §3.12) ──────────────────────


class TestPreRegistrationLock:
    """출하 config 의 grid + stage2_adjudication 은 2026-08-29 사전등록 값이다.
    여기 어긋나면 이 테스트가 깨진다 — 고치는 방법은 값 원복 또는 STRATEGY §3.12
    개정 PR + 이 잠금의 동시 갱신뿐 (조용한 드리프트가 곧 사후 amend 다)."""

    @pytest.fixture
    def shipped(self) -> dict:
        root = Path(__file__).resolve().parents[3]
        cfg = yaml.safe_load((root / "config" / "buy_signals.yaml").read_text(encoding="utf-8"))
        return cfg["held_add_mode"]["would_fire_logging"]

    def test_grid_is_the_preregistered_one(self, shipped: dict) -> None:
        assert shipped["enabled"] is True
        assert shipped["near_band"] == 5
        assert shipped["grid"] == {
            "absolute": [55, 60, 65, 70],
            "percentiles": [70, 80, 90],
            "rank_floor": {"percentile": 70, "floor": 60},
        }

    def test_stage2_adjudication_is_the_preregistered_one(self, shipped: dict) -> None:
        assert shipped["stage2_adjudication"] == {
            "alpha_horizon_days": 30,
            "benchmark": "SPY",
            "dedup_days": 7,
            "dedup_survivor": "first",
            "min_incremental_events": 20,
            "min_logging_weeks": 8,
            "settlement_rule": "as_of_date <= adjudication_date - 30d",
            "tie_band_alpha_pct": 0.5,
            "fire_rate_max_ratio": 0.25,
            "verdict_scope": "descriptive_screening",
        }, "stage2 사전등록 값이 바뀌었다 — STRATEGY §3.12 개정 PR 없이는 금지"
