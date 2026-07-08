"""Tier 1b — 집중도 드리프트 → #brief REBALANCE (`nuri/alerts/portfolio_signals.py`).

합성 티커 TST_* + placeholder 계좌만(privacy). 단위 테스트는 detect_violations 를
mock 하고, 통합 테스트 1건은 실제 detect_violations 경로를 seed 로 검증.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from nuri.alerts import portfolio_signals
from nuri.core.db import init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    # analyze_portfolio()/analyze_sector() 는 db_path 인자 없이 전역 DB_PATH 사용 →
    # monkeypatch 필수 (seeded_db 관례).
    import nuri.core.db as db_mod

    path = tmp_path / "port.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _violation(ticker, account, weight, limit=0.15):
    return {
        "ticker": ticker,
        "account": account,
        "violation_type": "position_limit_exceeded",
        "current_value": weight,
        "limit_value": limit,
        "reason": f"{account} 비중 {weight:.1f}% > 한도 {limit * 100:.0f}%",
    }


# ─── scan_concentration_drift (filter) ───────────────────────────────────────


def test_scan_filters_to_position_only(db_path):
    """손절/섹터/레버리지 위반은 제외, position_limit_exceeded 만."""
    fake = [
        _violation("TST_A", "Brokerage Alpha", 24.4),
        {"ticker": "TST_B", "violation_type": "stop_loss_exceeded", "reason": "손절"},
        {"ticker": "TST_C", "violation_type": "sector_limit_exceeded", "reason": "섹터"},
        {"ticker": "TST_D", "violation_type": "leverage_etf", "reason": "레버리지"},
    ]
    with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=fake):
        out = portfolio_signals.scan_concentration_drift(db_path=db_path)
    assert [v["ticker"] for v in out] == ["TST_A"]  # position only


def test_scan_empty_when_no_violations(db_path):
    with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
        assert portfolio_signals.scan_concentration_drift(db_path=db_path) == []


# ─── _build_rebalance_payload (#429 axis 룰) ──────────────────────────────────


def test_payload_is_rebalance_no_price_levels_no_sell_verb():
    p = portfolio_signals._build_rebalance_payload(_violation("TST_A", "Brokerage Alpha", 24.4), "2026-07-08")
    assert p["kind"] == "REBALANCE"
    assert p["ticker"] == "TST_A"
    assert "price_levels" not in p  # REBALANCE 는 alpha exit 아님 → 가격레벨 금지
    for verb in ("매도", "SELL", "청산"):
        assert verb not in p["reason"]  # #429: 집중도는 urgent SELL 아님
    assert "비중 조절 권고" in p["reason"]
    # privacy: reason 은 numeric 재구성 — account 키(broker name) 미노출
    assert "Brokerage Alpha" not in p["reason"]
    assert "비중 24.4% > 한도 15%" in p["reason"]


def test_pension_account_excluded_from_scan(db_path):
    """pension 계좌 집중도는 REBALANCE 로 안 뜸 (brief 가 pension 을 숨기는 정책과 일치)."""
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations",
        return_value=[
            _violation("TST_A", "pension", 95.0, limit=0.40),  # pension 95% > 40% 이지만 제외
            _violation("TST_B", "Brokerage Alpha", 24.4),
        ],
    ):
        out = portfolio_signals.scan_concentration_drift(db_path=db_path)
    assert [v["ticker"] for v in out] == ["TST_B"]  # pension 제외, 일반 계좌만


def test_payload_renders_lower_priority_bucket():
    """kind=REBALANCE → 렌더러 Lower Priority 버킷 (urgent Action Now 아님)."""
    from nuri.agents.discord.outbox import _classify_event, _format_event_line

    p = portfolio_signals._build_rebalance_payload(_violation("TST_A", "Brokerage Alpha", 24.4), "2026-07-08")
    assert _classify_event(p) == "Lower Priority"  # #429: 비긴급
    line = _format_event_line(p)
    assert line.startswith("TST_A | REBALANCE")
    assert "↳" not in line  # price_levels 라인 없음


# ─── stage_concentration_briefs ──────────────────────────────────────────────


def test_staging_writes_rebalance_events(db_path):
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations", return_value=[_violation("TST_A", "Brokerage Alpha", 24.4)]
    ):
        staged = portfolio_signals.stage_concentration_briefs(date="2026-07-08", db_path=db_path)
    assert staged == 1

    rows = query("SELECT priority, dedupe_key, payload_json FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["priority"] == "normal"  # 손절 high 와 구분
    assert rows[0]["dedupe_key"] == "rebalance:position:TST_A:Brokerage Alpha:2026-07-08"
    assert json.loads(rows[0]["payload_json"])["kind"] == "REBALANCE"


def test_staging_dedupes_same_ticker_account_day(db_path):
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations", return_value=[_violation("TST_A", "Brokerage Alpha", 24.4)]
    ):
        portfolio_signals.stage_concentration_briefs(date="2026-07-08", db_path=db_path)
        portfolio_signals.stage_concentration_briefs(date="2026-07-08", db_path=db_path)  # 재실행
    rows = query("SELECT COUNT(*) c FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert rows[0]["c"] == 1


def test_staging_multi_account_same_ticker_distinct(db_path):
    """같은 티커가 두 계좌에서 집중되면 각각 별개 REBALANCE (account-scoped dedupe)."""
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations",
        return_value=[
            _violation("TST_A", "Brokerage Alpha", 24.4),
            _violation("TST_A", "Brokerage Beta", 18.0),
        ],
    ):
        staged = portfolio_signals.stage_concentration_briefs(date="2026-07-08", db_path=db_path)
    assert staged == 2
    rows = query("SELECT dedupe_key FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert {r["dedupe_key"] for r in rows} == {
        "rebalance:position:TST_A:Brokerage Alpha:2026-07-08",
        "rebalance:position:TST_A:Brokerage Beta:2026-07-08",
    }


def test_no_breach_stages_nothing(db_path):
    with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
        assert portfolio_signals.stage_concentration_briefs(date="2026-07-08", db_path=db_path) == 0


# ─── 통합 — 실제 detect_violations (mock 없이) ────────────────────────────────


def test_integration_real_detect_violations_finds_concentration(db_path):
    """rebalance_advisor.detect_violations 실경로 + 신규 account 필드 노출 검증."""
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_A",
                "quantity": 90,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            },
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_B",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Energy",
            },
        ],
        db_path,
    )
    rows = []
    for t in ("TST_A", "TST_B"):
        rows.append(
            {
                "ticker": t,
                "date": today_kst(),
                "open": 100,
                "high": 100,
                "low": 100,
                "close": 100,
                "volume": 1_000_000,
                "adj_close": 100,
            }
        )
    upsert_prices(pd.DataFrame(rows), db_path)
    # analyze_portfolio 이 get_exchange_rate() 호출 → usd_krw 신선(today 앵커) 필요
    upsert_macro([{"indicator": "usd_krw", "date": today_kst(), "value": 1380.0, "source": "test"}], db_path)

    drifts = portfolio_signals.scan_concentration_drift(db_path=db_path)
    tickers = [v["ticker"] for v in drifts]
    assert "TST_A" in tickers  # 90% > core 15%
    assert "TST_B" not in tickers  # 10% < 15%
    # 신규 account 필드 (dedupe 용) 노출 확인
    assert drifts[0]["account"] == "Brokerage Alpha"


# ─── main() CLI ──────────────────────────────────────────────────────────────


def test_cli_dry_run(db_path, capsys):
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations", return_value=[_violation("TST_A", "Brokerage Alpha", 24.4)]
    ):
        rc = portfolio_signals.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TST_A" in out and "dry-run" in out
    rows = query("SELECT COUNT(*) c FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert rows[0]["c"] == 0  # dry-run → stage 안 함


def test_cli_stages_when_not_dry_run(db_path, capsys):
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations", return_value=[_violation("TST_A", "Brokerage Alpha", 24.4)]
    ):
        rc = portfolio_signals.main([])
    out = capsys.readouterr().out
    assert rc == 0 and "staged 1" in out


def test_cli_no_breach(db_path, capsys):
    with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
        rc = portfolio_signals.main([])
    assert rc == 0 and "없음" in capsys.readouterr().out
