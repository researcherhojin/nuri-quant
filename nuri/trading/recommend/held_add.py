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


def _get_held_positions() -> list[dict[str, Any]]:
    """portfolio 테이블 + 최신 가격 join — (ticker, account, qty, avg_price, current_price, pnl_pct).

    real_accounts (yaml substantive) 만 surface — test/sample/legacy stale 제외.
    days_held 는 portfolio 테이블에 timestamp 필드가 없어 fallback 30.
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
             ) pr ON p.ticker = pr.ticker"""
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


def _get_last_trim_age_days(ticker: str, max_days: int = 60) -> Optional[int]:
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
    pos: dict[str, Any], cfg: dict, score: float, breakout_above_trim: bool
) -> Optional[str]:
    """precedence=1. 최근 trim_action 후 잔여 add.

    Returns: trigger 충족 시 mode name, else None.
    """
    trig = cfg.get("modes", {}).get("tp1_residual_add", {}).get("trigger", {})
    if not trig:
        return None

    last_trim_age = _get_last_trim_age_days(pos["ticker"], max_days=int(trig.get("last_trim_age_days_max", 60)))
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

    if score < float(trig.get("composite_score_min", 75)):
        return None

    if trig.get("require_breakout_above_last_trim_price", True) and not breakout_above_trim:
        return None

    return "tp1_residual_add"


def _evaluate_ride_winner(pos: dict[str, Any], cfg: dict, score: float, sector_mom: float) -> Optional[str]:
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

    if score < float(trig.get("composite_score_min", 75)):
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

    if score < float(trig.get("composite_score_min", 80)):
        return None

    if rsi is None or rsi > float(trig.get("rsi_max", 35)):
        return None

    if pos["days_held"] < int(trig.get("days_held_min", 14)):
        return None

    # macro veto: regime ∉ {bear, crash} AND VIX < 28
    if trig.get("macro_veto", True):
        if regime in {"bear", "crash"}:
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
) -> Optional[str]:
    """precedence-sorted mutual exclusion. Returns first triggered mode or None.

    spec §4.3 — within (ticker, account, session) tuple emit at most ONE.
    """
    for mode_name in sorted(MODE_PRECEDENCE.keys(), key=lambda m: MODE_PRECEDENCE[m]):
        if mode_name == "tp1_residual_add":
            r = _evaluate_tp1_residual_add(pos, cfg, score, breakout_above_trim)
        elif mode_name == "ride_winner":
            r = _evaluate_ride_winner(pos, cfg, score, sector_mom)
        elif mode_name == "average_down":
            r = _evaluate_average_down(pos, cfg, score, rsi, regime, vix)
        else:
            r = None
        if r:
            return r
    return None


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

    positions = _get_held_positions()
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
    regime_fn = regime_provider or (lambda: ("neutral", 20.0))
    sector_mom_fn = sector_mom_provider or (lambda t: 0.0)
    breakout_fn = breakout_above_trim_provider or (lambda t: False)

    for pos in positions:
        key = f"{pos['ticker']}@{pos['account']}"

        # earnings blackout 가장 먼저 (모든 mode 차단)
        fetcher = earnings_fetcher_factory(pos["ticker"]) if earnings_fetcher_factory else None
        if is_in_earnings_blackout(pos["ticker"], days=earnings_days, today=today, fetcher=fetcher):
            result.skipped[key] = f"earnings blackout ±{earnings_days}d"
            continue

        score = float(score_fn(pos["ticker"]) or 0.0)
        rsi = rsi_fn(pos["ticker"])
        regime, vix = regime_fn()
        sector_mom = float(sector_mom_fn(pos["ticker"]) or 0.0)
        breakout = bool(breakout_fn(pos["ticker"]))

        mode = select_held_mode(
            pos,
            cfg,
            score,
            rsi,
            regime,
            vix,
            breakout_above_trim=breakout,
            sector_mom=sector_mom,
        )
        if mode is None:
            result.skipped[key] = "no mode triggered"
            continue

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
