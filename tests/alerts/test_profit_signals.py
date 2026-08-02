"""Tier 1e — 트레일링 give-back → #brief (`nuri/alerts/profit_signals.py`).

합성 티커 TST_* 만 사용 (privacy: 사용자 실보유/실티커 금지).
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.alerts import profit_signals as ps
from nuri.core.db import init_db, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "profit.db"
    init_db(path)
    return path


def _seed(path, *, ticker, account, avg, peak, current, qty=10):
    """진입 avg → 고점 peak → 현재 current 인 포지션 하나."""
    upsert_portfolio(
        [
            {
                "account": account,
                "ticker": ticker,
                "quantity": qty,
                "avg_price": avg,
                "currency": "USD",
                "sector": "Tech",
                "first_buy_date": "2026-01-02",
            }
        ],
        path,
    )
    rows = []
    for date, px in (("2026-03-02", peak), ("2026-07-31", current)):
        rows.append(
            {
                "ticker": ticker,
                "date": date,
                "open": px,
                "high": px,
                "low": px,
                "close": px,
                "volume": 1_000_000,
                "adj_close": px,
            }
        )
    upsert_prices(pd.DataFrame(rows), path)


def _core(monkeypatch, stop=-30):
    """계좌 전략을 core 로 고정하고 손절선을 넉넉히 — 트레일링만 격리해 본다."""
    import nuri.alerts.risk_signals as rs

    monkeypatch.setattr(ps, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(rs, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(rs, "get_stop_loss_for_account", lambda a: stop)


def test_position_that_never_rose_is_not_a_giveback(db_path, monkeypatch):
    """되돌릴 이익이 없었으면 트레일링이 아니다 — 그건 손절 소관이다.

    회귀 잠금: `check_trailing_stop_signals()` 는 HWM 을 max(고점, 진입가) 로 바닥
    처리해서, 오른 적 없는 종목도 -15% 손실이 '트레일링 도달' 로 잡힌다. 그대로
    알리면 이익 보호가 아닌 것을 이익 보호라 부르고 손절 알림과 중복된다.
    """
    _core(monkeypatch)
    # 고점이 진입가와 같다 = 오른 적 없음. 현재 -20% → 원본 신호는 뜬다.
    _seed(db_path, ticker="TST_FLAT", account="Brokerage Alpha", avg=100.0, peak=100.0, current=80.0)

    from nuri.trading.recommend.price_targets import check_trailing_stop_signals

    assert check_trailing_stop_signals(db_path=db_path), "원본 신호는 뜬다(전제 확인)"
    assert ps.scan_trailing_giveback(db_path=db_path) == [], "give-back 으로 올리면 안 된다"


def test_real_giveback_is_surfaced(db_path, monkeypatch):
    _core(monkeypatch)
    # +50% 까지 갔다가 고점 대비 -20% → 진입 대비 +20% 남음
    _seed(db_path, ticker="TST_WIN", account="Brokerage Alpha", avg=100.0, peak=150.0, current=120.0)

    sigs = ps.scan_trailing_giveback(db_path=db_path)

    assert [s["ticker"] for s in sigs] == ["TST_WIN"]
    assert sigs[0]["peak_gain_pct"] == pytest.approx(50.0)
    assert sigs[0]["given_back_pct"] == pytest.approx(60.0)  # (150-120)/(150-100)


def test_from_entry_percent_is_computed_not_composed(db_path, monkeypatch):
    """진입 대비 %는 직접 계산해야 한다 — 퍼센트 뺄셈으로 합성하면 틀린다.

    회귀 잠금: `peak_gain - |drop|` 로 만들면 +21.6% 뒤 -29.9% 가 -8.3% 로 나오지만
    실제는 -14.8% 다. 실데이터 렌더에서 잡힌 오류.
    """
    _core(monkeypatch)
    _seed(db_path, ticker="TST_W2", account="Brokerage Alpha", avg=100.0, peak=150.0, current=90.0)

    card = ps._build_giveback_payload(ps.scan_trailing_giveback(db_path=db_path)[0], "2026-08-02")["summary"]

    assert "진입 $100.00 대비 -10.0%" in card, card
    assert "-50.0%" not in card  # 50 - 40 같은 합성값이 새면 안 된다


def test_below_entry_says_full_giveback_not_over_100_percent(db_path, monkeypatch):
    """진입가 아래면 '이익 전량 반납' 이라 말한다 — '168% 반납' 은 무의미하다."""
    _core(monkeypatch)
    _seed(db_path, ticker="TST_W3", account="Brokerage Alpha", avg=100.0, peak=150.0, current=90.0)

    card = ps._build_giveback_payload(ps.scan_trailing_giveback(db_path=db_path)[0], "2026-08-02")["summary"]

    assert "전량 반납 (진입가 아래)" in card
    assert "중 " not in card, "진입가 아래인데 '고점 이익 중 N% 반납' 문구가 나오면 안 된다"


def test_pension_excluded(db_path, monkeypatch):
    import nuri.alerts.risk_signals as rs

    monkeypatch.setattr(ps, "get_account_strategy_name", lambda a: "pension")
    monkeypatch.setattr(rs, "get_account_strategy_name", lambda a: "pension")
    _seed(db_path, ticker="TST_P", account="Pension Gamma", avg=100.0, peak=150.0, current=120.0)

    assert ps.scan_trailing_giveback(db_path=db_path) == []


def test_stop_loss_breach_wins_no_double_card(db_path, monkeypatch):
    """같은 포지션에 손절 카드와 트레일링 카드가 둘 다 가면 안 된다."""
    _core(monkeypatch, stop=-5)  # 손절선을 -5% 로 좁혀 이탈 상태로 만든다
    _seed(db_path, ticker="TST_BOTH", account="Brokerage Alpha", avg=100.0, peak=150.0, current=90.0)

    from nuri.alerts.risk_signals import scan_stop_breaches

    assert [b["ticker"] for b in scan_stop_breaches(db_path=db_path)] == ["TST_BOTH"], "손절도 걸린 상태(전제)"
    assert ps.scan_trailing_giveback(db_path=db_path), "트레일링 자체는 감지된다(전제)"

    staged = ps.stage_trailing_briefs(date="2026-08-02", db_path=db_path)

    assert staged == 0, "손절이 이미 알린 종목은 트레일링으로 또 올리지 않는다"


def test_write_brief_stages_trailing(db_path, monkeypatch):
    """배선 잠금 — write_brief 가 트레일링 stage 를 실제로 호출한다.

    이 배선이 없어서 트레일링 신호가 대시보드에만 있고 디스코드로는 한 번도
    나가지 않았다 (2026-08-02 감사).
    """
    from unittest.mock import MagicMock, patch

    spy = MagicMock(return_value=1)
    with patch("nuri.alerts.profit_signals.stage_trailing_briefs", spy):
        from nuri.alerts import postmarket_brief as pmb

        with (
            patch("nuri.agents.discord.outbox._privacy_gate_payload", return_value=[]),
            patch("nuri.agents.discord.outbox.stage_brief", return_value=None),
            patch("nuri.alerts.risk_signals.stage_stop_breach_briefs", MagicMock()),
        ):
            pmb.write_brief("us", date="2026-08-02", db_path=db_path)

    spy.assert_called_once()
    assert spy.call_args[0][0] == "us"


def test_session_filter_splits_kr_and_us(db_path, monkeypatch):
    _core(monkeypatch)
    _seed(db_path, ticker="TST_US", account="Brokerage Alpha", avg=100.0, peak=150.0, current=120.0)
    _seed(db_path, ticker="900002.KQ", account="Brokerage Alpha", avg=100.0, peak=150.0, current=120.0)

    kr = [s["ticker"] for s in ps.scan_trailing_giveback("kr", db_path=db_path)]
    us = [s["ticker"] for s in ps.scan_trailing_giveback("us", db_path=db_path)]

    assert kr == ["900002.KQ"]  # KOSDAQ 도 KR (#764)
    assert us == ["TST_US"]


def test_missing_prices_skipped_without_crash(db_path, monkeypatch):
    _core(monkeypatch)
    upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "TST_NOPX",
                "quantity": 10,
                "avg_price": 100.0,
                "currency": "USD",
                "sector": "Tech",
                "first_buy_date": "2026-01-02",
            }
        ],
        db_path,
    )
    assert ps.scan_trailing_giveback(db_path=db_path) == []


def test_staging_writes_to_brief_outbox(db_path, monkeypatch):
    _core(monkeypatch)
    _seed(db_path, ticker="TST_WIN", account="Brokerage Alpha", avg=100.0, peak=150.0, current=120.0)

    staged = ps.stage_trailing_briefs(date="2026-08-02", db_path=db_path)

    from nuri.core.db import claim_pending_outbox

    _, rows = claim_pending_outbox("brief", db_path=db_path)
    assert staged == 1
    assert rows[0]["payload"]["kind"] == "SELL"
    assert "트레일링 도달" in rows[0]["payload"]["summary"]


def test_dedupe_same_day(db_path, monkeypatch):
    _core(monkeypatch)
    _seed(db_path, ticker="TST_WIN", account="Brokerage Alpha", avg=100.0, peak=150.0, current=120.0)

    first = ps.stage_trailing_briefs(date="2026-08-02", db_path=db_path)
    second = ps.stage_trailing_briefs(date="2026-08-02", db_path=db_path)

    assert (first, second) == (1, 0), "같은 날 두 번째는 dedupe 로 skip"


def test_cli_reports_when_nothing_to_show(db_path, monkeypatch, capsys):
    monkeypatch.setattr(ps, "scan_trailing_giveback", lambda *a, **k: [])
    assert ps.main([]) == 0
    assert "없음" in capsys.readouterr().out


def test_cli_dry_run_lists_without_staging(monkeypatch, capsys):
    sig = {
        "ticker": "TST_WIN",
        "account": "Brokerage Alpha",
        "drop_pct": -20.0,
        "peak_gain_pct": 50.0,
        "given_back_pct": 60.0,
    }
    monkeypatch.setattr(ps, "scan_trailing_giveback", lambda *a, **k: [sig])
    staged = []
    monkeypatch.setattr(ps, "stage_trailing_briefs", lambda *a, **k: staged.append(1))

    assert ps.main(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "TST_WIN" in out and "dry-run" in out
    assert staged == [], "dry-run 은 stage 하지 않는다"


def test_cli_stages_without_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(
        ps,
        "scan_trailing_giveback",
        lambda *a, **k: [
            {"ticker": "T", "account": "A", "drop_pct": -20.0, "peak_gain_pct": 50.0, "given_back_pct": 60.0}
        ],
    )
    monkeypatch.setattr(ps, "stage_trailing_briefs", lambda *a, **k: 1)

    assert ps.main([]) == 0
    assert "staged 1건" in capsys.readouterr().out


def test_signal_without_prices_is_skipped(monkeypatch):
    """상류가 entry/HWM 없는 행을 주더라도 죽지 않고 건너뛴다 (방어 가드)."""
    monkeypatch.setattr(ps, "get_account_strategy_name", lambda a: "core")
    monkeypatch.setattr(
        "nuri.trading.recommend.price_targets.check_trailing_stop_signals",
        lambda **k: [{"ticker": "TST_X", "account": "A", "entry_price": None, "high_water_mark": 10.0}],
    )
    assert ps.scan_trailing_giveback() == []
