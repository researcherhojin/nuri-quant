"""Read-only evidence inventory for independent research (#1884).

This is a current database inventory with a date cutoff, not a historical
point-in-time reconstruction or an official performance report.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from nuri.core.db import get_db


def inventory(*, db_path: Path, as_of: date, window: int, min_bars: int) -> dict:
    """Count evidence in one read transaction; never emit holdings or returns."""
    if window not in (7, 14, 30) or min_bars < 1:
        raise ValueError("window must be 7, 14 or 30; min_bars must be positive")
    cutoff = as_of.isoformat()
    maturity = (as_of - timedelta(days=window)).isoformat()
    with get_db(db_path=db_path, readonly=True) as conn:
        conn.execute("BEGIN")
        prices = conn.execute(
            """SELECT ticker, COUNT(*) AS bars, MAX(date) AS latest
               FROM prices WHERE date <= ? AND close > 0 GROUP BY ticker""",
            (cutoff,),
        ).fetchall()
        decisions = conn.execute(
            """SELECT d.status, d.as_of_date, o.alpha, o.realized_return,
                      o.decision_id AS outcome_id
               FROM agent_decisions d LEFT JOIN decision_outcomes o
                 ON o.decision_id = d.decision_id AND o.observation_window = ?
                 AND o.tracked_as_of_date <= ?
               WHERE d.as_of_date <= ?""",
            (window, cutoff, cutoff),
        ).fetchall()
    emitted = [r for r in decisions if r["status"] == "emitted"]
    elapsed = [r for r in emitted if r["as_of_date"] <= maturity]
    return {
        "kind": "research_evidence_inventory",
        "as_of": cutoff,
        "window_calendar_days": window,
        "min_bars": min_bars,
        "prices": {
            "symbols": len(prices),
            "symbols_with_required_bars": sum(r["bars"] >= min_bars for r in prices),
            "latest_bar_date": max((r["latest"] for r in prices), default=None),
        },
        "decisions": {
            "all_statuses": len(decisions),
            "emitted": len(emitted),
            "calendar_elapsed": len(elapsed),
            "elapsed_without_outcome_row": sum(r["outcome_id"] is None for r in elapsed),
            "elapsed_with_return": sum(r["realized_return"] is not None for r in elapsed),
            "elapsed_with_alpha": sum(r["alpha"] is not None for r in elapsed),
        },
        "limitations": [
            "Caller-selected database; production provenance is not verified.",
            "Current rows with date cutoffs; revisions and historical availability are not reconstructed.",
            "Price counts include all stored symbols, not an eligible investment universe.",
            "Calendar elapsed does not mean market settled; absent outcomes are not adjudication failures.",
            "No profitability, execution feasibility or promotion verdict is produced.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Explicit read-only source database")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--window", type=int, choices=(7, 14, 30), required=True)
    parser.add_argument("--min-bars", type=int, required=True, help="Research history requirement")
    args = parser.parse_args()
    print(
        json.dumps(inventory(db_path=args.db, as_of=args.as_of, window=args.window, min_bars=args.min_bars), indent=2)
    )


if __name__ == "__main__":
    main()
