"""Lock-tests for `nuri/alerts/postmarket_brief.py` (Issue #596 Phase 1).

8 behavioral lock-tests:
- Holdings PnL 합 = synthetic price delta × qty (±0.01% precision)
- pension 계좌 출력 제외 lock
- US session DST-aware dispatch (EDT/EST 양 상태)
- Idempotency (UPSERT, 같은 path 재실행 시 마지막 markdown 유지)
- Discord publish privacy gate (ticker+PnL combo abort)
- US session sector ETF schema lock (XLK..XLC 11종)
- KR session fallback (KOSPI200 만 emit)
- 빈 DB graceful — write_brief raise 안 함, 빈 markdown 출력

Test isolation: tmp_path + init_db(path), monkeypatch DB_PATH.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import yaml

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """4 holdings × 5d price seed — synthetic PnL 계산 검증용.

    AAPL/NVDA: US, 005930.KS/035720.KS: KR. 각 close 직선 trend 로 (close - prev_close)
    예측 가능. macro 도 VIX/F&G/USD-KRW 시드.
    """
    import nuri.core.db as db_mod

    path = tmp_path / "post.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio(
        [
            {"account": "Main", "ticker": "AAPL", "quantity": 10, "avg_price": 180,
             "currency": "USD", "sector": "Tech"},
            {"account": "Main", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semi"},
            {"account": "KR_acct", "ticker": "005930.KS", "quantity": 4, "avg_price": 60000,
             "currency": "KRW", "sector": "Semi"},
            {"account": "Pension_acct", "ticker": "VOO", "quantity": 2, "avg_price": 500,
             "currency": "USD", "sector": "ETF"},
        ],
        path,
    )

    # 5d price series — 매일 +1 (US) / +100 (KR) 단순 trend
    dates = pd.date_range("2026-04-27", periods=5, freq="B")
    rows = []
    for t, base, step in (
        ("AAPL", 200.0, 1.0),
        ("NVDA", 150.0, 1.0),
        ("005930.KS", 70000.0, 100.0),
        ("VOO", 520.0, 1.0),
        ("SPY", 550.0, 0.5),
        ("069500.KS", 38000.0, 50.0),
    ):
        for i, d in enumerate(dates):
            close = base + i * step
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": close - 0.5, "high": close + 1, "low": close - 1,
                "close": close, "volume": 1000000, "adj_close": close,
            })
    upsert_prices(pd.DataFrame(rows), path)

    # Macro: VIX/F&G/USD-KRW 2-point latest+prev
    upsert_macro(
        [
            {"indicator": "vix", "date": "2026-04-30", "value": 18.0, "source": "test"},
            {"indicator": "vix", "date": "2026-05-01", "value": 16.5, "source": "test"},
            {"indicator": "fear_greed", "date": "2026-04-30", "value": 55, "source": "test"},
            {"indicator": "fear_greed", "date": "2026-05-01", "value": 60, "source": "test"},
            {"indicator": "usd_krw", "date": "2026-04-30", "value": 1380, "source": "test"},
            {"indicator": "usd_krw", "date": "2026-05-01", "value": 1390, "source": "test"},
        ],
        path,
    )
    return path


@pytest.fixture
def portfolio_yaml(tmp_path, monkeypatch):
    """Synthetic portfolio.yaml — Main=core, KR_acct=long_term, Pension_acct=pension."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    yaml_path = config_dir / "portfolio.yaml"
    yaml_path.write_text(yaml.dump({
        "accounts": {
            "Main": {"strategy": "core"},
            "KR_acct": {"strategy": "long_term"},
            "Pension_acct": {"strategy": "pension"},
        }
    }))
    # postmarket_brief._resolve_strategy_name 은 parents[2]/config/portfolio.yaml 을 읽음
    # → 모듈 __file__ 을 tmp_path 하위로 redirect
    import nuri.alerts.postmarket_brief as pmb

    monkeypatch.setattr(pmb, "__file__", str(tmp_path / "nuri" / "alerts" / "postmarket_brief.py"))
    return yaml_path


def test_holdings_pnl_sum_matches_synthetic_delta(seeded_db, portfolio_yaml):
    """4 holdings × 5d 시드 → 마지막 일 PnL 합 = step × qty (±0.01%)."""
    from nuri.alerts.postmarket_brief import (
        _compute_holdings_pnl,
        _filter_actionable_accounts,
        _filter_session_holdings,
        _load_holdings_with_strategy,
    )

    holdings = _load_holdings_with_strategy()
    # US session 기준 — Main 계좌 AAPL/NVDA 만 (Pension_acct/VOO 는 actionable filter 에서 제외)
    us_only = _filter_session_holdings(holdings, "us")
    actionable = _filter_actionable_accounts(us_only)
    pnl = _compute_holdings_pnl(actionable)
    # AAPL: step 1 × 10 qty = 10. NVDA: step 1 × 5 qty = 5. total_abs = 15.
    assert abs(pnl["total_abs"] - 15.0) < 0.01, f"PnL mismatch: {pnl['total_abs']}"


def test_pension_excluded_from_postmarket(seeded_db, portfolio_yaml, tmp_path):
    """`account.strategy == "pension"` holdings 가 markdown 출력에 미포함."""
    from nuri.alerts.postmarket_brief import write_brief

    # Discord publish skip — outbox stub
    # `_publish_discord` 는 함수 내부에서 from nuri.agents.discord.outbox import
    # _privacy_gate_payload, stage_brief 를 호출 — outbox 자체를 차단해 실제 DB
    # 없이 lock-test 진행 (fn under test 자체가 아닌 dependency 만 mock).
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        path = write_brief("us", date="2026-05-01")
    md = path.read_text()
    # Pension 계좌의 VOO 는 출력에 포함 안 됨
    assert "VOO" not in md, f"Pension VOO leaked into postmarket brief:\n{md}"
    # Main 계좌 AAPL/NVDA 는 포함
    assert "AAPL" in md
    assert "NVDA" in md


def test_us_session_dst_aware_cron_dispatch():
    """NYSE 16:30 ET window — EDT (KST 05:30) / EST (KST 06:30) 양쪽 검증.

    cron 06:30 + 07:30 KST 등록이라 EDT 기간엔 cron 06:30 fire 시 NYSE 17:30
    ET (60분 늦음) → window 미달 → skip. EST 기간엔 cron 06:30 fire = NYSE
    16:30 ET (정확) → window 진입 → run.
    """
    from nuri.alerts.postmarket_brief import _is_now_within_us_postclose_window

    # EST (Jan 15, 2026, 06:30 KST) → NYSE 16:30 ET (DST off) → window 진입
    est_kst = datetime(2026, 1, 15, 6, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert _is_now_within_us_postclose_window(_now_kst=est_kst) is True

    # EDT (Jul 15, 2026, 06:30 KST) → NYSE 17:30 ET (DST on, 60min late) → skip
    edt_kst = datetime(2026, 7, 15, 6, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert _is_now_within_us_postclose_window(_now_kst=edt_kst) is False

    # EDT (Jul 15, 2026, 05:30 KST) → NYSE 16:30 ET → window 진입
    edt_kst_correct = datetime(2026, 7, 15, 5, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert _is_now_within_us_postclose_window(_now_kst=edt_kst_correct) is True


def test_idempotency_re_run_same_date_upserts(seeded_db, portfolio_yaml):
    """같은 (date, session) 재실행 시 markdown 파일 덮어쓰기 (UPSERT 의미)."""
    from nuri.alerts.postmarket_brief import write_brief

    # `_publish_discord` 는 함수 내부에서 from nuri.agents.discord.outbox import
    # _privacy_gate_payload, stage_brief 를 호출 — outbox 자체를 차단해 실제 DB
    # 없이 lock-test 진행 (fn under test 자체가 아닌 dependency 만 mock).
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        path1 = write_brief("kr", date="2026-05-01")
        first_content = path1.read_text()
        path2 = write_brief("kr", date="2026-05-01")
        second_content = path2.read_text()
    assert path1 == path2, "Same (date, session) must yield identical path"
    # Generated timestamp 가 다를 수 있으므로 markdown 헤더만 비교 — 둘 다 valid
    assert "Post-market Brief" in first_content
    assert "Post-market Brief" in second_content


def test_discord_publish_privacy_gate_blocks_holdings_combo():
    """`_publish_discord` 가 payload privacy violation 발견 시 publish abort + None.

    여기선 ticker+PnL combo 가 누설되는 가짜 payload 를 만들어 gate 가 차단함을 lock.
    """
    from nuri.alerts.postmarket_brief import _publish_discord

    # Fake violation finding mimicking scripts/verify/check_privacy_leak.Finding shape
    # (category / pattern attrs only — privacy gate caller 는 list 길이로 결정)
    fake_finding = type("F", (), {"category": "ticker_pnl", "pattern": "AAPL +5%"})()
    # `_publish_discord` 가 함수 내부에서 from nuri.agents.discord.outbox import
    # _privacy_gate_payload, stage_brief 하므로 source module 에 패치.
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[fake_finding]),
        patch("nuri.agents.discord.outbox.stage_brief") as stage_mock,
    ):
        result = _publish_discord({"session": "us", "date": "2026-05-01", "kind": "INFO"})
    assert result is None, "Privacy violation must abort publish"
    stage_mock.assert_not_called()  # stage_brief 호출 자체가 안 일어남


def test_sector_movers_us_returns_11_spdrs(seeded_db):
    """US session sector ETF schema — 11 SPDR (XLK/XLF/XLE/XLV/XLP/XLY/XLB/XLI/XLU/XLRE/XLC)."""
    from nuri.alerts.postmarket_brief import US_SECTOR_ETFS, _load_sector_movers

    sectors = _load_sector_movers("us")
    expected = {"XLK", "XLF", "XLE", "XLV", "XLP", "XLY", "XLB", "XLI", "XLU", "XLRE", "XLC"}
    actual = {s["ticker"] for s in sectors}
    assert actual == expected, f"Expected 11 SPDR sectors, got {actual}"
    assert set(US_SECTOR_ETFS) == expected
    assert len(sectors) == 11


def test_sector_movers_kr_fallback_kospi200(seeded_db):
    """KR session sector ETF 부재 시 fallback — KOSPI200 (069500.KS) 만 emit."""
    from nuri.alerts.postmarket_brief import _load_sector_movers

    sectors = _load_sector_movers("kr")
    tickers = [s["ticker"] for s in sectors]
    assert "069500.KS" in tickers, f"KR fallback must include KOSPI200 ETF: {tickers}"
    # KR sector ETF universe 는 fallback only (KOSPI200) — schema lock
    assert tickers == ["069500.KS"]


def test_empty_db_graceful_degradation(tmp_path, monkeypatch):
    """빈 DB 에서 `write_brief` 가 raise 안 함 + "데이터 없음" markdown 출력."""
    import nuri.alerts.postmarket_brief as pmb
    import nuri.core.db as db_mod

    path = tmp_path / "empty.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    # portfolio.yaml 도 없는 상태 — _resolve_strategy_name 이 'core' fallback
    monkeypatch.setattr(pmb, "__file__", str(tmp_path / "nuri" / "alerts" / "postmarket_brief.py"))

    # `_publish_discord` 는 함수 내부에서 from nuri.agents.discord.outbox import
    # _privacy_gate_payload, stage_brief 를 호출 — outbox 자체를 차단해 실제 DB
    # 없이 lock-test 진행 (fn under test 자체가 아닌 dependency 만 mock).
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        out_path = pmb.write_brief("us", date="2026-05-01")
    md = out_path.read_text()
    assert "Post-market Brief" in md
    assert "데이터 없음" in md, f"Empty DB must surface '데이터 없음':\n{md}"


# ─── Scheduler registration lock ──────────────────────────────────────────
def test_postmarket_jobs_registered_in_scheduler():
    """SCHEDULES 에 `postmarket_brief_kr` + `postmarket_brief_us_a/b` 등록."""
    from nuri.scheduler import SCHEDULES

    names = [j["name"] for j in SCHEDULES]
    assert "postmarket_brief_kr" in names
    assert "postmarket_brief_us_a" in names
    assert "postmarket_brief_us_b" in names

    kr = next(j for j in SCHEDULES if j["name"] == "postmarket_brief_kr")
    assert kr["cron"] == "0 16 * * 1-5", "KR session must fire at KST 16:00 weekdays"


# ─────────────────────────────────────────────────────────────────────────────
# 미커버 branch 일괄 lock-tests — Codecov patch 87% → 100% 목표 (#605 review)
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_strategy_name_missing_yaml_returns_default(monkeypatch, tmp_path):
    """portfolio.yaml load 실패 시 default 'core' return (line 68-69)."""
    from nuri.alerts import postmarket_brief as pm

    nonexistent = tmp_path / "no" / "portfolio.yaml"
    monkeypatch.setattr(pm, "Path", lambda *a, **kw: nonexistent)
    # _resolve_strategy_name 의 try/except 가 default 'core' 반환
    name = pm._resolve_strategy_name("any_account")
    assert name == "core"


def test_compute_holdings_pnl_handles_none_close_or_qty(seeded_db):
    """close/prev/qty 가 None/0 인 row 는 pnl_abs=None 으로 surface (line 154-159)."""
    from nuri.alerts.postmarket_brief import _compute_holdings_pnl

    holdings = {
        "acct_a": {
            "strategy": "core",
            "rows": [
                {"ticker": "AAA", "qty": 0, "close": 100, "prev_close": 95, "avg_price": 90},
                {"ticker": "BBB", "qty": 5, "close": None, "prev_close": 95, "avg_price": 90},
                {"ticker": "CCC", "qty": 5, "close": 100, "prev_close": None, "avg_price": 90},
            ],
        }
    }
    result = _compute_holdings_pnl(holdings)
    assert len(result["rows"]) == 3
    for r in result["rows"]:
        assert r["pnl_abs"] is None, f"{r['ticker']} pnl_abs should be None"
        assert r["pnl_pct"] is None
    assert result["total_abs"] == 0.0
    assert result["total_pct_weighted"] == 0.0


def test_load_sector_movers_query_exception_returns_none(monkeypatch, seeded_db):
    """prices query 실패 시 sector mover entry 는 close=None / delta_pct=None (line 191-193)."""
    from nuri.alerts import postmarket_brief as pm

    def boom(*args, **kwargs):
        raise RuntimeError("query exploded")

    monkeypatch.setattr(pm, "query", boom)
    rows = pm._load_sector_movers("us", db_path=seeded_db)
    # 11 SPDR ETFs all with None close/delta_pct
    assert len(rows) == 11
    for r in rows:
        assert r["close"] is None
        assert r["delta_pct"] is None


def test_format_markdown_skips_missing_macro(seeded_db):
    """macro dict 의 None entry 는 skip (line 228 continue branch)."""
    from nuri.alerts.postmarket_brief import _format_markdown

    macro = {"vix": None, "fear_greed": None}  # all None → skip every iteration
    md = _format_markdown(
        "us", "2026-05-04",
        macro=macro,
        holdings={},
        pnl={"total_abs": 0, "total_pct_weighted": 0, "rows": []},
        sectors=[],
    )
    # Macro Snapshot section 존재하지만 indicator line 없음
    assert "## Macro Snapshot" in md
    # 모든 indicator None → 어떤 macro line 도 emit 안 됨
    assert "VIX:" not in md and "F&G:" not in md


def test_publish_discord_gate_exception_aborts(monkeypatch):
    """privacy gate 자체가 raise 하면 publish abort + None return (line 323-325)."""
    from nuri.alerts.postmarket_brief import _publish_discord

    def gate_raises(payload):
        raise RuntimeError("gate fault")

    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", side_effect=gate_raises),
        patch("nuri.agents.discord.outbox.stage_brief") as stage_mock,
    ):
        result = _publish_discord({"session": "us", "date": "2026-05-04"})
    assert result is None
    stage_mock.assert_not_called()


def test_is_within_us_postclose_window_inside(monkeypatch):
    """KST 06:30 (= NYSE 16:30 ET, EST 기간) 시 window 내 → True (line 392-395)."""
    import datetime
    from zoneinfo import ZoneInfo

    from nuri.alerts.postmarket_brief import _is_now_within_us_postclose_window

    # EST 기간 KST 06:30 — NYSE 16:30 정확히
    est_winter_kst = datetime.datetime(2026, 12, 15, 6, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    assert _is_now_within_us_postclose_window(_now_kst=est_winter_kst) is True


def test_is_within_us_postclose_window_outside():
    """KST 12:00 정오 — NYSE 22:00 ET 야간, window 밖 → False."""
    import datetime
    from zoneinfo import ZoneInfo

    from nuri.alerts.postmarket_brief import _is_now_within_us_postclose_window

    noon_kst = datetime.datetime(2026, 12, 15, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert _is_now_within_us_postclose_window(_now_kst=noon_kst) is False


def test_run_postmarket_us_dst_aware_skips_outside_window(monkeypatch):
    """window 밖이면 write_brief 호출 없이 None return (line 399-401)."""
    from nuri.alerts import postmarket_brief as pm

    monkeypatch.setattr(pm, "_is_now_within_us_postclose_window", lambda: False)
    called: list[bool] = []
    monkeypatch.setattr(pm, "write_brief", lambda *a, **kw: called.append(True))
    rc = pm.run_postmarket_us_dst_aware()
    assert rc is None
    assert called == []


def test_run_postmarket_us_dst_aware_proceeds_in_window(monkeypatch, tmp_path):
    """window 내이면 write_brief('us') 호출 + 그 결과 path 반환 (line 402-406)."""
    from nuri.alerts import postmarket_brief as pm

    monkeypatch.setattr(pm, "_is_now_within_us_postclose_window", lambda: True)
    sentinel_path = tmp_path / "sentinel.md"
    monkeypatch.setattr(pm, "write_brief", lambda session, date=None, db_path=None: sentinel_path)
    rc = pm.run_postmarket_us_dst_aware()
    assert rc == sentinel_path


def test_main_cli_writes_brief(monkeypatch, capsys, tmp_path):
    """main(['--session', 'kr']) 가 write_brief 호출 + path 출력 (line 410)."""
    from nuri.alerts import postmarket_brief as pm

    sentinel = tmp_path / "out.md"
    monkeypatch.setattr(pm, "write_brief", lambda session, date=None, db_path=None: sentinel)
    rc = pm.main(["--session", "kr"])
    assert rc == 0
    assert str(sentinel) in capsys.readouterr().out


def test_brief_common_macro_query_exception_skipped(monkeypatch, seeded_db):
    """macro indicator query 실패 시 해당 entry None 으로 skip (line 44-45)."""
    from nuri.alerts import _brief_common as bc

    def boom(*a, **kw):
        raise RuntimeError("macro fault")

    monkeypatch.setattr(bc, "query", boom)
    snapshot = bc.load_macro_snapshot(db_path=seeded_db)
    # query 가 모든 indicator 에서 raise → 모든 키 None 유지
    assert snapshot["vix"] is None
    assert snapshot["spy"] is None


def test_format_holdings_table_empty_returns_placeholder():
    """빈 list → '보유 없음' placeholder (line 73)."""
    from nuri.alerts._brief_common import format_holdings_table

    assert format_holdings_table([]) == "_보유 없음_"


def test_format_markdown_macro_without_delta(seeded_db):
    """macro entry 에 delta 없음 (d is None) → 'date' 만 표시 (line 228)."""
    from nuri.alerts.postmarket_brief import _format_markdown

    macro = {"vix": {"value": 17.0, "date": "2026-05-04"}}  # delta key 없음
    md = _format_markdown(
        "us", "2026-05-04",
        macro=macro,
        holdings={},
        pnl={"total_abs": 0, "total_pct_weighted": 0, "rows": []},
        sectors=[],
    )
    assert "VIX: 17.00 (2026-05-04)" in md


def test_scheduler_runner_kr_swallows_exception(monkeypatch, caplog):
    """_run_postmarket_brief_kr 가 write_brief raise 시 logger.error + 진행 (graceful)."""
    import logging

    from nuri import scheduler

    def boom(*a, **kw):
        raise RuntimeError("write_brief explode")

    monkeypatch.setattr("nuri.alerts.postmarket_brief.write_brief", boom)
    with caplog.at_level(logging.ERROR, logger="nuri.scheduler"):
        scheduler._run_postmarket_brief_kr()
    assert any("postmarket_brief_kr" in r.message and "실행 실패" in r.message for r in caplog.records)


def test_scheduler_runner_kr_calls_write_brief(monkeypatch):
    """_run_postmarket_brief_kr 정상 path: write_brief('kr') 1회 호출."""
    from nuri import scheduler

    called: list[str] = []
    monkeypatch.setattr("nuri.alerts.postmarket_brief.write_brief", lambda s, *a, **kw: called.append(s))
    scheduler._run_postmarket_brief_kr()
    assert called == ["kr"]


def test_scheduler_runner_us_swallows_exception(monkeypatch, caplog):
    """_run_postmarket_brief_us 가 raise 시 logger.error 후 swallow."""
    import logging

    from nuri import scheduler

    def boom(*a, **kw):
        raise RuntimeError("dst aware explode")

    monkeypatch.setattr("nuri.alerts.postmarket_brief.run_postmarket_us_dst_aware", boom)
    with caplog.at_level(logging.ERROR, logger="nuri.scheduler"):
        scheduler._run_postmarket_brief_us()
    assert any("postmarket_brief_us" in r.message and "실행 실패" in r.message for r in caplog.records)


def test_scheduler_runner_us_calls_dst_aware(monkeypatch):
    """_run_postmarket_brief_us 정상 path: run_postmarket_us_dst_aware 호출."""
    from nuri import scheduler

    called: list[bool] = []
    monkeypatch.setattr("nuri.alerts.postmarket_brief.run_postmarket_us_dst_aware", lambda: called.append(True))
    scheduler._run_postmarket_brief_us()
    assert called == [True]
