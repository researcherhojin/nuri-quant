"""Lock-tests for P0 stale-data audit fixes (#507 audit 2026-04-30).

가드 — sell-bias 감사 결과 발견된 3개의 stale broker state 누설 경로:
1. tracker.save_recommendations: SELL on 0-qty ticker 차단
2. freshness.py: portfolio policy (24h warn / 72h fail)
3. actions._get_recommendations: API surface 에서 0-qty SELL 필터

각 fix 가 revert 되면 fail. 사용자 4월 ₩3.25M 손실 root cause guard.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nuri.core.db import (
    get_db,
    init_db,
    upsert_macro,
    upsert_portfolio,
    upsert_prices,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# --- 1. tracker.save_recommendations: SELL on 0-qty 차단 ----------------


@dataclass
class _MockAction:
    ticker: str
    action: str
    signals: list
    regime_note: str = ""


@dataclass
class _MockCandidate:
    ticker: str
    direction: str = "SELL"
    confidence: float = 80.0
    signal_id: str = "test"
    price: float = 100.0
    regime_fit: bool = True
    scoring_detail: dict | None = None
    tier: str = "actionable"


def test_save_recommendations_skips_sell_on_zero_qty_action(db):
    """E-2 rebalance SELL on 0-qty 차단."""
    from nuri.trading.recommend.tracker import save_recommendations

    upsert_portfolio(
        [
            {
                "account": "main",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db,
    )
    # Seed price for both
    import pandas as pd

    df = pd.DataFrame(
        {
            "ticker": ["AAPL", "GOOGL"],
            "date": ["2026-04-30"] * 2,
            "open": [100, 200],
            "high": [101, 201],
            "low": [99, 199],
            "close": [100, 200],
            "volume": [1000, 1000],
            "adj_close": [100, 200],
        }
    )
    upsert_prices(df, db)

    actions = [
        _MockAction("AAPL", "SELL", ["sig"]),  # held → persist
        _MockAction("GOOGL", "SELL", ["sig"]),  # not held → skip
        _MockAction("GOOGL", "BUY", ["sig"]),  # not held BUY → persist (universe scan)
    ]
    n = save_recommendations(actions=actions, db_path=db)
    assert n == 2
    with get_db(db) as conn:
        rows = list(conn.execute("SELECT ticker, action FROM recommendations ORDER BY ticker"))
    tickers = [(r[0], r[1]) for r in rows]
    assert ("AAPL", "SELL") in tickers
    assert ("GOOGL", "BUY") in tickers
    assert ("GOOGL", "SELL") not in tickers


def test_save_recommendations_skips_sell_on_zero_qty_candidate(db):
    """E-1 candidate SELL on 0-qty 차단."""
    from nuri.trading.recommend.tracker import save_recommendations

    upsert_portfolio(
        [
            {
                "account": "main",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db,
    )
    candidates = [
        _MockCandidate(ticker="AAPL", direction="SELL"),  # held → persist
        _MockCandidate(ticker="GOOGL", direction="SELL"),  # not held → skip
        _MockCandidate(ticker="GOOGL", direction="BUY"),  # not held BUY → persist
    ]
    n = save_recommendations(candidates=candidates, db_path=db)
    assert n == 2


def test_save_recommendations_zero_qty_row_treated_as_not_held(db):
    """portfolio.quantity == 0 인 row 는 held 아님 — DELETE 안 한 stale row 도 차단."""
    from nuri.trading.recommend.tracker import save_recommendations

    # qty=0 row 를 DB 에 직접 insert (replace_portfolio_account 가 정리 안 한 상황)
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES ('main', 'GOOGL', 0, 200.0, 'USD', 'Tech')"
        )
    actions = [_MockAction("GOOGL", "TRIM", ["sig"])]
    n = save_recommendations(actions=actions, db_path=db)
    assert n == 0


def test_save_recommendations_buy_unaffected_by_filter(db):
    """BUY action 은 universe scan 이므로 0-qty 필터 우회."""
    from nuri.trading.recommend.tracker import save_recommendations

    candidates = [_MockCandidate(ticker="NEWCO", direction="BUY")]
    n = save_recommendations(candidates=candidates, db_path=db)
    assert n == 1


# --- 2. freshness.py: portfolio policy ----------------------------------


def test_freshness_policies_includes_portfolio():
    """audit P0 #2: portfolio key 가 FRESHNESS_POLICIES 에 등록되어야 함."""
    from nuri.core.freshness import FRESHNESS_POLICIES

    assert "portfolio" in FRESHNESS_POLICIES
    p = FRESHNESS_POLICIES["portfolio"]
    assert p["warn_hours"] == 24
    assert p["fail_hours"] == 72
    assert "포트폴리오" in p["label"]


def test_freshness_portfolio_pass_when_fresh(db):
    """portfolio.updated_at < 24h → PASS."""
    from nuri.core.freshness import check_freshness

    upsert_portfolio(
        [
            {"account": "main", "ticker": "AAPL", "quantity": 1, "avg_price": 100, "currency": "USD", "sector": "Tech"},
        ],
        db,
    )
    res = check_freshness("portfolio", db_path=db)
    assert res["status"] == "PASS"
    assert res["age_hours"] is not None and res["age_hours"] < 24


def test_freshness_portfolio_fail_when_no_data(db):
    """portfolio 비어있음 → FAIL (사용자 sync 필요 surface)."""
    from nuri.core.freshness import check_freshness

    res = check_freshness("portfolio", db_path=db)
    assert res["status"] == "FAIL"


def test_freshness_summary_includes_portfolio(db):
    """get_freshness_summary 가 portfolio 도 surface 해야 함."""
    from nuri.core.freshness import check_all_freshness

    # Seed enough data so summary doesn't crash
    upsert_portfolio(
        [
            {"account": "main", "ticker": "AAPL", "quantity": 1, "avg_price": 100, "currency": "USD", "sector": "Tech"},
        ],
        db,
    )
    upsert_macro(
        [
            {"indicator": "vix", "date": "2026-04-30", "value": 20.0, "source": "test"},
        ],
        db,
    )
    details = check_all_freshness(db_path=db)
    keys = [d["key"] for d in details]
    assert "portfolio" in keys


# --- 3. actions._get_recommendations: API surface filter -----------------


def test_get_recommendations_filters_sell_on_zero_qty(db):
    """API 가 stale SELL 을 dashboard 에 surface 하지 않아야 함.

    tracker write-side filter 만으로는 부족 — 이미 persist 된 row 가 있을 수 있고
    legacy/future writer 가 우회할 수 있음. read-side dual guard.
    """
    from nuri.api.routes.actions import _get_recommendations

    upsert_portfolio(
        [
            {
                "account": "main",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db,
    )
    # Direct DB write to simulate stale row (writer 우회)
    with get_db(db) as conn:
        for ticker, action in [("AAPL", "SELL"), ("GOOGL", "SELL"), ("MSFT", "BUY")]:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES ('2026-04-30', ?, ?, 80.0)",
                (ticker, action),
            )

    import nuri.api.routes.actions as actions_mod
    import nuri.core.db as db_mod

    # actions._get_recommendations 는 default DB_PATH 를 사용 — monkeypatch 필요
    db_mod.DB_PATH = db
    actions_mod.query  # noqa: B018  — sanity ref
    results = _get_recommendations()

    tickers_actions = {(r["ticker"], r["action"]) for r in results}
    assert ("AAPL", "SELL") in tickers_actions
    assert ("MSFT", "BUY") in tickers_actions
    assert ("GOOGL", "SELL") not in tickers_actions, "stale SELL 누설"


# --- 4. #514 (Session 8): HOLD 도 portfolio JOIN filter ----------------


def test_get_recommendations_filters_hold_on_zero_qty(db):
    """0주 ticker 의 stale HOLD recommendation 도 surface 차단 (#514).

    원인: 4-18 매도된 TSM 의 4-30 latest HOLD conf 80 row 가 brief Hold 섹션에 surface.
    수정: SELL/TRIM/REDUCE 와 동일 패턴으로 HOLD 도 portfolio JOIN filter 적용.
    BUY 는 비보유 ticker 도 valid emit 이므로 filter 제외.
    """
    from nuri.api.routes.actions import _get_recommendations

    upsert_portfolio(
        [
            {
                "account": "main",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db,
    )
    # Direct DB write — stale HOLD on non-held ticker (TSM 4-18 매도 시뮬레이션)
    with get_db(db) as conn:
        for ticker, action in [
            ("AAPL", "HOLD"),  # held → surface
            ("TSM", "HOLD"),  # 0주 → 차단되어야 함
            ("MSFT", "BUY"),  # 비보유 BUY → surface 유지 (BUY 는 valid)
        ]:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES ('2026-04-30', ?, ?, 80.0)",
                (ticker, action),
            )

    import nuri.core.db as db_mod

    db_mod.DB_PATH = db
    results = _get_recommendations()

    tickers_actions = {(r["ticker"], r["action"]) for r in results}
    assert ("AAPL", "HOLD") in tickers_actions, "held HOLD 누락"
    assert ("MSFT", "BUY") in tickers_actions, "비보유 BUY 누락 (BUY 는 filter 제외)"
    assert ("TSM", "HOLD") not in tickers_actions, "stale HOLD 누설 (#514 fix)"
