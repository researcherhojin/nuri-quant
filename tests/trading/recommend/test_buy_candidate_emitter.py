"""Lock-tests for #507 BUY candidate emitter (Phase 1).

가드: 향후 sell-bias 회귀 방지. 각 gate / score path / blocked reason 별 1+ test.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from nuri.core.db import get_db, init_db, upsert_portfolio, upsert_prices
from nuri.core.rules import VIX_MAX_AGE_BUSINESS_DAYS
from nuri.core.timezone import today_kst
from nuri.quant.regime.classifier import UNKNOWN_REGIME, RegimeState
from nuri.trading.recommend.buy_candidate_emitter import (
    BuyCandidate,
    EmitResult,
    _build_why_now,
    _load_config,
    _score_ticker,
    emit_buy_candidates,
    render_markdown,
)

# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def cfg_path(tmp_path):
    """Minimal buy_signals.yaml override for deterministic tests."""
    cfg = {
        "exclude_held": True,
        "exclude_etf_leverage": True,
        "weights": {
            "factor_composite": 0.4,
            "momentum_5d": 0.25,
            "technical_rsi": 0.15,
            "breakout_30d": 0.2,
        },
        "quality_bar": {
            "base_threshold": 70,
            "max_candidates": 5,
            # 값은 출하 config 와 일부러 다르게 두되(= config 를 읽는다는 증명),
            # **키는 반드시 canonical** 이다. 이전 fixture 는 `neutral` / `bull` 을 썼는데
            # 둘 다 `ALL_REGIMES` 밖이라, 출하 config 의 같은 결함(#1130)을 이 스위트가
            # 재현조차 못 했다 — 테스트가 프로덕션이 도달 못 하는 우주를 잠그고 있었다.
            "per_regime": {"sideways_low_vol": 0, "bull_low_vol": -5, "sideways_high_vol": 999},
        },
        "gates": {
            "vix_block_above": 30,
            "vix_caution_above": 25,
            "cooldown_days": 5,
            # 출하 config 는 빈 집합(soft penalty 전용)이지만, 차단 **기구**가 살아 있음을
            # 확인하려면 fixture 에는 값이 있어야 한다.
            "blocking_regimes": ["bear_high_vol"],
        },
        "exclude_etfs": ["SOXL", "SQQQ", "TQQQ", "TSLL", "LABU"],
        "allocation": {
            "total_pct_by_regime": {"sideways_low_vol": 0.30, "bull_low_vol": 0.50},
            "unknown_regime_pct": 0.10,
            "default_pct": 0.25,
        },
        # 의도적 non-canonical (21/42): emitter 가 config 를 읽음(하드코딩 아님)을 증명.
        # 실제 출하 config 의 canonical(20/40) 정합은
        # test_buy_emitter_tp_ladder_matches_canonical_growth 가 별도로 lock.
        "risk": {"stop_pct": -7.0, "tp1_pct": 21.0, "tp2_pct": 42.0},
    }
    p = tmp_path / "buy_signals.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def _seed_factor(db_path, ticker: str, composite: float):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO factors (ticker, date, momentum_score, value_score, "
            "quality_score, sentiment_score, composite_score) "
            "VALUES (?, '2026-04-30', 0.5, 0.5, 0.5, 0.5, ?)",
            (ticker, composite),
        )


def _seed_prices(db_path, ticker: str, closes: list[float]):
    """Backfill ~45 trading days ending today.

    end 를 today 로 고정(상대일)해야 emitter 의 ``date('now', '-45 days')``
    윈도우 안에 들어온다. 고정 절대일로 두면 시간이 흐를수록 윈도우 밖으로
    밀려 ``len(grp) < 6`` 으로 skip → scored=0 회귀 (time-bomb).
    """
    dates = pd.bdate_range(end=today_kst(), periods=len(closes))
    df = pd.DataFrame(
        {
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "adj_close": closes,
        }
    )
    upsert_prices(df, db_path)


def _seed_rsi(db_path, ticker: str, rsi: float):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO signals (ticker, date, rsi_14) VALUES (?, '2026-04-30', ?)",
            (ticker, rsi),
        )


def _business_days_ago(n: int) -> str:
    """n **영업일** 전 날짜. 판정이 영업일 기준이라 시드도 그래야 한다 —
    달력일로 빼면 요일에 따라 영업일 수가 달라져 테스트가 요일 의존으로 flaky 해진다.

    ⚠️ `roll="forward"` 다 (#1270). 프로덕션은 나이를 `busday_count(observed, today)` 로
    재므로 이 헬퍼는 그 **역함수**여야 하는데, `roll="backward"` 는 오늘이 휴장일이면
    롤 자체가 영업일 1일을 먹어 왕복이 `n+1` 이 된다. 그래서 경계 시드가 임계를 넘겨
    **토·일에만** 노후로 떨어졌다. `forward` 는 7요일 전부 왕복 일치한다.
    """
    if n == 0:
        return today_kst()
    return str(np.busday_offset(today_kst(), -n, roll="forward"))


def _seed_vix(db_path, value: float, *, days_old: int = 0):
    """Seed VIX into macro (emitter reads indicator='vix' from macro — #753).

    날짜는 `today_kst()` 앵커 — 리터럴을 쓰면 `vix_gate.max_age_days` 를 넘기는 순간
    전부 '미상' 으로 떨어져 게이트 테스트가 조용히 뜻을 잃는다. 실제로 `'2026-04-30'`
    리터럴이 박혀 있었고, 신선도 검사를 넣자 3건이 한꺼번에 깨졌다
    (tests/CLAUDE.md "Time-bomb seed dates" 3차 발생).
    """
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, ?, 'test')",
            (_business_days_ago(days_old), value),
        )


#: 이번 테스트가 `classify_regime()` 에게 내게 할 레짐. `None` = 미상(분류 차단).
_REGIME: dict[str, str | None] = {"regime": None}


@pytest.fixture(autouse=True)
def _stub_classifier(monkeypatch):
    """`classify_regime()` 을 테스트가 지정한 레짐으로 고정한다.

    이전엔 `regime_transitions` 에 문자열을 직접 INSERT 했다(`_seed_regime`). 그 테이블은
    더 이상 게이트 출처가 아니고(#1131), 더 중요하게는 그 방식이 **프로덕션이 도달할 수
    없는 상태**를 만들었다 — `classify_regime()` 은 `ALL_REGIMES` 밖의 값을 내지 않는데
    스위트는 `"bear"` / `"neutral"` 을 넣고 초록이었다 (#1130). 이제 진짜 출처를 가로채
    canonical 값만 흘린다.

    기본값이 `None`(미상)인 것은 의도적이다: 레짐을 명시하지 않은 테스트는 미상 경로를
    지나가야 하고, 미상이 조용히 공격적인 배분을 받으면 그 테스트들이 깨진다.
    """
    _REGIME["regime"] = None

    def _fake(date=None, db_path=None):
        regime = _REGIME["regime"]
        if regime is None:
            return None
        trend, _, vol = regime.rpartition("_")
        return RegimeState(
            date="2026-04-30",
            trend=trend.split("_")[0] or "sideways",
            volatility="high" if "high" in regime else "low",
            regime=regime,
            confidence=0.8,
            details={},
        )

    monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _fake)


def _use_regime(regime: str | None):
    """이번 테스트가 볼 레짐 고정. `None` 이면 미상."""
    _REGIME["regime"] = regime


# --- Score / why-now ------------------------------------------------------


def test_score_ticker_high_factor():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    score, src = _score_ticker("X", {"composite": 0.9}, {"ret_5d": 5, "breakout_pct": 1}, 50, weights)
    assert 70 <= score <= 100
    assert src["factor"] == 90.0


def test_score_ticker_overbought_rsi_penalty():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, 88, weights)
    assert src["rsi"] < 30


def test_score_ticker_oversold_rsi_bonus():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, 28, weights)
    assert src["rsi"] == 60.0


def test_score_ticker_missing_rsi_neutral():
    weights = {"factor_composite": 0.4, "momentum_5d": 0.25, "technical_rsi": 0.15, "breakout_30d": 0.2}
    _, src = _score_ticker("X", {"composite": 0.5}, {"ret_5d": 0, "breakout_pct": 0}, None, weights)
    assert src["rsi"] == 50.0


def test_why_now_picks_strongest_source():
    msg = _build_why_now({"factor": 90, "momentum": 60, "rsi": 50, "breakout": 40}, {}, 50)
    assert "factor" in msg.lower() or "composite" in msg.lower()


def test_why_now_momentum():
    msg = _build_why_now(
        {"factor": 50, "momentum": 90, "rsi": 50, "breakout": 50},
        {"ret_5d": 12.5},
        50,
    )
    assert "12.5" in msg or "모멘텀" in msg


# --- Gate: VIX --------------------------------------------------------------


def test_vix_block_above_30(db, cfg_path):
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 35.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert res.blocked_reason is not None
    assert "VIX" in res.blocked_reason


def test_vix_gate_reads_macro_not_prices(db, cfg_path):
    """#753 회귀: VIX 는 macro 테이블에서 읽어야 한다 (prices.VIX 는 미수집).

    macro(indicator='vix') 에만 block 임계 초과 VIX 를 seed 하고 prices.VIX 는
    의도적으로 비운다. emitter 가 prices 경로(버그)로 되돌아가면 macro VIX 를
    무시해 vix=20.0 fallback → 차단 미발화 → FAIL.
    """
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _use_regime("sideways_low_vol")
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO macro (indicator, date, value, source) VALUES ('vix', ?, 35.0, 'test')",
            (str(today_kst()),),
        )
        # prices.VIX 행이 없음을 명시 (버그 mask 방지 가드)
        assert conn.execute("SELECT COUNT(*) FROM prices WHERE ticker='VIX'").fetchone()[0] == 0

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert res.blocked_reason is not None
    assert "VIX" in res.blocked_reason
    assert res.vix == pytest.approx(35.0)


def test_vix_caution_halves_allocation(db, cfg_path):
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 25 + [120.0, 121.0, 122.0, 123.0, 124.0, 125.0])
    _seed_rsi(db, "AAPL", 55)
    _seed_vix(db, 27.0)  # between caution(25) and block(30)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, f"expected candidate, blocked_reason={res.blocked_reason}"
    # neutral=30%, halved to 15%
    assert res.total_deploy_pct == pytest.approx(15.0, abs=0.5)


# --- Gate: VIX 미상 / 노후 (STRATEGY §2.6 Soft penalty) --------------------


def _seed_calm_setup(db):
    """caution 임계 아래(=평시) 조건 — VIX 만 바꿔가며 대조한다."""
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 25 + [120.0, 121.0, 122.0, 123.0, 124.0, 125.0])
    _seed_rsi(db, "AAPL", 55)
    _use_regime("sideways_low_vol")


def test_fresh_calm_vix_gets_full_allocation(db, cfg_path):
    """대조군 — 신선하고 낮은 VIX 는 전액. 이게 없으면 아래 두 테스트가 공허하다."""
    _seed_calm_setup(db)
    _seed_vix(db, 15.0)

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, f"blocked_reason={res.blocked_reason}"
    assert res.total_deploy_pct == pytest.approx(30.0, abs=0.5)
    assert res.vix == pytest.approx(15.0)


def test_missing_vix_halves_allocation_instead_of_passing_as_calm(db, cfg_path):
    """VIX 행이 아예 없으면 절반 포지션 — 통과가 아니다.

    2026-08-10 이전에는 `20.0` 을 지어내 **전액**이 나갔다. 20.0 이 caution(25)·
    block(30) 임계 아래라 어느 게이트도 안 걸렸기 때문이다.

    Gotcha-Test Pair: `_get_regime` 이 부재 시 숫자를 돌려주도록 되돌리거나, 호출부의
    `vix is None or vix >= VIX_CAUTION_ABOVE` 에서 None 분기를 빼면 30.0 이 나와 FAIL.
    """
    _seed_calm_setup(db)
    # VIX seed 없음

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, f"blocked_reason={res.blocked_reason}"
    assert res.vix is None, "없는 VIX 를 숫자로 지어냈다"
    assert res.total_deploy_pct == pytest.approx(15.0, abs=0.5)


def test_stale_vix_is_treated_as_unknown(db, cfg_path):
    """`max_age_days` 를 넘긴 VIX 는 '현재값' 이 아니다 — 미상 취급.

    수집기가 죽어도 `ORDER BY date DESC LIMIT 1` 은 몇 주 전 값을 계속 돌려준다.
    신선도 검사가 없으면 그 값이 무기한 현재 VIX 행세를 한다.

    Gotcha-Test Pair: `_get_regime` 의 age 검사를 지우면 stale 27.0 이 그대로 읽혀
    `res.vix == 27.0` 이 되어 FAIL.
    """
    _seed_calm_setup(db)
    _seed_vix(db, 27.0, days_old=VIX_MAX_AGE_BUSINESS_DAYS + 1)

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.vix is None, "노후 VIX 를 현재값으로 읽었다"
    assert res.total_deploy_pct == pytest.approx(15.0, abs=0.5)


def test_vix_within_max_age_is_still_used(db, cfg_path):
    """경계 — 임계 이내면 여전히 유효. 노후 판정이 과하면 상시 반포지션이 된다."""
    _seed_calm_setup(db)
    _seed_vix(db, 15.0, days_old=VIX_MAX_AGE_BUSINESS_DAYS)

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.vix == pytest.approx(15.0)
    assert res.total_deploy_pct == pytest.approx(30.0, abs=0.5)


def test_malformed_vix_row_degrades_instead_of_killing_the_emitter(db, cfg_path):
    """깨진 `macro.date` 는 상류 **데이터 결함** — emitter 전체를 죽이면 안 된다.

    조회 예외를 `(OperationalError, DatabaseError)` 로 좁히면서 파싱 경로가 무방비가
    됐다 (Codex 리뷰 P2). 결함 행 하나로 후보 산출이 통째로 멈추는 건 과잉이다.

    Gotcha-Test Pair: `vix_gate.latest_vix` 의 `except (ValueError, KeyError, IndexError)`
    를 지우면 ValueError 가 새어 이 테스트가 FAIL.
    """
    _seed_calm_setup(db)
    with get_db(db) as conn:
        conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('vix', 'not-a-date', 15.0, 'test')")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.vix is None, "깨진 행을 값으로 읽었다"
    assert res.candidates, "데이터 결함 하나로 emitter 가 멈췄다"
    assert res.total_deploy_pct == pytest.approx(15.0, abs=0.5)


def test_unknown_vix_is_not_printed_as_a_number(db, cfg_path):
    """브리핑 표기 — 미상을 `VIX=20.0` 처럼 찍으면 사용자가 측정값으로 읽는다."""
    _seed_calm_setup(db)

    res = emit_buy_candidates(config_path=cfg_path)
    md = render_markdown(res)
    assert "VIX=미상" in md, md[:300]
    assert "VIX=20.0" not in md


# --- Gate: regime ----------------------------------------------------------


def test_regime_in_the_configured_blocking_set_blocks_new_buy(db, cfg_path):
    """차단 **기구** 자체는 살아 있다 — fixture config 가 `bear_high_vol` 을 차단한다.

    이 테스트가 파라미터를 `["bear", "crash", "extreme_fear"]` 로 돌던 시절엔,
    프로덕션이 만들 수 없는 문자열을 DB 에 직접 넣고 초록이었다. `classify_regime()` 이
    낼 수 있는 값은 `ALL_REGIMES` 10개뿐이라 그 셋과 교집합이 없었기 때문이다 (#1130).
    """
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 20.0)
    _use_regime("bear_high_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "bear_high_vol" in (res.blocked_reason or "")


def test_shipped_config_softens_bear_instead_of_blocking_it(db):
    """출하 config 기준 약세 레짐의 실제 처분 — 차단이 아니라 배분 축소 (2026-08-21).

    사용자 판정: 레짐 축은 soft penalty 로만, hard veto 승격은 백테스트 후. 이 테스트가
    잠그는 것은 그 판정의 **두 절반**이다 — 차단되지 않을 것(`blocking_regimes` 가 비어
    있음)과, 그렇다고 강세장과 같은 배분을 받지도 않을 것(0.10).

    `default_pct`(0.30) 와 다른 값이어야 의미가 있다: 같으면 표에서 지워도 통과한다.
    """
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 30 + [130.0])
    _seed_vix(db, 20.0)
    _use_regime("bear_high_vol")

    res = emit_buy_candidates()  # 출하 config
    assert res.blocked_reason is None or "방어 모드" not in res.blocked_reason
    assert res.total_deploy_pct == pytest.approx(10.0, abs=0.5)


def test_stale_regime_transitions_row_no_longer_governs_the_gate(db, cfg_path, monkeypatch):
    """#1131 잠금 — 게이트는 `regime_transitions` 를 더 이상 읽지 않는다.

    그 테이블의 유일한 writer 를 부르는 예약 job 이 없어 값이 임의로 낡는다(실측 121일).
    여기서는 차단 레짐을 **테이블에** 심고, 분류기는 양성 레짐을 내게 둔다. 게이트가
    테이블로 되돌아가면 후보가 0 이 되어 이 테스트가 실패한다.
    """
    from nuri.core.db import get_db as _get_db

    with _get_db(db) as conn:
        conn.execute(
            "INSERT INTO regime_transitions (date, from_regime, to_regime, action_taken) "
            "VALUES ('2026-04-21', 'recovery', 'bear_high_vol', 'stale')",
        )
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.regime == "sideways_low_vol"
    assert res.candidates != []


def test_unclassifiable_market_is_unknown_and_gets_the_conservative_slice(db, cfg_path):
    """미상은 레짐이 아니다 — 조정 표에 매치되지 않고 별도 보수 배분을 받는다.

    이전엔 미상 라벨이 `"neutral"` 이었고 `total_pct_by_regime` 에 `neutral: 0.40` 이
    있어서 **레짐을 모를 때 표에서 가장 공격적인 배분**이 나갔다 (#1131).
    fixture 는 미상 0.10 / 최대 0.50 이라 두 값이 갈린다.
    """
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 20.0)
    _use_regime(None)  # classify_regime() → None

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.regime == UNKNOWN_REGIME
    assert res.candidates != []
    assert res.total_deploy_pct == pytest.approx(10.0, abs=0.5)


def test_a_canonical_regime_absent_from_the_table_uses_the_declared_default(db, cfg_path):
    """표에 없는 정식 레짐은 `default_pct` 로 — 지어낸 값이 아니라 **선언된** 기본값.

    fixture 의 default 는 0.25 이고 미상(0.10) · 등재 레짐(0.30/0.50) 어느 것과도 다르다.
    """
    _seed_factor(db, "AAPL", 0.9)
    _seed_prices(db, "AAPL", [100.0] * 30 + [120.0])
    _seed_vix(db, 20.0)
    _use_regime("recovery")  # canonical 이지만 fixture 표에 없음

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.regime == "recovery"
    assert res.total_deploy_pct == pytest.approx(25.0, abs=0.5)


def test_regime_threshold_999_blocked(db, cfg_path):
    """sideways_high_vol regime → per_regime adj 999 → effective block."""
    _seed_factor(db, "AAPL", 0.99)
    _seed_prices(db, "AAPL", [100.0] * 30 + [200.0])
    _seed_vix(db, 20.0)
    _use_regime("sideways_high_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "999" in (res.blocked_reason or "") or "차단" in (res.blocked_reason or "")


# --- Gate: held / cooldown / leverage --------------------------------------


def test_held_ticker_skipped(db, cfg_path):
    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": "AAPL",
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db,
    )
    _seed_factor(db, "AAPL", 0.95)
    _seed_prices(db, "AAPL", [100.0] * 30 + [200.0])
    _seed_rsi(db, "AAPL", 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert "AAPL" in res.skipped
    assert "held" in res.skipped["AAPL"].lower()


def test_cooldown_ticker_skipped(db, cfg_path):
    _seed_factor(db, "MSFT", 0.95)
    _seed_prices(db, "MSFT", [100.0] * 30 + [200.0])
    _seed_rsi(db, "MSFT", 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO pipeline_events (timestamp, event_type, payload) "
            "VALUES (datetime('now', '-1 days'), 'holdings_monitor_alert', '{\"ticker\": \"MSFT\"}')"
        )

    res = emit_buy_candidates(config_path=cfg_path)
    assert "MSFT" in res.skipped
    assert "cooldown" in res.skipped["MSFT"].lower()


def test_shipped_exclude_etfs_omits_nonleveraged_soxx():
    """#761: 출하 config exclude_etfs 는 레버리지/인버스만 — 비레버리지 SOXX 는 제외 X (BUY 가능)."""
    import yaml

    from nuri.trading.recommend.buy_candidate_emitter import CONFIG_PATH

    etfs = set(yaml.safe_load(CONFIG_PATH.read_text())["exclude_etfs"])
    assert "SOXX" not in etfs  # 비레버리지 반도체 ETF — 과거 하드코딩 버그로 오제외됨
    assert {"SOXL", "TQQQ", "TSLL", "LABU"} <= etfs  # 레버리지/인버스는 제외 유지


@pytest.mark.parametrize("etf", ["SOXL", "TQQQ", "TSLL", "LABU"])
def test_leverage_etf_skipped(db, cfg_path, etf):
    # exclude_etfs (config) 에 등재된 레버리지 ETF 는 BUY 후보에서 제외 (#761)
    _seed_factor(db, etf, 0.95)
    _seed_prices(db, etf, [100.0] * 30 + [200.0])
    _seed_rsi(db, etf, 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert etf in res.skipped
    assert "leverage" in res.skipped[etf].lower()


# --- Empty data path -------------------------------------------------------


def test_empty_factors_blocked(db, cfg_path):
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "factors" in (res.blocked_reason or "")


def test_below_threshold_blocked(db, cfg_path):
    _seed_factor(db, "WEAK", 0.30)
    _seed_prices(db, "WEAK", [100.0] * 30 + [99.0])  # flat
    _seed_rsi(db, "WEAK", 50)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates == []
    assert "threshold" in (res.blocked_reason or "")


# --- Happy path: emit + risk levels ----------------------------------------


def test_emit_reports_the_denominator(db, cfg_path):
    """채점 규모와 임계를 결과에 실어야 미실행 원장이 "왜 0건이었나" 를 답할 수 있다 (#1094).

    이게 없으면 원장은 늘 `n_scored=0` 을 적고, "채점 대상이 0" 과 "200개 채점했는데
    아무도 임계를 못 넘음" 이 구분되지 않는다.

    Mutation lock: `result.n_scored`/`n_qualified` 대입을 지우면 0 이 되어 FAIL.
    """
    _seed_factor(db, "STRONG", 0.95)
    _seed_prices(db, "STRONG", [100.0] * 25 + [110.0, 115.0, 120.0, 125.0, 130.0, 135.0])
    _seed_rsi(db, "STRONG", 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.n_scored >= 1, "채점 규모가 결과에 안 실렸다"
    assert res.n_qualified >= 1
    assert res.threshold is not None, "임계가 결과에 안 실렸다"


def test_emit_above_threshold(db, cfg_path):
    _seed_factor(db, "STRONG", 0.95)
    _seed_prices(db, "STRONG", [100.0] * 25 + [110.0, 115.0, 120.0, 125.0, 130.0, 135.0])
    _seed_rsi(db, "STRONG", 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c.ticker == "STRONG"
    assert c.score >= 70
    # entry≈135, stop=-7%, tp1=+21%, tp2=+42%
    assert c.stop == pytest.approx(c.entry * 0.93, abs=0.5)
    assert c.tp1 == pytest.approx(c.entry * 1.21, abs=0.5)
    assert c.tp2 == pytest.approx(c.entry * 1.42, abs=0.5)


def test_allocation_split_by_score(db, cfg_path):
    _seed_factor(db, "S1", 0.95)
    _seed_factor(db, "S2", 0.85)
    for t in ("S1", "S2"):
        _seed_prices(db, t, [100.0] * 25 + [110, 115, 120, 125, 130, 135])
        _seed_rsi(db, t, 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    res = emit_buy_candidates(config_path=cfg_path)
    assert len(res.candidates) == 2
    deploy_sum = sum(c.deploy_pct for c in res.candidates)
    # neutral=30%, no caution → total 30%
    assert deploy_sum == pytest.approx(30.0, abs=0.5)
    # higher score gets larger deploy
    sorted_by_score = sorted(res.candidates, key=lambda c: c.score, reverse=True)
    assert sorted_by_score[0].deploy_pct >= sorted_by_score[1].deploy_pct


# --- Render markdown -------------------------------------------------------


def test_render_blocked():
    r = EmitResult(blocked_reason="VIX 35.0 > 30", regime="neutral", vix=35.0)
    md = render_markdown(r)
    assert "BUY Candidates (0 — blocked)" in md
    assert "VIX 35.0 > 30" in md


def test_render_with_candidates():
    r = EmitResult(
        candidates=[
            BuyCandidate(
                ticker="MSFT",
                score=82,
                deploy_pct=20.0,
                entry=400.0,
                stop=372.0,
                tp1=484.0,
                tp2=568.0,
                why_now="Multi-factor 상위",
                sources={"factor": 90},
            )
        ],
        regime="neutral",
        vix=20.0,
        total_deploy_pct=20.0,
        timestamp_kst="2026-04-30 02:00:00 KST",
    )
    md = render_markdown(r)
    assert "MSFT" in md
    assert "82/100" in md
    assert "Entry $400.0" in md
    assert "Stop $372.0" in md
    assert "Multi-factor 상위" in md


def test_render_markdown_tp_label_derived_from_price():
    """라벨의 %는 가격에서 파생되어야 한다 (하드코딩 literal 금지).

    과거 render_markdown 이 (-7%)/(+21%)/(+42%) 를 하드코딩해, 값을 20/40 으로
    바꾼 뒤에도 brief 라벨은 +21/+42 로 표시되는 모순이 있었다 (codex P2).
    entry=100, stop=93, tp1=120, tp2=140 → 라벨 -7% / +20% / +40%.
    """
    r = EmitResult(
        candidates=[
            BuyCandidate(
                ticker="ZZZ",
                score=80,
                deploy_pct=10.0,
                entry=100.0,
                stop=93.0,
                tp1=120.0,
                tp2=140.0,
                why_now="x",
                sources={"factor": 90},
            )
        ],
        regime="neutral",
        vix=20.0,
        total_deploy_pct=10.0,
        timestamp_kst="2026-04-30 02:00:00 KST",
    )
    md = render_markdown(r)
    assert "(-7%)" in md
    assert "(+20%)" in md
    assert "(+40%)" in md
    # 옛 하드코딩 회귀 방지
    assert "(+21%)" not in md and "(+42%)" not in md


# --- Config load -----------------------------------------------------------


def test_load_config_defaults():
    cfg = _load_config()  # uses package CONFIG_PATH
    assert "weights" in cfg
    assert "gates" in cfg
    assert "risk" in cfg
    # VIX 임계는 buy_signals.yaml 이 아닌 rules.yaml(core.rules)이 canonical (#760).
    from nuri.core.rules import VIX_BLOCK_ABOVE

    assert VIX_BLOCK_ABOVE == 30


def test_emit_result_dataclass_defaults():
    r = EmitResult()
    assert r.candidates == []
    assert r.skipped == {}
    assert r.blocked_reason is None


# --- Brief integration sanity (#507 → premarket_brief) --------------------


def test_brief_surfaces_buy_candidates(db, cfg_path):
    """premarket_brief._collect_context() must surface emitter output."""
    _seed_factor(db, "STRONG", 0.95)
    _seed_prices(db, "STRONG", [100.0] * 25 + [110, 115, 120, 125, 130, 135])
    _seed_rsi(db, "STRONG", 55)
    _seed_vix(db, 20.0)
    _use_regime("sideways_low_vol")

    # emitter reads CONFIG_PATH, not config_path arg in _collect_context.
    # Patch CONFIG_PATH so the brief picks up our test config.
    import nuri.trading.recommend.buy_candidate_emitter as emitter_mod

    with patch.object(emitter_mod, "CONFIG_PATH", cfg_path):
        from nuri.alerts.premarket_brief import _collect_context

        ctx = _collect_context()

    bc = ctx.get("buy_candidates")
    assert bc is not None, "buy_candidates ctx key missing — brief integration broken"
    # 1 emitted (STRONG only) — others non-existent in fresh DB
    assert any(c.ticker == "STRONG" for c in bc.candidates) or bc.blocked_reason


def test_buy_emitter_tp_ladder_matches_canonical_growth():
    """SSoT lock: BUY emitter 출하 config 의 TP 사다리는 rules.yaml
    take_profit.growth (canonical 20/40) 와 일치해야 한다.

    buy_signals.yaml 가 canonical 에서 다시 fork (예: 21/42) 하면 실패한다.
    근거: brief(+21%) vs /targets(+20%) 운영자-facing 모순 회귀 방지
    (recommend/CLAUDE.md "price_targets.py canonical — caller 재유도 금지").
    """
    from nuri.core.rules import TAKE_PROFIT_GROWTH

    risk = _load_config().get("risk", {})  # 실제 config/buy_signals.yaml 로드
    assert risk["tp1_pct"] == TAKE_PROFIT_GROWTH["target_1"], (
        f"buy_signals tp1_pct={risk.get('tp1_pct')} != canonical "
        f"{TAKE_PROFIT_GROWTH['target_1']} (rules.yaml take_profit.growth)"
    )
    assert risk["tp2_pct"] == TAKE_PROFIT_GROWTH["target_2"], (
        f"buy_signals tp2_pct={risk.get('tp2_pct')} != canonical "
        f"{TAKE_PROFIT_GROWTH['target_2']} (rules.yaml take_profit.growth)"
    )


# --- Thesis Surface (#1165) --------------------------------------------------


def _register_thesis(db, ticker, status="active"):
    from nuri.core.db.thesis_ops import add_criteria, upsert_thesis

    tid = upsert_thesis(
        ticker=ticker,
        author="user",
        stance="bullish",
        bull_case="테스트 상승 논지",
        bear_case="테스트 하락 논지",
        evidence=[{"side": "bull", "claim": "테스트", "source_type": "measurement"}],
        status=status,
        db_path=db,
    )
    add_criteria(
        tid,
        [{"kind": "machine", "statement": "테스트 기준", "metric": "close", "op": "<", "threshold": 1}],
        db_path=db,
    )
    return tid


def test_candidate_surfaces_active_thesis(db, cfg_path):
    """active 논지가 있으면 후보에 라벨이 붙는다 — emit 진입점 통과 잠금 (wiring axis)."""
    _seed_calm_setup(db)
    _register_thesis(db, "AAPL", status="active")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, f"blocked_reason={res.blocked_reason}"
    assert res.candidates[0].thesis == "v1 bullish"

    md = render_markdown(res)
    assert "Thesis: ✓ v1 bullish" in md


def test_candidate_without_thesis_surfaces_absence_not_block(db, cfg_path):
    """논지 없음은 Surface 만 — 후보를 막지 않는다 (Escalation §2.6 Surface 등급)."""
    _seed_calm_setup(db)

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates, "논지 부재가 emit 을 막으면 Surface 가 아니라 gate 다"
    assert res.candidates[0].thesis is None

    md = render_markdown(res)
    assert "Thesis: 없음" in md


def test_draft_thesis_counts_as_absent(db, cfg_path):
    """draft 는 결정 화면에 붙지 않는다 — 원장 규약과 동일하게 없음 취급."""
    _seed_calm_setup(db)
    _register_thesis(db, "AAPL", status="draft")

    res = emit_buy_candidates(config_path=cfg_path)
    assert res.candidates
    assert res.candidates[0].thesis is None


class TestBusinessDaysAgoIsTheInverseOfBusdayCount:
    """시드 헬퍼는 프로덕션 나이 계산의 **역함수**여야 한다 (#1270).

    `vix_gate.latest_vix` 는 `np.busday_count(observed, today)` 로 나이를 잰다.
    헬퍼가 그 역함수가 아니면 "임계 이내" 로 시드한 행이 임계를 넘어버려,
    경계 테스트가 **코드와 무관하게** 특정 요일에만 빨간불이 된다.

    `roll="backward"` 는 오늘이 휴장일일 때 롤이 영업일 1일을 소비해 왕복이
    `n+1` 이 됐다 — 2026-08-29(토) 에 `test_vix_within_max_age_is_still_used` 가
    실제로 이렇게 깨졌다. 요일 의존이라 평일에는 5/7 확률로 조용했다.
    """

    # 월~일 전부. 요일 하나만 보면 그게 하필 통과하는 요일일 수 있다.
    @pytest.mark.parametrize(
        "anchor",
        ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-29", "2026-08-30"],
    )
    @pytest.mark.parametrize("n", [1, 2, 3])
    def test_round_trip_holds_on_every_weekday(self, anchor, n, monkeypatch):
        """Mutation lock: `roll="forward"` → `"backward"` 로 되돌리면 토·일에서 FAIL."""
        # ⚠️ 문자열 타깃(`"tests.trading...today_kst"`)은 여기서 **조용히 no-op** 이다.
        # `tests/` 가 패키지가 아니라 이 모듈이 다른 이름으로 로드돼 있고, 문자열은
        # 같은 파일의 *두 번째 사본*을 import 해 거기를 패치한다 — 실행 중인 사본은
        # 그대로다. 실제로 그렇게 짰다가 평일 앵커 15개가 전부 FAIL 했다
        # (`today_kst` 가 진짜 오늘을 계속 반환). `sys.modules[__name__]` 은 실행 중인
        # 사본 자신이라 이름 규칙과 무관하다 (tests/CLAUDE.md "conftest import 경로").
        monkeypatch.setattr(sys.modules[__name__], "today_kst", lambda: anchor)
        seeded = _business_days_ago(n)
        age = int(np.busday_count(seeded, anchor))
        assert age == n, f"{anchor} 기준 {n}영업일 전으로 시드했는데 나이가 {age} 로 읽힌다"

    def test_boundary_seed_is_not_judged_stale(self, monkeypatch):
        """임계와 같은 나이는 노후가 아니다 — 게이트가 `age > MAX` 로 판정하므로."""
        monkeypatch.setattr(sys.modules[__name__], "today_kst", lambda: "2026-08-29")
        age = int(np.busday_count(_business_days_ago(VIX_MAX_AGE_BUSINESS_DAYS), "2026-08-29"))
        assert age <= VIX_MAX_AGE_BUSINESS_DAYS
