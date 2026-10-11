"""데이터 타당성 점검의 나머지 분기 — 대상 집합 구성 · 4일 동행 프록시 · 남은 pending 카드.

합성 티커 TST_* 만 쓴다 (privacy).
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.alerts import data_sanity as ds
from nuri.core.db import get_db, init_db, query, upsert_prices

CFG = {"lookback_bars": 20, "divergence_1d_pp": 8.0, "divergence_3d_pp": 12.0, "proxy_max_lag_days": 5}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sanity.db"
    init_db(path)
    return path


def _seed_closes(path, ticker, closes):
    """연속 일자 종가 — OHLC 를 close 로 평탄화해 불가능 검사에 안 걸리게."""
    rows = [
        {
            "ticker": ticker,
            "date": f"2026-07-{i + 1:02d}",
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1_000_000,
            "adj_close": c,
        }
        for i, c in enumerate(closes)
    ]
    upsert_prices(pd.DataFrame(rows), path)


def test_scope_takes_secondaries_without_a_primary_and_class_benchmarks_without_a_main_one(monkeypatch):
    """기준 티커가 없는 정책도 보조 티커는 대상이고, 단일 벤치마크가 없어도 자산군별 벤치마크는
    대상이다 — 빈 값이 `"None"` 이라는 티커로 새면 안 된다."""
    monkeypatch.setattr(
        "nuri.core.rules.RULES",
        {
            "freshness_tickers": {
                "metals": {"secondary": ["TST_S1"]},
                "us": {"primary": "TST_P", "secondary": ["TST_S2"]},
            },
            "measurement_mode": {"benchmark_by_asset_class": {"us_equity": "TST_BM", "kr_equity": None}},
        },
    )

    assert ds.scoped_tickers() == ["TST_BM", "TST_P", "TST_S1", "TST_S2"]


def test_a_proxy_moving_with_the_series_for_four_days_is_silent(db_path, monkeypatch):
    """1일·3일 누적 괴리 모두 임계 아래면 발견이 없다 — 4일 겹침이라 3일 누적 검사까지 돈다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_M"])
    monkeypatch.setattr(ds, "_config", lambda: {**CFG, "enabled": True, "proxies": {"TST_M": "TST_MP"}})
    _seed_closes(db_path, "TST_M", [100, 102, 104.04, 106.12])  # 매일 +2%
    _seed_closes(db_path, "TST_MP", [50, 51, 52.02, 53.06])  # 같은 +2%

    assert ds.check_proxy_divergence("TST_M", "TST_MP", CFG, db_path=db_path) is None
    assert ds.scan(db_path=db_path) == []


def test_a_card_still_pending_from_an_earlier_day_is_not_restaged(db_path, monkeypatch):
    """dispatcher 가 멈춰 이틀 전 카드가 아직 pending 이면 재알림 창(1일)은 지났어도 outbox dedupe 가
    막는다 — staged 로 세지 않고 행도 겹치지 않는다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_H"])
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": True, "lookback_bars": 20, "proxies": {}})
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": "TST_H",
                    "date": "2026-07-31",
                    "open": 100,
                    "high": 90,
                    "low": 110,
                    "close": 100,
                    "volume": 1,
                    "adj_close": 100,
                }
            ]
        ),
        db_path,
    )
    assert ds.stage_findings(db_path=db_path) == 1
    with get_db(db_path) as conn:
        conn.execute("UPDATE discord_outbox SET created_at = datetime('now', '-2 days')")  # status 는 pending 그대로

    assert ds.stage_findings(db_path=db_path) == 0
    rows = query(
        "SELECT status FROM discord_outbox WHERE dedupe_key = 'data-sanity:TST_H:impossible_ohlc'", db_path=db_path
    )
    assert rows == [{"status": "pending"}]
