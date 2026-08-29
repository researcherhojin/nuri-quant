"""held_add would-fire 원장 — 후보 임계 그리드의 전방 측정 (#1173, #788 Stage 1).

## 무엇을 재나

임계는 바꾸지 않는다. 매일 보유×계좌마다 "임계가 X 였다면 발화했을까" 를 후보
그리드 전체에 대해 기록한다:

- ``current``      — config 의 mode 별 composite_score_min (75/75/80)
- ``abs_{T}``      — 절대 완화: 전 mode 에 단일 임계 T (config `grid.absolute`)
- ``p{P}``         — 상대: 당일 **비-blackout 보유 전체** score 분포의 P 백분위를
                     전 mode 에 적용 (모집단을 게이트 통과분으로 좁히면 표본이
                     0~2개로 붕괴한다 — codex 리뷰 A)
- ``rank_floor``   — 결합: max(백분위 임계, 절대 floor)

variant 의 발화 = "gates[m] ∧ score ≥ 임계" 의 첫 precedence mode — 라이브
`select_held_mode` 와 같은 결합 형태라 임계 완화가 current 와 **다른 상위
precedence mode** 를 고를 수 있고, 그것까지가 측정 대상이다 (Stage 2 incremental
정의는 "V 가 어떤 mode 를 고르든 V 발화 ∧ current 미발화").

## 무엇을 기록하지 않나

- ``days_held`` — `_get_held_positions` 의 30 은 하드코딩 fallback 이지 측정값이
  아니다. append-only 원장에 조작값을 관측치로 박으면 Stage 2 공변량이 영구
  오염된다 (codex P1). gates 에는 fallback 의 효과가 남지만 모든 variant 가 같은
  gates 를 공유하므로 variant **간** 비교에서는 상쇄된다.

- blackout 행의 score/RSI/sector_mom — provider 를 타기 전에 끊기므로 (종전
  short-circuit 유지) 관측치 자체가 없다. NULL 로 남는다.

## 멱등성

UNIQUE(as_of_date, ticker, account) + ON CONFLICT DO UPDATE — 하루 안의 재실행은
최신 평가로 갱신하고, **이번 실행에 없는 그날의 고아 행은 삭제**한다 (당일 최종
데이터 스냅샷이 canonical — upsert 만으로는 재실행 사이에 판 보유의 행과 낡은
백분위 grid 가 남는다, codex diff P2). 재실행 감사는 run_id / updated_at 으로.

Stage 2 판정 스펙(사전등록)은 `config/buy_signals.yaml`
`held_add_mode.would_fire_logging.stage2_adjudication` + STRATEGY §3.12 가 정본.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from nuri.core.db import get_db
from nuri.core.timezone import kst_now

from .held_add import MODE_PRECEDENCE

logger = logging.getLogger(__name__)

MODES_BY_PRECEDENCE = sorted(MODE_PRECEDENCE.keys(), key=lambda m: MODE_PRECEDENCE[m])


def compute_grid_thresholds(
    scores: list[float],
    current_thresholds: dict[str, float],
    grid_cfg: dict[str, Any],
) -> dict[str, dict[str, Optional[float]]]:
    """variant → mode → 임계. 백분위 variant 는 당일 score 분포가 비어 있으면 None
    (발화 불가로 처리 — 전원 blackout 인 날은 어차피 gates 가 전부 false 다)."""
    out: dict[str, dict[str, Optional[float]]] = {"current": {m: current_thresholds[m] for m in MODES_BY_PRECEDENCE}}
    for t in grid_cfg.get("absolute", []):
        out[f"abs_{int(t)}"] = dict.fromkeys(MODES_BY_PRECEDENCE, float(t))

    pct_values: dict[int, Optional[float]] = {}
    for p in grid_cfg.get("percentiles", []):
        val = float(np.percentile(scores, int(p))) if scores else None
        pct_values[int(p)] = val
        out[f"p{int(p)}"] = dict.fromkeys(MODES_BY_PRECEDENCE, val)

    rf = grid_cfg.get("rank_floor") or {}
    if rf:
        p = int(rf.get("percentile", 70))
        floor = float(rf.get("floor", 60))
        base = pct_values.get(p)
        if base is None:
            base = float(np.percentile(scores, p)) if scores else None
        val = max(base, floor) if base is not None else None
        out["rank_floor"] = dict.fromkeys(MODES_BY_PRECEDENCE, val)
    return out


def compute_would_fire(
    score: float,
    gates: dict[str, bool],
    grid_thresholds: dict[str, dict[str, Optional[float]]],
) -> dict[str, Optional[str]]:
    """variant 별 발화 mode (없으면 None) — precedence 순 첫 (gates ∧ score ≥ 임계)."""
    out: dict[str, Optional[str]] = {}
    for variant, per_mode in grid_thresholds.items():
        fired = None
        for m in MODES_BY_PRECEDENCE:
            thr = per_mode.get(m)
            if thr is not None and gates.get(m) and score >= thr:
                fired = m
                break
        out[variant] = fired
    return out


def compute_near_threshold(
    score: float,
    gates: dict[str, bool],
    current_thresholds: dict[str, float],
    near_band: float,
) -> bool:
    """current 임계 ±near_band 이내 (gates 통과 mode 한정) — 경계 표본 식별용."""
    return any(gates.get(m) and abs(score - current_thresholds[m]) <= near_band for m in MODES_BY_PRECEDENCE)


def log_would_fire_rows(
    rows: list[dict[str, Any]],
    wf_cfg: dict[str, Any],
    current_thresholds: dict[str, float],
    as_of_date: str,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """당일 평가 행 일괄 기록 (멱등 upsert). 반환: 기록 행 수.

    rows 원소: {ticker, account, score, pnl_pct, rsi, sector_mom, headroom_pct,
    gates, earnings_blackout} — `emit_held_add_shadow` 가 라이브 emit 과 같은
    provider 스냅샷으로 채운다.
    """
    grid_cfg = wf_cfg.get("grid") or {}
    near_band = float(wf_cfg.get("near_band", 5))
    scores = [float(r["score"]) for r in rows if not r["earnings_blackout"] and r["score"] is not None]
    grid = compute_grid_thresholds(scores, current_thresholds, grid_cfg)
    grid_json = json.dumps(grid, ensure_ascii=False)
    now_iso = kst_now().isoformat()

    n = 0
    with get_db(db_path) as conn:
        # 당일 고아 행 삭제 — 이번 실행에 없는 (ticker, account) 는 그날의 canonical
        # 스냅샷이 아니다 (재실행 사이 매도/보유 변동). 같은 트랜잭션이라 부분 상태가
        # 노출되지 않는다.
        existing = conn.execute(
            "SELECT id, ticker, account FROM held_add_would_fire WHERE as_of_date = ?", (as_of_date,)
        ).fetchall()
        current_keys = {(r["ticker"], r["account"]) for r in rows}
        orphans = [row["id"] for row in existing if (row["ticker"], row["account"]) not in current_keys]
        if orphans:
            conn.execute(
                f"DELETE FROM held_add_would_fire WHERE id IN ({','.join('?' * len(orphans))})",
                orphans,
            )
        for r in rows:
            blackout = bool(r["earnings_blackout"])
            gates = {m: bool(v) for m, v in r["gates"].items()}
            score_val = r["score"]
            if blackout or score_val is None:
                wf: dict[str, Optional[str]] = dict.fromkeys(grid.keys())
                near = 0
            else:
                wf = compute_would_fire(float(score_val), gates, grid)
                near = int(compute_near_threshold(float(score_val), gates, current_thresholds, near_band))
            conn.execute(
                """INSERT INTO held_add_would_fire
                     (as_of_date, ticker, account, score, pnl_pct, rsi, sector_mom,
                      headroom_pct, gates_json, grid_thresholds_json, would_fire_json,
                      near_threshold, earnings_blackout, run_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(as_of_date, ticker, account) DO UPDATE SET
                     score=excluded.score, pnl_pct=excluded.pnl_pct, rsi=excluded.rsi,
                     sector_mom=excluded.sector_mom, headroom_pct=excluded.headroom_pct,
                     gates_json=excluded.gates_json,
                     grid_thresholds_json=excluded.grid_thresholds_json,
                     would_fire_json=excluded.would_fire_json,
                     near_threshold=excluded.near_threshold,
                     earnings_blackout=excluded.earnings_blackout,
                     run_id=excluded.run_id, updated_at=excluded.updated_at""",
                (
                    as_of_date,
                    r["ticker"],
                    r["account"],
                    None if r["score"] is None else float(r["score"]),
                    float(r["pnl_pct"]),
                    r.get("rsi"),
                    None if r.get("sector_mom") is None else float(r["sector_mom"]),
                    r.get("headroom_pct"),
                    json.dumps(gates, ensure_ascii=False),
                    grid_json,
                    json.dumps(wf, ensure_ascii=False),
                    near,
                    int(blackout),
                    run_id,
                    now_iso,
                    now_iso,
                ),
            )
            n += 1
    return n
