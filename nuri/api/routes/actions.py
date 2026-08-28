"""Action-First API — 오늘 뭐 해야 하는지 우선순위로 정리.

🔴 즉시 실행: SIEGE 위반, 손절선 돌파, 강한 SELL 시그널
🟡 오늘 확인: 익절 도달, 트레일링 진입, 헤지 검토
✅ 유지: 정상 보유 종목
🔍 기회 탐색: 비보유 이슈 종목 + 매수 판정
"""

import json
import logging
import threading
import time
from datetime import timedelta

from fastapi import APIRouter, Depends

from nuri.api.cache import portfolio_version
from nuri.api.limits import heavy_slot
from nuri.core.axis import is_alpha_flat_sell
from nuri.core.catalyst import has_recent_catalyst
from nuri.core.db import query
from nuri.core.fx import latest_usd_krw_value
from nuri.core.live_price import DEFAULT_DIVERGENCE_THRESHOLD_PCT, check_divergence
from nuri.core.rules import get_stop_loss_for_account
from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])

# 캐시 (5분 TTL) — dashboard.py와 동일 패턴
CACHE_TTL = 300  # 5분
# `version` — 포트폴리오가 바뀌면 TTL 이 남아 있어도 캐시를 버린다 (#1279).
# `_market_context_cache` 는 macro 만 보므로 버전 키가 없다.
_actions_cache: dict = {"data": None, "timestamp": 0, "version": None}
_opportunities_cache: dict = {"data": None, "timestamp": 0, "version": None}
_market_context_cache: dict = {"data": None, "timestamp": 0}
# single-flight — TTL 만료 시 동시 요청이 전부 재계산하는 걸 막는다 (#1119).
# `_scan_lock` (아래) 과 같은 이유·같은 패턴이다.
_actions_lock = threading.Lock()
_opportunities_lock = threading.Lock()
_market_context_lock = threading.Lock()


def _fresh(cache: dict, now: float, version: str) -> bool:
    """캐시가 아직 유효한가 — TTL **과** 포트폴리오 버전을 함께 본다 (#1279).

    버전 비교를 빼면 보유를 바꾼 직후 최대 5분간 옛 평단으로 계산된 액션이 나간다.
    그건 낡은 숫자가 아니라 **거짓 손절 신호**다 (`nuri/api/cache.py` 참조).
    """
    return bool(cache["data"]) and (now - cache["timestamp"]) < CACHE_TTL and cache["version"] == version


# ─── /api/actions ───


@router.get("/actions", dependencies=[Depends(heavy_slot)])
def get_actions():
    """우선순위 분류된 오늘의 액션 리스트."""
    now = time.time()
    # 버전은 **빌드 전에** 읽어 저장한다 (#1279). 빌드 도중 쓰기가 들어오면 저장된
    # 버전이 옛 것이라 다음 요청이 한 번 더 재계산할 뿐이다 — 반대로 빌드 후에 읽으면
    # 새 버전을 옛 데이터에 붙여 **낡은 응답을 신선하다고 판정**한다. 안전한 방향으로 튄다.
    version = portfolio_version()
    if _fresh(_actions_cache, now, version):
        return _actions_cache["data"]
    try:
        with _actions_lock:
            # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다 (#1119)
            now = time.time()
            if _fresh(_actions_cache, now, version):
                return _actions_cache["data"]
            result = _build_actions()
            _actions_cache["data"] = result
            _actions_cache["timestamp"] = time.time()
            _actions_cache["version"] = version
            return result
    except Exception:
        logger.exception("actions API error")
        # PR A: exception fallback 도 4-bucket shape 유지 (portfolio 포함).
        # Frontend page.tsx fallback 과 동일 shape → "장애 시 포트폴리오 bucket
        # 이 사라져 리밸런스 권고가 silent 됨" 이라는 class of failure 방지.
        return {"urgent": [], "check": [], "hold": [], "portfolio": []}


def _build_actions() -> dict:
    """consensus + SIEGE + targets를 종합하여 🔴/🟡/✅/📊 분류.

    PR A (2026-04-21): `portfolio` bucket 추가. SIEGE position_limit/sector_limit
    위반은 "매도 강제" (urgent) 가 아닌 "리밸런스 권고" (portfolio) 로 route.
    Stop-loss breach 같은 alpha-driven 긴급 신호만 urgent 에 남김.
    """
    urgent: list[dict] = []  # 🔴 alpha-driven immediate action (stop-loss, SELL + catalyst)
    check: list[dict] = []  # 🟡 today's review items (targets, short squeeze risk)
    hold: list[dict] = []  # ✅ steady state
    portfolio: list[dict] = []  # 📊 portfolio-rule signals (concentration, sector cap)

    # ── 데이터 수집 ──
    recommendations = _get_recommendations()
    siege_violations = _get_siege_violations()
    targets_status = _get_targets_status()
    portfolio_holdings = _get_portfolio_map()

    violation_tickers = {v["ticker"] for v in siege_violations}

    # 연금 계좌 종목 식별 (월간 리밸런싱 → daily action에서 제외)
    pension_tickers = {
        t
        for t, h in portfolio_holdings.items()
        if any(kw in (h.get("account") or "").lower() for kw in ("연금", "pension", "irp"))
    }

    from nuri.core.ticker_names import get_ticker_name

    seen_tickers: set[str] = set()  # 중복 방지
    for rec in recommendations:
        ticker = rec["ticker"]
        # 연금 종목 skip (daily action 불필요)
        if ticker in pension_tickers:
            continue
        # 중복 ticker skip (복수 계좌 동일 종목)
        if ticker in seen_tickers:
            continue
        # 미보유 종목 skip (#998). `recommendations` 는 보유 테이블이 아니라 스캔
        # 유니버스(AMD·AMZN·INTC…)를 함께 담는다. 걸러내지 않으면 미보유 종목이
        # `pnl=0 / 비중=0 / 계좌=''` 인 채 "✅ 유지" 로 들어가, **매도한 종목이 아직
        # 보유 중인 것처럼** 읽힌다 (2026-08-03 실측: hold 6건 중 4건이 미보유,
        # 그중 하나는 당일 매도한 KB금융). 이 모듈 docstring 이 이미 정한 계약대로
        # 비보유 종목의 자리는 "🔍 기회 탐색"(`/api/opportunities`) 이다.
        if ticker not in portfolio_holdings:
            continue
        seen_tickers.add(ticker)

        action = rec["action"]
        # PR B: alpha axis. consensus `save_to_recommendations` 가 PR A 이후 이미
        # write 중. Legacy/pre-migration row 는 None.
        alpha_action = rec.get("alpha_action")
        portfolio_action = rec.get("portfolio_action")
        confidence = rec["confidence"]
        holding = portfolio_holdings.get(ticker, {})
        # #1279: 기본값 0 을 주지 않는다 — 미상이 보합으로 둔갑하는 지점이었다.
        pnl_pct = holding.get("pnl_pct")
        # #1284: 환산 불가면 None 이 온다. #1279 의 `pnl_pct` 와 같은 이유로 0 을 넣지 않는다
        # — 0 은 "비중 없음" 으로 읽히는데 실제로는 "모른다" 이다.
        position_pct = holding.get("position_pct")
        # 보유 행이 고른 계좌(worst-PnL)와 **같은 계좌**의 타겟을 본다 — 티커로만
        # 조회하면 둘이 갈라져 서로 다른 원가 기준이 한 줄에 섞인다 (#982).
        # 계좌 라벨이 없으면 조회 자체를 하지 않는다: 키가 (ticker, None) 이 되면
        # `_get_targets_status` 가 만드는 어떤 키와도 안 맞아 결과가 항상 빈 dict 다.
        # 위의 `ticker not in portfolio_holdings` 가드 때문에 실제로는 도달하지 않지만,
        # 도달 불가를 **타입으로도** 말해두면 이 파일의 진짜 오류가 노이즈에 안 묻힌다.
        account_label = holding.get("account")
        target = targets_status.get((ticker, account_label), {}) if account_label else {}

        # A-5: 시장 시간이면 live price fetch + divergence 체크. stored price 는
        # T-1 이라 장중 >3% 차이가 날 수 있음 (NFLX 사례). 지금은 flag 만 — 실제
        # threshold 비교는 stored 를 계속 사용 (A-5b 에서 live 로 승격 예정).
        stored_price = holding.get("current_price") or 0
        diverged, divergence_pct, live_price = check_divergence(ticker, stored_price)

        item = {
            "ticker": ticker,
            "name": get_ticker_name(ticker),
            "action": action,
            # PR B: per-item axis 노출. Frontend 가 향후 badge surface 할 수 있게 (chore PR).
            "alpha_action": alpha_action,
            "portfolio_action": portfolio_action,
            "confidence": confidence,
            "agreement": rec.get("agreement"),
            "pnl_pct": round(pnl_pct, 1) if pnl_pct is not None else None,
            "position_pct": round(position_pct, 1) if position_pct is not None else None,
            "current_price": holding.get("current_price"),
            "avg_price": holding.get("avg_price"),
            "account": holding.get("account", ""),
            # #527: multi-account 노출. 1 개 계좌면 1-element list, 2+ 면 breakdown.
            "accounts": holding.get("accounts") or [],
            "stop_loss": target.get("stop_loss"),
            "target_1": target.get("target_1"),
            "target_2": target.get("target_2"),
            "reasons": [],
            # A-2b: `_get_recommendations` 가 parse 해둔 JSON 을 그대로 노출.
            # Frontend (A-2c) 가 actions card 에서 10-agent breakdown + basis/penalty
            # 표시. codex A-2b Round 1 HIGH — `_build_actions` 이 drop 하던 bug fix.
            "scoring_detail": rec.get("scoring_detail"),
            "agent_verdicts": rec.get("agent_verdicts"),
            # A-5: live oracle snapshot (None 이면 시장외 or fetch fail)
            "live_price": live_price,
            "divergence_pct": round(divergence_pct, 2) if live_price is not None else None,
            "divergence_flag": diverged,
            # #1182: 증거 체인 링크 + 판정 기준일 — 매칭 decision 없으면 None
            "decision_id": rec.get("decision_id"),
            "as_of": rec.get("as_of"),
        }
        if diverged:
            item["reasons"].append(
                f"⚠ 실시간 시세 divergence {divergence_pct:+.1f}% "
                f"(stored {stored_price:.2f} → live {live_price:.2f}, 임계 {DEFAULT_DIVERGENCE_THRESHOLD_PCT}%)",
            )

        # ── 🔴 즉시 실행 조건 ──

        # 강한 SELL 시그널 — stop-loss breach 는 urgent (alpha-driven, 기계적).
        # PR B (codex #2): `action == "SELL"` 대신 `is_alpha_flat_sell` 로 전환 —
        # alpha_action == "FLAT" 명시 OR (back-compat) alpha_action=None +
        # action="SELL" (pre-migration-22 legacy row). 두 경우 모두 SELL path 진입.
        #
        # **Known remaining risk** (PR C strict=True 승격까지 열려있음):
        # post-migration 에 miswriter 가 `alpha_action=None, action="SELL"` 을 emit
        # 하면 여전히 SELL path 로 들어간다. PR A (#429) risk_agent 는 concentration
        # 을 `HOLD + portfolio_action=REBALANCE` 로 emit 해 이 경로에 진입 안 하지만,
        # 미래의 임의 writer 까지 구조적 차단은 strict=True 승격 후에나 성립. 현 PR B
        # scope 는 "legacy row 를 깨지 않는 전환" 수준. 승격 조건은 codex Plan Q1-B.
        if is_alpha_flat_sell(alpha_action, action):
            item["reasons"].append(f"10-Agent SELL (conf {confidence})")
            # A-3: 하드코딩 -7 제거. holding 이 최대 비중 계좌의 row 이므로 그
            # account 의 strategy stop_loss 와 비교 — pnl_pct 와 cost basis 일치.
            stop_loss_threshold = get_stop_loss_for_account(holding.get("account"))
            # 손익을 모르면 돌파를 **주장할 수 없다** (#1279). 미상은 아래 catalyst
            # 경로로 흘러 "왜 매도?" 맥락을 요구받는다 — 기계적 청산은 측정값에만.
            if pnl_pct is not None and pnl_pct < stop_loss_threshold:
                # stop-loss breach — 기계적 실행 (§2.2). catalyst 무관.
                # "근접" 이 아니라 **돌파**다 (#994). 이 분기 자체가 `pnl_pct <
                # threshold` — 관찰이 아니라 기계적 청산 신호이고, 초과폭을 같이
                # 적어야 사용자가 -7% 근처인지 35%p 초과인지 구분한다.
                over = stop_loss_threshold - pnl_pct  # 임계 대비 초과폭 (%p)
                item["reasons"].append(
                    f"손실 {pnl_pct:+.1f}% — 손절선 {stop_loss_threshold}% 돌파 ({over:.1f}%p 초과)",
                )
                item["priority"] = "urgent"
                urgent.append(item)
                continue
            # A-4: non-emergency SELL 은 catalyst 필요. 없으면 hold bucket 으로
            # 강등 (사용자에게 "왜 매도?" 맥락 없이 urgent 로 올리지 않음).
            has_catalyst, catalyst_reason = has_recent_catalyst(ticker)
            if not has_catalyst:
                item["reasons"].append(f"SELL 근거 없음 ({catalyst_reason}) — 관망")
                item["priority"] = "hold"
                hold.append(item)
                continue
            item["reasons"].append(f"catalyst: {catalyst_reason}")
            item["priority"] = "check"
            check.append(item)
            continue

        # ── 📊 포트폴리오 리밸런스 (SIEGE 룰 위반) ──
        # PR A: SIEGE position_limit/sector_limit 는 "매도 강제" 가 아니라 "리밸런스
        # 권고" — 사용자가 타이밍·수단 결정. 사용자 -₩7M 손실 재발 차단 경로.
        if ticker in violation_tickers:
            violation = next(v for v in siege_violations if v["ticker"] == ticker)
            item["reasons"].append(f"리밸런스 권고 — {violation['detail']}")
            item["priority"] = "portfolio"
            portfolio.append(item)
            continue

        # ── 🟡 오늘 확인 조건 ──

        promoted = False

        # 리더(성장주) 이동평균선 이탈 → 추세 break (고정 익절 폐기된 리더의 유일한 익절 트리거)
        if target.get("leader_trail_triggered"):
            from nuri.core.rules import TAKE_PROFIT_LEADER

            _ma_p = int(TAKE_PROFIT_LEADER.get("trail_ma", 50))
            item["reasons"].append(f"⭐ 리더 {_ma_p}일선 이탈 ({_pnl_phrase(pnl_pct)}) — 추세 break, 청산 검토")
            promoted = True

        # 2차 익절 도달 (리더는 고정 익절 미적용 → skip)
        elif (
            not target.get("is_leader")
            and target.get("target_2")
            and item["current_price"]
            and item["current_price"] >= target["target_2"]
        ):
            item["reasons"].append("2차 익절 도달 — 트레일링 전환 권장")
            promoted = True

        # 1차 익절 도달 (리더 skip)
        elif (
            not target.get("is_leader")
            and target.get("target_1")
            and item["current_price"]
            and item["current_price"] >= target["target_1"]
        ):
            item["reasons"].append(f"1차 익절 도달 ({_pnl_phrase(pnl_pct)}) — 50% 매도 고려")
            promoted = True

        # 높은 공매도 비율
        short_pct = _get_short_interest(ticker)
        if short_pct and short_pct > 10:
            item["reasons"].append(f"공매도 {short_pct:.1f}% — squeeze 주의")
            promoted = True

        if promoted:
            item["priority"] = "check"
            check.append(item)
            continue

        # ── ✅ 유지 ──
        item["priority"] = "hold"
        item["reasons"].append(f"BUY (conf {confidence})" if action == "BUY" else f"HOLD (conf {confidence})")
        hold.append(item)

    return {
        "urgent": urgent,
        "check": check,
        "hold": hold,
        "portfolio": portfolio,
        "generated_at": kst_now().isoformat(),
    }


# ─── /api/opportunities ───


@router.get("/opportunities")
def get_opportunities():
    """비보유 이슈 종목 탐색 — scan + WSB + macro events 기반 판정."""
    now = time.time()
    # 보유 종목을 제외하는 목록이라 포트폴리오 파생이다 — 새로 산 종목이 5분간
    # "기회" 로 계속 뜨면 안 된다 (#1279).
    version = portfolio_version()
    if _fresh(_opportunities_cache, now, version):
        return _opportunities_cache["data"]
    try:
        with _opportunities_lock:
            # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다 (#1119)
            now = time.time()
            if _fresh(_opportunities_cache, now, version):
                return _opportunities_cache["data"]
            result = {"opportunities": _build_opportunities(), "generated_at": kst_now().isoformat()}
            _opportunities_cache["data"] = result
            _opportunities_cache["timestamp"] = time.time()
            _opportunities_cache["version"] = version
            return result
    except Exception:
        logger.exception("opportunities API error")
        return {"opportunities": []}


def _build_opportunities() -> list[dict]:
    """스캔 결과 + 뉴스 이슈에서 비보유 종목을 찾고 찬성/반대/판정 생성."""
    portfolio_tickers = set(_get_portfolio_map().keys())

    # 스캔 결과 (최근 저장된 것)
    scan_results = _get_recent_scan_results()

    # 시그널 드리프트 (현재 유효한 시그널)
    improving_signals = _get_improving_signals()

    opportunities = []
    for s in scan_results:
        ticker = s["ticker"]
        if ticker in portfolio_tickers:
            continue

        pros: list[str] = []
        cons: list[str] = []

        # 찬성 근거
        if s.get("signal") == "breakout" and s.get("score", 0) >= 50:
            pros.append(f"breakout 시그널 (Score {s['score']})")
        if s.get("signal") == "momentum" and s.get("change_5d", 0) > 10:
            pros.append(f"강한 모멘텀 5D +{s['change_5d']:.1f}%")
        if s.get("rsi") and s["rsi"] < 35:
            if "rsi_oversold" in improving_signals:
                pros.append(f"RSI {s['rsi']:.0f} 과매도 (rsi_oversold 승률 상승 중)")
            else:
                pros.append(f"RSI {s['rsi']:.0f} 과매도")
        if s.get("volume_ratio", 0) >= 2.0:
            pros.append(f"거래량 {s['volume_ratio']:.1f}x 폭증")

        # 반대 근거
        if s.get("rsi") and s["rsi"] > 80:
            cons.append(f"RSI {s['rsi']:.0f} 과매수")
        if s.get("change_5d", 0) < -15:
            cons.append(f"5D {s['change_5d']:+.1f}% 급락 — 하락 모멘텀")
        if s.get("change_5d", 0) > 20:
            cons.append(f"5D +{s['change_5d']:.1f}% 이미 급등 — 추격 매수 위험")
        if s.get("signal") == "volume_spike" and s.get("change_5d", 0) < -10:
            cons.append("급락 + volume_spike — 원인 확인 필요")

        # 판정
        verdict, verdict_level = _compute_verdict(pros, cons, s)

        opportunities.append(
            {
                "ticker": ticker,
                "price": s.get("price"),
                "change_1d": s.get("change_1d"),
                "change_5d": s.get("change_5d"),
                "volume_ratio": s.get("volume_ratio"),
                "rsi": s.get("rsi"),
                "signal": s.get("signal"),
                "score": s.get("score"),
                "pros": pros,
                "cons": cons,
                "verdict": verdict,
                "verdict_level": verdict_level,
            }
        )

    # score 높은 순 + volume_spike 우선
    opportunities.sort(key=lambda x: x["score"] or 0, reverse=True)
    return opportunities[:10]


def _compute_verdict(pros: list[str], cons: list[str], scan: dict) -> tuple[str, str]:
    """찬성/반대 근거를 종합하여 판정."""
    score = scan.get("score", 0)
    rsi = scan.get("rsi", 50)
    change_5d = scan.get("change_5d", 0)

    # 🔴 매수 금지
    if change_5d < -20 and rsi < 20:
        return "매수 금지 — 극단적 하락, 원인 확인 전 진입 위험", "danger"
    if not pros and cons:
        return "매수 금지 — 근거 부족", "danger"

    # 🟢 매수 고려
    if len(pros) >= 2 and not cons and score >= 40:
        return "매수 고려 — 다수 시그널 정렬", "positive"

    # 🟡 관망
    if pros and cons:
        return "관망 — 혼재 시그널, 조건부 진입 대기", "neutral"
    if change_5d > 15:
        return "관망 — 과매수 구간, 눌림목 대기", "neutral"

    return "데이터 부족 — 판단 불가", "muted"


# ─── /api/market-context ───


@router.get("/market-context", dependencies=[Depends(heavy_slot)])
def get_market_context():
    """시장 컨텍스트 — 매크로 이벤트 + 시스템 건강 (#137 UI)."""
    now = time.time()
    if _market_context_cache["data"] and (now - _market_context_cache["timestamp"]) < CACHE_TTL:
        return _market_context_cache["data"]
    try:
        with _market_context_lock:
            # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다 (#1119)
            now = time.time()
            if _market_context_cache["data"] and (now - _market_context_cache["timestamp"]) < CACHE_TTL:
                return _market_context_cache["data"]
            result = {
                "macro_events": _get_macro_events(),
                "system_health": _get_system_health(),
                "generated_at": kst_now().isoformat(),
            }
            _market_context_cache["data"] = result
            _market_context_cache["timestamp"] = time.time()
            return result
    except Exception:
        logger.exception("market-context API error")
        return {"macro_events": [], "system_health": {}, "generated_at": kst_now().isoformat()}


# ─── 내부 헬퍼 ──


def _get_recommendations() -> list[dict]:
    """최신 consensus 결과 조회.

    A-2b: `scoring_detail` + `agent_verdicts` 컬럼도 노출 — frontend (A-2c) 가
    10-agent contribution breakdown 시각화 + basis_action/penalty 표시에 사용.
    """
    # P0 stale-data fix (#507 audit 2026-04-30): SELL/TRIM/REDUCE 는 portfolio.qty>0
    # 인 경우만 surface. tracker.py write-side filter 가 1차 차단하지만, 이미 persist
    # 된 stale row + 다른 writer 경로 (legacy / future) 도 이중으로 막음.
    #
    # #514 (Session 8 발견): HOLD 도 동일 filter 확장. 4-18 매도된 TSM 의 stale HOLD
    # row (conf 80) 가 brief 에 surface 되는 noise 차단. BUY 는 비보유 ticker 도 valid
    # emit 이므로 filter 제외.
    rows = query("""
        SELECT r.ticker, r.action, r.confidence, r.signals,
               r.scoring_detail, r.agent_verdicts,
               r.alpha_action, r.portfolio_action,
               r.date AS as_of, d.id AS decision_id
        FROM recommendations r
        -- 증거 체인 연결 (#1182): decisions 는 같은 consensus run 이 같은 date 로
        -- 기록하고 UNIQUE(date, ticker) 라 same-date LEFT JOIN 이 정확히 1행이다.
        -- 매칭 없으면(레거시/부분 실행) decision_id NULL — 프론트는 링크를 안 그린다.
        LEFT JOIN decisions d ON d.date = r.date AND d.ticker = r.ticker
        -- `source IS NULL` = 합의 파이프라인 산출물. `buy_candidate_emitter` 행이
        -- 같은 테이블에 들어오면서(#1078) 필터 없이는 emitter 후보가 합의 결과처럼
        -- 액션 카드에 섞인다. 이 화면의 계약은 '합의가 오늘 낸 결론' 이다.
        WHERE r.source IS NULL
          AND r.date = (SELECT MAX(date) FROM recommendations WHERE source IS NULL)
          AND (
              r.action NOT IN ('SELL', 'TRIM', 'REDUCE', 'HOLD')
              OR r.ticker IN (SELECT ticker FROM portfolio WHERE quantity > 0)
          )
        ORDER BY r.confidence DESC
    """)
    results = []
    for r in rows:
        agreement = None
        if r["signals"]:
            try:
                data = json.loads(r["signals"])
                agreement = data.get("agreement_rate")
            except (json.JSONDecodeError, TypeError):
                pass
        # Parse 실패 → None. source=consensus/candidate 로 frontend 분기 (PR #364/#366).
        scoring_detail = None
        if r.get("scoring_detail"):
            try:
                scoring_detail = json.loads(r["scoring_detail"])
            except (json.JSONDecodeError, TypeError):
                pass
        agent_verdicts = None
        if r.get("agent_verdicts"):
            try:
                agent_verdicts = json.loads(r["agent_verdicts"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(
            {
                "ticker": r["ticker"],
                "action": r["action"],
                "confidence": round(r["confidence"] * 100)
                if r["confidence"] and r["confidence"] <= 1
                else round(r["confidence"] or 0),
                "agreement": round(agreement * 100) if agreement is not None and agreement <= 1 else agreement,
                "scoring_detail": scoring_detail,
                "agent_verdicts": agent_verdicts,
                # PR A: alpha/portfolio axis — Frontend UI 가 action 배지 옆에 바둑돌
                # 형태로 표시할 수 있게 노출. legacy row 는 NULL (back-compat OK).
                "alpha_action": r.get("alpha_action"),
                "portfolio_action": r.get("portfolio_action"),
                # #1182: 증거 체인 (/decisions/[id]) + 이 판정의 기준일
                "decision_id": r.get("decision_id"),
                "as_of": r.get("as_of"),
            }
        )
    return results


def _get_siege_violations() -> list[dict]:
    """SIEGE 인증 위반 사항 조회."""
    import re

    violations = []
    try:
        from nuri.trading.engine.certification import certify

        # API path — persist 실패 swallow (E4-0a codex R1 P1).
        cert = certify(caller="api:actions:violations", swallow_persist_errors=True)
        for c in cert.conditions:
            if not c.passed and c.severity == "error":
                detail = c.detail or ""
                if c.id == "position_limit":
                    # "위반: TSLA(15.4%>15%)" or "위반: TSLA(15.4%>15%), NBIS(16%>15%)"
                    matches = re.findall(r"(\S+?)\([\d.]+%>[\d.]+%\)", detail)
                    for ticker in matches:
                        violations.append(
                            {
                                "ticker": ticker,
                                "detail": f"Certification: {c.description} — {detail}",
                                "condition_id": c.id,
                            }
                        )
                    if not matches:
                        violations.append(
                            {"ticker": "", "detail": f"Certification: {c.description} — {detail}", "condition_id": c.id}
                        )
                else:
                    violations.append(
                        {"ticker": "", "detail": f"Certification: {c.description} — {detail}", "condition_id": c.id}
                    )
    except Exception as e:
        logger.debug(f"SIEGE violations: {e}")
    return violations


def _get_targets_status() -> dict[tuple[str, str], dict]:
    """포트폴리오 가격 타겟 조회 — **(ticker, 계좌라벨)** 로 키잉.

    같은 티커를 두 계좌에 보유하면 평단이 달라 손절/익절선도 다르다. 티커로만
    키잉하면 한 계좌 것만 남고, 그게 `_get_portfolio_map()` 이 고른 계좌와
    일치한다는 보장이 없다 — 그러면 UI 에서 **보유 정보와 손절선이 서로 다른
    계좌 기준**으로 나란히 붙는다. 여기서 계좌까지 키에 넣고, 소비자가
    `_get_portfolio_map()` 이 고른 계좌로 조회해 둘을 일치시킨다 (#982).
    """
    from nuri.api.routes.dashboard import _get_account_labels

    labels = _get_account_labels()
    targets: dict[tuple[str, str], dict] = {}
    try:
        from nuri.trading.recommend.price_targets import (
            calculate_portfolio_targets,
            check_leader_trail_signals,
        )

        # 계좌가 없는 행은 **건너뛴다**. `labels.get(None, None)` 은 None 을 돌려주므로
        # 그대로 두면 (ticker, None) 키가 만들어지는데, 소비자는 항상 라벨 문자열로
        # 조회하므로 그 키는 영영 안 맞는다 — 타겟이 들어가 있으면서 안 읽힌다.
        # `len(targets)` 은 세므로 "있다" 고 보이는 게 더 나쁘다. 넣지 않고 로그를 남긴다.
        def _key(row: dict) -> tuple[str, str] | None:
            # `isinstance` 로 좁히는 이유는 두 가지다. 타입 체커에게 None 배제를 말해주고,
            # 동시에 문자열이 아닌 account 도 실제로 걸러낸다 — 키는 (str, str) 이어야
            # 소비자의 조회와 맞는다.
            account = row.get("account")
            if not isinstance(account, str) or not account:
                logger.debug("targets: account 없는 행 skip — %s", row.get("ticker"))
                return None
            return (str(row["ticker"]), labels.get(account, account))

        try:
            _leader_trail = {k for k in (_key(x) for x in check_leader_trail_signals()) if k}
        except Exception:
            _leader_trail = set()
        for t in calculate_portfolio_targets():
            key = _key(t)
            if key is None:
                continue
            targets[key] = {
                "stop_loss": t.get("stop_loss"),
                "target_1": t.get("target_1"),
                "target_2": t.get("target_2"),
                "trailing_stop_pct": t.get("trailing_stop_pct"),
                "analyst_target": t.get("analyst_target"),
                "is_leader": t.get("is_leader"),
                "leader_ma": t.get("leader_ma"),
                "leader_trail_triggered": key in _leader_trail,
            }
    except Exception as e:
        logger.debug(f"Targets: {e}")
    return targets


def _get_real_accounts() -> set[str]:
    """실계좌 집합 — 판별은 `nuri.core.rules.get_real_accounts()` 가 canonical."""
    from nuri.core.rules import get_real_accounts

    return get_real_accounts()


def _is_worse(new: float | None, cur: float | None) -> bool:
    """worst-PnL 집계에서 `new` 가 `cur` 보다 나쁜가 — None(측정 불가) 안전 (#1279).

    None 은 "가장 나쁨" 이 아니라 **모름**이다. 측정 가능한 쪽이 계좌·손익 자리를 갖는다 —
    그러지 않으면 비상장 한 줄이 같은 티커의 측정 가능한 보유를 가려 손절 판정을 통째로
    삼킨다. 둘 다 None 이면 바꿀 이유가 없다.
    """
    if new is None:
        return False
    if cur is None:
        return True
    return new < cur


def _pnl_phrase(pnl: float | None) -> str:
    """근거 문자열의 손익 표기. 미상이면 숫자를 지어내지 않는다 (#1279).

    부호는 **포맷 스펙에 맡긴다** (`:+`). 리터럴 `+` 를 앞에 붙이면 손실이 `+-5%` 로
    찍힌다 (codex 리뷰 P2). 리더 트레일링은 고점 대비 이탈이라 진입가 아래에서도
    발화할 수 있어 실제로 도달 가능한 경로다.
    """
    return f"{pnl:+.0f}%" if pnl is not None else "손익 미상"


def _get_portfolio_map() -> dict[str, dict]:
    """보유 종목 → 현재 상태 매핑."""
    from nuri.api.routes.dashboard import _get_account_labels

    real_accounts = _get_real_accounts()
    rows = query("""
        SELECT p.account, p.ticker, p.quantity, p.avg_price, p.currency,
               pr.close as current_price
        FROM portfolio p
        LEFT JOIN (
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
        ) pr ON p.ticker = pr.ticker
    """)
    # #527: stale test/sample/legacy account 의 row 가 합산 비중·pnl 을 왜곡한다.
    # portfolio.yaml 의 substantive accounts 만 본다.
    if real_accounts:
        rows = [r for r in rows if r["account"] in real_accounts]

    # #1278: 날짜 상한 + 미래행 경고는 공용 리더가 담당한다 (nuri/core/fx.py).
    # #1284: `or 1400` 이 여기 있었다. 비중%는 **원화 자산과 달러 자산을 더한 값**을 분모로
    # 쓰므로, 원화 보유가 하나라도 있고 환율이 없으면 US 종목의 비중까지 말할 수 없다.
    # 분모가 미상이면 분자가 정확해도 비율은 미상이다.
    from nuri.core.fx import is_krw_holding

    rate = latest_usd_krw_value()
    has_krw = any(is_krw_holding(r["ticker"], r["currency"]) for r in rows)
    weights_unavailable = rate is None and has_krw

    # 총 자산 계산 (비중% 산정용)
    total_value = 0
    items = []
    for r in rows:
        # #1279: 시장가와 **비중 계산용 가격**을 분리한다.
        # `market_price` 가 None 이면 시세 미수집(예: 비상장) — 손익은 **측정 불가**다.
        # 반면 비중은 원가로도 말할 수 있고, 0 으로 지우면 다른 종목 비중이 부풀려진다.
        # 이전에는 하나의 `price` 가 둘을 겸해서, 원가로 대체된 값이 손익 계산에도 들어가
        # **미상이 0.0%(보합)으로 둔갑**했다.
        market_price = r["current_price"]
        price = market_price if market_price is not None else (r["avg_price"] or 0)
        qty = r["quantity"] or 0
        is_kr = is_krw_holding(r["ticker"], r["currency"])
        # 원화 보유인데 환율이 없으면 이 행의 USD 값은 미상이다.
        # 삼항 대신 분기로 쓴다 — 타입체커가 `rate` 를 좁힐 수 있어야 "도달 불가" 가
        # 조용히 도달 가능해지는 순간을 잡아준다 (#1283 에서 같은 형태를 밟았다).
        if not is_kr:
            val = price * qty
        elif rate is None:
            val = None
        else:
            val = price * qty / rate
        if val is not None:
            total_value += val
        items.append((r, val, market_price, is_kr))

    # 분모가 미상이면 **모든** 비중이 미상이다 — 달러 종목도 마찬가지다.
    # 부분합을 분모로 쓰면 남은 종목들의 비중이 조용히 부풀려진다.
    if weights_unavailable:
        total_value = None

    labels = _get_account_labels()

    def _is_pension_label(label: str | None) -> bool:
        low = (label or "").lower()
        return any(kw in low for kw in ("연금", "pension", "irp"))

    # A-6: 동일 ticker 의 여러 계좌를 aggregate — 이전에는 largest-position row
    # 하나만 keep 해 breach/divergence masking 버그 (A-4 codex Round 1-3 재발 flag).
    # A-6 codex Round 1 P2: pension 계좌는 daily action 에서 제외되므로 aggregation
    # 대상에서도 분리해야 taxable + pension 혼합 ticker 에서 taxable 슬라이스가
    # pension label 에 의해 skip 되는 cross-contamination 방지. 규칙:
    #   - non-pension rows 만 aggregate (worst-pnl 이 account/pnl 을 차지)
    #   - non-pension rows 가 없으면(=pension-only ticker) pension 중 worst 로 채움
    #     — 이 경우 downstream `_build_actions` 가 pension_tickers set 으로 suppress
    #   - position_pct 는 항상 전체 합산 (실제 노출도)
    # #527: 합산 표시만 surface 되어 multi-account 노출 사실 자체가 보이지 않던
    # 문제 해결 — `accounts` list 로 per-account breakdown 도 함께 반환한다.
    result: dict[str, dict] = {}
    for r, val, price, is_kr in items:
        ticker = r["ticker"]
        avg = r["avg_price"] or 0
        # 시세가 없으면 **None** — 0.0 은 "보합" 으로 읽히는 지어낸 값이다 (#1279).
        # STRATEGY §2.6 의 VIX 게이트와 같은 원칙: 측정 불가는 숫자로 메우지 않는다.
        pnl = ((price - avg) / avg * 100) if (avg > 0 and price is not None) else None
        # #1284: 환산 불가면 **None** — 0 은 "비중 없음" 으로 읽히는 지어낸 값이다.
        # 빈 포트폴리오(total_value == 0)의 0 은 지어낸 값이 아니라 사실이므로 그대로 둔다.
        if total_value is None or val is None:
            pos_pct = None
        elif total_value > 0:
            pos_pct = val / total_value * 100
        else:
            pos_pct = 0
        account_label = labels.get(r["account"], r["account"])
        is_pension = _is_pension_label(account_label)

        per_account = {
            "account": account_label,
            "quantity": r["quantity"],
            "avg_price": avg,
            "current_price": price,
            "pnl_pct": pnl,
            "position_pct": pos_pct,
        }

        existing = result.get(ticker)
        if existing is None:
            result[ticker] = {
                "current_price": price,
                "avg_price": avg,
                "quantity": r["quantity"],
                "pnl_pct": pnl,
                "position_pct": pos_pct,
                "account": account_label,
                "accounts": [per_account],  # #527: per-account breakdown
                "_pension_only": is_pension,  # 내부 flag — 아래 정리에서 제거
            }
            continue

        # #1284: 미상은 전파된다 — 한 계좌의 비중을 모르면 합산 비중도 모른다.
        # `None` 을 0 으로 취급해 더하면 다계좌 노출이 과소 보고된다.
        if existing["position_pct"] is None or pos_pct is None:
            existing["position_pct"] = None
        else:
            existing["position_pct"] += pos_pct
        existing["accounts"].append(per_account)
        # non-pension row 가 들어오면 이전 pension-only state 를 non-pension 으로 승격
        if not is_pension and existing["_pension_only"]:
            existing["_pension_only"] = False
            existing["pnl_pct"] = pnl
            existing["current_price"] = price
            existing["avg_price"] = avg
            existing["quantity"] = r["quantity"]
            existing["account"] = account_label
            continue
        # 현재까지 non-pension 이면 pension row 는 무시 (aggregation 오염 방지)
        if is_pension and not existing["_pension_only"]:
            continue
        # 동질 (둘 다 pension 이거나 둘 다 non-pension) → worst-pnl 이 승리
        if _is_worse(pnl, existing["pnl_pct"]):
            existing["pnl_pct"] = pnl
            existing["current_price"] = price
            existing["avg_price"] = avg
            existing["quantity"] = r["quantity"]
            existing["account"] = account_label

    # 내부 flag 정리 — caller 에 노출 안 함
    for h in result.values():
        h.pop("_pension_only", None)
    return result


def _get_short_interest(ticker: str) -> float | None:
    """공매도 비율 조회."""
    rows = query(
        "SELECT numeric_value FROM external_analysis WHERE ticker = ? AND data_type = 'short_pct_float' ORDER BY date DESC LIMIT 1",
        (ticker,),
    )
    return rows[0]["numeric_value"] if rows else None


# Scan-level cache + double-checked lock — prevents duplicate scan_market() calls
# when multiple concurrent /api/opportunities requests arrive before first completes.
# (Race observed 2026-04-21: dashboard first-load 29.2s caused by 2 parallel scans.)
_SCAN_CACHE_TTL = 60  # 1분 — scan 결과가 장중 급변하지 않음
_scan_results_cache: dict = {"data": None, "timestamp": 0.0}
_scan_lock = threading.Lock()


def _get_recent_scan_results() -> list[dict]:
    """최근 스캔 결과를 cache + lock 경유로 반환 (중복 scan 방지)."""
    now = time.time()
    # Fast path — 다른 request 가 이미 채운 cache 재사용 (lock 없이 read)
    if _scan_results_cache["data"] is not None:
        if now - _scan_results_cache["timestamp"] < _SCAN_CACHE_TTL:
            return _scan_results_cache["data"]

    with _scan_lock:
        # Double-check — lock 대기 중에 다른 thread 가 채웠을 수 있음
        now = time.time()
        if _scan_results_cache["data"] is not None:
            if now - _scan_results_cache["timestamp"] < _SCAN_CACHE_TTL:
                return _scan_results_cache["data"]

        try:
            from nuri.trading.swing.scanner import scan_market

            results = scan_market(extended=False)
            formatted = [
                {
                    "ticker": r.ticker,
                    "price": r.price,
                    "change_1d": r.change_1d,
                    "change_5d": r.change_5d,
                    "volume_ratio": r.volume_ratio,
                    "rsi": r.rsi,
                    "signal": r.signal,
                    "score": r.score,
                }
                for r in results[:30]
            ]
            _scan_results_cache["data"] = formatted
            _scan_results_cache["timestamp"] = time.time()
            return formatted
        except Exception as e:
            logger.debug(f"Scan: {e}")
            return []


def _get_improving_signals() -> set[str]:
    """승률 상승 중인 시그널 목록."""
    improving = set()
    try:
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift()
        for d in drifts:
            if d.status == "improving":
                improving.add(d.signal_id)
    except Exception:
        pass
    return improving


_CATEGORY_KO: dict[str, str] = {
    "geopolitical_escalation": "지정학 긴장 고조",
    "geopolitical_de_escalation": "지정학 긴장 완화",
    "oil_supply_shock": "유가 충격",
    "trade_war": "무역 분쟁",
    "fed_dovish": "Fed 완화 시사",
    "fed_hawkish": "Fed 긴축 시사",
    "earnings_beat": "실적 호실적",
    "earnings_miss": "실적 부진",
    "sector_rally": "섹터 랠리",
    "demand_growth": "수요 증가",
    "export_surge": "수출 급증",
}


def _get_macro_events() -> list[dict]:
    """최근 7일 매크로 이벤트 (category != neutral, confidence >= 0.5).

    headline을 카테고리 한국어 + 원문 요약으로 변환.
    """
    cutoff = (kst_now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = query(
        """
        SELECT category, headline, sentiment, confidence, published_at, source
        FROM macro_events
        WHERE published_at >= ?
          AND category != 'neutral'
          AND confidence >= 0.5
        ORDER BY ABS(sentiment) DESC
        LIMIT 10
    """,
        (cutoff,),
    )
    results = []
    seen_categories: dict[str, int] = {}
    for r in rows:
        cat = r["category"] or ""
        # 같은 카테고리 3개 이상이면 skip (중복 TSMC 뉴스 방지)
        seen_categories[cat] = seen_categories.get(cat, 0) + 1
        if seen_categories[cat] > 2:
            continue
        ko_label = _CATEGORY_KO.get(cat, cat)
        results.append(
            {
                **dict(r),
                "category_ko": ko_label,
            }
        )
    return results[:8]


def _get_system_health() -> dict:
    """시스템 건강 요약 — SIEGE / 레짐 / 매크로 / 데이터 신선도."""
    health = {"siege": {}, "regime": {}, "macro": {}, "freshness": {}}

    # SIEGE
    try:
        from nuri.trading.engine.certification import certify

        # API path — persist 실패 swallow (E4-0a codex R1 P1).
        cert = certify(caller="api:actions:health", swallow_persist_errors=True)
        health["siege"] = {
            "score": round(cert.score),
            "certified": cert.certified,
            "passed": cert.passed,
            "failed": cert.failed,
            "warnings": cert.warnings,
            "total": cert.total_conditions,
        }
    except Exception:
        health["siege"] = {"score": 0, "certified": False}

    # 레짐
    try:
        from nuri.quant.regime.classifier import classify_regime

        r = classify_regime()
        if r:
            health["regime"] = {
                "regime": r.regime,
                "trend": r.trend,
                "volatility": r.volatility,
                "confidence": round(r.confidence * 100),
            }
    except Exception:
        pass

    # 매크로
    try:
        from nuri.quant.regime.macro_score import compute_macro_score

        m = compute_macro_score()
        health["macro"] = {"score": round(m.total_score), "interpretation": m.interpretation}
    except Exception:
        pass

    # 신선도
    try:
        from nuri.core.freshness import check_all_freshness

        details = check_all_freshness()
        fail_count = sum(1 for d in details if d["status"] == "FAIL")
        warn_count = sum(1 for d in details if d["status"] == "WARN")
        health["freshness"] = {
            "status": "FAIL" if fail_count > 0 else "WARN" if warn_count > 0 else "PASS",
            "fail_count": fail_count,
            "warn_count": warn_count,
        }
    except Exception:
        pass

    return health
