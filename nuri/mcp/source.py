"""nuri-read 가 읽을 DB 를 정하고, 그 DB 가 얼마나 낡았는지 알려준다 (#1617).

## 왜 필요한가

개발 머신(MBP)에서 `db_path=None` 은 `data/portfolio.db` — 로컬 개발 DB — 로 풀린다.
그 DB 는 아무도 갱신하지 않아 2026-08-28 에 멈춰 있었고, 서버 지시문은 매매 판단
질문에 이 도구를 조회하라고 한다. 즉 5주 전 SIEGE 판정·후보·VIX 를 현재처럼 내고
있었다. 운영 원장의 시간 단위 사본은 `data/replicas/*.db` 에 따로 있다
(`scripts/deploy/state_replicator.sh`). push 가 `rsync --partial` 이라 전송이 끊기면 실제
파일명에 반쪽 파일이 남을 수 있다 — 그 경우 `freshness()` 는 예외 대신 stale 로 보고한다.

## 출처 우선순위

1. `NURI_DB_PATH` 가 설정돼 있으면 그대로 (테스트·의도적 지정 — `connection.py` 와 같은 축)
2. `data/replicas/*.db` 중 가장 최근 파일 (MBP)
3. 기본 DB (`nuri.core.db.DB_PATH`) — mini 에서는 이것이 원장 자체다

조용한 폴백은 없다: 어느 출처를 골랐는지 `data_freshness` 가 항상 말한다. 경로는
반환하지 않는다 — 복제본 파일명에 mini 호스트명이 들어간다 (privacy scanner 대상).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from nuri.core.db import DB_PATH, DatabaseError, query
from nuri.core.timezone import KST

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLICA_DIR = REPO_ROOT / "data" / "replicas"

#: 복제본 파일 나이 상한. replicator 는 매시간 push 하므로 3시간이면 두 번 연속 실패다.
#: 투자 룰이 아니라 인프라 임계라 config/rules.yaml 이 아닌 코드 상수로 둔다 (api/limits.py 선례).
REPLICA_STALE_HOURS = 3.0

#: 최신 데이터 날짜의 나이 상한(일, KST 달력) — 출처 종류가 아니라 데이터로 판정하므로 mini 의
#: 로컬 원장에도 그대로 맞다. 산출물마다 생기는 주기가 달라 상한도 다르다.
#:
#: - VIX: 미국 거래일 종가. 주말에 미국 월요일 휴장이 겹치면 수요일 KST 에 금요일 날짜가
#:   5일이 되고, 성금요일(목→화)도 5일이다. 4 였을 때는 평범한 주말 직후 화요일 새벽에
#:   경계에 걸렸다 (Codex 리뷰, #1617).
#: - 인증: `premarket_brief` 외에 대시보드 API(engine/targets/actions 라우트)도 `certify()`
#:   를 불러 행을 쓴다. 주기가 트래픽에 달려 있어 VIX 와 같은 넉넉한 상한만 건다.
#: - 후보 run: `premarket_brief`(평일 09:00 ET = 22~23시 KST)가 차단된 날에도 하루 1행을
#:   쓰고(`run_date = today_kst()`), 미국 휴장일도 건너뛰지 않는 일일 heartbeat 다. 정상
#:   최대 공백은 월요일 브리프 전에 금요일 run 을 보는 3일 — VIX 의 5일을 쓰면 브리프를
#:   세 번 놓쳐도 fresh 로 나온다 (Codex 재리뷰 P2).
#:
#: `nuri/core/freshness.py`(대시보드 SLA)를 재사용하지 않는 이유: 그쪽 조회는 읽기 전용이 아니라
#: 이 패키지의 `readonly=True` 계약을 깨고, `candidate_runs` 정책이 없으며, `certification`
#: 48h 는 주말을 넘기지 못한다.
DATA_STALE_DAYS = 5
CANDIDATE_RUN_STALE_DAYS = 3

#: 판정 대상 — (응답 키, SQL, 사람이 읽을 이름, 상한). 하나만 봐서는 안 된다: macro 는 매시간
#: 수집돼 가장 늦게 멈추는 잡이라, VIX 만 보면 `premarket_brief` 가 멈춰도 fresh 로 나온다 (Codex P1).
_LATEST = (
    ("vix_date", "SELECT MAX(date) AS v FROM macro WHERE indicator = 'vix'", "VIX", DATA_STALE_DAYS),
    ("certification_at", "SELECT MAX(timestamp) AS v FROM certifications", "certification", DATA_STALE_DAYS),
    ("candidate_run_date", "SELECT MAX(run_date) AS v FROM candidate_runs", "candidate run", CANDIDATE_RUN_STALE_DAYS),
)


@dataclass(frozen=True)
class Source:
    path: Path
    kind: str  # "env_override" | "replica" | "local"


def resolve_source(replica_dir: Path = REPLICA_DIR) -> Source:
    """읽을 DB 를 고른다 — 우선순위는 모듈 독스트링."""
    env = os.environ.get("NURI_DB_PATH")
    if env:
        return Source(Path(env), "env_override")
    replicas = []
    for p in replica_dir.glob("*.db"):
        try:
            replicas.append((p.stat().st_mtime, p))
        except OSError:  # glob 과 stat 사이에 교체·삭제됨 — 기동을 막지 않고 건너뛴다
            continue
    if replicas:
        return Source(max(replicas)[1], "replica")
    return Source(DB_PATH, "local")


def freshness(source: Source, now: float | None = None) -> dict[str, Any]:
    """출처 종류 · 파일 나이 · 데이터 최신 시각 · stale 판정. 경로는 넣지 않는다."""
    now = time.time() if now is None else now
    try:
        age_hours: float | None = round((now - source.path.stat().st_mtime) / 3600, 2)
    except OSError:
        age_hours = None

    reasons: list[str] = []
    if age_hours is None:
        reasons.append("source file missing")
    elif source.kind == "replica" and age_hours > REPLICA_STALE_HOURS:
        reasons.append(f"replica not updated for {age_hours}h (> {REPLICA_STALE_HOURS}h)")

    latest: dict[str, Any] = {key: None for key, *_ in _LATEST}
    today = datetime.fromtimestamp(now, KST).date()  # today_kst() 와 같은 달력 — 시각 주입용
    checks = _LATEST if age_hours is not None else ()  # 파일 부재 — 조회해도 같은 실패만 반복
    for key, sql, label, limit in checks:
        try:
            rows = query(sql, db_path=source.path, readonly=True)
        except DatabaseError as e:  # OperationalError(테이블 부재)와 손상 파일 둘 다
            reasons.append(f"{label} unreadable ({type(e).__name__})")
            continue
        value = rows[0]["v"] if rows else None
        latest[key] = value
        if value is None:
            reasons.append(f"no {label} in the source")
            continue
        try:
            days = (today - date.fromisoformat(str(value)[:10])).days
        except ValueError:
            reasons.append(f"unparseable {label} date {value!r}")
            continue
        if days > limit:
            reasons.append(f"latest {label} is {days} days old (> {limit})")

    note = None
    if source.kind == "local":
        note = "no replica found — local DB; this is the production ledger only on the mini"

    return {
        "source": source.kind,
        "file_age_hours": age_hours,
        "latest": latest,
        "stale": bool(reasons),
        "stale_reasons": reasons,
        "note": note,
    }
