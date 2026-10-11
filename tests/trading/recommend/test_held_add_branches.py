"""held_add would-fire 측정의 headroom 조회 실패 경로 (#1173).

headroom 은 측정 행의 **기록 항목**이지 판정 입력이 아니다 — 조회가 죽어도 행은 남고
(`headroom_pct` NULL), 루프는 다음 보유로 간다. blackout 행(`_safe_headroom`)과 정상 평가
행(인라인 try) 두 경로가 따로 있어 둘 다 잠근다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from nuri.core.db import init_db, query
from nuri.trading.recommend import held_add as ha

MODES = {
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
GRID = {"absolute": [55, 60, 65, 70], "percentiles": [70, 80, 90], "rank_floor": {"percentile": 70, "floor": 60}}
TODAY = date(2026, 5, 4)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "wf.db"
    init_db(path)
    return path


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    cfg = {
        "held_add_mode": {
            "enabled": True,
            "shadow_mode_until": "2099-12-31",
            "earnings_blackout_days": 5,
            "modes": MODES,
            "would_fire_logging": {"enabled": True, "near_band": 5, "grid": GRID},
        }
    }
    p = tmp_path / "buy_signals.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def test_a_failed_headroom_lookup_keeps_every_measurement_row(db_path, cfg_path, monkeypatch):
    """blackout 보유와 평가된 보유 모두 행이 남는다 — headroom 만 NULL 이다."""
    monkeypatch.setattr(
        ha,
        "_get_held_positions",
        lambda db_path=None: [
            {"ticker": "TST_A", "account": "acct_a", "pnl_pct": 60.0, "days_held": 40},
            {"ticker": "TST_B", "account": "acct_a", "pnl_pct": 2.0, "days_held": 40},
        ],
    )
    monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda ticker, max_days=60, db_path=None: 10)
    monkeypatch.setattr(
        ha,
        "_get_account_strategy_profile",
        lambda account: {"stop_loss": -7, "max_single_position": 0.15, "tp1_pct": 20.0},
    )

    def cap_lookup_down(ticker, account, db_path=None):
        raise RuntimeError("cap read failed")

    monkeypatch.setattr(ha, "derive_position_cap", cap_lookup_down)

    def factory(ticker):  # TST_A 만 실적 ±5일 안
        return SimpleNamespace(calendar={"Earnings Date": [date(2026, 5, 6)]} if ticker == "TST_A" else {})

    result = ha.emit_held_add_shadow(
        config_path=cfg_path,
        today=TODAY,
        earnings_fetcher_factory=factory,
        score_provider=lambda t: 10.0,  # 어떤 mode 도 발화하지 않는다 — 판정 쪽 cap 조회까지 가지 않게
        rsi_provider=lambda t: 50.0,
        regime_provider=lambda: ("bull_low_vol", 15.0),
        sector_mom_provider=lambda t: 0.0,
        breakout_above_trim_provider=lambda t: False,
        db_path=db_path,
    )

    assert result.skipped == {"TST_A@acct_a": "earnings blackout ±5d", "TST_B@acct_a": "no mode triggered"}
    rows = {
        r["ticker"]: r
        for r in query(
            "SELECT ticker, earnings_blackout, score, headroom_pct FROM held_add_would_fire", db_path=db_path
        )
    }
    assert rows == {
        "TST_A": {"ticker": "TST_A", "earnings_blackout": 1, "score": None, "headroom_pct": None},
        "TST_B": {"ticker": "TST_B", "earnings_blackout": 0, "score": 10.0, "headroom_pct": None},
    }
