"""Tier 1a — stop-loss breach → #brief (`nuri/alerts/risk_signals.py`).

합성 티커 TST_* 만 사용(privacy: 사용자 실보유/실티커 금지). breach 판정은
가격에서 유도(소스에 signed-% 리터럴 미포함).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from nuri.alerts import risk_signals
from nuri.core.db import init_db, query, upsert_portfolio, upsert_prices


def _seed_price(path, ticker, close):
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "date": "2026-07-08",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                    "adj_close": close,
                }
            ]
        ),
        path,
    )


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "risk.db"
    init_db(path)
    return path


def _seed(path, *, ticker, account, avg, current):
    upsert_portfolio(
        [{"account": account, "ticker": ticker, "quantity": 10, "avg_price": avg, "currency": "USD", "sector": "Tech"}],
        path,
    )
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "date": "2026-07-08",
                    "open": current,
                    "high": current,
                    "low": current,
                    "close": current,
                    "volume": 1_000_000,
                    "adj_close": current,
                }
            ]
        ),
        path,
    )


# ─── scan_stop_breaches ──────────────────────────────────────────────────────


def test_breach_detected_when_below_threshold(db_path, monkeypatch):
    # core stop_loss = -7% → avg 100, current 90 = -10% → breach
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)

    breaches = risk_signals.scan_stop_breaches(db_path=db_path)

    assert len(breaches) == 1
    b = breaches[0]
    assert b["ticker"] == "TST_A"
    assert b["threshold"] == -7
    assert b["pnl_pct"] == pytest.approx(-10.0)


def test_no_breach_when_above_threshold(db_path, monkeypatch):
    # avg 100, current 95 = -5% > -7% → no breach
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=95.0)

    assert risk_signals.scan_stop_breaches(db_path=db_path) == []


def test_pension_account_excluded(db_path, monkeypatch):
    # 깊은 손실이라도 pension 은 daily action 대상 아님 → 제외
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "pension")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -30)
    _seed(db_path, ticker="TST_A", account="Pension Gamma", avg=100.0, current=50.0)

    assert risk_signals.scan_stop_breaches(db_path=db_path) == []


def test_session_filter_kr_vs_us(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=88.0)
    _seed(db_path, ticker="005930.KS", account="Brokerage Alpha", avg=100.0, current=88.0)

    us = risk_signals.scan_stop_breaches(session="us", db_path=db_path)
    kr = risk_signals.scan_stop_breaches(session="kr", db_path=db_path)
    all_ = risk_signals.scan_stop_breaches(db_path=db_path)

    assert [b["ticker"] for b in us] == ["TST_A"]
    assert [b["ticker"] for b in kr] == ["005930.KS"]
    assert len(all_) == 2


def test_missing_price_skipped(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    # 보유만 있고 prices 없음 → current None → skip (KeyError/crash 없이)
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_A",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    assert risk_signals.scan_stop_breaches(db_path=db_path) == []


def test_zero_price_skipped_no_false_breach(db_path, monkeypatch):
    """P1 regression — current==0 (상장폐지/거래정지/불량 price) 은 -100% false
    SELL 을 내면 안 됨. risk_agent 와 동일한 truthiness 가드.
    """
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=0.0)

    assert risk_signals.scan_stop_breaches(db_path=db_path) == []  # -100% false breach 없음


def test_breaches_sorted_worst_first(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)  # -10%
    _seed(db_path, ticker="TST_B", account="Brokerage Alpha", avg=100.0, current=80.0)  # -20%

    breaches = risk_signals.scan_stop_breaches(db_path=db_path)
    assert [b["ticker"] for b in breaches] == ["TST_B", "TST_A"]  # 깊은 손실 우선


# ─── _build_breach_payload ───────────────────────────────────────────────────


def test_payload_shape_is_actionable_sell():
    breach = {
        "ticker": "TST_A",
        "account": "Brokerage Alpha",
        "avg": 100.0,
        "current": 90.0,
        "pnl_pct": -10.0,
        "threshold": -7,
    }
    payload = risk_signals._build_breach_payload(breach, "2026-07-08")

    assert payload["kind"] == "SELL"  # → priority 0 "Action Now"
    assert payload["ticker"] == "TST_A"
    assert payload["note"] == "Brokerage Alpha"  # 다계좌 구분
    assert "손절선 돌파" in payload["reason"]
    # #571: 이미 손절선을 뚫은 포지션에 "entry"(=평단) 를 보여주는 건 방향이 거꾸로다.
    # 지금 필요한 건 진입가가 아니라 현재가와 손실 규모 — price_levels 대신 구조화 필드.
    assert "price_levels" not in payload
    assert payload["current"] == 90.0
    assert payload["avg"] == 100.0


def test_payload_renders_actionable_line():
    # #571 렌더러 계약: producer 가 만든 `summary` 카드가 그대로 나간다.
    # 1줄 종목·경과일 / 2줄 현재가·평단·손실 / 3줄 룰 근거.
    from nuri.agents.discord.outbox import _format_event_line

    breach = {
        "ticker": "TST_A",
        "account": "Brokerage Alpha",
        "avg": 100.0,
        "current": 90.0,
        "pnl_pct": -10.0,
        "threshold": -7,
        "qty": 10.0,
        "loss_amount": -100.0,
        "breach_days": 3,
        "first_breach_date": "2026-07-06",
        "first_breach_pnl_pct": -8.0,
    }
    line = _format_event_line(risk_signals._build_breach_payload(breach, "2026-07-08"))
    lines = line.split("\n")

    assert "TST_A" in lines[0] and "3일째" in lines[0]
    assert "$90" in lines[1] and "$100" in lines[1]  # 현재가와 평단이 모두 보인다
    assert "평가손실" in lines[1]
    assert "-7% 손절" in lines[-1]
    assert any("07-06" in x for x in lines)  # 최초 이탈일 이후 추가 하락 맥락


def test_breach_card_carries_the_numbers_a_decision_needs():
    """8일 연속 같은 줄만 오던 회귀 잠금 — 경과일·평가손실이 빠지면 FAIL.

    사용자 판정: "이것만 보고는 무슨 말을 하고 싶은 것인지 모르겠습니다".
    구 카드에는 현재가·손실액·경과일이 전부 없었다.
    """
    from nuri.agents.discord.outbox import _format_event_line

    breach = {
        "ticker": "TST_A",
        "account": "Brokerage Alpha",
        "avg": 100.0,
        "current": 50.0,
        "pnl_pct": -50.0,
        "threshold": -20,
        "qty": 10.0,
        "loss_amount": -500.0,
        "breach_days": 7,
        "first_breach_date": "2026-07-01",
        "first_breach_pnl_pct": -25.0,
    }
    card = _format_event_line(risk_signals._build_breach_payload(breach, "2026-07-08"))

    assert "7일째" in card  # 며칠째인지
    assert "-$500" in card  # 얼마를 잃고 있는지 (부호는 통화기호 앞)
    assert "-30.0%p" in card  # 이탈폭 (-50 - -20)
    assert "-25.0%p" in card  # 최초 이탈 이후 추가 하락 (-50 - -25)


def test_kosdaq_holding_is_scanned_in_kr_session(db_path, monkeypatch):
    """`.KQ`(KOSDAQ) 가 KR 세션 손절 스캔에서 누락되던 버그 잠금 (#764 split-brain).

    `.KS` 만 필터하면 KOSDAQ 보유분이 KR 세션에서 통째로 빠지고 US 세션에 섞인다.
    """
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="900001.KQ", account="Brokerage Alpha", avg=100.0, current=80.0)

    kr = risk_signals.scan_stop_breaches("kr", db_path=db_path)
    us = risk_signals.scan_stop_breaches("us", db_path=db_path)

    assert [b["ticker"] for b in kr] == ["900001.KQ"]  # KR 세션이 잡는다
    assert us == []  # US 세션에 섞이지 않는다


def test_breach_age_counts_only_the_latest_consecutive_run(db_path):
    """중간에 손절선 위로 회복했으면 그 이전은 세지 않는다."""
    for date, close in [
        ("2026-07-04", 80.0),  # 이탈 (구간 A)
        ("2026-07-05", 95.0),  # 회복 — 여기서 끊긴다
        ("2026-07-06", 85.0),  # 재이탈 (구간 B)
        ("2026-07-07", 84.0),
        ("2026-07-08", 83.0),
    ]:
        upsert_prices(
            pd.DataFrame(
                [
                    {
                        "ticker": "TST_A",
                        "date": date,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "volume": 1_000_000,
                        "adj_close": close,
                    }
                ]
            ),
            db_path,
        )

    age = risk_signals._price_context("TST_A", avg=100.0, threshold=-10, db_path=db_path)

    assert age["breach_days"] == 3  # 07-06 ~ 07-08 만
    assert age["first_breach_date"] == "2026-07-06"


# ─── stage_stop_breach_briefs ────────────────────────────────────────────────


def test_staging_writes_sell_events_to_brief_outbox(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)

    staged = risk_signals.stage_stop_breach_briefs(date="2026-07-08", db_path=db_path)
    assert staged == 1

    rows = query(
        "SELECT channel, priority, dedupe_key, payload_json FROM discord_outbox WHERE channel='brief'",
        db_path=db_path,
    )
    assert len(rows) == 1
    assert rows[0]["priority"] == "high"
    assert rows[0]["dedupe_key"] == "stop-breach:TST_A:Brokerage Alpha:2026-07-08"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["kind"] == "SELL" and payload["ticker"] == "TST_A"


def test_staging_dedupes_same_ticker_same_day(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)

    risk_signals.stage_stop_breach_briefs(date="2026-07-08", db_path=db_path)
    risk_signals.stage_stop_breach_briefs(date="2026-07-08", db_path=db_path)  # 재실행

    rows = query("SELECT COUNT(*) c FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert rows[0]["c"] == 1  # dedupe_key 로 1건만


def test_multi_account_same_ticker_distinct_briefs(db_path, monkeypatch):
    """P2-B — 같은 티커가 두 계좌에서 이탈하면 각각 별개 brief (dedupe 로 collapse
    안 됨). 계좌별 avg 가 달라 entry/stop 도 다르므로 하나로 합치면 안 됨.
    """
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_A",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            },
            {
                "account": "Brokerage Beta",
                "ticker": "TST_A",
                "quantity": 5,
                "avg_price": 120.0,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db_path,
    )
    _seed_price(db_path, "TST_A", 90.0)  # Alpha -10%, Beta -25% — 둘 다 이탈

    assert len(risk_signals.scan_stop_breaches(db_path=db_path)) == 2

    staged = risk_signals.stage_stop_breach_briefs(date="2026-07-08", db_path=db_path)
    assert staged == 2  # collapse 안 됨 + non-None 카운트 정확

    rows = query("SELECT dedupe_key FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert {r["dedupe_key"] for r in rows} == {
        "stop-breach:TST_A:Brokerage Alpha:2026-07-08",
        "stop-breach:TST_A:Brokerage Beta:2026-07-08",
    }


def test_e2e_pension_excluded_via_real_helper(db_path):
    """P2-D — mock 없이 실제 get_account_strategy_name(portfolio.yaml 읽기) 경로로
    pension 제외를 검증. helper 를 monkeypatch 하는 다른 테스트가 못 잡는 통합 갭.
    """
    portfolio_yaml = db_path.parent / "portfolio.yaml"
    portfolio_yaml.write_text(
        yaml.dump(
            {
                "accounts": {
                    "Pension Gamma": {"strategy": "pension"},
                    "Brokerage Alpha": {"strategy": "core"},
                }
            }
        )
    )
    real_open = open

    def mock_open(path, **kwargs):
        if str(path).endswith("portfolio.yaml"):
            return real_open(portfolio_yaml, **kwargs)
        return real_open(path, **kwargs)

    upsert_portfolio(
        [
            {
                "account": "Pension Gamma",
                "ticker": "TST_P",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "ETF",
            },
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_A",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            },
        ],
        db_path,
    )
    _seed_price(db_path, "TST_P", 50.0)  # -50% (pension stop -30 이탈이지만 제외)
    _seed_price(db_path, "TST_A", 90.0)  # -10% (core stop -7 이탈)

    with patch("builtins.open", side_effect=mock_open):
        breaches = risk_signals.scan_stop_breaches(db_path=db_path)

    assert [b["ticker"] for b in breaches] == ["TST_A"]  # pension 제외, core 만


def test_no_breach_stages_nothing(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=99.0)

    assert risk_signals.stage_stop_breach_briefs(date="2026-07-08", db_path=db_path) == 0


# ─── main() CLI ──────────────────────────────────────────────────────────────


def test_cli_dry_run_scans_without_staging(db_path, monkeypatch, capsys):
    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)

    rc = risk_signals.main(["--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "TST_A" in out and "dry-run" in out
    rows = query("SELECT COUNT(*) c FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert rows[0]["c"] == 0  # dry-run → stage 안 함


def test_cli_stages_when_breach_and_not_dry_run(db_path, monkeypatch, capsys):
    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=90.0)

    rc = risk_signals.main([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "staged 1" in out
    rows = query("SELECT COUNT(*) c FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert rows[0]["c"] == 1


def test_cli_no_breach_reports_clean(db_path, monkeypatch, capsys):
    import nuri.core.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Brokerage Alpha", avg=100.0, current=99.0)

    rc = risk_signals.main([])
    assert rc == 0
    assert "없음" in capsys.readouterr().out


# ─── #571 심각도 · 비중 · 추세 ────────────────────────────────────────────────


def _breach(**over):
    b = {
        "ticker": "TST_A",
        "account": "Brokerage Alpha",
        "avg": 100.0,
        "current": 80.0,
        "pnl_pct": -20.0,
        "threshold": -7,
        "qty": 10.0,
        "loss_amount": -200.0,
        "breach_days": 5,
        "first_breach_date": "2026-07-28",
        "first_breach_pnl_pct": -10.0,
    }
    b.update(over)
    return b


def test_severity_marker_separates_deep_from_shallow():
    """카드가 전부 같은 색이면 -1%p 이탈과 -40%p 이탈이 구분되지 않는다.

    사용자 판정: "보고 판단하기 애매하다". 🔴 = 이탈폭이 임계 이하 **또는** 악화 중.
    """
    deep = risk_signals._build_breach_payload(_breach(pnl_pct=-48.0, first_breach_pnl_pct=-40.0), "2026-08-02")
    assert deep["summary"].startswith("🔴")

    # 얕게 이탈(-1.3%p) + 최초 이탈보다 회복 → 경계
    shallow = risk_signals._build_breach_payload(
        _breach(pnl_pct=-8.3, threshold=-7, first_breach_pnl_pct=-8.7), "2026-08-02"
    )
    assert shallow["summary"].startswith("🟠")
    assert "회복 중" in shallow["summary"]


def test_deep_breach_is_severe_even_when_not_worsening():
    """이탈폭이 크면 반등 중이어도 심각으로 본다 — 폭과 방향은 별개 축."""
    p = risk_signals._build_breach_payload(_breach(pnl_pct=-40.0, first_breach_pnl_pct=-45.0), "2026-08-02")
    assert p["summary"].startswith("🔴")
    assert "얕은" not in p["summary"]  # 폭이 큰데 얕다고 말하면 안 된다


def test_card_shows_account_weight_and_trend():
    p = risk_signals._build_breach_payload(
        _breach(weight_pct=8.2, ret_5d=-6.1, ret_20d=-14.3, drawdown_52w=-61.0), "2026-08-02"
    )
    s = p["summary"]
    assert "계좌비중 8.2%" in s
    assert "5일 -6.1%" in s and "20일 -14.3%" in s
    assert "52주고 대비 -61%" in s


def test_weight_omitted_for_mixed_currency_account(db_path, monkeypatch):
    """통화가 섞인 계좌는 환율 없이 합산하면 틀린다 — 비중을 아예 빼야 한다."""
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Mixed", avg=100.0, current=80.0)  # USD
    upsert_portfolio(
        [
            {
                "account": "Mixed",
                "ticker": "005930.KS",
                "quantity": 3,
                "avg_price": 1000.0,
                "currency": "KRW",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    _seed_price(db_path, "005930.KS", 900.0)

    b = risk_signals.scan_stop_breaches(db_path=db_path)

    assert b, "이탈은 잡혀야 한다"
    assert all(x["weight_pct"] is None for x in b), "혼합 통화 계좌는 비중을 계산하면 안 된다"


def test_weight_computed_for_single_currency_account(db_path, monkeypatch):
    monkeypatch.setattr(risk_signals, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(risk_signals, "get_stop_loss_for_account", lambda a: -7)
    _seed(db_path, ticker="TST_A", account="Solo", avg=100.0, current=80.0)  # 10주 × 80 = 800
    upsert_portfolio(
        [
            {
                "account": "Solo",
                "ticker": "TST_B",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    _seed_price(db_path, "TST_B", 120.0)  # 10주 × 120 = 1200 → 총 2000, TST_A 비중 40%

    b = risk_signals.scan_stop_breaches(db_path=db_path)

    assert len(b) == 1 and b[0]["ticker"] == "TST_A"
    assert b[0]["weight_pct"] == pytest.approx(40.0)
