"""수집 데이터 타당성 점검 (`nuri/alerts/data_sanity.py`).

합성 티커 TST_* 만 사용 (privacy: 사용자 실보유/실티커 금지).

이 파일의 핵심 잠금은 **"검사가 못 돈 사실을 말하는가"** 다. 조용히 통과하는 검사는
이 레포가 반복해서 당한 실패라(#910/#911 dead gate, #953/#954 green dead gate),
데이터가 없거나 묵었을 때 아무 말도 안 하는 회귀는 반드시 FAIL 해야 한다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.alerts import data_sanity as ds
from nuri.core.db import init_db, upsert_prices

CFG = {"lookback_bars": 20, "divergence_1d_pp": 8.0, "divergence_3d_pp": 12.0, "proxy_max_lag_days": 5}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sanity.db"
    init_db(path)
    return path


def _seed(path, ticker, bars):
    """bars = [(date, open, high, low, close), ...]"""
    rows = [
        {
            "ticker": ticker,
            "date": d,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": 1_000_000,
            "adj_close": c,
        }
        for d, o, h, lo, c in bars
    ]
    upsert_prices(pd.DataFrame(rows), path)


def _series(ticker, closes, start_day=1):
    """연속 일자 종가 시리즈 — OHLC 는 close 로 평탄화(불가능 검사에 안 걸리게)."""
    return [(f"2026-07-{start_day + i:02d}", c, c, c, c) for i, c in enumerate(closes)]


# ── 물리적으로 불가능한 OHLC ────────────────────────────────────────────


def test_close_outside_high_low_is_flagged(db_path):
    """어떤 폭락도 close 를 [low, high] 밖으로 보내지 않는다 — 오탐이 원리적으로 없다."""
    _seed(db_path, "TST_BAD", [("2026-07-31", 100, 105, 95, 120)])

    assert ds.check_impossible_ohlc("TST_BAD", 20, db_path=db_path) == ["2026-07-31 close 가 [low, high] 밖"]


def test_high_below_low_is_flagged(db_path):
    _seed(db_path, "TST_INV", [("2026-07-31", 100, 90, 110, 100)])

    assert ds.check_impossible_ohlc("TST_INV", 20, db_path=db_path) == ["2026-07-31 high < low"]


def test_zero_price_is_flagged(db_path):
    _seed(db_path, "TST_ZERO", [("2026-07-31", 0, 0, 0, 0)])

    assert ds.check_impossible_ohlc("TST_ZERO", 20, db_path=db_path) == ["2026-07-31 0 이하 가격"]


def test_healthy_bars_are_silent(db_path):
    _seed(db_path, "TST_OK", [("2026-07-31", 100, 105, 95, 102)])

    assert ds.check_impossible_ohlc("TST_OK", 20, db_path=db_path) == []


def test_crash_day_is_not_flagged(db_path):
    """-30% 폭락은 데이터 오류가 아니다 — 자체 이력 분포를 안 쓰는 이유가 이것이다.

    회귀 잠금: z-score/백분위 기반 검사를 넣으면 진짜 폭락 때 발화하고, 그걸 죽이려
    임계를 올리다 결국 아무 말도 안 하는 검사가 된다.
    """
    _seed(
        db_path,
        "TST_CRASH",
        [("2026-07-28", 100, 100, 100, 100), ("2026-07-29", 100, 100, 70, 70)],  # -30%
    )

    assert ds.check_impossible_ohlc("TST_CRASH", 20, db_path=db_path) == []


def test_null_ohlc_does_not_crash(db_path):
    """OHLC 가 비어도 죽지 않는다 — 상류가 close 만 준 행이 실제로 있다."""
    upsert_prices(
        pd.DataFrame(
            [
                {
                    "ticker": "TST_NULL",
                    "date": "2026-07-31",
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": 100.0,
                    "volume": None,
                    "adj_close": 100.0,
                }
            ]
        ),
        db_path,
    )

    assert ds.check_impossible_ohlc("TST_NULL", 20, db_path=db_path) == []


# ── 프록시 괴리 ─────────────────────────────────────────────────────────


def test_missing_proxy_reports_its_own_inability(db_path):
    """프록시 데이터가 없으면 **그 사실을 말한다.** 조용히 통과하면 안 된다.

    회귀 잠금: 프로덕션 `069500.KS` 는 실제로 0행이다(2026-08-02 실측). `if not ref:
    return None` 로 되돌리면 KOSPI 타당성 검사가 영원히 죽은 채 초록으로 보인다.
    """
    _seed(db_path, "TST_BASE", _series("TST_BASE", [100, 101, 102]))

    msg = ds.check_proxy_divergence("TST_BASE", "TST_ABSENT", CFG, db_path=db_path)

    assert msg is not None and "데이터 없음" in msg and "검사 불가" in msg


def test_stale_proxy_reports_its_own_inability(db_path):
    """묵은 겹침으로 '이상 없음' 이라 말하면 안 된다 — dev 복제본에서 실제로 그랬다.

    회귀 잠금: lag 가드를 지우면 2개월 묵은 프록시 34행으로 최근 봉을 검사한 척한다.
    """
    _seed(
        db_path,
        "TST_B2",
        [
            ("2026-05-01", 100, 100, 100, 100),
            ("2026-05-02", 100, 100, 100, 100),
            ("2026-07-30", 100, 100, 100, 100),
            ("2026-07-31", 100, 100, 100, 100),
        ],
    )
    _seed(db_path, "TST_STALE", [("2026-05-01", 50, 50, 50, 50), ("2026-05-02", 50, 50, 50, 50)])

    msg = ds.check_proxy_divergence("TST_B2", "TST_STALE", CFG, db_path=db_path)

    assert msg is not None and "뒤처짐" in msg and "검사 불가" in msg


def test_single_overlap_day_reports_inability(db_path):
    """겹치는 날이 1일이면 수익률을 만들 수 없다 — 그것도 말한다."""
    _seed(db_path, "TST_B3", _series("TST_B3", [100, 101]))
    _seed(db_path, "TST_P1", [("2026-07-01", 50, 50, 50, 50)])

    msg = ds.check_proxy_divergence("TST_B3", "TST_P1", CFG, db_path=db_path)

    assert msg is not None and "부족" in msg


def test_divergence_1d_fires(db_path):
    """같은 시장인데 하루 수익률이 10%p 벌어지면 둘 중 하나가 틀렸다."""
    _seed(db_path, "TST_B4", _series("TST_B4", [100, 110]))  # +10%
    _seed(db_path, "TST_P2", _series("TST_P2", [100, 100]))  # 0%

    msg = ds.check_proxy_divergence("TST_B4", "TST_P2", CFG, db_path=db_path)

    assert msg is not None and "1일 수익률" in msg and "10.0%p" in msg


def test_both_moving_together_is_silent(db_path):
    """진짜 폭락이면 프록시도 같이 빠진다 — 그래서 조용하다.

    회귀 잠금: 이게 자체 이력 분포 대신 프록시 괴리를 고른 이유다. 둘 다 -25% 인데
    발화하면 검사가 시장 사건을 데이터 오류로 오인하는 것이다.
    """
    _seed(db_path, "TST_B5", _series("TST_B5", [100, 75]))
    _seed(db_path, "TST_P3", _series("TST_P3", [200, 150]))

    assert ds.check_proxy_divergence("TST_B5", "TST_P3", CFG, db_path=db_path) is None


def test_divergence_3d_catches_slow_drift(db_path):
    """매일 5%p 씩 벌어지는 피드는 1일 임계(8%p)를 한 번도 안 넘고 통과한다.

    회귀 잠금: 3일 누적 검사를 지우면 이 시나리오가 조용해진다.
    """
    _seed(db_path, "TST_B6", _series("TST_B6", [100, 105, 110.25, 115.76]))  # 매일 +5%
    _seed(db_path, "TST_P4", _series("TST_P4", [100, 100, 100, 100]))  # 매일 0%

    msg = ds.check_proxy_divergence("TST_B6", "TST_P4", CFG, db_path=db_path)

    assert msg is not None, "1일 괴리 5%p 는 임계 미달이지만 3일 누적 15.8%p 는 넘는다"
    assert "3일 누적" in msg


# ── scan / staging ──────────────────────────────────────────────────────


def test_scoped_tickers_are_the_gate_inputs():
    """검사 대상 = SIEGE freshness 기준 + 측정 벤치마크. 임의 목록이 아니다."""
    assert ds.scoped_tickers() == ["GC=F", "KOSPI", "SPY", "TLT"]


def test_scan_disabled_returns_nothing(db_path, monkeypatch):
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": False})
    assert ds.scan(db_path=db_path) == []


def test_scan_covers_every_scoped_ticker(db_path, monkeypatch):
    """대상 중 하나라도 빠뜨리면 안 된다 — 루프가 조용히 좁아지는 회귀를 잠근다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_A", "TST_B"])
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": True, "lookback_bars": 20, "proxies": {}})
    for t in ("TST_A", "TST_B"):
        _seed(db_path, t, [("2026-07-31", 100, 90, 110, 100)])  # high < low

    assert [f["ticker"] for f in ds.scan(db_path=db_path)] == ["TST_A", "TST_B"]


def test_scan_classifies_unavailable_apart_from_divergence(db_path, monkeypatch):
    """'검사 못 함' 과 '괴리 발견' 은 다른 사건이다 — 같은 라벨로 뭉치면 안 된다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_C"])
    monkeypatch.setattr(ds, "_config", lambda: {**CFG, "enabled": True, "proxies": {"TST_C": "TST_GONE"}})
    _seed(db_path, "TST_C", _series("TST_C", [100, 101]))

    assert [f["kind"] for f in ds.scan(db_path=db_path)] == ["proxy_unavailable"]


def test_staging_writes_to_ops_outbox(db_path, monkeypatch):
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_D"])
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": True, "lookback_bars": 20, "proxies": {}})
    _seed(db_path, "TST_D", [("2026-07-31", 100, 105, 95, 120)])

    staged = ds.stage_findings(db_path=db_path)

    from nuri.core.db import claim_pending_outbox

    _, rows = claim_pending_outbox("ops", db_path=db_path)
    assert staged == 1
    assert rows[0]["payload"]["kind"] == "data_sanity"
    assert "데이터 오류" in rows[0]["payload"]["summary"]


def test_divergence_card_says_it_cannot_tell_which(db_path, monkeypatch):
    """큰 괴리가 시장 사건인지 피드 오류인지 이 검사는 모른다 — 아는 척하면 안 된다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_E"])
    monkeypatch.setattr(ds, "_config", lambda: {**CFG, "enabled": True, "proxies": {"TST_E": "TST_PX"}})
    _seed(db_path, "TST_E", _series("TST_E", [100, 110]))
    _seed(db_path, "TST_PX", _series("TST_PX", [100, 100]))

    ds.stage_findings(db_path=db_path)

    from nuri.core.db import claim_pending_outbox

    _, rows = claim_pending_outbox("ops", db_path=db_path)
    summary = rows[0]["payload"]["summary"]
    assert "실제 시장 급변일 수도" in summary and "데이터 오류일 수도" in summary
    assert "freshness 는 여전히 PASS" in summary


def test_unavailable_card_is_informational_not_alarm(db_path, monkeypatch):
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_F"])
    monkeypatch.setattr(ds, "_config", lambda: {**CFG, "enabled": True, "proxies": {"TST_F": "TST_NONE"}})
    _seed(db_path, "TST_F", _series("TST_F", [100, 101]))

    ds.stage_findings(db_path=db_path)

    from nuri.core.db import claim_pending_outbox

    _, rows = claim_pending_outbox("ops", db_path=db_path)
    assert rows[0]["payload"]["summary"].startswith("ℹ️")
    assert "미실행" in rows[0]["payload"]["summary"]


def test_dedupe_same_finding(db_path, monkeypatch):
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_G"])
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": True, "lookback_bars": 20, "proxies": {}})
    _seed(db_path, "TST_G", [("2026-07-31", 100, 90, 110, 100)])

    first = ds.stage_findings(db_path=db_path)
    second = ds.stage_findings(db_path=db_path)

    assert (first, second) == (1, 0)


def _age_outbox(db_path, days):
    """이미 발송된 것처럼 만든다 — outbox dedupe 는 pending 만 막으므로 status 도 옮긴다."""
    from nuri.core.db import get_db

    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE discord_outbox SET status = 'sent', created_at = datetime('now', ?)",
            (f"-{days} days",),
        )


def test_standing_unavailable_is_not_repeated_daily(db_path, monkeypatch):
    """프록시 미수집은 상시 조건이다 — 매일 같은 카드를 올리면 #ops 전체가 무시된다.

    회귀 잠금: outbox `dedupe_key` 는 **pending 행만** 막는다. 억제 창을 지우면
    발송 다음 날부터 같은 카드가 매일 다시 올라온다.
    """
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_I"])
    monkeypatch.setattr(
        ds,
        "_config",
        lambda: {
            **CFG,
            "enabled": True,
            "proxies": {"TST_I": "TST_MIA"},
            "repeat_days_unavailable": 7,
            "repeat_days_finding": 1,
        },
    )
    _seed(db_path, "TST_I", _series("TST_I", [100, 101]))

    assert ds.stage_findings(db_path=db_path) == 1
    _age_outbox(db_path, 3)

    assert ds.stage_findings(db_path=db_path) == 0, "3일 뒤에도 억제 창(7일) 안이다"


def test_standing_unavailable_resurfaces_after_window(db_path, monkeypatch):
    """억제는 침묵이 아니다 — 창이 지나면 다시 말한다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_J"])
    monkeypatch.setattr(
        ds,
        "_config",
        lambda: {
            **CFG,
            "enabled": True,
            "proxies": {"TST_J": "TST_MIA"},
            "repeat_days_unavailable": 7,
            "repeat_days_finding": 1,
        },
    )
    _seed(db_path, "TST_J", _series("TST_J", [100, 101]))

    ds.stage_findings(db_path=db_path)
    _age_outbox(db_path, 8)

    assert ds.stage_findings(db_path=db_path) == 1


def test_real_finding_repeats_next_day(db_path, monkeypatch):
    """실제 데이터 오류는 조치 대상이다 — 상시 조건과 달리 매일 다시 알린다."""
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_K"])
    monkeypatch.setattr(
        ds,
        "_config",
        lambda: {
            "enabled": True,
            "lookback_bars": 20,
            "proxies": {},
            "repeat_days_unavailable": 7,
            "repeat_days_finding": 1,
        },
    )
    _seed(db_path, "TST_K", [("2026-07-31", 100, 90, 110, 100)])

    ds.stage_findings(db_path=db_path)
    _age_outbox(db_path, 2)

    assert ds.stage_findings(db_path=db_path) == 1, "억제 창 1일이 지났으니 다시 알린다"


def test_clean_data_stages_nothing(db_path, monkeypatch):
    monkeypatch.setattr(ds, "scoped_tickers", lambda: ["TST_H"])
    monkeypatch.setattr(ds, "_config", lambda: {"enabled": True, "lookback_bars": 20, "proxies": {}})
    _seed(db_path, "TST_H", _series("TST_H", [100, 101, 102]))

    assert ds.stage_findings(db_path=db_path) == 0


# ── 배선 · CLI ──────────────────────────────────────────────────────────


def test_scheduler_wires_the_job():
    """배선 잠금 — 스케줄러에 job 이 없으면 이 모듈은 영원히 안 돈다.

    이 레포에서 '구현했는데 배선이 없어 한 번도 안 돌았다' 가 반복됐다
    (트레일링 신호 · US 포스트마켓 브리프 · held_add). 잠근다.
    """
    from nuri.scheduler import SCHEDULES

    job = next((j for j in SCHEDULES if j["name"] == "data_sanity"), None)
    assert job is not None, "SCHEDULES 에 data_sanity job 이 없다"
    assert job["cron"] == "20 7 * * *"


def test_scheduler_job_survives_db_failure(monkeypatch, caplog):
    """관측이 스케줄러를 죽이면 안 된다 (#894)."""
    from nuri import scheduler

    monkeypatch.setattr(ds, "stage_findings", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))

    scheduler._run_data_sanity()  # 예외가 새어나오면 FAIL

    assert "실행 실패" in caplog.text


def test_scheduler_job_logs_findings(monkeypatch, caplog):
    from nuri import scheduler

    monkeypatch.setattr(ds, "stage_findings", lambda *a, **k: 3)
    scheduler._run_data_sanity()
    assert "3건 표면화" in caplog.text


def test_scheduler_job_logs_clean(monkeypatch, caplog):
    from nuri import scheduler

    monkeypatch.setattr(ds, "stage_findings", lambda *a, **k: 0)
    scheduler._run_data_sanity()
    assert "이상 없음" in caplog.text


def test_cli_reports_clean(monkeypatch, capsys):
    monkeypatch.setattr(ds, "scan", lambda *a, **k: [])
    assert ds.main([]) == 0
    assert "이상 없음" in capsys.readouterr().out


def test_cli_dry_run_lists_without_staging(monkeypatch, capsys):
    monkeypatch.setattr(ds, "scan", lambda *a, **k: [{"ticker": "TST_X", "kind": "impossible_ohlc", "detail": "d"}])
    staged = []
    monkeypatch.setattr(ds, "stage_findings", lambda *a, **k: staged.append(1))

    assert ds.main(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "TST_X" in out and "dry-run" in out
    assert staged == [], "dry-run 은 stage 하지 않는다"


def test_cli_stages_without_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(ds, "scan", lambda *a, **k: [{"ticker": "TST_Y", "kind": "impossible_ohlc", "detail": "d"}])
    monkeypatch.setattr(ds, "stage_findings", lambda *a, **k: 1)

    assert ds.main([]) == 0
    assert "staged 1건" in capsys.readouterr().out


def test_config_block_exists_and_is_read():
    """config 가 실제로 읽히는지 — 코드에 하드코딩된 임계가 있으면 여기서 안 잡히지만,
    키가 사라지면(dead config 반대 방향) 즉시 FAIL 한다."""
    cfg = ds._config()
    assert set(cfg) >= {"enabled", "lookback_bars", "divergence_1d_pp", "divergence_3d_pp", "proxy_max_lag_days"}
