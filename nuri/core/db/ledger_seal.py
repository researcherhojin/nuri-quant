"""`recommendations` 판정 원장 봉인 — 날짜별 해시 체인 (#1718).

§3.11 판정 표본의 모집단은 `recommendations` 다. 사전등록은 "판정 기준을 사후에 바꾸지 않는다"
를 약속하지만, 행 자체를 사후에 고치거나 지우지 않았다는 것은 지금까지 기계적으로 보일 수 없었다.
여기서 하루가 끝난(KST 날짜 < 오늘) 행들을 날짜별로 해시하고 앞 날짜의 봉인과 체인으로 잇는다.
봉인된 행의 고정 필드를 바꾸거나, 행을 지우거나, 봉인된 날짜에 행을 끼워 넣거나, 봉인 이전
날짜에 행을 소급해 넣으면 `verify()` 가 잡는다.

**봉인하지 않는 컬럼** — 나중에 정당하게 바뀐다:
`outcome_*` · `hit` · `hit_quality` · `tracked_at` (tracker 의 사후 측정), `regime`
(`scripts/ops/backfill_regime_labels.py` 의 라벨 백필). 결과 원장 `decision_outcomes` 는
규칙이 바뀌면 재측정하도록 설계돼 있어(#1459) 봉인 대상이 아니다.

**한계** — DB 를 고칠 수 있는 사람은 체인 전체를 다시 계산할 수도 있다. 그래서 체인 머리를
DB 밖에 남긴다: 월간 alpha 진행 리포트(#brief, Discord 타임스탬프)가 봉인 날짜와 머리 해시를
싣는다. 첫 봉인(genesis)은 그 시점의 원장을 **있는 그대로** 봉인한다 — 그 이전에 무엇이
바뀌었는지는 증명하지 못한다.

`verify()` 만으로는 **최신 봉인을 지우고 행을 고친 뒤 다시 봉인한 것**(또는 봉인 전체 삭제)을
잡지 못한다 — 남은 체인은 그 자체로 정합하다. 그건 DB 밖에 남은 머리와 대조해야 보인다:
`--anchor DATE HASH` (리포트가 실은 64자 전체 해시. 앞 12자만 싣던 때는 2^24 번 시도로 맞출 수 있었다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional

from .connection import get_db

#: 봉인하는 필드 — **동결** (`_CONFIG_CLOSURE_V1` 과 같은 규칙). 바꾸면 과거 봉인과 비교가 깨지므로
#: 목록을 고치지 말고 `FIELD_SET` 을 v2 로 올리고 새 체인을 시작한다. `id` 가 들어가야 삭제 후
#: 재삽입(같은 내용, 새 id)이 잡힌다.
FIELDS_V1: tuple[str, ...] = (
    "id",
    "date",
    "ticker",
    "action",
    "confidence",
    "signals",
    "entry_price",
    "agent_verdicts",
    "scoring_detail",
    "alpha_action",
    "portfolio_action",
    "source",
    "code_rev",
    "execution_config_sha_v1",
)
FIELD_SET = "v1"
GENESIS = "0" * 64


def _day_digest(conn, date: str) -> tuple[int, str]:
    cols = ", ".join(FIELDS_V1)
    rows = conn.execute(f"SELECT {cols} FROM recommendations WHERE date = ? ORDER BY id", (date,)).fetchall()
    h = hashlib.sha256()
    for row in rows:
        h.update(
            json.dumps(
                [row[i] for i in range(len(FIELDS_V1))], ensure_ascii=False, separators=(",", ":"), default=str
            ).encode()
        )
        h.update(b"\n")
    return len(rows), h.hexdigest()


def _seal_hash(prev_hash: str, date: str, n_rows: int, digest: str) -> str:
    return hashlib.sha256(f"{FIELD_SET}|{prev_hash}|{date}|{n_rows}|{digest}".encode()).hexdigest()


def latest_seal(db_path: Optional[Path] = None) -> Optional[dict]:
    """가장 최근 봉인 (날짜·머리 해시). 봉인이 없으면 None."""
    with get_db(db_path) as conn:
        row = conn.execute("SELECT date, seal_hash FROM recommendation_seals ORDER BY date DESC LIMIT 1").fetchone()
    return {"date": row[0], "seal_hash": row[1]} if row else None


def seal_closed_days(today: str, db_path: Optional[Path] = None) -> list[str]:
    """마지막 봉인 이후, 오늘(KST) 이전의 날짜를 차례로 봉인한다. 봉인한 날짜 목록을 돌려준다.

    오늘은 봉인하지 않는다 — 같은 날 합의 재실행이 행을 덮어쓴다(UPSERT).
    """
    from .provenance import code_rev

    sealed: list[str] = []
    with get_db(db_path) as conn:
        last = conn.execute("SELECT date, seal_hash FROM recommendation_seals ORDER BY date DESC LIMIT 1").fetchone()
        prev_date, prev_hash = (last[0], last[1]) if last else ("", GENESIS)
        days = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM recommendations WHERE date > ? AND date < ? ORDER BY date",
                (prev_date, today),
            ).fetchall()
        ]
        for date in days:
            n_rows, digest = _day_digest(conn, date)
            seal = _seal_hash(prev_hash, date, n_rows, digest)
            conn.execute(
                """INSERT INTO recommendation_seals (date, n_rows, digest, prev_hash, seal_hash, field_set, code_rev)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (date, n_rows, digest, prev_hash, seal, FIELD_SET, code_rev()),
            )
            sealed.append(date)
            prev_hash = seal
    return sealed


def verify(db_path: Optional[Path] = None) -> list[str]:
    """체인을 genesis 부터 다시 계산해 어긋난 곳을 돌려준다. 빈 목록 = 무결."""
    problems: list[str] = []
    with get_db(db_path) as conn:
        seals = conn.execute(
            "SELECT date, n_rows, digest, prev_hash, seal_hash, field_set FROM recommendation_seals ORDER BY date"
        ).fetchall()
        expected_prev = GENESIS
        for date, n_rows, digest, prev_hash, seal_hash, field_set in seals:
            if field_set != FIELD_SET:
                problems.append(f"{date}: field_set {field_set!r} — 이 코드는 {FIELD_SET!r} 만 검증한다")
                continue
            if prev_hash != expected_prev:
                problems.append(f"{date}: 앞 봉인과 체인이 끊겼다 (prev_hash 불일치)")
            if _seal_hash(prev_hash, date, n_rows, digest) != seal_hash:
                problems.append(f"{date}: 봉인 행 자체가 바뀌었다 (seal_hash 불일치)")
            now_n, now_digest = _day_digest(conn, date)
            if (now_n, now_digest) != (n_rows, digest):
                change = f"행 수 {n_rows} → {now_n}" if now_n != n_rows else f"행 {n_rows}개 중 봉인 필드 변경"
                problems.append(f"{date}: 봉인 후 행이 바뀌었다 ({change})")
            expected_prev = seal_hash
        if seals:
            last_date = seals[-1][0]
            sealed_dates = {s[0] for s in seals}
            for (date,) in conn.execute(
                "SELECT DISTINCT date FROM recommendations WHERE date <= ? ORDER BY date", (last_date,)
            ).fetchall():
                if date not in sealed_dates:
                    problems.append(f"{date}: 봉인된 구간 안의 날짜에 봉인 없는 행이 있다 (소급 삽입)")
    return problems


def verify_anchor(date: str, seal_hash: str, db_path: Optional[Path] = None) -> list[str]:
    """DB 밖에 남은 머리(월간 리포트의 봉인 날짜·해시)가 지금 체인에 그대로 있는가.

    봉인을 지우고 다시 만들면 체인은 정합해도 그 날짜의 seal_hash 가 바뀐다.
    """
    with get_db(db_path) as conn:
        row = conn.execute("SELECT seal_hash FROM recommendation_seals WHERE date = ?", (date,)).fetchone()
    if row is None:
        return [f"{date}: 외부에 남은 봉인이 체인에 없다 (봉인 삭제)"]
    if row[0] != seal_hash:
        return [f"{date}: 외부에 남은 머리와 다르다 (봉인 재계산)"]
    return []


def main(argv: Optional[list[str]] = None) -> int:
    from nuri.core.timezone import today_kst

    parser = argparse.ArgumentParser(description="recommendations 판정 원장 봉인 (#1718)")
    parser.add_argument("--db", type=Path, default=None, help="대상 DB (기본: 설정된 DB)")
    parser.add_argument("--seal", action="store_true", help="오늘 이전의 미봉인 날짜를 봉인한다")
    parser.add_argument("--anchor", nargs=2, metavar=("DATE", "HASH"), help="월간 리포트가 실은 봉인 날짜·해시와 대조")
    args = parser.parse_args(argv)

    if args.seal:
        sealed = seal_closed_days(today_kst(), db_path=args.db)
        print(f"봉인 {len(sealed)}일" + (f" ({sealed[0]} ~ {sealed[-1]})" if sealed else ""))
    problems = verify(db_path=args.db)
    if args.anchor:
        problems += verify_anchor(*args.anchor, db_path=args.db)
    head = latest_seal(db_path=args.db)
    if head:
        print(f"봉인 머리: {head['date']} · {head['seal_hash'][:16]}")
    for p in problems:
        print(f"✗ {p}")
    print("✓ 무결" if not problems else f"✗ {len(problems)}건 불일치")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
