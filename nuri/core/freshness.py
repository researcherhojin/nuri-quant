"""데이터 신선도 체크 — Dagster PASS/WARN/FAIL + Palantir TSLU 패턴."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from nuri.core.db import query
from nuri.core.timezone import KST, kst_now

FRESHNESS_POLICIES = {
    "prices": {
        "query": "SELECT MAX(date) FROM prices WHERE ticker = 'SPY'",
        "warn_hours": 48,
        "fail_hours": 120,  # 주말/공휴일 감안 (금→화 = 96h, classifier.py와 동일)
        "label": "주가 데이터",
    },
    "macro_vix": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'vix'",
        "warn_hours": 24,
        "fail_hours": 72,
        "label": "VIX",
    },
    "factors": {
        # BUY 후보 점수의 최대 입력(`buy_signals.yaml` 가중치 0.40)인데 정책이 없어서
        # 2026-04-14 → 2026-08-18 넉 달간 낡은 채로도 어떤 화면에도 안 떴다 (#1071).
        # `factors.date` 는 쓴 날이 아니라 **시장 데이터 날짜**다 (`_market_as_of`) — 그래서
        # 이 검사는 잡의 생존과 입력의 신선도를 **동시에** 본다. 잡이 멈추면 날짜가 얼고,
        # 가격이 멈춰도 날짜가 얼기 때문이다. `today_kst()` 로 찍던 시절엔 주말·휴장에도
        # 당일 행이 생겨 이 정책이 낡음을 잡는 게 아니라 세탁했다 (#1071 Codex P1).
        # 그래서 임계도 `prices` 와 같다 — 재료가 같으니 주말/공휴일 여유도 같아야 한다.
        "query": "SELECT MAX(date) FROM factors",
        "warn_hours": 48,
        "fail_hours": 120,
        "label": "멀티팩터 스코어",
    },
    "signals": {
        # BUY 점수의 0.15 가중치(RSI)와 SIEGE 게이트 일부가 읽는 테이블인데 정책이 없어서
        # 커버리지가 40종목(가격 753 대비)으로 넉 달을 갔고, 오늘 run 이 무엇을 남기든
        # 어떤 화면에도 안 떴다 (#1101). `factors` 와 같은 이유로 `MAX(date)` 는 잡 생존과
        # 입력 신선도를 동시에 본다 — technical 은 prices 를 재료로 하는 순수 계산이라
        # prices 가 멈춰도, 잡이 멈춰도 날짜가 언다. 임계도 재료(prices)와 동일.
        "query": "SELECT MAX(date) FROM signals",
        "warn_hours": 48,
        "fail_hours": 120,
        "label": "기술 지표",
    },
    "macro_fear_greed": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'fear_greed'",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "Fear & Greed",
    },
    "consensus": {
        # FIX (Session 10): `diagnose` step_completed event 가 실제로 emit 되지 않아 항상 FAIL.
        # `recommendations.date` (consensus 결과 persist) 를 source of truth 로 변경.
        # save_to_recommendations 가 매 consensus run 마다 today date row 갱신.
        # date 는 'YYYY-MM-DD' string — datetime 비교 위해 datetime() 캐스트.
        # `source IS NULL` = 합의 산출물. #1078 이후 `buy_candidate_emitter` 도 같은
        # 테이블에 쓰므로, 필터가 없으면 합의 job 이 죽은 날에도 브리핑이 낸 후보 행
        # 하나가 "합의 신선함" 으로 읽힌다 — 관측이 거짓말하는 형태다.
        "query": "SELECT datetime(MAX(date)) FROM recommendations WHERE source IS NULL",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "에이전트 합의",
    },
    "certification": {
        # E4-0a (PR #410) 이후 SIEGE 인증 실행은 `certifications` 테이블에 직접 persist.
        # 이전 policy 는 pipeline_events 'certification_result' 이벤트를 기대했으나 emitter 부재
        # → 항상 FAIL. certifications.timestamp 는 ISO datetime (kst_now().isoformat()).
        "query": "SELECT MAX(timestamp) FROM certifications",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "Certification",
    },
    "portfolio": {
        # P0 stale-data fix (#507 audit 2026-04-30): broker 매도/매수 발생 후 yaml
        # sync 누락 시 0주 ticker 에 SELL 권고가 누설됨. 24h 이상이면 WARN, 72h
        # FAIL — `import_portfolio.py` 매일 수동 실행 가정. updated_at 은 KST naive.
        "query": "SELECT MAX(updated_at) FROM portfolio",
        "warn_hours": 24,
        "fail_hours": 72,
        "label": "포트폴리오 sync",
    },
}


def _parse_timestamp(value: str) -> datetime:
    """날짜/시간 문자열 파싱 (YYYY-MM-DD 또는 ISO datetime, 옵션으로 microseconds/timezone).

    지원 포맷:
    - `YYYY-MM-DD`
    - `YYYY-MM-DD HH:MM:SS` / `YYYY-MM-DDTHH:MM:SS`
    - `YYYY-MM-DDTHH:MM:SS.ffffff±HH:MM` (kst_now().isoformat() — E4-0a certifications)

    fromisoformat 은 Python 3.11+ 에서 extended ISO 를 완전 지원.
    """
    s = value.strip()
    # fromisoformat 먼저 시도 — tz-aware / microseconds 모두 지원 (Python 3.11+)
    try:
        dt = datetime.fromisoformat(s)
        # 타임존이 없으면 KST 로 간주
        return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt
    except ValueError:
        pass
    # strptime fallback (date-only 같은 짧은 포맷)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=KST)
        except ValueError:
            continue
    raise ValueError(f"지원하지 않는 날짜 형식: {value}")


def check_freshness(key: str, db_path: Optional[Path] = None) -> dict:
    """단일 데이터 소스의 신선도 체크."""
    policy = FRESHNESS_POLICIES[key]
    now = kst_now()

    try:
        rows = query(policy["query"], db_path=db_path)
    except Exception:
        return {
            "key": key,
            "label": policy["label"],
            "status": "FAIL",
            "last_updated": None,
            "age_hours": None,
            "message": "쿼리 실행 실패",
        }

    # 결과에서 값 추출 (MAX() 결과는 첫 번째 컬럼)
    value = None
    if rows:
        row = rows[0]
        # dict에서 첫 번째 값 추출
        value = list(row.values())[0]

    if value is None:
        return {
            "key": key,
            "label": policy["label"],
            "status": "FAIL",
            "last_updated": None,
            "age_hours": None,
            "message": "데이터 없음",
        }

    try:
        last_dt = _parse_timestamp(str(value))
    except ValueError:
        return {
            "key": key,
            "label": policy["label"],
            "status": "FAIL",
            "last_updated": str(value),
            "age_hours": None,
            "message": f"날짜 파싱 실패: {value}",
        }

    age_hours = (now - last_dt).total_seconds() / 3600

    if age_hours <= policy["warn_hours"]:
        status = "PASS"
        message = f"최신 ({age_hours:.1f}h)"
    elif age_hours <= policy["fail_hours"]:
        status = "WARN"
        message = f"업데이트 필요 ({age_hours:.1f}h)"
    else:
        status = "FAIL"
        message = f"오래됨 ({age_hours:.1f}h)"

    return {
        "key": key,
        "label": policy["label"],
        "status": status,
        "last_updated": str(value),
        "age_hours": round(age_hours, 1),
        "message": message,
    }


def check_all_freshness(db_path: Optional[Path] = None) -> list[dict]:
    """모든 정책에 대한 신선도 체크."""
    return [check_freshness(key, db_path) for key in FRESHNESS_POLICIES]


def get_freshness_summary(db_path: Optional[Path] = None) -> dict:
    """신선도 요약 → {pass: N, warn: N, fail: N, details: [...]}."""
    details = check_all_freshness(db_path)
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for d in details:
        counts[d["status"].lower()] += 1
    return {**counts, "details": details}
