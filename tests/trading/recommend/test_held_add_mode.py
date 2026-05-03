"""Tests for nuri/trading/recommend/held_add.py — #518 phase 2a (3 modes + shadow).

Lock-in:
  - 3 modes × 2 account contexts × earnings blackout
  - Mutual exclusion: tp1_residual_add(1) > ride_winner(2) > average_down(3)
  - Cap derivation: 같은 NVDA 가 2 계좌 → 2 independent emits
  - Earnings blackout: ±5d 안에 있으면 모든 mode 차단
  - Shadow mode: shadow_mode_until 까지 held_add_shadow 테이블 only

spec: docs/plans/507_buy_candidate_emitter_phase2_spec.md §4.6.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from nuri.core.db import init_db, query
from nuri.trading.recommend import held_add as ha

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """portfolio + prices 테이블 시드."""
    path = tmp_path / "test.db"
    init_db(path)
    conn = sqlite3.connect(path)
    # 2 accounts, 같은 NVDA + 다른 ticker
    conn.executemany(
        "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
        [
            # acct_alpha (core 15% cap): NVDA 14주 + MSFT 큰 비중 → NVDA cap headroom 확보
            ("acct_alpha", "NVDA", 14.0, 100.0, "USD"),
            ("acct_alpha", "MSFT", 200.0, 100.0, "USD"),
            # acct_beta (active 25% cap): NVDA 5주 + BBB 큰 비중 → headroom 확보
            ("acct_beta", "NVDA", 5.0, 100.0, "USD"),
            ("acct_beta", "BBB", 100.0, 100.0, "USD"),
        ],
    )
    # prices: NVDA +60% pnl (winner), MSFT -5% pnl (small loss, pullback range for core)
    conn.executemany(
        "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
        [
            ("NVDA", "2026-05-04", 160.0),  # +60% pnl
            ("MSFT", "2026-05-04", 95.0),  # -5% pnl
        ],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def cfg_held_add(tmp_path: Path) -> dict:
    """held_add_mode config — spec defaults."""
    return {
        "held_add_mode": {
            "enabled": True,
            "shadow_mode_until": "2026-05-15",
            "earnings_blackout_days": 5,
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
                    },
                    "precedence": 3,
                },
            },
        }
    }


@pytest.fixture
def cfg_yaml_path(tmp_path: Path, cfg_held_add: dict) -> Path:
    p = tmp_path / "buy_signals.yaml"
    p.write_text(yaml.safe_dump(cfg_held_add), encoding="utf-8")
    return p


@pytest.fixture
def stub_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """rules.get_account_strategy stub: alpha=core, beta=active."""

    def _stub(account: str) -> dict:
        if account == "acct_alpha":
            return {
                "stop_loss": -7,
                "max_single_position": 0.15,
                "tp1_pct": 21.0,
            }
        if account == "acct_beta":
            return {
                "stop_loss": -10,
                "max_single_position": 0.25,
                "tp1_pct": 21.0,
            }
        return {"stop_loss": -7, "max_single_position": 0.15, "tp1_pct": 21.0}

    monkeypatch.setattr("nuri.trading.recommend.held_add._get_account_strategy_profile", _stub)
    monkeypatch.setattr("nuri.core.account_cap.get_account_strategy", _stub)


# ─── 1. Earnings blackout ──────────────────────────────────────────


class TestEarningsBlackout:
    def test_blackout_within_window(self) -> None:
        """earnings_date ±5d 안 → True."""
        today = date(2026, 5, 4)
        fetcher = SimpleNamespace(calendar={"Earnings Date": [date(2026, 5, 6)]})  # +2d
        assert ha.is_in_earnings_blackout("MSFT", days=5, today=today, fetcher=fetcher) is True

    def test_outside_window(self) -> None:
        today = date(2026, 5, 4)
        fetcher = SimpleNamespace(calendar={"Earnings Date": [date(2026, 5, 20)]})  # +16d
        assert ha.is_in_earnings_blackout("MSFT", days=5, today=today, fetcher=fetcher) is False

    def test_no_earnings_date(self) -> None:
        """earnings_date 없음 → False (fail-open)."""
        today = date(2026, 5, 4)
        fetcher = SimpleNamespace(calendar={})
        assert ha.is_in_earnings_blackout("XYZ", days=5, today=today, fetcher=fetcher) is False

    def test_exception_returns_false(self) -> None:
        """fetcher exception → False (보수적)."""
        today = date(2026, 5, 4)

        class _Bad:
            @property
            def calendar(self):
                raise RuntimeError("network")

        assert ha.is_in_earnings_blackout("XYZ", days=5, today=today, fetcher=_Bad()) is False


# ─── 2. Shadow mode flag ───────────────────────────────────────────


class TestShadowMode:
    def test_today_before_until_is_shadow(self) -> None:
        cfg = {"shadow_mode_until": "2026-05-15"}
        assert ha._is_shadow_mode(cfg, today=date(2026, 5, 4)) is True

    def test_today_after_until_is_live(self) -> None:
        cfg = {"shadow_mode_until": "2026-05-15"}
        assert ha._is_shadow_mode(cfg, today=date(2026, 5, 16)) is False

    def test_no_until_means_live(self) -> None:
        assert ha._is_shadow_mode({}, today=date(2026, 5, 4)) is False


# ─── 3. Mode evaluation (mutual exclusion + precedence) ────────────


class TestModeEvaluation:
    def test_ride_winner_triggers_when_tp1_residual_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, cfg_held_add: dict
    ) -> None:
        """trim event 없음 → tp1_residual skip → ride_winner 평가."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_account_strategy_profile",
            lambda account: {"stop_loss": -7, "tp1_pct": 21.0},
        )
        pos = {
            "ticker": "NVDA",
            "account": "acct_alpha",
            "pnl_pct": 60.0,  # >= 21 × 2.5 = 52.5
            "days_held": 35,
        }
        mode = ha.select_held_mode(
            pos,
            cfg_held_add["held_add_mode"],
            score=80,
            rsi=55,
            regime="neutral",
            vix=18,
            breakout_above_trim=False,
            sector_mom=8,
        )
        assert mode == "ride_winner"

    def test_tp1_residual_takes_precedence_over_ride_winner(
        self, monkeypatch: pytest.MonkeyPatch, cfg_held_add: dict
    ) -> None:
        """trim 후 +30% pnl + breakout — tp1_residual 이 ride_winner 보다 우선."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: 10,  # trim 10일전
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_account_strategy_profile",
            lambda account: {"stop_loss": -7, "tp1_pct": 21.0},
        )
        pos = {
            "ticker": "NVDA",
            "account": "acct_alpha",
            "pnl_pct": 60.0,  # tp1×1.2=25.2 충족, ride_winner tp1×2.5=52.5 도 충족
            "days_held": 35,
        }
        mode = ha.select_held_mode(
            pos,
            cfg_held_add["held_add_mode"],
            score=80,
            rsi=55,
            regime="neutral",
            vix=18,
            breakout_above_trim=True,
            sector_mom=8,
        )
        assert mode == "tp1_residual_add"  # precedence=1

    def test_average_down_macro_veto_in_bear(self, monkeypatch: pytest.MonkeyPatch, cfg_held_add: dict) -> None:
        """regime=bear → average_down macro veto."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_account_strategy_profile",
            lambda account: {"stop_loss": -10, "tp1_pct": 21.0},
        )
        pos = {
            "ticker": "MSFT",
            "account": "acct_alpha",
            "pnl_pct": -5.0,  # window [-7, -3]
            "days_held": 20,
        }
        mode = ha.select_held_mode(
            pos,
            cfg_held_add["held_add_mode"],
            score=85,
            rsi=30,
            regime="bear",
            vix=18,
            breakout_above_trim=False,
            sector_mom=0,
        )
        assert mode is None

    def test_average_down_triggers_in_neutral(self, monkeypatch: pytest.MonkeyPatch, cfg_held_add: dict) -> None:
        """regime=neutral + RSI 30 + pnl -5% (window) → average_down."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_account_strategy_profile",
            lambda account: {"stop_loss": -10, "tp1_pct": 21.0},
        )
        pos = {
            "ticker": "MSFT",
            "account": "acct_alpha",
            "pnl_pct": -5.0,
            "days_held": 20,
        }
        mode = ha.select_held_mode(
            pos,
            cfg_held_add["held_add_mode"],
            score=85,
            rsi=30,
            regime="neutral",
            vix=18,
            breakout_above_trim=False,
            sector_mom=0,
        )
        assert mode == "average_down"

    def test_average_down_macro_veto_high_vix(self, monkeypatch: pytest.MonkeyPatch, cfg_held_add: dict) -> None:
        """VIX >= 28 → average_down macro veto."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_account_strategy_profile",
            lambda account: {"stop_loss": -10, "tp1_pct": 21.0},
        )
        pos = {
            "ticker": "MSFT",
            "account": "acct_alpha",
            "pnl_pct": -5.0,
            "days_held": 20,
        }
        mode = ha.select_held_mode(
            pos,
            cfg_held_add["held_add_mode"],
            score=85,
            rsi=30,
            regime="neutral",
            vix=30,
            breakout_above_trim=False,
            sector_mom=0,
        )
        assert mode is None


# ─── 4. emit_held_add_shadow E2E (multi-account independent caps) ──


class TestEmitHeldAddShadow:
    def test_multi_account_independent_emits(
        self,
        db_path: Path,
        cfg_yaml_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stub_strategy: None,
    ) -> None:
        """E2 핵심: NVDA 가 2 계좌 → 2 candidates (각 cap 독립)."""
        # _get_held_positions 가 default DB 를 본다 — db_path 로 swap
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_held_positions",
            lambda: [
                # acct_alpha NVDA: pnl +60% 충족 (winner)
                {
                    "ticker": "NVDA",
                    "account": "acct_alpha",
                    "qty": 14.0,
                    "avg_price": 100.0,
                    "current_price": 160.0,
                    "pnl_pct": 60.0,
                    "days_held": 35,
                },
                # acct_beta NVDA: pnl +60% 도 충족
                {
                    "ticker": "NVDA",
                    "account": "acct_beta",
                    "qty": 5.0,
                    "avg_price": 100.0,
                    "current_price": 160.0,
                    "pnl_pct": 60.0,
                    "days_held": 35,
                },
            ],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,  # trim 없음 → ride_winner 진입
        )

        # earnings: 모두 안전
        def _fetcher_factory(t: str) -> SimpleNamespace:
            return SimpleNamespace(calendar={})

        result = ha.emit_held_add_shadow(
            config_path=cfg_yaml_path,
            today=date(2026, 5, 4),
            earnings_fetcher_factory=_fetcher_factory,
            score_provider=lambda t: 85.0,
            rsi_provider=lambda t: 55.0,
            regime_provider=lambda: ("neutral", 18.0),
            sector_mom_provider=lambda t: 10.0,
            db_path=db_path,
        )

        # NVDA 가 2 계좌 emit
        accts = sorted(c.account for c in result.candidates if c.ticker == "NVDA")
        assert accts == ["acct_alpha", "acct_beta"]

        # 모두 ride_winner (precedence)
        assert all(c.mode == "ride_winner" for c in result.candidates)

        # cap_max_pct 가 계좌별로 다르다 (E2 invariant)
        alpha_cap = next(c.cap_max_pct for c in result.candidates if c.account == "acct_alpha")
        beta_cap = next(c.cap_max_pct for c in result.candidates if c.account == "acct_beta")
        assert alpha_cap == 15.0  # core
        assert beta_cap == 25.0  # active

        # shadow_mode ON (until 2026-05-15)
        assert result.shadow_mode is True

        # held_add_shadow 테이블에 persist 됨
        rows = query("SELECT ticker, account, mode FROM held_add_shadow", db_path=db_path)
        assert len(rows) == 2
        assert {r["account"] for r in rows} == {"acct_alpha", "acct_beta"}

    def test_earnings_blackout_blocks_emit(
        self,
        db_path: Path,
        cfg_yaml_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stub_strategy: None,
    ) -> None:
        """earnings ±5d → 모든 mode 차단."""
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_held_positions",
            lambda: [
                {
                    "ticker": "MSFT",
                    "account": "acct_alpha",
                    "qty": 3.0,
                    "avg_price": 100.0,
                    "current_price": 160.0,
                    "pnl_pct": 60.0,
                    "days_held": 35,
                }
            ],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )

        # MSFT earnings 4-30 (±4d 이내)
        def _factory(t: str) -> SimpleNamespace:
            return SimpleNamespace(calendar={"Earnings Date": [date(2026, 4, 30)]})

        result = ha.emit_held_add_shadow(
            config_path=cfg_yaml_path,
            today=date(2026, 5, 4),
            earnings_fetcher_factory=_factory,
            score_provider=lambda t: 85.0,
            rsi_provider=lambda t: 30.0,
            regime_provider=lambda: ("neutral", 18.0),
            sector_mom_provider=lambda t: 0.0,
            db_path=db_path,
        )
        assert len(result.candidates) == 0
        assert "MSFT@acct_alpha" in result.skipped
        assert "earnings blackout" in result.skipped["MSFT@acct_alpha"]

    def test_disabled_returns_empty(self, tmp_path: Path) -> None:
        """held_add_mode.enabled=False → no-op."""
        cfg_path = tmp_path / "buy_signals.yaml"
        cfg_path.write_text(yaml.safe_dump({"held_add_mode": {"enabled": False}}))
        result = ha.emit_held_add_shadow(config_path=cfg_path)
        assert result.candidates == []
        assert result.shadow_mode is True  # default

    def test_cap_headroom_zero_skips_emit(
        self,
        tmp_path: Path,
        cfg_yaml_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stub_strategy: None,
    ) -> None:
        """cap headroom <= 0 → mode 충족해도 skip (스펙 §4.1 cap_max 강제)."""
        # NVDA가 acct_alpha 100% 차지 → cap headroom 0
        path = tmp_path / "test_cap_zero.db"
        init_db(path)
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
            ("acct_alpha", "NVDA", 100.0, 100.0, "USD"),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_held_positions",
            lambda: [
                {
                    "ticker": "NVDA",
                    "account": "acct_alpha",
                    "qty": 100.0,
                    "avg_price": 100.0,
                    "current_price": 160.0,
                    "pnl_pct": 60.0,
                    "days_held": 35,
                }
            ],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.held_add._get_last_trim_age_days",
            lambda ticker, max_days=60: None,
        )

        result = ha.emit_held_add_shadow(
            config_path=cfg_yaml_path,
            today=date(2026, 5, 4),
            earnings_fetcher_factory=lambda t: SimpleNamespace(calendar={}),
            score_provider=lambda t: 85.0,
            rsi_provider=lambda t: 55.0,
            regime_provider=lambda: ("neutral", 18.0),
            sector_mom_provider=lambda t: 10.0,
            db_path=path,
        )
        assert len(result.candidates) == 0
        assert "NVDA@acct_alpha" in result.skipped
        assert "cap headroom" in result.skipped["NVDA@acct_alpha"]

    def test_why_now_strings_per_mode(self) -> None:
        """_build_why_now: 3 modes 별 catalyst 문구 — surface 일관성 lock."""
        pos = {"pnl_pct": 60.0}
        assert "TRIM" in ha._build_why_now("tp1_residual_add", pos)
        assert "winner" in ha._build_why_now("ride_winner", pos)
        assert "pullback" in ha._build_why_now("average_down", pos)
        # unknown mode fallback
        assert "unknown_mode" in ha._build_why_now("unknown_mode", pos)
