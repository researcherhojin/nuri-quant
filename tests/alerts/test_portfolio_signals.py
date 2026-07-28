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


# ─── Tier 1c: scan_sector_drift ──────────────────────────────────────────────


def _sector_violation(ticker, sector, weight, limit=0.35):
    return {
        "ticker": ticker,
        "sector": sector,
        "violation_type": "sector_limit_exceeded",
        "current_value": weight,
        "limit_value": limit,
        "reason": f"섹터({sector}) 비중 {weight:.1f}% > 한도 {limit * 100:.0f}%",
    }


def test_scan_sector_filters_and_dedups_by_sector(db_path):
    """sector_limit_exceeded 만 + 섹터당 1건 (종목당 나오는 것 collapse)."""
    fake = [
        _violation("TST_A", "Brokerage Alpha", 24.4),  # position — 제외
        _sector_violation("TST_B", "Semiconductor", 45.0),
        _sector_violation("TST_C", "Semiconductor", 45.0),  # 같은 섹터 → dedup
        _sector_violation("TST_D", "Energy", 40.0),
    ]
    with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=fake):
        out = portfolio_signals.scan_sector_drift(db_path=db_path)
    assert [v["sector"] for v in out] == ["Semiconductor", "Energy"]  # 섹터당 1건


def test_sector_payload_is_rebalance_ticker_is_sector(db_path):
    p = portfolio_signals._build_sector_rebalance_payload(
        _sector_violation("TST_B", "Semiconductor", 45.0), "2026-07-08"
    )
    assert p["kind"] == "REBALANCE"
    assert p["ticker"] == "Semiconductor"  # ticker 슬롯 = 섹터명
    assert "price_levels" not in p
    for verb in ("매도", "SELL", "청산"):
        assert verb not in p["reason"]
    assert "섹터 비중 45.0% > 한도 35%" in p["reason"]


def test_sector_staging_and_dedupe(db_path):
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations",
        return_value=[_sector_violation("TST_B", "Semiconductor", 45.0)],
    ):
        s1 = portfolio_signals.stage_sector_briefs(date="2026-07-08", db_path=db_path)
        s2 = portfolio_signals.stage_sector_briefs(date="2026-07-08", db_path=db_path)  # 재실행
    assert s1 == 1 and s2 == 0  # dedupe
    rows = query("SELECT dedupe_key, priority FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == "rebalance:sector:Semiconductor:2026-07-08"
    assert rows[0]["priority"] == "normal"


def test_integration_real_detect_violations_sector(db_path):
    """실 detect_violations 로 섹터 초과 검출 + 신규 sector 필드 노출."""
    # 한 계좌에 같은 섹터 3종목 = 섹터 100% > 35% (계좌 집중은 각 <15% 로 회피)
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": f"TST_{i}",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Semiconductor",
            }
            for i in range(8)
        ],
        db_path,
    )
    rows = [
        {
            "ticker": f"TST_{i}",
            "date": today_kst(),
            "open": 100,
            "high": 100,
            "low": 100,
            "close": 100,
            "volume": 1_000_000,
            "adj_close": 100,
        }
        for i in range(8)
    ]
    upsert_prices(pd.DataFrame(rows), db_path)
    upsert_macro([{"indicator": "usd_krw", "date": today_kst(), "value": 1380.0, "source": "test"}], db_path)

    drifts = portfolio_signals.scan_sector_drift(db_path=db_path)
    assert any(v["sector"] == "Semiconductor" for v in drifts)  # 100% > 35%
    assert drifts[0]["sector"] == "Semiconductor"  # 신규 필드 노출


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


def test_cli_shows_concentration_and_sector(db_path, capsys):
    """main() 이 집중도 + 섹터 둘 다 표시 + stage."""
    with patch(
        "nuri.analysis.rebalance_advisor.detect_violations",
        return_value=[
            _violation("TST_A", "Brokerage Alpha", 24.4),
            _sector_violation("TST_B", "Semiconductor", 45.0),
        ],
    ):
        rc = portfolio_signals.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[집중도] TST_A" in out and "[섹터] Semiconductor" in out
    assert "staged 2" in out  # 집중도 1 + 섹터 1


# ═══════════════════════════════════════════════════════
# Tier 1d — §3.11 실험 슬리브 상한 (#834)
# ═══════════════════════════════════════════════════════


def _sleeve_row(strategy="core", used=25.0, cap=10.0, account="Brokerage Alpha"):
    return {
        "account": account,
        "strategy": strategy,
        "cap_pct": cap,
        "sleeve_usd": 2500.0,
        "equity_usd": 10_000.0,
        "used_pct": used,
        "over": used > cap,
    }


def test_sleeve_scan_keeps_only_over_cap(db_path):
    rows = [_sleeve_row(used=25.0), _sleeve_row(strategy="active", used=5.0, cap=20.0, account="Brokerage Beta")]
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=rows):
        got = portfolio_signals.scan_sleeve_breach(db_path=db_path)
    assert [r["strategy"] for r in got] == ["core"]


def test_sleeve_scan_does_not_exclude_pension(db_path):
    """1b/1c 와 달리 pension 을 감추지 않는다 — 상한 0 위반은 사전등록 위반이다.

    Gotcha-Test Pair: `_is_pension_account` 필터를 1b/1c 처럼 복사해 넣으면 FAIL.
    """
    rows = [_sleeve_row(strategy="pension", used=3.0, cap=0.0, account="연금저축")]
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=rows):
        got = portfolio_signals.scan_sleeve_breach(db_path=db_path)
    assert len(got) == 1, "pension 슬리브 침범이 조용히 사라짐"


def test_sleeve_payload_is_rebalance_without_sell_verb_or_price_levels():
    """#429 축 — 슬리브 초과는 REBALANCE 만. 매도 동사·price_levels 금지.

    Gotcha-Test Pair: kind 를 SELL 로 바꾸거나 price_levels 를 붙이면 FAIL.
    """
    payload = portfolio_signals._build_sleeve_rebalance_payload(_sleeve_row(), "2026-07-08")
    assert payload["kind"] == "REBALANCE"
    assert "price_levels" not in payload
    for verb in ("매도", "청산", "손절", "SELL"):
        assert verb not in payload["reason"], f"REBALANCE payload 에 매도 동사({verb})"


def test_sleeve_payload_hides_account_name(db_path):
    """계좌 키(broker name)는 사용자 노출 텍스트에 들어가면 안 된다 — 전략 라벨만.

    Gotcha-Test Pair: ticker 슬롯에 row['account'] 를 쓰면 FAIL.
    """
    row = _sleeve_row(account="Brokerage Alpha")
    payload = portfolio_signals._build_sleeve_rebalance_payload(row, "2026-07-08")
    assert "Brokerage Alpha" not in json.dumps(payload, ensure_ascii=False)
    assert "core" in payload["ticker"]


def test_sleeve_staging_writes_normal_priority_and_dedupes(db_path):
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=[_sleeve_row()]):
        s1 = portfolio_signals.stage_sleeve_briefs(date="2026-07-08", db_path=db_path)
        s2 = portfolio_signals.stage_sleeve_briefs(date="2026-07-08", db_path=db_path)  # 재실행
    assert (s1, s2) == (1, 0)
    rows = query("SELECT priority, dedupe_key FROM discord_outbox WHERE channel='brief'", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["priority"] == "normal"
    assert rows[0]["dedupe_key"] == "rebalance:sleeve:Brokerage Alpha:2026-07-08"


def test_sleeve_within_cap_stages_nothing(db_path):
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=[_sleeve_row(used=5.0)]):
        assert portfolio_signals.stage_sleeve_briefs(date="2026-07-08", db_path=db_path) == 0


def test_cli_shows_sleeve_breach(db_path, capsys):
    with (
        patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]),
        patch("nuri.analysis.sleeve.sleeve_utilization", return_value=[_sleeve_row()]),
    ):
        rc = portfolio_signals.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[슬리브] core" in out and "staged 1" in out
