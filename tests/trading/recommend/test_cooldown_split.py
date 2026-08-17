"""#517 Phase 2b — Cooldown SELL-type split lock-tests.

Spec: docs/plans/507_buy_candidate_emitter_phase2_spec.md §3
LLM consult: data/llm_consults/2026-04-30_507-phase2-spec-review.md (codex+Qwen B3 REFINE: 14→21d).

Forward-only event taxonomy:
- payload.action_type ∈ {hard_sell, trim_action, position_reduce, divergence_alert}
- legacy event_type IN (holdings_monitor_alert / take_profit_trigger / trim_recommendation) → fallback_days

각 케이스: emit → cooldown days 안 cooldown set 포함 / 밖 미포함 검증.
"""

from __future__ import annotations

import json

import pytest

from nuri.core.db import get_db, init_db
from nuri.trading.recommend.buy_candidate_emitter import _get_cooldown_tickers_by_type

COOLDOWN_CFG = {
    "hard_sell_days": 21,
    "trim_days": 0,  # re-add 허용
    "reduce_days": 7,
    "divergence_days": 3,
    "fallback_days": 5,
}


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """tmp_path DB + module-level CONFIG_PATH 격리. event 직접 INSERT 로 timestamp 제어."""
    db = tmp_path / "test_cooldown.db"
    init_db(db)
    monkeypatch.setattr(
        "nuri.trading.recommend.buy_candidate_emitter.query_df",
        # `db_path=` 를 받아 무시한다 — 이 스텁은 이미 tmp DB 로 고정돼 있고,
        # 시그니처만 맞추면 된다 (#1078 에서 emitter 가 db_path 를 forward 하기 시작).
        lambda sql, params=None, db_path=None: _run_query_df(db, sql, params),
    )
    yield db


def _run_query_df(db_path, sql, params=None):
    """params 시그니처 호환 — buy_candidate_emitter._get_cooldown_tickers_by_type 가 params= 사용."""
    import pandas as pd

    from nuri.core.db import query_df

    return query_df(sql, params=params or (), db_path=db_path)


def _insert_event(
    db_path,
    *,
    ticker: str,
    action_type: str | None,
    days_ago: int = 0,
    event_type: str = "holdings_monitor_technical_sell",
):
    """직접 INSERT — timestamp 제어. action_type=None 이면 legacy row."""
    payload = {"ticker": ticker}
    if action_type is not None:
        payload["action_type"] = action_type
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (event_type, payload, timestamp) VALUES (?, ?, datetime('now', ?))",
            (event_type, json.dumps(payload), f"-{days_ago} days"),
        )
        conn.commit()


# ─── Case 1: hard_sell (21d) ─────────────────────────────────────────────


def test_hard_sell_within_21d_suppressed(isolated_db):
    """hard_sell 14d ago → cooldown set 포함 (21d 한도 안)."""
    _insert_event(isolated_db, ticker="AAPL", action_type="hard_sell", days_ago=14)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "AAPL" in result


def test_hard_sell_after_21d_released(isolated_db):
    """hard_sell 22d ago → cooldown 해제 (21d 한도 밖)."""
    _insert_event(isolated_db, ticker="AAPL", action_type="hard_sell", days_ago=22)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "AAPL" not in result


# ─── Case 2: trim_action (0d — re-add 허용) ─────────────────────────────


def test_trim_action_zero_days_no_suppression(isolated_db):
    """trim_action 1d ago → cooldown 차단 안 됨 (trim_days=0, 50% 잔여 holding 동안 re-add 허용).

    B1 mitigation: same-session spam 은 holdings_monitor.dedupe_key 가 24h 차단.
    """
    _insert_event(isolated_db, ticker="MSFT", action_type="trim_action", days_ago=1)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "MSFT" not in result


# ─── Case 3: position_reduce (7d) ────────────────────────────────────────


def test_position_reduce_within_7d_suppressed(isolated_db):
    """position_reduce 5d ago → cooldown 포함."""
    _insert_event(isolated_db, ticker="GOOGL", action_type="position_reduce", days_ago=5)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "GOOGL" in result


def test_position_reduce_after_7d_released(isolated_db):
    """position_reduce 8d ago → 해제."""
    _insert_event(isolated_db, ticker="GOOGL", action_type="position_reduce", days_ago=8)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "GOOGL" not in result


# ─── Case 4: divergence_alert (3d) ───────────────────────────────────────


def test_divergence_alert_within_3d_suppressed(isolated_db):
    """divergence_alert 2d ago → cooldown 포함 (3d 한도 안)."""
    _insert_event(isolated_db, ticker="NVDA", action_type="divergence_alert", days_ago=2)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "NVDA" in result


def test_divergence_alert_after_3d_released(isolated_db):
    """divergence_alert 4d ago → 해제 (정보성, 빠른 회복)."""
    _insert_event(isolated_db, ticker="NVDA", action_type="divergence_alert", days_ago=4)
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "NVDA" not in result


# ─── Case 5: legacy event (action_type IS NULL → fallback_days) ─────────


def test_legacy_event_within_fallback_5d_suppressed(isolated_db):
    """legacy holdings_monitor_alert (action_type=NULL) 2d ago → fallback_days=5 cooldown 포함.

    B2 STOP fix — backfill 폐기, 레거시 row 는 보수적 fallback 적용.
    """
    _insert_event(
        isolated_db,
        ticker="TSLA",
        action_type=None,
        days_ago=2,
        event_type="holdings_monitor_alert",
    )
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "TSLA" in result


def test_legacy_event_after_fallback_5d_released(isolated_db):
    """legacy event 6d ago → fallback 5d 한도 밖 해제."""
    _insert_event(
        isolated_db,
        ticker="TSLA",
        action_type=None,
        days_ago=6,
        event_type="holdings_monitor_alert",
    )
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "TSLA" not in result


def test_legacy_take_profit_trigger_fallback(isolated_db):
    """legacy take_profit_trigger (action_type=NULL) 도 fallback 적용."""
    _insert_event(
        isolated_db,
        ticker="META",
        action_type=None,
        days_ago=3,
        event_type="take_profit_trigger",
    )
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert "META" in result


# ─── 혼합 케이스 ──────────────────────────────────────────────────────────


def test_mixed_action_types_all_correctly_classified(isolated_db):
    """다중 ticker × 다중 action_type — 각 cooldown 정책 독립 적용."""
    _insert_event(isolated_db, ticker="AAA", action_type="hard_sell", days_ago=14)  # 21d 안
    _insert_event(isolated_db, ticker="BBB", action_type="trim_action", days_ago=0)  # 0d (release)
    _insert_event(isolated_db, ticker="CCC", action_type="position_reduce", days_ago=5)  # 7d 안
    _insert_event(isolated_db, ticker="DDD", action_type="divergence_alert", days_ago=2)  # 3d 안
    _insert_event(
        isolated_db,
        ticker="EEE",
        action_type=None,
        days_ago=2,
        event_type="holdings_monitor_alert",
    )  # fallback 5d 안
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert result == {"AAA", "CCC", "DDD", "EEE"}, f"Got: {result}"


def test_no_events_empty_set(isolated_db):
    """이벤트 없으면 cooldown set 비어있음."""
    result = _get_cooldown_tickers_by_type(COOLDOWN_CFG)
    assert result == set()


def test_disabled_days_zero_skipped(isolated_db):
    """trim_days=0 같이 days <= 0 인 type 은 SQL query 건너뜀."""
    cfg_no_trim = {**COOLDOWN_CFG, "trim_days": 0}
    _insert_event(isolated_db, ticker="ZZZ", action_type="trim_action", days_ago=0)
    result = _get_cooldown_tickers_by_type(cfg_no_trim)
    assert "ZZZ" not in result
