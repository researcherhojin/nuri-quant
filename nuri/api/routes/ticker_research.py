"""종목 브리핑 자료 — 저장된 사실을 조회하고 명시적 요청 때만 수집한다."""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path

from nuri.api.auth import require_write_auth
from nuri.api.limits import heavy_slot
from nuri.core.db import audit_log, get_db, query
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ticker"])
Symbol = Path(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9^][A-Za-z0-9.^=-]*$")
_collection_lock = threading.Lock()
_briefing_lock = threading.Lock()
_briefing_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="public-briefing")


def _stored_dossier(ticker: str) -> dict | None:
    rows = query(
        "SELECT details FROM external_analysis WHERE ticker=? AND source='yahoo_finance' "
        "AND data_type='company_research' ORDER BY date DESC, collected_at DESC LIMIT 1",
        (ticker,),
    )
    dossier = None
    if rows:
        try:
            parsed = json.loads(rows[0]["details"])
            if isinstance(parsed, dict) and parsed.get("ticker") == ticker:
                dossier = parsed
        except (ValueError, TypeError):
            logger.warning("기업 자료 JSON 오류: %s", ticker)
    return dossier


def _collected_today(dossier: dict | None) -> bool:
    return bool(
        dossier and dossier.get("schema_version") == 6 and str(dossier.get("collected_at", "")).startswith(today_kst())
    )


@router.get("/ticker/{symbol}/research")
def get_ticker_research(symbol: str = Symbol):
    ticker = symbol.upper()
    dossier = _stored_dossier(ticker)
    news = query(
        "SELECT date, title, url, source FROM news WHERE ticker=? ORDER BY date DESC, id DESC LIMIT 8", (ticker,)
    )
    events = query(
        "SELECT date, event_type, description FROM events WHERE ticker=? ORDER BY date DESC LIMIT 8", (ticker,)
    )
    fundamentals = query("SELECT * FROM fundamentals WHERE ticker=? ORDER BY date DESC LIMIT 12", (ticker,))
    return {
        "ticker": ticker,
        "dossier": _public_dossier(dossier),
        "public_briefing": _stored_briefing(ticker, dossier),
        "news": news,
        "events": events,
        "fundamentals_history": fundamentals,
        "news_count": len(news),
        "today": today_kst(),
        "collected_today": _collected_today(dossier),
    }


@router.post("/ticker/{symbol}/research/refresh", dependencies=[Depends(heavy_slot)])
def refresh_ticker_research(symbol: str = Symbol, force: bool = False, user=Depends(require_write_auth)):
    from nuri.collectors.company_research import CompanyResearchCollector

    ticker = symbol.upper()
    if not force and _collected_today(_stored_dossier(ticker)):
        return {"saved": 0, "ticker": ticker, "reused": True}
    if not _collection_lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="다른 종목 자료를 수집 중입니다.", headers={"Retry-After": "5"})
    try:
        if not force and _collected_today(_stored_dossier(ticker)):
            return {"saved": 0, "ticker": ticker, "reused": True}
        collector = CompanyResearchCollector()
        # 사용자 요청 수집은 실패 알림을 외부에 전송하지 않는다.
        data = collector.collect(ticker=ticker)
        count = collector.save(data)
    except Exception:
        logger.exception("기업 자료 수집 실패: %s", symbol)
        raise HTTPException(status_code=502, detail="기업 자료를 수집하지 못했습니다.") from None
    finally:
        _collection_lock.release()
    audit_log("REFRESH", "external_analysis", symbol.upper(), "company_research", user_id=user.get("sub", "unknown"))
    if not count:
        raise HTTPException(status_code=404, detail="이 심볼의 회사 정보를 공급자에서 확인하지 못했습니다.")
    return {"saved": count, "ticker": symbol.upper()}


def _public_dossier(dossier: dict | None) -> dict | None:
    if dossier is None:
        return None
    # 원문은 분석 캐시에만 보관한다. API가 기사 전문을 재게시하지 않는다.
    allowed = {
        "ticker",
        "schema_version",
        "collected_at",
        "unavailable",
        "profile",
        "business",
        "statements",
        "fund",
        "price_history",
        "news",
        "news_check",
    }
    result = {key: value for key, value in dossier.items() if key in allowed}
    profile_keys = {
        "name",
        "symbol",
        "description",
        "sector",
        "industry",
        "country",
        "website",
        "exchange",
        "quote_type",
        "currency",
        "financial_currency",
        "market_cap",
        "display_name",
        "identity_source_url",
    }
    result["profile"] = {key: value for key, value in dossier.get("profile", {}).items() if key in profile_keys}
    news_keys = {
        "date",
        "title",
        "url",
        "source",
        "article_url",
        "excerpt",
        "topics",
        "content_checked_at",
        "content_status",
    }
    result["news"] = [
        {key: value for key, value in item.items() if key in news_keys} for item in dossier.get("news", [])
    ]
    return result


def _stored_briefing(ticker: str, dossier: dict | None) -> dict | None:
    from nuri.llm.research_briefing import MODEL, VERSION, evidence_hash, public_bundle

    rows = query(
        "SELECT details FROM external_analysis WHERE ticker=? AND source='source_backed_briefing' "
        "AND data_type='public_briefing' ORDER BY date DESC, collected_at DESC LIMIT 1",
        (ticker,),
    )
    if not rows or not dossier:
        return None
    try:
        result = json.loads(rows[0]["details"])
        if (
            result.get("evidence_hash") != evidence_hash(public_bundle(dossier))
            or result.get("prompt_version") != VERSION
            or result.get("model") != MODEL
        ):
            return {"status": "stale", "message": "자료가 갱신되었습니다. 최신 근거로 브리핑을 다시 생성하세요."}
        if result.get("status") == "pending" and not _pending_alive(result):
            return {"status": "unavailable", "message": "생성 작업이 중단되었습니다. 다시 실행하세요."}
        return result
    except (ValueError, TypeError):
        return None


def _pending_alive(result: dict) -> bool:
    try:
        started = datetime.fromisoformat(result["started_at"])
        age = kst_now() - started
        return started.tzinfo is not None and timedelta(0) <= age < timedelta(minutes=30)
    except (KeyError, ValueError, TypeError):
        return False


def _claim_briefing_job(ticker: str, result: dict):
    # 프로세스 간 중복 송신도 막는다. 모든 pending 행의 lease를 같은 쓰기 트랜잭션에서 확인한다.
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT details FROM external_analysis WHERE source='source_backed_briefing' "
            "AND data_type='public_briefing' AND value='pending'"
        ).fetchall()
        for row in rows:
            try:
                if _pending_alive(json.loads(row[0])):
                    raise HTTPException(status_code=503, detail="브리핑을 생성 중입니다.", headers={"Retry-After": "5"})
            except (ValueError, TypeError):
                continue
        now = kst_now().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO external_analysis "
            "(date,source,ticker,data_type,value,details,collected_at) VALUES(?,?,?,?,?,?,?)",
            (
                today_kst(),
                "source_backed_briefing",
                ticker,
                "public_briefing",
                "pending",
                json.dumps(result, ensure_ascii=False),
                now,
            ),
        )


def _save_briefing(ticker: str, result: dict):
    now = kst_now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO external_analysis "
            "(date,source,ticker,data_type,value,details,collected_at) VALUES(?,?,?,?,?,?,?)",
            (
                today_kst(),
                "source_backed_briefing",
                ticker,
                "public_briefing",
                result["status"],
                json.dumps(result, ensure_ascii=False, allow_nan=False),
                now,
            ),
        )


def _clear_failed_job(ticker: str, pending: dict):
    try:
        _save_briefing(
            ticker, {**pending, "status": "unavailable", "message": "브리핑 생성이 중단되었습니다. 다시 실행하세요."}
        )
    except Exception:
        logger.exception("브리핑 실패 상태 저장 오류: %s", ticker)


def _build_briefing(ticker: str, dossier: dict, pending: dict):
    from nuri.llm.research_briefing import generate_briefing

    try:
        _save_briefing(ticker, generate_briefing(dossier))
    except Exception:
        logger.exception("공개 브리핑 생성 실패: %s", ticker)
        _clear_failed_job(ticker, pending)
    finally:
        _briefing_lock.release()


@router.post("/ticker/{symbol}/research/briefing", status_code=202, dependencies=[Depends(heavy_slot)])
def request_public_briefing(symbol: str = Symbol, user=Depends(require_write_auth)):
    from nuri.llm.research_briefing import MODEL, VERSION, evidence_hash, public_bundle

    ticker = symbol.upper()
    dossier = _stored_dossier(ticker)
    if not dossier:
        raise HTTPException(status_code=409, detail="먼저 기업 자료를 갱신하세요.")
    current = _stored_briefing(ticker, dossier)
    if current and current.get("status") == "ready":
        return {"ticker": ticker, "status": "ready", "reused": True}
    if not _briefing_lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="브리핑을 생성 중입니다.", headers={"Retry-After": "5"})
    try:
        bundle = public_bundle(dossier)
        pending = {
            "status": "pending",
            "model": MODEL,
            "evidence_hash": evidence_hash(bundle),
            "prompt_version": VERSION,
            "started_at": kst_now().isoformat(),
        }
        _claim_briefing_job(ticker, pending)
        try:
            _briefing_worker.submit(_build_briefing, ticker, dossier, pending)
        except Exception:
            _clear_failed_job(ticker, pending)
            raise
    except HTTPException:
        _briefing_lock.release()
        raise
    except Exception:
        _briefing_lock.release()
        raise HTTPException(status_code=502, detail="브리핑 작업을 시작하지 못했습니다.") from None
    audit_log("GENERATE", "external_analysis", ticker, "public_briefing", user_id=user.get("sub", "unknown"))
    return {"ticker": ticker, "status": "pending"}
