"""데이터 신선도 체크 — Dagster PASS/WARN/FAIL + Palantir TSLU 패턴."""
from datetime import datetime
from pathlib import Path
from typing import Optional

from nuri.core.db import query
from nuri.core.timezone import KST, kst_now

FRESHNESS_POLICIES = {
    "prices": {
        "query": "SELECT MAX(date) FROM prices WHERE ticker = 'SPY'",
        "warn_hours": 18,
        "fail_hours": 30,
        "label": "주가 데이터",
    },
    "macro_vix": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'vix'",
        "warn_hours": 24,
        "fail_hours": 72,
        "label": "VIX",
    },
    "macro_fear_greed": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'fear_greed'",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "Fear & Greed",
    },
    "consensus": {
        "query": "SELECT MAX(timestamp) FROM pipeline_events WHERE step = 'diagnose' AND event_type = 'step_completed'",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "에이전트 합의",
    },
    "certification": {
        "query": "SELECT MAX(timestamp) FROM pipeline_events WHERE event_type = 'certification_result'",
        "warn_hours": 24,
        "fail_hours": 48,
        "label": "SIEGE 인증",
    },
}


def _parse_timestamp(value: str) -> datetime:
    """날짜/시간 문자열 파싱 (YYYY-MM-DD 또는 ISO datetime)."""
    # ISO datetime (YYYY-MM-DD HH:MM:SS 또는 YYYY-MM-DDTHH:MM:SS)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            # 타임존이 없으면 KST로 간주
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
