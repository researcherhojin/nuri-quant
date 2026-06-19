"""Lock-tests for #507 BUY candidate emitter (Phase 1).

가드: 향후 sell-bias 회귀 방지. 각 gate / score path / blocked reason 별 1+ test.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from nuri.core.db import get_db, init_db, upsert_portfolio, upsert_prices
from nuri.core.timezone import today_kst
from nuri.trading.recommend.buy_candidate_emitter import (
    LEVERAGE_ETFS,
    BuyCandidate,
    EmitResult,
    _build_why_now,
    _load_config,
    _score_ticker,
    emit_buy_candidates,
    render_markdown,
)

# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def cfg_path(tmp_path):
    """Minimal buy_signals.yaml override for deterministic tests."""
    cfg = {
        "exclude_held": True,
        "exclude_etf_leverage": True,
        "weights": {
            "factor_composite": 0.4,
            "momentum_5d": 0.25,
            "technical_rsi": 0.15,
            "breakout_30d": 0.2,
        },
        "quality_bar": {
            "base_threshold": 70,
            "max_candidates": 5,
            "per_regime": {"neutral": 0, "bull": -5, "sideways_high_vol": 999},
        },
        "gates": {"vix_block_above": 30, "vix_caution_above": 25, "cooldown_days": 5},
        "allocation": {
            "total_pct_by_regime": {"neutral": 0.30, "bull": 0.50},
        },
        # 의도적 non-canonical (21/42): emitter 가 config 를 읽음(하드코딩 아님)을 증명.
        # 실제 출하 config 의 canonical(20/40) 정합은
        # test_buy_emitter_tp_ladder_matches_canonical_growth 가 별도로 lock.
        "risk": {"stop_pct": -7.0, "tp1_pct": 21.0, "tp2_pct": 42.0},
    }
    p = tmp_path / "buy_signals.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def _seed_factor(db_path, ticker: str, composite: float):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO factors (ticker, date, momentum_score, value_score, "
            "quality_score, sentiment_score, composite_score) "
            "VALUES (?, '2026-04-30', 0.5, 0.5, 0.5, 0.5, ?)",
            (ticker, composite),
        )


def _seed_prices(db_path, ticker: str, closes: list[float]):
    """Backfill ~45 trading days ending today.

    end 를 today 로 고정(상대일)해야 emitter 의 ``date('now', '-45 days')``
    윈도우 안에 들어온다. 고정 절대일로 두면 시간이 흐를수록 윈도우 밖으로
    밀려 ``len(grp) < 6`` 으로 skip → scored=0 회귀 (time-bomb).
    """
    dates = pd.bdate_range(end=today_kst(), periods=len(closes))
    df = pd.DataFrame(
        {
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "adj_close": closes,
        }
    )
    upsert_prices(df, db_path)


def _seed_rsi(db_path, ticker: str, rsi: float):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO signals (ticker, date, rsi_14) VALUES (?, '2026-04-30', ?)",
            (ticker, rsi),
        )


def _seed_vix(db_path, value: float):
    """Seed VIX into macro (emitter reads indicator='vix' from macro — #753)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2026-04-30', ?, 'test')",
            (value,),
        )


def _seed_regime(db_path, regime: str):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) "
            "VALUES ('2026-04-30', 'unknown', ?, 'test')",
            (regime,),
        )


# --- Score / why-now ------------------------------------------------------


def test_score_ticker_high_factor():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    score, src = _score_ticker("X", {"composite": 0.9}, {"ret_5d": 5, "breakout_pct": 1}, 50, weights)
    assert 70 <= score <= 100
    assert src["factor"] == 90.0


def test_score_ticker_overbought_rsi_penalty():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, 88, weights)
    assert src["rsi"] < 30


def test_score_ticker_oversold_rsi_bonus():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, 28, weights)
    assert src["rsi"] == 60.0


def test_score_ticker_missing_rsi_neutral():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, None, weights)
    assert src["rsi"] == 50.0


def test_why_now_picks_strongest_source():
    msg = _build_why_now({"factor": 90, "momentum": 60, "rsi": 50, "breakout": 40}, {}, 50)
    assert "factor" in msg.lower() or "composite" in msg.lower()


def test_why_now_momentum():
    msg = _build_why_now(
        {"factor": 50, "momentum": 90, "rsi": 50, "breakout": 50},
        {"ret_5d": 12.5},
        50,
    )
    assert "12.5" in msg or "모멘텀" in msg


# --- Gate: VIX --------------------------------------------------------------


def test_vix_block_above_30(db, cfg_path):
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 35.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert res.blocked_reason is not None
    assert "VIX" in res.blocked_reason


def test_vix_gate_reads_macro_not_prices(db, cfg_path):
    """#753 회귀: VIX 는 macro 테이블에서 읽어야 한다 (prices.VIX 는 미수집).

    macro(indicator='vix') 에만 block 임계 초과 VIX 를 seed 하고 prices.VIX 는
    의도적으로 비운다. emitter 가 prices 경로(버그)로 되돌아가면 macro VIX 를
    무시해 vix=20.0 fallback → 차단 미발화 → FAIL.
    """
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_regime(db, "neutral")
    with get_db(db) as conn:
        conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2026-04-30', 35.0, 'test')")
        # prices.VIX 행이 없음을 명시 (버그 mask 방지 가드)
        assert conn.execute("SELECT COUNT(*) FROM prices WHERE ticker='VIX'").fetchone()[0] == 0

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert res.blocked_reason is not None
    assert "VIX" in res.blocked_reason
    assert res.vix == pytest.approx(35.0)


def test_vix_caution_halves_allocation(db, cfg_path):
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 25 + [120.0, 121.0, 122.0, 123.0, 124.0, 125.0])
    _seed_rsi(db, "AAPL", 55)
    _seed_vix(db, 27.0)  # between caution(25) and block(30)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, f"expected candidate, blocked_reason={res.blocked_reason}"
    # neutral=30%, halved to 15%
    assert res.total_deploy_pct == pytest.approx(15.0, abs=0.5)


# --- Gate: regime ----------------------------------------------------------


@pytest.mark.parametrize("regime", ["bear", "crash", "extreme_fear"])
def test_regime_blocks_new_buy(db, cfg_path, regime):
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 20.0)
    _seed_regime(db, regime)

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert regime in (res.blocked_reason or "")


def test_regime_threshold_999_blocked(db, cfg_path):
    """sideways_high_vol regime → per_regime adj 999 → effective block."""
    _seed_factor(db, "AAPL", 0.99)
    _seed_prices(db, "AAPL", [100.0] * 30 + [200.0])
    _seed_vix(db, 20.0)
    _seed_regime(db, "sideways_high_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "999" in (res.blocked_reason or "") or "차단" in (res.blocked_reason or "")


# --- Gate: held / cooldown / leverage --------------------------------------


def test_held_ticker_skipped(db, cfg_path):
    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db,
    )
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 30 + [200.0])
    _seed_rsi(db, "AAPL", 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert "AAPL" in res.skipped
    assert "held" in res.skipped["AAPL"].lower()


def test_cooldown_ticker_skipped(db, cfg_path):
    _seed_factor(db, "MSFT", 0.95)
    _seed_prices(db, "MSFT", [100.0] * 30 + [200.0])
    _seed_rsi(db, "MSFT", 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (timestamp, event_type, payload) "
            "VALUES (datetime('now', '-1 days'), 'holdings_monitor_alert', '{\"ticker\": \"MSFT\"}')"
        )

    res = emit_buy_candidates(config_path=cfg_path)
    assert "MSFT" in res.skipped
    assert "cooldown" in res.skipped["MSFT"].lower()


@pytest.mark.parametrize("etf", ["SOXL", "TQQQ", "TSLL", "LABU"])
def test_leverage_etf_skipped(db, cfg_path, etf):
    assert etf in LEVERAGE_ETFS
    _seed_factor(db, etf, 0.95)
    _seed_prices(db, etf, [100.0] * 30 + [200.0])
    _seed_rsi(db, etf, 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert etf in res.skipped
    assert "leverage" in res.skipped[etf].lower()


# --- Empty data path -------------------------------------------------------


def test_empty_factors_blocked(db, cfg_path):
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "factors" in (res.blocked_reason or "")


def test_below_threshold_blocked(db, cfg_path):
    _seed_factor(db, "WEAK", 0.30)
    _seed_prices(db, "WEAK", [100.0] * 30 + [99.0])  # flat
    _seed_rsi(db, "WEAK", 50)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "threshold" in (res.blocked_reason or "")


# --- Happy path: emit + risk levels ----------------------------------------


def test_emit_above_threshold(db, cfg_path):
    _seed_factor(db, "STRONG", 0.95)
    _seed_prices(db, "STRONG", [100.0] * 25 + [110.0, 115.0, 120.0, 125.0, 130.0, 135.0])
    _seed_rsi(db, "STRONG", 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c.ticker == "STRONG"
    assert c.score >= 70
    # entry≈135, stop=-7%, tp1=+21%, tp2=+42%
    assert c.stop == pytest.approx(c.entry * 0.93, abs=0.5)
    assert c.tp1 == pytest.approx(c.entry * 1.21, abs=0.5)
    assert c.tp2 == pytest.approx(c.entry * 1.42, abs=0.5)


def test_allocation_split_by_score(db, cfg_path):
    _seed_factor(db, "S1", 0.95)
    _seed_factor(db, "S2", 0.85)
    for t in ("S1", "S2"):
        _seed_prices(db, t, [100.0] * 25 + [110, 115, 120, 125, 130, 135])
        _seed_rsi(db, t, 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    res = emit_buy_candidates(config_path=cfg_path)
    assert len(res.candidates) == 2
    deploy_sum = sum(c.deploy_pct for c in res.candidates)
    # neutral=30%, no caution → total 30%
    assert deploy_sum == pytest.approx(30.0, abs=0.5)
    # higher score gets larger deploy
    sorted_by_score = sorted(res.candidates, key=lambda c: c.score, reverse=True)
    assert sorted_by_score[0].deploy_pct >= sorted_by_score[1].deploy_pct


# --- Render markdown -------------------------------------------------------


def test_render_blocked():
    r = EmitResult(blocked_reason="VIX 35.0 > 30", regime="neutral", vix=35.0)
    md = render_markdown(r)
    assert "BUY Candidates (0 — blocked)" in md
    assert "VIX 35.0 > 30" in md


def test_render_with_candidates():
    r = EmitResult(
        candidates=[
            BuyCandidate(
                ticker="MSFT",
                score=82,
                deploy_pct=20.0,
                entry=400.0,
                stop=372.0,
                tp1=484.0,
                tp2=568.0,
                why_now="Multi-factor 상위",
                sources={"factor": 90},
            )
        ],
        regime="neutral",
        vix=20.0,
        total_deploy_pct=20.0,
        timestamp_kst="2026-04-30 02:00:00 KST",
    )
    md = render_markdown(r)
    assert "MSFT" in md
    assert "82/100" in md
    assert "Entry $400.0" in md
    assert "Stop $372.0" in md
    assert "Multi-factor 상위" in md


def test_render_markdown_tp_label_derived_from_price():
    """라벨의 %는 가격에서 파생되어야 한다 (하드코딩 literal 금지).

    과거 render_markdown 이 (-7%)/(+21%)/(+42%) 를 하드코딩해, 값을 20/40 으로
    바꾼 뒤에도 brief 라벨은 +21/+42 로 표시되는 모순이 있었다 (codex P2).
    entry=100, stop=93, tp1=120, tp2=140 → 라벨 -7% / +20% / +40%.
    """
    r = EmitResult(
        candidates=[
            BuyCandidate(
                ticker="ZZZ",
                score=80,
                deploy_pct=10.0,
                entry=100.0,
                stop=93.0,
                tp1=120.0,
                tp2=140.0,
                why_now="x",
                sources={"factor": 90},
            )
        ],
        regime="neutral",
        vix=20.0,
        total_deploy_pct=10.0,
        timestamp_kst="2026-04-30 02:00:00 KST",
    )
    md = render_markdown(r)
    assert "(-7%)" in md
    assert "(+20%)" in md
    assert "(+40%)" in md
    # 옛 하드코딩 회귀 방지
    assert "(+21%)" not in md and "(+42%)" not in md


# --- Config load -----------------------------------------------------------


def test_load_config_defaults():
    cfg = _load_config()  # uses package CONFIG_PATH
    assert "weights" in cfg
    assert "gates" in cfg
    assert "risk" in cfg
    assert cfg["gates"]["vix_block_above"] == 30


def test_emit_result_dataclass_defaults():
    r = EmitResult()
    assert r.candidates == []
    assert r.skipped == {}
    assert r.blocked_reason is None


# --- Brief integration sanity (#507 → premarket_brief) --------------------


def test_brief_surfaces_buy_candidates(db, cfg_path):
    """premarket_brief._collect_context() must surface emitter output."""
    _seed_factor(db, "STRONG", 0.95)
    _seed_prices(db, "STRONG", [100.0] * 25 + [110, 115, 120, 125, 130, 135])
    _seed_rsi(db, "STRONG", 55)
    _seed_vix(db, 20.0)
    _seed_regime(db, "neutral")

    # emitter reads CONFIG_PATH, not config_path arg in _collect_context.
    # Patch CONFIG_PATH so the brief picks up our test config.
    import nuri.trading.recommend.buy_candidate_emitter as emitter_mod

    with patch.object(emitter_mod, "CONFIG_PATH", cfg_path):
        from nuri.alerts.premarket_brief import _collect_context

        ctx = _collect_context()

    bc = ctx.get("buy_candidates")
    assert bc is not None, "buy_candidates ctx key missing — brief integration broken"
    # 1 emitted (STRONG only) — others non-existent in fresh DB
    assert any(c.ticker == "STRONG" for c in bc.candidates) or bc.blocked_reason


def test_buy_emitter_tp_ladder_matches_canonical_growth():
    """SSoT lock: BUY emitter 출하 config 의 TP 사다리는 rules.yaml
    take_profit.growth (canonical 20/40) 와 일치해야 한다.

    buy_signals.yaml 가 canonical 에서 다시 fork (예: 21/42) 하면 실패한다.
    근거: brief(+21%) vs /targets(+20%) 운영자-facing 모순 회귀 방지
    (recommend/CLAUDE.md "price_targets.py canonical — caller 재유도 금지").
    """
    from nuri.core.rules import TAKE_PROFIT_GROWTH

    risk = _load_config().get("risk", {})  # 실제 config/buy_signals.yaml 로드
    assert risk["tp1_pct"] == TAKE_PROFIT_GROWTH["target_1"], (
        f"buy_signals tp1_pct={risk.get('tp1_pct')} != canonical "
        f"{TAKE_PROFIT_GROWTH['target_1']} (rules.yaml take_profit.growth)"
    )
    assert risk["tp2_pct"] == TAKE_PROFIT_GROWTH["target_2"], (
        f"buy_signals tp2_pct={risk.get('tp2_pct')} != canonical "
        f"{TAKE_PROFIT_GROWTH['target_2']} (rules.yaml take_profit.growth)"
    )
