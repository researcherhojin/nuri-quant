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
    # `signals` 는 시장별 두 정책이다 (#1101). BUY 점수의 0.15 가중치(RSI)와 SIEGE 게이트
    # 일부가 읽는 테이블인데 정책이 없어서 커버리지가 40종목(가격 753 대비)으로 넉 달을
    # 갔고, 오늘 run 이 무엇을 남기든 어떤 화면에도 안 떴다.
    #
    # 맨 `MAX(date)` 로는 부족하다 (Codex 1차): 잡이 보유 18종목만 갱신해도 그 몇 행이
    # 날짜를 끌어올려 초록이 된다. 그래서 **`config/universe.yaml` 해당 시장 멤버의 60%
    # 이상이 계산된 날짜 중 최신**만 센다. 멤버 목록·floor 전부 판정 시점에 config 에서
    # 도출한다 (`check_freshness` 의 `floor_from` 처리):
    # - 하나로 합치지 않는다 (2차): KR/US 는 서로 다른 날짜로 갈라져 합산 floor 는 US
    #   단독으로 넘는다 — KR 전면 정지가 US 뒤에 숨는다
    # - 상수 floor 금지 (6차): universe 를 줄인 설치가 영구 FAIL 이 된다
    # - **멤버 IN 제한** (7차): 전 행을 세면 universe 밖 보유 종목이 floor 를 떠받쳐
    #   "구성된 채점 universe 가 낡았는데 PASS" 가 가능하다. 멤버로 제한하면 시장 구분도
    #   universe 자체가 하므로 별도 LIKE 필터가 필요 없다
    # - universe 미구성 시장은 검사 생략 — KR 슬리브 없는 설치가 영구 빨강이면 아무도 안 본다
    "signals": {
        "query": (
            "SELECT MAX(date) FROM (SELECT date FROM signals "
            "WHERE ticker IN ({placeholders}) "
            "GROUP BY date HAVING COUNT(*) >= {floor})"
        ),
        "floor_from": "us",
        "warn_hours": 48,
        "fail_hours": 120,
        "label": "기술 지표 (US)",
    },
    "signals_kr": {
        # 임계는 prices 와 같은 48/120 — 설날·추석 연휴에는 정직하게 WARN/FAIL 이 뜬다
        # (시장이 닫혀 지표가 실제로 낡은 상태다).
        "query": (
            "SELECT MAX(date) FROM (SELECT date FROM signals "
            "WHERE ticker IN ({placeholders}) "
            "GROUP BY date HAVING COUNT(*) >= {floor})"
        ),
        "floor_from": "kr",
        "warn_hours": 48,
        "fail_hours": 120,
        "label": "기술 지표 (KR)",
    },
    # `fundamentals` 도 시장별 두 정책이다 — `signals` 와 같은 구성, 같은 이유 (#1109).
    # composite 가중치 1.00 중 **0.50**(value 0.25 + quality 0.25)이 이 테이블에서 나오는데
    # 정책이 없어서, 주간 잡이 보유 18종목만 갱신하는 동안 나머지 ~728 종목이 얼마나 낡든
    # 어떤 화면에도 안 떴다. #1071 이 `factors` 에서, #1101 이 `signals` 에서 닫은 같은 구멍이다.
    #
    # 맨 `MAX(date)` 로는 부족하다: 보유 18종목만 갱신돼도 그 몇 행이 날짜를 끌어올려
    # 초록이 된다 — 실제로 2026-04-29~05-04 에 6~9행짜리 쓰기가 그 모양이었다.
    # 그래서 `signals` 와 같은 **universe 멤버 IN 제한 + 60% 커버리지 floor** 를 쓴다.
    #
    # 합치지 않는 이유도 같다: US 543 / KR 203 이라 합산 floor(60% of 746 = 448)는 US 만으로
    # 넘는다 — KIS 가 전면 실패해 KR 이 통째로 비어도 PASS 다.
    #
    # 임계가 48/120 이 아닌 이유: 이 잡은 **주 1회**(일요일 00:00)다. 다음 실행 직전 정상
    # 나이가 168h 이므로 48h WARN 은 매주 6일을 빨갛게 만든다. 192h(8일) = 한 번 걸렀다,
    # 360h(15일) = 두 번 걸렀다.
    "fundamentals": {
        "query": (
            "SELECT MAX(date) FROM (SELECT date FROM fundamentals "
            "WHERE ticker IN ({placeholders}) "
            "GROUP BY date HAVING COUNT(*) >= {floor})"
        ),
        "floor_from": "us",
        "warn_hours": 192,
        "fail_hours": 360,
        "label": "펀더멘탈 (US)",
    },
    "fundamentals_kr": {
        "query": (
            "SELECT MAX(date) FROM (SELECT date FROM fundamentals "
            "WHERE ticker IN ({placeholders}) "
            "GROUP BY date HAVING COUNT(*) >= {floor})"
        ),
        "floor_from": "kr",
        "warn_hours": 192,
        "fail_hours": 360,
        "label": "펀더멘탈 (KR)",
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

    sql = policy["query"]
    params: tuple = ()
    if "floor_from" in policy:
        import math

        from nuri.core.coverage import _load_universe

        # 커버리지 검사는 **구성된 universe 멤버**만 센다 — 전 행을 세면 universe 밖
        # 보유 종목이 floor 를 떠받친다. floor 는 멤버의 60%, **올림** — 내림이면 작은
        # universe 에서 33~58% 커버리지가 초록으로 통한다 (Codex 7차).
        members = sorted(_load_universe().get(policy["floor_from"]) or ())
        if not members:
            return {
                "key": key,
                "label": policy["label"],
                "status": "PASS",
                "last_updated": None,
                "age_hours": None,
                "message": "해당 시장 universe 미구성 — 검사 생략",
            }
        floor = max(1, math.ceil(len(members) * 0.6))
        sql = sql.format(placeholders=", ".join("?" * len(members)), floor=floor)
        params = tuple(members)

    try:
        rows = query(sql, params, db_path=db_path)
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
