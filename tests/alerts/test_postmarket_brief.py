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
            {
                "account": "Main",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 180,
                "currency": "USD",
                "sector": "Tech",
            },
            {"account": "Main", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semi"},
            {
                "account": "KR_acct",
                "ticker": "005930.KS",
                "quantity": 4,
                "avg_price": 60000,
                "currency": "KRW",
                "sector": "Semi",
            },
            {
                "account": "Pension_acct",
                "ticker": "VOO",
                "quantity": 2,
                "avg_price": 500,
                "currency": "USD",
                "sector": "ETF",
            },
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
            rows.append(
                {
                    "ticker": t,
                    "date": d.strftime("%Y-%m-%d"),
                    "open": close - 0.5,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000000,
                    "adj_close": close,
                }
            )
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
    yaml_path.write_text(
        yaml.dump(
            {
                "accounts": {
                    "Main": {"strategy": "core"},
                    "KR_acct": {"strategy": "long_term"},
                    "Pension_acct": {"strategy": "pension"},
                }
            }
        )
    )
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


def test_write_brief_stages_concentration_rebalance_us_only(seeded_db, portfolio_yaml):
    """Tier 1b wiring lock — write_brief('us') 만 집중도 REBALANCE 를 stage.

    배선 제거 시 FAIL. US-only 게이트(P2-2): kr/us 양 세션 호출 시 dispatcher 가
    US 행 sent 처리 후 KR 재삽입해 하루 2건 나던 것을 단일 세션으로 차단.
    """
    from unittest.mock import MagicMock

    from nuri.alerts.postmarket_brief import write_brief

    spy = MagicMock(return_value=0)
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
        patch("nuri.alerts.portfolio_signals.stage_concentration_briefs", spy),
    ):
        write_brief("us", date="2026-05-01")
        write_brief("kr", date="2026-05-01")

    spy.assert_called_once()  # US 만 — KR 은 호출 안 함
    args, _ = spy.call_args
    assert args[0] == "2026-05-01"  # date 전달


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
        "us",
        "2026-05-04",
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
        "us",
        "2026-05-04",
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


# ─── Phase 2 (#596): market_postmortem persistence ──────────────────────────


def test_write_brief_persists_postmortem_row(seeded_db, portfolio_yaml):
    """Phase 2: write_brief() 1회 실행 → market_postmortem row 1개 누적."""
    from nuri.alerts.postmarket_brief import write_brief
    from nuri.core.db import query

    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        write_brief("us", date="2026-05-01")

    rows = query(
        "SELECT * FROM market_postmortem WHERE date = ? AND session = ?",
        ("2026-05-01", "us"),
        db_path=seeded_db,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["vix"] == 16.5
    assert row["fear_greed"] == 60.0
    # 5d delta is None (only 2 macro rows seeded — < 6 required)
    assert row["vix_5d_delta"] is None
    # holdings_total_pnl_pct populated from compute step
    assert row["holdings_total_pnl_pct"] is not None


def test_write_brief_postmortem_idempotent(seeded_db, portfolio_yaml):
    """같은 (date, session) 두 번 호출 → row 1개 유지 (PK UPSERT)."""
    from nuri.alerts.postmarket_brief import write_brief
    from nuri.core.db import query

    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        write_brief("us", date="2026-05-01")
        write_brief("us", date="2026-05-01")

    rows = query(
        "SELECT COUNT(*) AS n FROM market_postmortem",
        db_path=seeded_db,
    )
    assert rows[0]["n"] == 1


def test_write_brief_postmortem_failure_does_not_break_brief(seeded_db, portfolio_yaml, monkeypatch):
    """upsert_postmortem 가 raise 해도 브리프 markdown 자체는 생성 (graceful)."""
    import nuri.alerts.postmarket_brief as pmb
    from nuri.alerts.postmarket_brief import write_brief

    def _boom(*a, **kw):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(pmb, "_persist_postmortem", _boom)
    with (
        patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
        patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
    ):
        path = write_brief("us", date="2026-05-01")
    assert path.exists()  # markdown still written


# ─── _load_5d helpers — empty / coerce-error / zero-divisor branches ─────


class TestLoad5dHelpers:
    """`_load_5d_macro_delta` (lines 362-369) + `_load_5d_price_delta_pct` (379-385)."""

    def test_macro_delta_returns_none_when_under_6_rows(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_macro_delta

        path = tmp_path / "macro.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        # 3 rows only
        records = [
            {"date": "2026-04-25", "indicator": "VIX", "value": 18.0, "source": "test"},
            {"date": "2026-04-26", "indicator": "VIX", "value": 19.0, "source": "test"},
            {"date": "2026-04-27", "indicator": "VIX", "value": 20.0, "source": "test"},
        ]
        upsert_macro(records, path)

        assert _load_5d_macro_delta("VIX", db_path=path) is None

    def test_macro_delta_handles_non_numeric_value(self, tmp_path, monkeypatch):
        """value 컬럼이 non-numeric → TypeError/ValueError fallback (lines 367-368)."""
        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_macro_delta
        from nuri.core.db import get_db

        path = tmp_path / "macro_bad.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        # 6 rows, but value 일부가 non-coercible 문자열
        with get_db(path) as conn:
            cur = conn.cursor()
            for i, val in enumerate(["abc", 1.0, 2.0, 3.0, 4.0, 5.0]):
                cur.execute(
                    "INSERT INTO macro (date, indicator, value, source) VALUES (?, ?, ?, ?)",
                    (f"2026-04-{20 + i:02d}", "FOO", val, "test"),
                )
            conn.commit()

        # latest = 'abc' → ValueError → None
        assert _load_5d_macro_delta("FOO", db_path=path) is None

    def test_price_delta_returns_none_when_five_back_zero(self, tmp_path, monkeypatch):
        """five_back == 0 → ZeroDivision 회피 None (line 384)."""
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_price_delta_pct

        path = tmp_path / "price_zero.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        # ORDER BY date DESC LIMIT 6 → oldest = "2026-04-20" → close=0 (five_back)
        rows = []
        for i, close in enumerate([0.0, 100.0, 101.0, 102.0, 103.0, 104.0]):
            rows.append(
                {
                    "date": f"2026-04-{20 + i:02d}",
                    "ticker": "ZERO",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                    "adj_close": close,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)

        assert _load_5d_price_delta_pct("ZERO", db_path=path) is None

    def test_price_delta_returns_none_when_under_6_rows(self, tmp_path, monkeypatch):
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_price_delta_pct

        path = tmp_path / "price_short.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        rows = []
        for i, close in enumerate([100.0, 101.0, 102.0]):
            rows.append(
                {
                    "date": f"2026-04-{20 + i:02d}",
                    "ticker": "SHORT",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                    "adj_close": close,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)

        assert _load_5d_price_delta_pct("SHORT", db_path=path) is None

    def test_price_delta_returns_normal_pct_when_data_ok(self, tmp_path, monkeypatch):
        """6 rows + non-zero five_back → 정상 % return."""
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_price_delta_pct

        path = tmp_path / "price_ok.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        rows = []
        for i, close in enumerate([100.0, 100.0, 100.0, 100.0, 100.0, 110.0]):
            rows.append(
                {
                    "date": f"2026-04-{20 + i:02d}",
                    "ticker": "OK",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                    "adj_close": close,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)

        # rows ORDER BY date DESC LIMIT 6 → latest=110 (i=5), five_back=100 (i=0)
        result = _load_5d_price_delta_pct("OK", db_path=path)
        assert result == pytest.approx(10.0)

    def test_macro_delta_returns_normal_when_data_ok(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts.postmarket_brief import _load_5d_macro_delta

        path = tmp_path / "macro_ok.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        records = [
            {"date": f"2026-04-{20 + i:02d}", "indicator": "BAR", "value": v, "source": "test"}
            for i, v in enumerate([10.0, 11.0, 12.0, 13.0, 14.0, 20.0])
        ]
        upsert_macro(records, path)

        # latest=20, five_back=10 → delta = 10
        result = _load_5d_macro_delta("BAR", db_path=path)
        assert result == pytest.approx(10.0)


class TestWriteBriefBranchCoverage:
    """postmarket_brief.py write_brief 분기 — codecov 갭 (#611)."""

    def test_publish_discord_returns_id_skips_skip_log(self, seeded_db, portfolio_yaml, caplog):
        """postmarket_brief.py 472->475: outbox_id 가 None 이 아니면 'skip' 로그 출력 안 함."""
        from nuri.alerts.postmarket_brief import write_brief

        # _publish_discord 가 outbox_id (str) 반환 → 472 분기 False → 475 로 스킵
        with (
            patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
            patch("nuri.agents.discord.outbox.stage_brief", return_value="outbox-uuid-1234"),
            caplog.at_level("INFO"),
        ):
            path = write_brief("us", date="2026-05-01")
        assert path.exists()
        # 'skip' 또는 '미발행' 메시지가 로그에 없어야 함 (472 False 분기 확인)
        assert not any("미발행" in rec.message for rec in caplog.records)

    def test_holdings_no_pnl_match_continues_outer_loop(self):
        """postmarket_brief.py 267->265: actionable row 가 pnl rows 와 매칭 안 되면 inner for 가
        break 없이 종료 → flat_rows 누락 (외부 루프 다음 row 로 진행, #611)."""
        from nuri.alerts.postmarket_brief import _format_markdown

        # holdings 에 AAPL 있지만 pnl rows 에는 다른 ticker → 매칭 실패 시나리오
        macro = {"vix": None, "fear_greed": None, "regime": None}
        holdings = {
            "acct_x": {
                "label": "Acct X",
                "rows": [{"ticker": "AAPL", "account": "acct_x", "qty": 1, "avg_price": 100, "current_price": 100}],
            }
        }
        # pnl["rows"] 는 ZZZ 만 → AAPL 매칭 실패, 267 inner for break 없이 종료 → 265 로 점프
        pnl = {
            "rows": [{"ticker": "ZZZ", "account": "other", "pnl_pct": 1.0, "pnl_abs": 0.0}],
            "total_abs": 0.0,
            "total_pct": 0.0,
        }
        sectors = []
        md = _format_markdown("us", "2026-05-01", macro, holdings, pnl, sectors)
        # holdings flat_rows 가 비어있어 "데이터 없음" 출력 (267->265 분기 확인)
        assert "데이터 없음" in md
        # AAPL holdings 행은 표 안에 없음
        assert "## Holdings" in md


# ─── #596 Phase 3 — retro lessons (similar days + forward outcome + LLM) ──────


class TestRetroLessons:
    """Pattern memory retro: 유사 과거 + 전방 결과 + LLM 합성 (disabled-safe)."""

    def _seed_spy(self, path, start="2026-01-02", n=30, base=500.0, step=1.0):
        import pandas as pd

        from nuri.core.db import upsert_prices

        dates = pd.date_range(start, periods=n, freq="B")
        rows = [
            {
                "ticker": "SPY",
                "date": d.strftime("%Y-%m-%d"),
                "open": base + i * step,
                "high": base + i * step + 1,
                "low": base + i * step - 1,
                "close": base + i * step,
                "volume": 1_000_000,
                "adj_close": base + i * step,
            }
            for i, d in enumerate(dates)
        ]
        upsert_prices(pd.DataFrame(rows), path)

    def test_forward_spy_return_computes_pct(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        self._seed_spy(path, start="2026-01-02", n=10, base=500.0, step=1.0)
        # 1/02 close=500, +2 거래일 close=502 → +0.4%
        r = pmb._forward_spy_return("2026-01-02", days=2, db_path=path)
        assert r is not None and abs(r - 0.4) < 0.01

    def test_forward_spy_return_none_when_insufficient(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        self._seed_spy(path, start="2026-01-02", n=3, base=500.0)
        assert pmb._forward_spy_return("2026-01-02", days=7, db_path=path) is None

    def test_retro_empty_when_no_similar_days(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        feats = {"regime": "bull_low_vol", "vix": 16.0, "fear_greed": 60.0}
        assert pmb._generate_retro_lessons("us", "2026-06-01", feats, db_path=path) == []

    def test_retro_deterministic_summary_with_outcomes(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db, upsert_postmortem

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        self._seed_spy(path, start="2026-01-02", n=30, base=500.0, step=1.0)
        # 유사 과거 2건 — 같은 session/regime, 전방 SPY 데이터 충분한 초반 날짜
        for d in ("2026-01-05", "2026-01-06"):
            upsert_postmortem(
                date=d,
                session="us",
                regime="bull_low_vol",
                vix=16.0,
                fear_greed=60.0,
                vix_5d_delta=-1.0,
                fg_5d_delta=5.0,
                spy_5d_delta=1.0,
                top_sector_delta_pct=1.5,
                holdings_total_pnl_pct=2.0,
                db_path=path,
            )
        feats = {
            "regime": "bull_low_vol",
            "vix": 16.0,
            "fear_greed": 60.0,
            "vix_5d_delta": -1.0,
            "fg_5d_delta": 5.0,
            "spy_5d_delta": 1.0,
            "top_sector_delta_pct": 1.5,
            "holdings_total_pnl_pct": 2.0,
        }
        with patch.dict("os.environ", {"OLLAMA_HOST": ""}):  # LLM off → deterministic only
            lessons = pmb._generate_retro_lessons("us", "2026-06-01", feats, db_path=path)
        assert lessons and "유사 2건" in lessons[0] and "SPY 중앙값" in lessons[0]

    def test_synthesize_retro_llm_disabled_safe(self, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        out = pmb._synthesize_retro_llm({"vix": 16}, [({"date": "2026-01-05", "vix": 16}, 1.2)])
        assert out == []

    def test_synthesize_retro_llm_parses_ollama(self, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        enriched = [({"date": "2026-01-05", "vix": 16, "fear_greed": 60, "regime": "bull"}, 1.2)]
        with patch("nuri.llm.report._generate_ollama", return_value="- 변동성 낮을 때 추격 자제\n- 눌림목 분할 진입"):
            out = pmb._synthesize_retro_llm({"vix": 16, "fear_greed": 60, "regime": "bull"}, enriched)
        assert len(out) == 2 and out[0].startswith("💡") and "추격 자제" in out[0]

    def test_retro_surfaces_in_markdown_and_persists(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db, query, upsert_macro, upsert_postmortem, upsert_prices

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        monkeypatch.setattr(pmb, "__file__", str(tmp_path / "nuri" / "alerts" / "postmarket_brief.py"))
        self._seed_spy(path, start="2026-01-02", n=40, base=500.0, step=1.0)
        upsert_macro([{"indicator": "vix", "date": "2026-02-02", "value": 16.0, "source": "t"}], path)
        for d in ("2026-01-05", "2026-01-06"):
            upsert_postmortem(
                date=d,
                session="us",
                regime=None,
                vix=16.0,
                fear_greed=None,
                spy_5d_delta=1.0,
                holdings_total_pnl_pct=0.0,
                db_path=path,
            )
        with (
            patch.dict("os.environ", {"OLLAMA_HOST": ""}),
            patch("nuri.alerts.postmarket_brief._publish_discord", return_value=None),
        ):
            out_path = pmb.write_brief("us", date="2026-02-02", db_path=path)
        md = out_path.read_text()
        assert "📚 Retro" in md
        row = query("SELECT retro_lessons FROM market_postmortem WHERE date='2026-02-02'", db_path=path)
        assert row and row[0]["retro_lessons"] and "SPY 중앙값" in row[0]["retro_lessons"]

    def test_synthesize_retro_llm_empty_response_safe(self, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        enriched = [({"date": "2026-01-05", "vix": 16, "fear_greed": 60, "regime": "bull"}, 1.2)]
        with patch("nuri.llm.report._generate_ollama", return_value="   "):
            assert pmb._synthesize_retro_llm({"vix": 16}, enriched) == []

    def test_synthesize_retro_llm_no_outcomes_safe(self, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        # 전방 결과(fwd) 전부 None → 보낼 라인 없음 → []
        assert pmb._synthesize_retro_llm({"vix": 16}, [({"date": "2026-01-05"}, None)]) == []

    def test_synthesize_retro_llm_exception_safe(self, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        enriched = [({"date": "2026-01-05", "vix": 16, "fear_greed": 60, "regime": "bull"}, 1.2)]
        with patch("nuri.llm.report._generate_ollama", side_effect=RuntimeError("ollama down")):
            assert pmb._synthesize_retro_llm({"vix": 16}, enriched) == []

    def test_retro_find_similar_exception_safe(self, tmp_path, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        with patch("nuri.core.db.find_similar_days", side_effect=RuntimeError("db gone")):
            assert pmb._generate_retro_lessons("us", "2026-06-01", {"vix": 16}, db_path=tmp_path / "x.db") == []

    def test_forward_spy_return_none_on_zero_base(self, tmp_path, monkeypatch):
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db, upsert_prices

        path = tmp_path / "z.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        dates = pd.date_range("2026-01-02", periods=5, freq="B")
        rows = [
            {
                "ticker": "SPY",
                "date": d.strftime("%Y-%m-%d"),
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 0.0,
                "volume": 1,
                "adj_close": 0.0,
            }
            for d in dates
        ]
        upsert_prices(pd.DataFrame(rows), path)
        assert pmb._forward_spy_return("2026-01-02", days=2, db_path=path) is None

    def test_write_brief_survives_retro_failure(self, seeded_db, portfolio_yaml, tmp_path, monkeypatch):
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setattr(pmb, "__file__", str(tmp_path / "nuri" / "alerts" / "postmarket_brief.py"))
        with (
            patch("nuri.alerts.postmarket_brief._generate_retro_lessons", side_effect=RuntimeError("boom")),
            patch("nuri.alerts.postmarket_brief._publish_discord", return_value=None),
        ):
            out_path = pmb.write_brief("us", date="2026-05-01", db_path=seeded_db)
        assert out_path.exists()  # 브리프 자체는 생성 (retro 실패 무관)

    def test_ollama_host_local_guard(self, monkeypatch):
        """STRATEGY §4.4.3 — 비-localhost OLLAMA_HOST 는 거부 (egress 방어)."""
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        assert pmb._ollama_host_is_local() is False
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        assert pmb._ollama_host_is_local() is True
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        assert pmb._ollama_host_is_local() is True
        # 비-localhost → 거부 (외부 유출 방어)
        monkeypatch.setenv("OLLAMA_HOST", "http://remote-host.example.com:11434")
        assert pmb._ollama_host_is_local() is False

    def test_synthesize_retro_llm_blocks_nonlocal_host(self, monkeypatch):
        """비-localhost host 면 _generate_ollama 호출 자체가 안 일어남 (egress 차단)."""
        from nuri.alerts import postmarket_brief as pmb

        monkeypatch.setenv("OLLAMA_HOST", "http://attacker.example.com:11434")
        enriched = [({"date": "2026-01-05", "vix": 16, "fear_greed": 60, "regime": "bull"}, 1.2)]
        with patch("nuri.llm.report._generate_ollama") as gen:
            out = pmb._synthesize_retro_llm({"vix": 16}, enriched)
        assert out == []
        gen.assert_not_called()

    def test_retro_strips_sensitive_fields_before_llm(self, tmp_path, monkeypatch):
        """find_similar_days(SELECT *) 의 holdings_pnl blob 이 LLM 데이터 흐름에 안 들어감."""
        import nuri.core.db as db_mod
        from nuri.alerts import postmarket_brief as pmb
        from nuri.core.db import init_db, upsert_postmortem

        path = tmp_path / "r.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        self._seed_spy(path, start="2026-01-02", n=30, base=500.0, step=1.0)
        upsert_postmortem(
            date="2026-01-05",
            session="us",
            regime="bull",
            vix=16.0,
            fear_greed=60.0,
            holdings_pnl={"rows": [{"ticker": "SECRET_TICKER", "account": "SECRET_ACCT", "pnl_abs": 99999}]},
            spy_5d_delta=1.0,
            holdings_total_pnl_pct=12.3,
            db_path=path,
        )
        captured = {}
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

        def _fake(prompt):
            captured["prompt"] = prompt
            return "- 교훈1"

        feats = {"regime": "bull", "vix": 16.0, "fear_greed": 60.0, "spy_5d_delta": 1.0, "holdings_total_pnl_pct": 12.3}
        with patch("nuri.llm.report._generate_ollama", side_effect=_fake):
            pmb._generate_retro_lessons("us", "2026-06-01", feats, db_path=path)
        # 개인 보유/account/PnL 이 prompt 에 절대 미포함
        assert "SECRET_TICKER" not in captured.get("prompt", "")
        assert "SECRET_ACCT" not in captured.get("prompt", "")
        assert "99999" not in captured.get("prompt", "")
        assert "12.3" not in captured.get("prompt", "")
