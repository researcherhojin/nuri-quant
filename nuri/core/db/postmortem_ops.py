"""Phase 2 post-market postmortem (#596 Phase 2).

Daily snapshot of regime/macro/holdings + similarity-based pattern recall:
"오늘과 비슷한 과거 N건, 그때 결과는?" — answers "next time this regime
hits, here's what historically followed and how the system reacted."

Schema: `market_postmortem` (PK = (date, session)). Hybrid layout — columns
that drive similarity search (regime, vix, fg, 5d-deltas, sector top mover,
holdings PnL) are first-class so we can prefilter via index; full payload
JSON blobs (`macro_summary`, `holdings_pnl`, `sector_movers`, `catalysts`,
`retro_lessons`) live alongside for the markdown / LLM retro consumer.

Similarity = cosine over an 8-d feature vector built from the indexed columns
(regime is one-hot encoded vs the seen-regime universe in the candidate set,
falling back to a single signed indicator when the regime appears nowhere
else). N+7d outcomes are surfaced via join with `decision_outcomes` left to
the caller (forward_outcome_tracker integration is Phase 3 scope).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from .connection import get_db

_VALID_SESSIONS = ("kr", "us")


def upsert_postmortem(
    date: str,
    session: str,
    *,
    regime: Optional[str] = None,
    vix: Optional[float] = None,
    fear_greed: Optional[float] = None,
    vix_5d_delta: Optional[float] = None,
    fg_5d_delta: Optional[float] = None,
    spy_5d_delta: Optional[float] = None,
    top_sector_delta_pct: Optional[float] = None,
    holdings_total_pnl_pct: Optional[float] = None,
    macro_summary: Optional[dict[str, Any]] = None,
    holdings_pnl: Optional[dict[str, Any]] = None,
    sector_movers: Optional[list[dict[str, Any]]] = None,
    catalysts: Optional[dict[str, Any]] = None,
    retro_lessons: Optional[list[str]] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Idempotent UPSERT — same (date, session) overwrites the row."""
    if session not in _VALID_SESSIONS:
        raise ValueError(f"session must be one of {_VALID_SESSIONS}, got {session!r}")

    macro_json = json.dumps(macro_summary or {}, ensure_ascii=False)
    holdings_json = json.dumps(holdings_pnl or {}, ensure_ascii=False)
    sectors_json = json.dumps(sector_movers or [], ensure_ascii=False)
    catalysts_json = json.dumps(catalysts or {}, ensure_ascii=False)
    lessons_json = json.dumps(retro_lessons or [], ensure_ascii=False)

    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO market_postmortem
               (date, session, regime, vix, fear_greed,
                vix_5d_delta, fg_5d_delta, spy_5d_delta,
                top_sector_delta_pct, holdings_total_pnl_pct,
                macro_summary, holdings_pnl, sector_movers, catalysts, retro_lessons)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date, session) DO UPDATE SET
                   regime = excluded.regime,
                   vix = excluded.vix,
                   fear_greed = excluded.fear_greed,
                   vix_5d_delta = excluded.vix_5d_delta,
                   fg_5d_delta = excluded.fg_5d_delta,
                   spy_5d_delta = excluded.spy_5d_delta,
                   top_sector_delta_pct = excluded.top_sector_delta_pct,
                   holdings_total_pnl_pct = excluded.holdings_total_pnl_pct,
                   macro_summary = excluded.macro_summary,
                   holdings_pnl = excluded.holdings_pnl,
                   sector_movers = excluded.sector_movers,
                   catalysts = excluded.catalysts,
                   retro_lessons = excluded.retro_lessons""",
            (
                date,
                session,
                regime,
                vix,
                fear_greed,
                vix_5d_delta,
                fg_5d_delta,
                spy_5d_delta,
                top_sector_delta_pct,
                holdings_total_pnl_pct,
                macro_json,
                holdings_json,
                sectors_json,
                catalysts_json,
                lessons_json,
            ),
        )


def _feature_vector(row: dict[str, Any], regime_universe: list[str]) -> list[float]:
    """8-d (or 8 + |regime_universe|-d) cosine-friendly vector.

    Numeric columns are passed straight; missing → 0.0 so cosine isn't
    biased by the prior. Regime is one-hot expanded over the candidate set
    so two distinct regimes contribute orthogonal mass even when the rest
    of the row matches.
    """
    vec = [
        float(row.get("vix") or 0.0),
        float(row.get("fear_greed") or 0.0),
        float(row.get("vix_5d_delta") or 0.0),
        float(row.get("fg_5d_delta") or 0.0),
        float(row.get("spy_5d_delta") or 0.0),
        float(row.get("top_sector_delta_pct") or 0.0),
        float(row.get("holdings_total_pnl_pct") or 0.0),
    ]
    regime = row.get("regime")
    for r in regime_universe:
        vec.append(1.0 if regime == r else 0.0)
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity ∈ [-1, 1]. Zero norm → 0.0 (degenerate)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def find_similar_days(
    *,
    session: str,
    regime: Optional[str] = None,
    vix: Optional[float] = None,
    fear_greed: Optional[float] = None,
    vix_5d_delta: Optional[float] = None,
    fg_5d_delta: Optional[float] = None,
    spy_5d_delta: Optional[float] = None,
    top_sector_delta_pct: Optional[float] = None,
    holdings_total_pnl_pct: Optional[float] = None,
    k: int = 5,
    exclude_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return the top-k most similar prior postmortems to the supplied query vector.

    Each result dict carries the original row fields plus `similarity` (cosine).
    Sorted descending by similarity. Caller can join with `decision_outcomes`
    on date to recover N+7d outcome (Phase 3 wiring).
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"session must be one of {_VALID_SESSIONS}, got {session!r}")

    # indexed feature 컬럼만 SELECT — cosine 는 이 수치만 사용. 개인 JSON blob
    # (holdings_pnl/macro_summary/sector_movers/catalysts/retro_lessons)은 결과에서
    # 제외해 caller egress footgun 차단 (#797, STRATEGY §4.4.3). blob 필요 시 별 fetch.
    _SIM_COLS = (
        "date, session, regime, vix, fear_greed, vix_5d_delta, fg_5d_delta, "
        "spy_5d_delta, top_sector_delta_pct, holdings_total_pnl_pct"
    )
    with get_db(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(f"SELECT {_SIM_COLS} FROM market_postmortem WHERE session = ?", (session,)).fetchall()
        ]
    if exclude_date:
        rows = [r for r in rows if r["date"] != exclude_date]
    if not rows:
        return []

    regime_universe = sorted({r["regime"] for r in rows if r["regime"]})
    if regime and regime not in regime_universe:
        regime_universe.append(regime)

    query_row = {
        "regime": regime,
        "vix": vix,
        "fear_greed": fear_greed,
        "vix_5d_delta": vix_5d_delta,
        "fg_5d_delta": fg_5d_delta,
        "spy_5d_delta": spy_5d_delta,
        "top_sector_delta_pct": top_sector_delta_pct,
        "holdings_total_pnl_pct": holdings_total_pnl_pct,
    }
    qv = _feature_vector(query_row, regime_universe)

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        rd = dict(r)
        sim = _cosine(qv, _feature_vector(rd, regime_universe))
        scored.append((sim, rd))

    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[dict[str, Any]] = []
    for sim, rd in scored[: max(0, int(k))]:
        rd["similarity"] = sim
        out.append(rd)
    return out
