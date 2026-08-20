"""종목 상세 API — 모든 데이터를 한 번에."""

import json
import logging
import threading
import time
from dataclasses import asdict

from fastapi import APIRouter, Query

from nuri.core.db import query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ticker"])

# screen_candidates 는 universe 전체를 스캔(O(종목수×지표계산)) → 종목 상세 GET 마다
# 재실행하면 수초 지연. 다른 라우트와 동일한 5분 TTL 모듈 캐시로 1회 스캔 결과 공유.
_CANDIDATES_CACHE_TTL = 300  # 5분
_candidates_cache: dict = {"data": None, "timestamp": 0.0}
# single-flight — TTL 만료 시 동시 요청이 전부 재스캔하는 걸 막는다 (#1119)
_candidates_lock = threading.Lock()

# 스케줄러가 매일 consensus 를 저장하므로 정상 운영 시 최신 행은 오늘/어제.
# 주말·공휴일 갭(최대 ~3일)은 허용하되, 그보다 오래되면(스케줄러 정지 등) live
# 재계산으로 폴백 — stale consensus 를 권위 있는 값으로 serve 하지 않기 위함.
_CONSENSUS_MAX_AGE_DAYS = 7


def _read_consensus_from_db(ticker: str) -> dict | None:
    """recommendations 테이블의 최근 consensus 1건을 복원. 없거나 stale 하면 None.

    스케줄러가 매 consensus run 마다 save_to_recommendations 로 전 종목을 저장하므로
    상세 GET 에서 analyze_ticker(10-agent, 네트워크+연산)를 재실행할 필요가 없다.
    dissent 는 recommendations.signals 에 count 만 있어 agent_verdicts 에서 재구성한다
    (final_action 기준 — divergence/veto penalty 가 적용된 행은 canonical scoring.py 의
    pre-penalty 기준과 미세하게 다를 수 있으나, 표시용 설명 필드라 허용).
    """
    from datetime import timedelta

    from nuri.core.timezone import kst_now

    rows = query(
        # emitter 행 제외 — 이 함수는 "최신 **합의**" 를 돌려준다 (#1078). 필터가 없으면
        # 같은 ticker 의 emitter 후보가 날짜만 최신이라는 이유로 합의 행세를 한다.
        "SELECT action, confidence, signals, agent_verdicts, date "
        "FROM recommendations WHERE ticker = ? AND source IS NULL ORDER BY date DESC LIMIT 1",
        (ticker,),
    )
    if not rows:
        return None

    row = rows[0]
    # freshness 가드: 너무 오래된 행이면 None → 호출자가 live 재계산
    cutoff = (kst_now().date() - timedelta(days=_CONSENSUS_MAX_AGE_DAYS)).isoformat()
    if not row["date"] or row["date"] < cutoff:
        return None

    try:
        verdicts = json.loads(row["agent_verdicts"]) if row["agent_verdicts"] else []
    except (json.JSONDecodeError, TypeError):
        verdicts = []
    if not isinstance(verdicts, list):
        verdicts = []
    try:
        sig = json.loads(row["signals"]) if row["signals"] else {}
    except (json.JSONDecodeError, TypeError):
        sig = {}

    final_action = row["action"]
    dissent = [
        f"{v.get('agent_name', '?')}({v.get('action', '?')}, {float(v.get('confidence') or 0):.0f}): {v.get('reasoning', '')}"
        for v in verdicts
        if isinstance(v, dict) and v.get("action") != final_action
    ]
    return {
        "final_action": final_action,
        "final_confidence": row["confidence"],
        "agreement_rate": sig.get("agreement_rate") if isinstance(sig, dict) else None,
        "verdicts": verdicts,
        "dissent": dissent,
        "as_of": row["date"],  # 캐시된 결정의 기준일 — staleness 투명성
    }


def _get_consensus(ticker: str) -> dict:
    """DB(recommendations) 우선 read, 미스(포트폴리오 외 종목 등) 시에만 live 분석."""
    cached = _read_consensus_from_db(ticker)
    if cached is not None:
        return cached

    try:
        from nuri.core.timezone import today_kst
        from nuri.trading.agents.consensus import analyze_ticker

        consensus = analyze_ticker(ticker)
        return {
            "final_action": consensus.final_action,
            "final_confidence": consensus.final_confidence,
            "agreement_rate": consensus.agreement_rate,
            "verdicts": [asdict(v) for v in consensus.verdicts],
            "dissent": consensus.dissent,
            "as_of": today_kst(),
        }
    except Exception:
        # 예외 문자열을 응답에 실으면 스택 트레이스·내부 경로가 외부로 나간다
        # (CodeQL py/stack-trace-exposure). 진단은 로그, 클라이언트에는 generic 메시지
        # — `nuri/api/CLAUDE.md` "Error handling" 의 soft 패턴.
        logger.exception("live consensus 계산 실패: %s", ticker)
        return {"error": "consensus unavailable"}


def _get_signals(ticker: str) -> list:
    """캐시된 universe 스캔 결과에서 해당 종목 시그널만 필터. 5분 TTL."""
    now = time.time()
    if _candidates_cache["data"] is None or (now - _candidates_cache["timestamp"]) >= _CANDIDATES_CACHE_TTL:
        with _candidates_lock:
            # double-check — 락을 기다리는 동안 다른 요청이 채웠을 수 있다 (#1119).
            # screen_candidates 는 실측 3.5초라, 락이 없으면 TTL 만료 시각에
            # 도착한 요청들이 전부 같은 스캔을 중복 수행한다.
            now = time.time()
            if _candidates_cache["data"] is None or (now - _candidates_cache["timestamp"]) >= _CANDIDATES_CACHE_TTL:
                try:
                    from nuri.trading.recommend.candidates import screen_candidates

                    data = screen_candidates(lookback_days=10)
                except Exception:
                    # 스캔 실패 시 캐시를 빈 결과로 고정하지 않음 — 다음 요청이 재시도
                    return []
                _candidates_cache["data"] = data
                _candidates_cache["timestamp"] = now
    return [asdict(c) for c in _candidates_cache["data"] if c.ticker == ticker]


@router.get("/tickers/search")
def search_tickers(q: str = Query(..., min_length=1, max_length=20)):
    """종목 검색 — ticker code 또는 한국 종목명 부분 매칭. universe + DB 가격 기반."""
    from pathlib import Path

    import yaml

    from nuri.core.ticker_names import get_ticker_name

    term = q.strip().upper()
    results: list[dict] = []
    seen: set[str] = set()

    # 1) universe.yaml에서 ticker code 매칭
    universe_path = Path(__file__).resolve().parents[3] / "config" / "universe.yaml"
    all_tickers: list[str] = []
    if universe_path.exists():
        with open(universe_path) as f:
            uni = yaml.safe_load(f) or {}
        for group in uni.values():
            if isinstance(group, dict) and "tickers" in group:
                all_tickers.extend(group["tickers"])

    # ticker code 매칭 (NVDA, 005930 등)
    for t in all_tickers:
        if term in t.upper() and t not in seen:
            seen.add(t)
            price_row = query("SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
            results.append(
                {
                    "ticker": t,
                    "name": get_ticker_name(t),
                    "price": price_row[0]["close"] if price_row else None,
                    "date": price_row[0]["date"] if price_row else None,
                }
            )
        if len(results) >= 8:
            break

    # 2) 한글 이름 매칭 (KR 종목 — "삼성" → 005930.KS)
    if len(results) < 8:
        term_lower = q.strip().lower()
        for t in all_tickers:
            if t in seen:
                continue
            if t.endswith(".KS") or t.endswith(".KQ"):
                name = get_ticker_name(t)
                if name and term_lower in name.lower():
                    seen.add(t)
                    price_row = query("SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
                    results.append(
                        {
                            "ticker": t,
                            "name": name,
                            "price": price_row[0]["close"] if price_row else None,
                            "date": price_row[0]["date"] if price_row else None,
                        }
                    )
            if len(results) >= 8:
                break

    return {"results": results, "count": len(results)}


@router.get("/tickers/market-context")
def get_market_context():
    """시장 현황 — VIX, Fear&Greed, 매크로 점수를 독립적으로 조회. 레짐 분류 실패해도 작동."""
    vix_row = query("SELECT value, date FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT 1")
    fg_row = query("SELECT value, date FROM macro WHERE indicator='fear_greed' ORDER BY date DESC LIMIT 1")

    # Macro score
    try:
        from nuri.quant.regime.macro_score import compute_macro_score

        # compute_macro_score 는 MacroScore dataclass 를 반환한다 (dict 아님 — #754).
        macro = compute_macro_score()
        macro_score = macro.total_score
    except Exception:
        macro_score = None

    # Regime (best effort — may fail if SPY stale)
    trend = None
    try:
        from nuri.quant.regime.classifier import classify_regime

        regime = classify_regime()
        if regime:
            trend = regime.trend
    except Exception:
        pass

    return {
        "trend": trend,
        "vix": round(vix_row[0]["value"], 1) if vix_row else None,
        "vix_date": vix_row[0]["date"] if vix_row else None,
        "fear_greed": round(fg_row[0]["value"], 1) if fg_row else None,
        "fg_date": fg_row[0]["date"] if fg_row else None,
        "macro_score": round(macro_score, 1) if macro_score else None,
    }


@router.get("/tickers/latest-prices")
def get_latest_prices(tickers: str = Query(..., description="Comma-separated ticker list")):
    """여러 종목의 최신 가격을 한 번에 조회. quicklink 카드용 batch endpoint."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) > 20:
        ticker_list = ticker_list[:20]

    result: dict[str, dict] = {}
    for t in ticker_list:
        rows = query(
            "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 2",
            (t,),
        )
        if rows:
            latest = rows[0]["close"]
            prev = rows[1]["close"] if len(rows) > 1 else None
            result[t] = {"price": latest, "prev": prev, "date": rows[0]["date"]}
        else:
            result[t] = {"price": None, "prev": None, "date": None}

    return {"prices": result}


@router.get("/ticker/{symbol}")
def get_ticker_detail(symbol: str):
    """단일 종목의 모든 분석 데이터."""
    from nuri.core.ticker_names import get_ticker_name

    ticker = symbol.upper()
    result = {"ticker": ticker, "name": get_ticker_name(ticker)}

    # 1. 가격
    price_row = query(
        "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
        (ticker,),
    )
    result["price"] = {
        "close": price_row[0]["close"] if price_row else None,
        "date": price_row[0]["date"] if price_row else None,
    }

    # 2. 펀더멘탈
    fund = query("SELECT * FROM fundamentals WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,))
    result["fundamentals"] = dict(fund[0]) if fund else None

    # 3. 10 에이전트 합의 — recommendations DB read 우선 (스케줄러 일일 저장),
    #    미스 시에만 live analyze_ticker. 매 GET 10-agent 재실행 제거.
    result["consensus"] = _get_consensus(ticker)

    # 4. Wall Street — 애널리스트 등급 (최근 10건)
    ratings = query(
        "SELECT date, firm, to_grade, action, target_price FROM analyst_ratings "
        "WHERE ticker=? ORDER BY date DESC LIMIT 10",
        (ticker,),
    )
    result["analyst_ratings"] = [dict(r) for r in ratings]

    # 5. Earnings Surprise
    earnings = query(
        "SELECT quarter, eps_actual, eps_estimate, surprise_pct FROM earnings_surprises "
        "WHERE ticker=? ORDER BY quarter DESC LIMIT 8",
        (ticker,),
    )
    result["earnings"] = [dict(e) for e in earnings]

    # 6. Insider 매매 (최근 10건)
    insiders = query(
        "SELECT date, insider_name, position, transaction_type, shares, value "
        "FROM insider_trades WHERE ticker=? ORDER BY date DESC LIMIT 10",
        (ticker,),
    )
    result["insider_trades"] = [dict(i) for i in insiders]

    # 7. 애널리스트 컨센서스 (기존 estimates)
    est = query("SELECT * FROM estimates WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,))
    result["estimates"] = dict(est[0]) if est else None

    # 8. 슈퍼투자자 보유
    si = query(
        "SELECT investor, portfolio_pct, filing_date FROM superinvestors "
        "WHERE ticker=? AND investor_class = 'conviction' ORDER BY portfolio_pct DESC LIMIT 5",
        (ticker,),
    )
    result["superinvestors"] = [dict(s) for s in si]

    # 9. 최근 시그널 — universe 스캔 결과 5분 캐시에서 필터 (매 GET 재스캔 제거)
    result["signals"] = _get_signals(ticker)

    return result


@router.get("/ticker/{symbol}/prices")
def get_ticker_prices(symbol: str, days: int = Query(180, ge=30, le=1825)):
    """종목 가격 히스토리 (차트용)."""
    ticker = symbol.upper()
    rows = query(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, days),
    )
    # 오래된 순으로 정렬
    prices = [dict(r) for r in reversed(rows)]
    return {"ticker": ticker, "prices": prices, "count": len(prices)}
