"""데이터 신선도 체크 — Dagster PASS/WARN/FAIL + Palantir TSLU 패턴.

임계(warn/fail 시간)는 **정책**이라 `config/freshness.yaml` 에 있고(#1180,
config-over-code), 쿼리·라벨은 구현이라 여기 남는다. 아래 각 정책의 긴 주석은
쿼리 형태의 근거이므로 임계가 config 로 나가도 유지한다.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from nuri.core.db import query
from nuri.core.timezone import KST, kst_now

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "freshness.yaml"

# 임계 없는 정책 골격 — warn_hours/fail_hours 는 _load_config() 가 config 에서 주입한다.
FRESHNESS_POLICIES: dict[str, dict] = {
    "prices": {
        "query": "SELECT MAX(date) FROM prices WHERE ticker = 'SPY'",
        "label": "주가 데이터",
    },
    "macro_vix": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'vix'",
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
        "label": "펀더멘탈 (US)",
    },
    "fundamentals_kr": {
        "query": (
            "SELECT MAX(date) FROM (SELECT date FROM fundamentals "
            "WHERE ticker IN ({placeholders}) "
            "GROUP BY date HAVING COUNT(*) >= {floor})"
        ),
        "floor_from": "kr",
        "label": "펀더멘탈 (KR)",
    },
    "macro_fear_greed": {
        "query": "SELECT MAX(date) FROM macro WHERE indicator = 'fear_greed'",
        "label": "Fear & Greed",
    },
    # macro_score 의 나머지 입력 두 그룹 (#1180 Codex P1) — vix/fear_greed 만 gate 하면
    # 수익률곡선·put/call·고용·CPI·금리가 낡은 채로 점수에 들어가 verdict 가 선다.
    #
    # **present-only per-indicator MIN** 이 핵심이다: macro_score 는 **결측** 지표를
    # coverage 재정규화로 점수에서 제외하므로(#1026) 없는 지표를 gate 하면 점수에
    # 안 들어가는 입력으로 판단을 막는 셈이다. 반면 **낡은**(행은 있는데 오래된) 지표는
    # `_get_latest_macro` 가 나이 불문 반환해 점수에 그대로 들어간다 — 그게 여기서 잡는
    # 대상이다. GROUP BY 는 존재하는 지표만 만들고, 그중 가장 낡은 것(MIN)을 본다.
    # 그룹 전체 부재 → NULL → FAIL: 구성된 프로덕션에서 그룹째 사라진 건 수집 장애다.
    # 합산 MAX 금지(멀쩡한 지표가 죽은 지표를 가린다)는 signals/ark 와 같은 원칙.
    "macro_market": {
        # 시장성 일간 지표 — 국채 3종 + put/call. fail 임계는 prices(120h)보다 넓은 132h (#1242):
        # 소스(FRED H.15·CBOE)가 T+1 발행이라 영업일 D 관측은 D+1 늦은 오후 ET 에나 열린다.
        # 금요일 관측이 다음 주 수요일 새벽 KST 까지 최신인 게 정상이고, 날짜 문자열
        # 00:00 KST 앵커 기준 정상 최대 나이 ~127h (2026-08-26 02:00 KST 실측 — FAIL 122h
        # 상태에서 FRED 직접 조회로 금요일 이후 관측 부재 확증). 120h 로 되돌리면 매주
        # 수요일 00:00~새벽 KST 에 건강한 파이프라인이 구조적으로 FAIL 한다.
        "query": (
            "SELECT MIN(d) FROM (SELECT MAX(date) AS d FROM macro "
            "WHERE indicator IN ('us_10y_yield', 'us_2y_yield', 'us_3m_yield', 'put_call_ratio') "
            "GROUP BY indicator)"
        ),
        "label": "매크로 시장지표 (금리·PCR)",
    },
    "macro_monthly": {
        # 월간 릴리즈 지표 — 고용·CPI·기준금리. 관측월 기준 날짜라 정상 나이가 수 주다:
        # 45일(1080h) = 한 사이클 지연, 75일(1800h) = 두 사이클째 안 들어왔다.
        "query": (
            "SELECT MIN(d) FROM (SELECT MAX(date) AS d FROM macro "
            "WHERE indicator IN ('unemployment', 'cpi_yoy', 'fed_funds_rate') "
            "GROUP BY indicator)"
        ),
        "label": "매크로 월간지표 (고용·CPI·금리)",
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
        "label": "에이전트 합의",
    },
    "certification": {
        # E4-0a (PR #410) 이후 SIEGE 인증 실행은 `certifications` 테이블에 직접 persist.
        # 이전 policy 는 pipeline_events 'certification_result' 이벤트를 기대했으나 emitter 부재
        # → 항상 FAIL. certifications.timestamp 는 ISO datetime (kst_now().isoformat()).
        "query": "SELECT MAX(timestamp) FROM certifications",
        "label": "Certification",
    },
    "ark": {
        # ARK 는 **엔드포인트가 200 인 채로 내용만 언다** (#1145). 실측: ARKF 가 7.5개월 전
        # 보유를 담은 CSV 를 정상 서빙하는 동안 다른 4개 펀드는 최신이었다. 다운로드도
        # 파싱도 성공하므로 수집기 실패율·collector_runs 어디에도 안 걸린다.
        #
        # 맨 `MAX(date) FROM ark` 는 **초록**이다 — 멀쩡한 펀드 4개가 죽은 펀드 하나를
        # 가린다. 위 `signals` 정책이 KR/US 를 안 합치는 것과 같은 이유이고, 여기서는
        # 펀드가 그 축이다. 그래서 **펀드별 최신 날짜의 최소값**, 즉 가장 낡은 펀드를 본다.
        #
        # 임계: 수집 잡은 화~토 07:30 이고 CSV 기준일은 보통 전 영업일이라 정상 나이가
        # 24~72h 다. 주말·공휴일 흡수해 168h(7일) WARN — `config/rules.yaml
        # ark.max_source_lag_days` 와 같은 값이다. 336h(14일) = 2주째 안 움직였다.
        #
        # **`ark` 테이블을 보지 않는다** (#1147). 거기엔 보유 종목과 겹치는 행만 들어가므로
        # 펀드별 `MAX(date)` 는 "이 펀드가 마지막으로 발행한 날" 이 아니라 "우리가 이 펀드
        # 종목을 마지막으로 들고 있던 날" 이다. ARKG 는 매일 갱신되는데 우리가 그 보유 종목을
        # 안 들어서 4개월째 행이 없었고, 정책이 멀쩡한 펀드를 가장 낡았다고 지목했다 —
        # 소스 감시가 우리 포트폴리오 구성에 의존해버린 것이다. 수집기가 필터와 무관하게
        # 쓰는 `ark_source_dates` 를 본다 (`ark.py _record_source_dates`, 마이그레이션 55).
        #
        # **`COUNT(*) = 5` 가 핵심이다.** 이게 없으면 한 펀드의 행이 아예 **없을 때** MIN 이
        # 남은 펀드들만 보고 초록을 준다 — 새 펀드를 추가했는데 수집이 한 번도 성공 못 한
        # 경우가 정확히 그 모양이고, "진짜로 얼었는데 초록" 이 그대로 남는다. 부재는 최신이
        # 아니라 **미상**이고, 미상은 통과가 아니다. NULL 을 주면 `check_freshness` 가
        # FAIL/"데이터 없음" 으로 처리한다.
        #
        # 목록과 개수는 `ark.py ARK_HOLDINGS_FILES` 와 일치해야 하고,
        # `tests/core/test_ark_freshness_policy.py` 가 양방향으로 대조한다.
        "query": (
            "SELECT CASE WHEN COUNT(*) = 5 THEN MIN(csv_date) END FROM ark_source_dates "
            "WHERE fund IN ('ARKK', 'ARKW', 'ARKG', 'ARKQ', 'ARKF') AND csv_date IS NOT NULL"
        ),
        "label": "ARK 보유 (가장 낡은 펀드)",
    },
    "portfolio": {
        # P0 stale-data fix (#507 audit 2026-04-30): broker 매도/매수 발생 후 yaml
        # sync 누락 시 0주 ticker 에 SELL 권고가 누설됨. 24h 이상이면 WARN, 72h
        # FAIL — `import_portfolio.py` 매일 수동 실행 가정. updated_at 은 KST naive.
        "query": "SELECT MAX(updated_at) FROM portfolio",
        "label": "포트폴리오 sync",
    },
}


def _load_config() -> dict:
    """config/freshness.yaml 로드 + 정책 골격에 임계 주입 (#1180).

    키 목록은 양방향 대조한다 — config 에만 있는 키(낡은 항목)와 코드에만 있는 키
    (임계 없는 정책) 둘 다 기동 시 ValueError. 조용히 기본값으로 넘어가면
    config-over-code 가 다시 무너진다.
    """
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    thresholds = cfg.get("thresholds") or {}
    code_keys = set(FRESHNESS_POLICIES)
    cfg_keys = set(thresholds)
    if code_keys != cfg_keys:
        missing = code_keys - cfg_keys
        stale = cfg_keys - code_keys
        raise ValueError(
            f"freshness.yaml 임계와 FRESHNESS_POLICIES 불일치 — config 누락: {sorted(missing)}, config 잉여: {sorted(stale)}"
        )

    for key, hours in thresholds.items():
        FRESHNESS_POLICIES[key]["warn_hours"] = hours["warn_hours"]
        FRESHNESS_POLICIES[key]["fail_hours"] = hours["fail_hours"]

    gate = cfg.get("verdict_gate") or []
    unknown = [k for k in gate if k not in code_keys]
    if unknown:
        raise ValueError(f"freshness.yaml verdict_gate 에 미등록 정책 키: {unknown}")
    return cfg


_CONFIG = _load_config()

# /api/dashboard verdict 가 신선도를 확인하는 입력 키 목록 (config 정의, #1180)
VERDICT_GATE_KEYS: tuple[str, ...] = tuple(_CONFIG.get("verdict_gate") or ())


def stale_verdict_inputs(db_path: Optional[Path] = None) -> list[dict]:
    """verdict gate 입력 중 FAIL 인 정책만 반환 (#1180, Surface rung).

    WARN 은 통과 — 주말/공휴일의 정상 나이를 WARN 으로 두는 정책이 많아
    WARN 까지 막으면 매주 판단이 죽는다. FAIL = 임계 초과 확정만 센다.
    """
    return [r for r in (check_freshness(k, db_path) for k in VERDICT_GATE_KEYS) if r["status"] == "FAIL"]


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
