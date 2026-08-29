"""Held add-mode emitter — #518 phase 2a (shadow mode 14d).

3 modes (precedence + mutual exclusion):
  1. tp1_residual_add (precedence 1) — 최근 TRIM 후 잔여 포지션 add (breakout 위)
  2. ride_winner    (precedence 2) — winner momentum add (cap headroom 활용)
  3. average_down   (precedence 3) — pullback add (RSI 과매도 + macro veto)

Multi-account: same ticker held in 2 accounts → 2 independent (ticker, account) emits
(derive_position_cap from nuri.core.account_cap).

Earnings blackout: earnings_date ± N days → 모든 mode 차단 (Qwen risk).

Shadow mode: held_add_mode.shadow_mode_until 까지 → held_add_shadow 테이블 only,
brief surface 안 함. 14d × ~5 emits/day = ~70 sample 누적 후 2c calibration.

Spec: docs/plans/507_buy_candidate_emitter_phase2_spec.md §4.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from nuri.core.account_cap import derive_position_cap
from nuri.core.db import get_db, query_df
from nuri.core.rules import TAKE_PROFIT_GROWTH
from nuri.core.timezone import kst_now, today_kst
from nuri.quant.regime.classifier import UNKNOWN_REGIME

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "buy_signals.yaml"

# Mode precedence (낮을수록 먼저 emit). spec §4.1.
MODE_PRECEDENCE: dict[str, int] = {
    "tp1_residual_add": 1,
    "ride_winner": 2,
    "average_down": 3,
}


@dataclass
class HeldAddCandidate:
    """Single (ticker, account) held add emit."""

    ticker: str
    account: str
    mode: str  # tp1_residual_add | ride_winner | average_down
    score: float  # composite score (0-100)
    pnl_pct: float
    current_pct: float  # per-account 현재 비중
    cap_max_pct: float
    headroom_pct: float
    why_now: str
    sources: dict[str, Any] = field(default_factory=dict)


@dataclass
class HeldAddResult:
    """Output of one held_add emit run."""

    candidates: list[HeldAddCandidate] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # "ticker@account" → reason
    shadow_mode: bool = True
    shadow_mode_until: str = ""
    timestamp_kst: str = ""


def _load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config/buy_signals.yaml (held_add_mode block only) — path injectable for tests."""
    p = path or CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_shadow_mode(cfg: dict, today: Optional[date] = None) -> bool:
    """shadow_mode_until 보다 today 가 작거나 같으면 shadow ON."""
    today = today or date.fromisoformat(today_kst())
    until_str = cfg.get("shadow_mode_until")
    if not until_str:
        return False
    try:
        until = date.fromisoformat(str(until_str))
    except (ValueError, TypeError):
        return False
    return today <= until


def is_in_earnings_blackout(
    ticker: str,
    days: int = 5,
    today: Optional[date] = None,
    fetcher: Optional[Any] = None,
) -> bool:
    """earnings_date ± `days` 안에 있으면 True (blackout, held_add 차단).

    Args:
        ticker: 평가 대상.
        days: blackout 윈도우 (±일).
        today: KST 기준 today (테스트 주입용).
        fetcher: yf.Ticker compatible. None 이면 yfinance.Ticker live fetch.

    Returns:
        True 면 blackout (held_add 차단). 데이터 부재 / 예외 시 False (보수적
        — fail-open. earnings 가 안 잡히면 차단보다 진행이 낫다, spec §4.4
        에선 catalog miss 를 명시 안 함; 운영에서 false-negative 가 커버됨).
    """
    today = today or date.fromisoformat(today_kst())
    try:
        if fetcher is None:
            import yfinance as yf

            fetcher = yf.Ticker(ticker.upper())
        cal = getattr(fetcher, "calendar", None) or {}
        earnings_dates = cal.get("Earnings Date") or []
        if not earnings_dates:
            return False
        earnings_date = earnings_dates[0]
        if hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        if not isinstance(earnings_date, date):
            return False
        delta = abs((earnings_date - today).days)
        return delta <= days
    except Exception as e:
        logger.warning("earnings blackout check failed for %s: %s", ticker, e)
        return False


def _get_real_accounts() -> set[str]:
    """실계좌 집합 — 판별은 `nuri.core.rules.get_real_accounts()` 가 canonical."""
    from nuri.core.rules import get_real_accounts

    return get_real_accounts()


def _get_held_positions(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """portfolio 테이블 + 최신 가격 join — (ticker, account, qty, avg_price, current_price, pnl_pct).

    real_accounts (yaml substantive) 만 surface — test/sample/legacy stale 제외.
    days_held 는 portfolio 테이블에 timestamp 필드가 없어 fallback 30 — **측정값이
    아니다** (#1173 would-fire 원장은 그래서 이 값을 기록하지 않는다).
    """
    df = query_df(
        """SELECT p.account, p.ticker, p.quantity AS qty, p.avg_price,
                  pr.close AS current_price
             FROM portfolio p
             LEFT JOIN (
                 SELECT ticker, close FROM prices
                 WHERE (ticker, date) IN (
                     SELECT ticker, MAX(date) FROM prices GROUP BY ticker
                 )
             ) pr ON p.ticker = pr.ticker""",
        db_path=db_path,
    )
    if df.empty:
        return []
    real_accounts = _get_real_accounts()
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        if real_accounts and str(row["account"]) not in real_accounts:
            continue
        avg = float(row["avg_price"] or 0)
        cur = float(row["current_price"] or 0) or avg
        if avg <= 0 or float(row["qty"] or 0) <= 0:
            continue
        pnl_pct = (cur - avg) / avg * 100.0
        out.append(
            {
                "ticker": str(row["ticker"]),
                "account": str(row["account"]),
                "qty": float(row["qty"]),
                "avg_price": avg,
                "current_price": cur,
                "pnl_pct": pnl_pct,
                "days_held": 30,  # fallback — portfolio 테이블에 entry_date 없음
            }
        )
    return out


def _get_last_trim_age_days(ticker: str, max_days: int = 60, db_path: Optional[Path] = None) -> Optional[int]:
    """최근 trim_action 이벤트 age (일). 없으면 None.

    `pipeline_events.payload.action_type='trim_action'` (#517 Phase 2b 기준).
    """
    df = query_df(
        f"""SELECT MAX(timestamp) AS last_ts
              FROM pipeline_events
             WHERE json_extract(payload, '$.ticker') = ?
               AND json_extract(payload, '$.action_type') = 'trim_action'
               AND timestamp >= datetime('now', '-{max_days} days')""",
        params=(ticker,),
        db_path=db_path,
    )
    if df.empty or df["last_ts"].iloc[0] is None:
        return None
    last_ts = str(df["last_ts"].iloc[0])
    try:
        from datetime import datetime as _dt

        last_date = _dt.fromisoformat(last_ts.split(" ")[0]).date()
        today = date.fromisoformat(today_kst())
        return (today - last_date).days
    except Exception:
        return None


def _get_account_strategy_profile(account: str) -> dict[str, Any]:
    """rules.yaml::account_strategies[strategy] 반환 — stop_loss / max_single_position 등."""
    from nuri.core.rules import get_account_strategy

    return get_account_strategy(account)


def _evaluate_tp1_residual_add(
    pos: dict[str, Any],
    cfg: dict,
    score: float,
    breakout_above_trim: bool,
    score_min_override: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """precedence=1. 최근 trim_action 후 잔여 add.

    score_min_override: config 임계 대신 쓸 값 (#1173 would-fire 측정 전용 —
    -inf 를 주면 score 외 조건만 평가한다). None = 기존 동작.

    Returns: trigger 충족 시 mode name, else None.
    """
    trig = cfg.get("modes", {}).get("tp1_residual_add", {}).get("trigger", {})
    if not trig:
        return None

    last_trim_age = _get_last_trim_age_days(
        pos["ticker"], max_days=int(trig.get("last_trim_age_days_max", 60)), db_path=db_path
    )
    if last_trim_age is None:
        return None
    if last_trim_age < int(trig.get("last_trim_age_days_min", 5)):
        return None
    if last_trim_age > int(trig.get("last_trim_age_days_max", 60)):
        return None

    profile = _get_account_strategy_profile(pos["account"])
    tp1_pct = abs(float(profile.get("tp1_pct", TAKE_PROFIT_GROWTH["target_1"])))
    pnl_threshold = tp1_pct * float(trig.get("unrealized_pnl_min_factor", 1.2))
    if pos["pnl_pct"] < pnl_threshold:
        return None

    score_min = score_min_override if score_min_override is not None else float(trig.get("composite_score_min", 75))
    if score < score_min:
        return None

    if trig.get("require_breakout_above_last_trim_price", True) and not breakout_above_trim:
        return None

    return "tp1_residual_add"


def _evaluate_ride_winner(
    pos: dict[str, Any],
    cfg: dict,
    score: float,
    sector_mom: float,
    score_min_override: Optional[float] = None,
) -> Optional[str]:
    """precedence=2. winner momentum add."""
    trig = cfg.get("modes", {}).get("ride_winner", {}).get("trigger", {})
    if not trig:
        return None

    profile = _get_account_strategy_profile(pos["account"])
    tp1_pct = abs(float(profile.get("tp1_pct", TAKE_PROFIT_GROWTH["target_1"])))
    pnl_threshold = tp1_pct * float(trig.get("unrealized_pnl_min_factor", 2.5))
    if pos["pnl_pct"] < pnl_threshold:
        return None

    if pos["days_held"] < int(trig.get("days_held_min", 30)):
        return None

    score_min = score_min_override if score_min_override is not None else float(trig.get("composite_score_min", 75))
    if score < score_min:
        return None

    if sector_mom < float(trig.get("sector_momentum_min", 5)):
        return None

    return "ride_winner"


def _evaluate_average_down(
    pos: dict[str, Any],
    cfg: dict,
    score: float,
    rsi: Optional[float],
    regime: str,
    vix: Optional[float],
    score_min_override: Optional[float] = None,
) -> Optional[str]:
    """precedence=3. pullback add (RSI 과매도 + macro veto)."""
    trig = cfg.get("modes", {}).get("average_down", {}).get("trigger", {})
    if not trig:
        return None

    profile = _get_account_strategy_profile(pos["account"])
    stop_loss = float(profile.get("stop_loss", -7))  # 음수 (e.g. -7, -10)

    pnl_min = stop_loss * float(trig.get("unrealized_pnl_min_factor", 0.3))  # core: -10×0.3=-3
    pnl_max = stop_loss * float(trig.get("unrealized_pnl_max_factor", 0.7))  # core: -10×0.7=-7
    # window: pnl_max ≤ pnl ≤ pnl_min (둘 다 음수, max 가 더 음수)
    lower, upper = sorted([pnl_min, pnl_max])
    if not (lower <= pos["pnl_pct"] <= upper):
        return None

    score_min = score_min_override if score_min_override is not None else float(trig.get("composite_score_min", 80))
    if score < score_min:
        return None

    if rsi is None or rsi > float(trig.get("rsi_max", 35)):
        return None

    if pos["days_held"] < int(trig.get("days_held_min", 14)):
        return None

    # macro veto: 레짐 목록 + 미상 + VIX < 28
    if trig.get("macro_veto", True):
        # 목록은 config SSoT (#1130). 코드에 `{bear, crash}` 로 박혀 있었는데 둘 다
        # `ALL_REGIMES` 밖이라 `classify_regime()` 이 내는 어떤 값과도 겹치지 않았다 —
        # macro veto 의 레짐 절반이 도입 이래 한 번도 발화하지 못했다는 뜻이다.
        # (VIX 절반은 #1076 에서 고쳐져 정상 동작해 왔다.)
        if regime in set(trig.get("macro_veto_regimes") or []):
            return None
        # 레짐 미상도 veto 다 — 바로 아래 VIX 미측정과 같은 논리다 (#1131). 이 경로의
        # regime 은 `scheduler.py` 가 `buy_candidate_emitter._get_regime()` 결과를
        # 그대로 넘긴 값이고, 그쪽이 분류 실패·데이터 노후를 `UNKNOWN_REGIME` 으로
        # 표면화한다. "거시가 무서우면 물타기 금지" 에서 미상은 **거시가 평온하다는
        # 확인이 안 된** 상태이므로 통과시키면 안 된다.
        if regime == UNKNOWN_REGIME:
            return None
        # VIX 미측정(None)은 **veto** 다. `_get_regime()` 이 부재·조회실패·노후를
        # 20.0 으로 메우지 않고 None 을 돌려주기 때문에(#753) 여기로 들어온다.
        # macro_veto 의 의미는 "거시가 무서우면 물타기 금지"이고, 미측정은 거시가
        # 평온하다는 **확인이 안 된** 상태다 — 통과시키면 측정 실패가 조용히 매수
        # 조건을 여는 그 형태가 된다. 예전엔 `None >= 28` 로 TypeError 를 냈고,
        # 스케줄러가 그걸 삼켜 VIX 수집이 끊긴 날 잡이 조용히 아무것도 안 했다 (#1076).
        if vix is None or vix >= 28:
            return None

    return "average_down"


def select_held_mode(
    pos: dict[str, Any],
    cfg: dict,
    score: float,
    rsi: Optional[float],
    regime: str,
    vix: Optional[float],
    breakout_above_trim: bool = False,
    sector_mom: float = 0.0,
    score_min_override: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """precedence-sorted mutual exclusion. Returns first triggered mode or None.

    spec §4.3 — within (ticker, account, session) tuple emit at most ONE.
    """
    for mode_name in sorted(MODE_PRECEDENCE.keys(), key=lambda m: MODE_PRECEDENCE[m]):
        if mode_name == "tp1_residual_add":
            r = _evaluate_tp1_residual_add(
                pos, cfg, score, breakout_above_trim, score_min_override=score_min_override, db_path=db_path
            )
        elif mode_name == "ride_winner":
            r = _evaluate_ride_winner(pos, cfg, score, sector_mom, score_min_override=score_min_override)
        elif mode_name == "average_down":
            r = _evaluate_average_down(pos, cfg, score, rsi, regime, vix, score_min_override=score_min_override)
        else:
            r = None
        if r:
            return r
    return None


def evaluate_mode_gates(
    pos: dict[str, Any],
    cfg: dict,
    rsi: Optional[float],
    regime: str,
    vix: Optional[float],
    breakout_above_trim: bool = False,
    sector_mom: float = 0.0,
    db_path: Optional[Path] = None,
) -> dict[str, bool]:
    """mode 별 **score 외 조건** 통과 여부 (#1173 would-fire 측정 축).

    각 evaluator 를 score 임계 -inf 로 호출해 score 게이트만 무력화한다 — 나머지
    조건(pnl 창·trim age·RSI·macro veto·days_held)은 라이브와 동일 코드가 평가하므로
    측정 경로와 실주행 경로가 갈라질 수 없다. `select_held_mode(...)` 는
    "gates[m] ∧ score ≥ 임계" 의 첫 precedence 와 동치다 (잠금 테스트가 고정).
    """
    no_score_gate = float("-inf")
    return {
        "tp1_residual_add": _evaluate_tp1_residual_add(
            pos, cfg, 0.0, breakout_above_trim, score_min_override=no_score_gate, db_path=db_path
        )
        is not None,
        "ride_winner": _evaluate_ride_winner(pos, cfg, 0.0, sector_mom, score_min_override=no_score_gate) is not None,
        "average_down": _evaluate_average_down(pos, cfg, 0.0, rsi, regime, vix, score_min_override=no_score_gate)
        is not None,
    }


def _safe_headroom(pos: dict[str, Any], db_path: Optional[Path]) -> Optional[float]:
    """측정 행용 headroom — 조회 실패는 None (blackout 경로에서도 run 을 못 죽인다)."""
    try:
        return derive_position_cap(pos["ticker"], pos["account"], db_path=db_path)["headroom_pct"]
    except Exception:
        logger.debug("would-fire headroom 조회 실패: %s@%s", pos["ticker"], pos["account"], exc_info=True)
        return None


def current_mode_thresholds(cfg: dict) -> dict[str, float]:
    """config 의 mode 별 composite_score_min — evaluator 내부 기본값(75/75/80)과 동일 소스."""
    modes = cfg.get("modes", {})
    return {
        "tp1_residual_add": float(modes.get("tp1_residual_add", {}).get("trigger", {}).get("composite_score_min", 75)),
        "ride_winner": float(modes.get("ride_winner", {}).get("trigger", {}).get("composite_score_min", 75)),
        "average_down": float(modes.get("average_down", {}).get("trigger", {}).get("composite_score_min", 80)),
    }


def _persist_shadow(
    candidate: HeldAddCandidate,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """held_add_shadow 테이블에 1 row insert."""
    payload = {
        "score": candidate.score,
        "pnl_pct": candidate.pnl_pct,
        "why_now": candidate.why_now,
        "sources": candidate.sources,
    }
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO held_add_shadow
                 (ticker, account, mode, score, current_pct, cap_max_pct,
                  headroom_pct, payload_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate.ticker,
                candidate.account,
                candidate.mode,
                candidate.score,
                candidate.current_pct,
                candidate.cap_max_pct,
                candidate.headroom_pct,
                json.dumps(payload, ensure_ascii=False),
                run_id,
            ),
        )


def emit_held_add_shadow(
    config_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    today: Optional[date] = None,
    earnings_fetcher_factory: Optional[Any] = None,
    score_provider: Optional[Any] = None,
    rsi_provider: Optional[Any] = None,
    regime_provider: Optional[Any] = None,
    sector_mom_provider: Optional[Any] = None,
    breakout_above_trim_provider: Optional[Any] = None,
    db_path: Optional[Path] = None,
) -> HeldAddResult:
    """Run held_add evaluation across all held positions (per-account).

    shadow_mode 가 ON 이면 candidates 는 held_add_shadow 테이블에만 persist 되고
    brief surface 안 됨. shadow_mode_until 경과 시 caller (e.g. premarket_brief)
    가 candidates 를 brief 에 surface 한다.

    Provider 패턴: 테스트는 in-memory provider 주입, 운영은 DB 기반 default
    (None) 사용 — score / rsi / regime / sector_mom 은 운영 시 buy_candidate_emitter
    helper 재사용.
    """
    cfg_root = _load_config(config_path)
    cfg = (cfg_root or {}).get("held_add_mode") or {}
    if not cfg.get("enabled", False):
        return HeldAddResult(timestamp_kst=kst_now().isoformat())

    today = today or date.fromisoformat(today_kst())
    shadow = _is_shadow_mode(cfg, today=today)
    earnings_days = int(cfg.get("earnings_blackout_days", 5))

    # would-fire 측정 (#1173 — #788 Stage 1): 임계는 바꾸지 않고, 후보 그리드별
    # "발화했을 것인가" 를 append-only 원장에 기록한다. 라이브 emit 과 같은 provider
    # 스냅샷을 쓰므로 측정과 실주행의 시점이 갈라질 수 없다.
    wf_cfg = cfg.get("would_fire_logging") or {}
    wf_enabled = bool(wf_cfg.get("enabled", False))
    thresholds = current_mode_thresholds(cfg)
    wf_rows: list[dict[str, Any]] = []

    positions = _get_held_positions(db_path=db_path)
    result = HeldAddResult(
        shadow_mode=shadow,
        shadow_mode_until=str(cfg.get("shadow_mode_until", "")),
        timestamp_kst=kst_now().isoformat(),
    )

    # provider 기본값 — 테스트 외 운영에선 DB-backed 동작이 필요하지만 shadow
    # phase 2a 에선 caller (scheduler / brief) 에서 inject. None 이면 안전한
    # neutral 값 반환 (해당 mode trigger 가 작동 안 함).
    score_fn = score_provider or (lambda t: 0.0)
    rsi_fn = rsi_provider or (lambda t: None)
    # provider 부재 시 **미상**이다. 이전 기본값 `("neutral", 20.0)` 은 둘 다 조작된
    # 평온값이었다 — `"neutral"` 은 `ALL_REGIMES` 밖이라 어떤 veto 목록에도 걸리지 않고
    # `20.0 < 28` 이라 VIX veto 도 통과한다. macro veto 의 **두 절반이 동시에 fail-open**
    # 이었고, 이 함수 docstring 이 regime 은 `buy_candidate_emitter._get_regime()` 에서
    # 온다고 적은 계약과도 모순이었다. 프로덕션은 항상 provider 를 주입하지만
    # (`scheduler.py`) 기본값이 지뢰로 남을 이유가 없다.
    regime_fn = regime_provider or (lambda: (UNKNOWN_REGIME, None))
    sector_mom_fn = sector_mom_provider or (lambda t: 0.0)
    breakout_fn = breakout_above_trim_provider or (lambda t: False)

    for pos in positions:
        key = f"{pos['ticker']}@{pos['account']}"

        # earnings blackout 가장 먼저 (모든 mode 차단) — provider 를 **타기 전에**
        # 끊는다 (종전 동작 유지, codex diff P2). 측정이 켜져 있으면 blackout 행도
        # 기록하되 score/RSI 는 NULL — 어떤 게이트도 소비하지 않은 값을 관측치처럼
        # 적으면 days_held 를 뺀 것과 같은 원칙을 어긴다. "그날 평가 불능이었다" 는
        # 사실 자체만 남긴다 (Stage 2 이벤트 집합에선 제외).
        fetcher = earnings_fetcher_factory(pos["ticker"]) if earnings_fetcher_factory else None
        if is_in_earnings_blackout(pos["ticker"], days=earnings_days, today=today, fetcher=fetcher):
            result.skipped[key] = f"earnings blackout ±{earnings_days}d"
            if wf_enabled:
                wf_rows.append(
                    {
                        "ticker": pos["ticker"],
                        "account": pos["account"],
                        "score": None,
                        "pnl_pct": pos["pnl_pct"],
                        "rsi": None,
                        "sector_mom": None,
                        "headroom_pct": _safe_headroom(pos, db_path),
                        "gates": dict.fromkeys(MODE_PRECEDENCE, False),
                        "earnings_blackout": True,
                    }
                )
            continue

        score = float(score_fn(pos["ticker"]) or 0.0)
        rsi = rsi_fn(pos["ticker"])
        regime, vix = regime_fn()
        sector_mom = float(sector_mom_fn(pos["ticker"]) or 0.0)
        breakout = bool(breakout_fn(pos["ticker"]))

        gates = evaluate_mode_gates(
            pos,
            cfg,
            rsi,
            regime,
            vix,
            breakout_above_trim=breakout,
            sector_mom=sector_mom,
            db_path=db_path,
        )

        cap_info: Optional[dict[str, Any]] = None
        if wf_enabled:
            # headroom 은 측정 행의 기록 항목 — 실패해도 행을 버리지 않는다 (None 기록).
            try:
                cap_info = derive_position_cap(pos["ticker"], pos["account"], db_path=db_path)
            except Exception:
                logger.debug("would-fire headroom 조회 실패: %s", key, exc_info=True)
                cap_info = None
            wf_rows.append(
                {
                    "ticker": pos["ticker"],
                    "account": pos["account"],
                    "score": score,
                    "pnl_pct": pos["pnl_pct"],
                    "rsi": rsi,
                    "sector_mom": sector_mom,
                    "headroom_pct": (cap_info or {}).get("headroom_pct"),
                    "gates": gates,
                    "earnings_blackout": False,
                }
            )

        # 라이브 mode = gates ∧ score ≥ config 임계의 첫 precedence.
        # `select_held_mode` 와 동치다 (잠금: TestGatesEquivalence) — 측정 축(gates)과
        # 라이브 결정이 같은 평가를 공유해 둘이 갈라질 수 없게 하는 구조.
        mode = next(
            (
                m
                for m in sorted(MODE_PRECEDENCE.keys(), key=lambda m: MODE_PRECEDENCE[m])
                if gates[m] and score >= thresholds[m]
            ),
            None,
        )
        if mode is None:
            result.skipped[key] = "no mode triggered"
            continue

        if cap_info is None:
            cap_info = derive_position_cap(pos["ticker"], pos["account"], db_path=db_path)
        if cap_info["headroom_pct"] <= 0:
            result.skipped[key] = (
                f"{mode}: cap headroom 0 (current {cap_info['current_pct']}% ≥ cap {cap_info['cap_max_pct']}%)"
            )
            continue

        candidate = HeldAddCandidate(
            ticker=pos["ticker"],
            account=pos["account"],
            mode=mode,
            score=score,
            pnl_pct=pos["pnl_pct"],
            current_pct=cap_info["current_pct"],
            cap_max_pct=cap_info["cap_max_pct"],
            headroom_pct=cap_info["headroom_pct"],
            why_now=_build_why_now(mode, pos),
            sources={"score": score, "rsi": rsi, "regime": regime, "vix": vix},
        )
        result.candidates.append(candidate)

        if shadow:
            try:
                _persist_shadow(candidate, run_id=run_id, db_path=db_path)
            except Exception as e:
                logger.warning("held_add_shadow persist failed for %s: %s", key, e)

    if wf_enabled and wf_rows:
        # 관측은 본 작업을 게이트하지 않는다 (#894) — 기록 실패가 emit 을 죽이면 안 된다.
        try:
            from nuri.trading.recommend.held_add_would_fire import log_would_fire_rows

            n_logged = log_would_fire_rows(
                wf_rows,
                wf_cfg,
                thresholds,
                as_of_date=today.isoformat(),
                run_id=run_id,
                db_path=db_path,
            )
            logger.info("[held_add_would_fire] %d행 기록 (#1173 Stage 1)", n_logged)
        except Exception as e:
            logger.warning("held_add would-fire 기록 실패 (emit 은 정상): %s", e)

    return result


def _build_why_now(mode: str, pos: dict[str, Any]) -> str:
    """Single-sentence catalyst per mode."""
    if mode == "tp1_residual_add":
        return f"최근 TRIM 후 breakout 위 add — pnl {pos['pnl_pct']:+.1f}%"
    if mode == "ride_winner":
        return f"winner momentum — pnl {pos['pnl_pct']:+.1f}% (cap headroom 활용)"
    if mode == "average_down":
        return f"pullback add — pnl {pos['pnl_pct']:+.1f}% RSI 과매도 (macro non-bear)"
    return f"{mode} — pnl {pos['pnl_pct']:+.1f}%"
