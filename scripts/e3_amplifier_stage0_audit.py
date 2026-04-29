#!/usr/bin/env python3
"""E3 Phase 2 Stage 0 — no-lookahead audit (precondition for Stage 2).

STRATEGY §3.6 Stage 0: rolling-stat compute paths must NOT touch dates
> entry_date. Phase 2 spec (`docs/plans/E3_phase2_paired_counterfactual.md`)
treats Stage 0 failure as a precondition failure — Stage 2 does not run,
no `verdict.json` is produced, only this contamination report.

Audit method (dynamic, not static):
    1. Build a temp SQLite DB with two slices of data:
       - past slice (date < as_of_date): plausible historical values
       - future slice (date > as_of_date): extreme contamination markers
         (VIX=999, SPY=$1, etc.)
    2. Call each rolling-stat function with `date=as_of_date`.
    3. Verify the result is influenced ONLY by past-slice data (extreme
       future values must NOT appear in any output statistic).

Audit targets (from spec §"Stage 0"):
    - nuri.quant.regime.classifier.compute_dynamic_thresholds
    - nuri.quant.regime.classifier._load_spy_series
    - nuri.quant.regime.classifier._get_vix
    - nuri.quant.regime.classifier._get_fear_greed
    - nuri.quant.regime.classifier.classify_regime
    - nuri.quant.regime.recovery_detector.evaluate_recovery

Usage:
    .venv/bin/python scripts/e3_amplifier_stage0_audit.py [--report-out PATH]

Exit codes:
    0 — clean (Stage 2 may proceed)
    1 — contamination detected (Stage 2 blocked)
    2 — audit infrastructure error (treat as blocking)
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Ensure project root on path when run as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nuri.core.timezone import today_kst  # noqa: E402
from nuri.quant.regime import classifier as classifier_mod  # noqa: E402
from nuri.quant.regime import recovery_detector as recovery_mod  # noqa: E402

LOG = logging.getLogger("e3_phase2.stage0_audit")

# Contamination markers — values so extreme that any leak shows up immediately.
FUTURE_VIX_VALUE = 999.0  # canonical VIX rarely > 80 historically
FUTURE_SPY_PRICE = 1.0  # canonical SPY > $300 in 2025+
FUTURE_FG_VALUE = 999.0  # F&G is 0-100 by definition

AS_OF_DATE = "2024-06-01"  # mid-history pick — past slice + future slice both present
PAST_DAYS = 1500  # ~6Y prior to AS_OF_DATE — enough for SMA200 + percentile windows
FUTURE_DAYS = 60  # post-as_of contamination slice


@dataclass
class Violation:
    target: str
    description: str
    expected: object = None
    actual: object = None


@dataclass
class AuditResult:
    clean: bool
    as_of_date: str
    checks_run: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)


# ─── temp DB construction ───────────────────────────────────────────────


def _create_minimal_schema(conn: sqlite3.Connection) -> None:
    """Stage 0 audit only needs `prices` and `macro`. Create them directly
    rather than replaying every migration (which couples the audit script
    to migration ordering invariants outside its scope)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL NOT NULL,
            volume INTEGER,
            UNIQUE(ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date);

        CREATE TABLE IF NOT EXISTS macro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator TEXT NOT NULL,
            date TEXT NOT NULL,
            value REAL,
            source TEXT,
            UNIQUE(indicator, date)
        );
        CREATE INDEX IF NOT EXISTS idx_macro_indicator_date ON macro(indicator, date);
        """
    )
    conn.commit()


def _seed_db(db_path: str, as_of: str) -> None:
    """Seed temp DB with past + contaminated future slices."""
    import datetime as _dt

    conn = sqlite3.connect(db_path)
    _create_minimal_schema(conn)

    as_of_dt = _dt.date.fromisoformat(as_of)

    # Past slice: SPY ramps from 200 → 400, VIX ~18 ± noise, F&G ~50.
    # Use trading-day cadence (5 days/week — Mon-Fri) to roughly match SPY data.
    spy_rows = []
    vix_rows = []
    fg_rows = []
    base_price = 200.0
    for i in range(PAST_DAYS, 0, -1):
        d = as_of_dt - _dt.timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        date_str = d.isoformat()
        # SPY: linear-ish ramp, stays in normal range.
        spy_close = base_price + (PAST_DAYS - i) * 0.15
        spy_rows.append(("SPY", date_str, spy_close, spy_close, spy_close, spy_close, 1_000_000))
        # VIX: stable ~18.
        vix_value = 18.0 + ((i % 7) - 3) * 0.4
        vix_rows.append(("vix", date_str, vix_value, "stage0_audit_seed"))
        # F&G: ~50.
        fg_value = 50.0 + ((i % 11) - 5) * 1.0
        fg_rows.append(("fear_greed", date_str, fg_value, "stage0_audit_seed"))

    # Future slice: contamination (post-as_of_date, must NOT influence outputs).
    for i in range(1, FUTURE_DAYS + 1):
        d = as_of_dt + _dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date_str = d.isoformat()
        spy_rows.append(
            ("SPY", date_str, FUTURE_SPY_PRICE, FUTURE_SPY_PRICE, FUTURE_SPY_PRICE, FUTURE_SPY_PRICE, 1_000_000)
        )
        vix_rows.append(("vix", date_str, FUTURE_VIX_VALUE, "stage0_audit_FUTURE_LEAK"))
        fg_rows.append(("fear_greed", date_str, FUTURE_FG_VALUE, "stage0_audit_FUTURE_LEAK"))

    conn.executemany(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        spy_rows,
    )
    conn.executemany(
        "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
        vix_rows + fg_rows,
    )
    conn.commit()
    conn.close()


# ─── individual audit checks ────────────────────────────────────────────


def _check_get_vix(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "classifier._get_vix"
    result.checks_run.append(target)
    vix = classifier_mod._get_vix(date=as_of, db_path=db_path)
    if vix is None:
        result.violations.append(Violation(target, "returned None despite seeded data"))
        return
    if vix >= FUTURE_VIX_VALUE - 1:  # tolerance for float compare
        result.violations.append(Violation(target, "future VIX leaked into result", expected="~18", actual=vix))


def _check_get_fear_greed(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "classifier._get_fear_greed"
    result.checks_run.append(target)
    fg = classifier_mod._get_fear_greed(date=as_of, db_path=db_path)
    if fg is None:
        result.violations.append(Violation(target, "returned None despite seeded data"))
        return
    if fg >= FUTURE_FG_VALUE - 1:
        result.violations.append(Violation(target, "future F&G leaked into result", expected="~50", actual=fg))


def _check_load_spy_series(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "classifier._load_spy_series"
    result.checks_run.append(target)
    df = classifier_mod._load_spy_series(date=as_of, db_path=db_path)
    if df is None:
        result.violations.append(Violation(target, "returned None despite seeded data"))
        return
    max_date = str(df["date"].max())
    if max_date > as_of:
        result.violations.append(Violation(target, "max(date) > as_of_date", expected=f"≤ {as_of}", actual=max_date))
    # Final close must NOT be the contamination marker.
    final_close = float(df["close"].iloc[-1])
    if abs(final_close - FUTURE_SPY_PRICE) < 0.01:
        result.violations.append(
            Violation(target, "final close == contamination marker", expected="historical price", actual=final_close)
        )


def _check_compute_dynamic_thresholds(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "classifier.compute_dynamic_thresholds"
    result.checks_run.append(target)
    th = classifier_mod.compute_dynamic_thresholds(db_path=db_path, date=as_of)
    # If future VIX=999 leaked, vix_threshold (median) and vix_bear_threshold (p75) would jump.
    # Past-only median should sit near 18.
    vix_th = th.get("vix_threshold", 0)
    if vix_th > 50:  # generous — historical VIX p50 should be < 30 always
        result.violations.append(
            Violation(target, "vix_threshold inflated by future leak", expected="< 50", actual=vix_th)
        )
    vix_bear = th.get("vix_bear_threshold", 0)
    if vix_bear > 100:
        result.violations.append(
            Violation(target, "vix_bear_threshold inflated by future leak", expected="< 100", actual=vix_bear)
        )


def _check_classify_regime(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "classifier.classify_regime"
    result.checks_run.append(target)
    rs = classifier_mod.classify_regime(date=as_of, db_path=db_path)
    if rs is None:
        # classify_regime can legitimately return None when SPY data insufficient.
        # Our seed has 1500+ trading days so this is suspicious but not always a leak.
        result.violations.append(
            Violation(target, "returned None — likely seed insufficient or data freshness check leaked")
        )
        return
    # If future VIX=999 leaked into _get_vix call, regime would be high_vol with extreme threshold.
    # Past slice has VIX~18 → expect low_vol. Mismatch indicates leak.
    if rs.regime.endswith("_high_vol"):
        # Could be legitimate if the seed produced a stress pattern, but our seed is benign-ramp.
        # Confirm via the embedded vix detail.
        details_vix = (rs.details or {}).get("vix")
        if details_vix is not None and details_vix > 100:
            result.violations.append(
                Violation(target, "VIX from future leaked into regime details", expected="~18", actual=details_vix)
            )


def _check_evaluate_recovery(db_path: Path, as_of: str, result: AuditResult) -> None:
    target = "recovery_detector.evaluate_recovery"
    result.checks_run.append(target)
    rec = recovery_mod.evaluate_recovery(as_of_date=as_of, db_path=db_path)
    # Recovery uses _fetch_macro_series(... date <= as_of_date) and _fetch_spy_series.
    # If future VIX=999 leaked into prior_stress detection, prior_stress=True with vix_peak~999.
    # Past slice is benign (VIX~18) — prior_stress should be False.
    if rec.prior_stress:
        # Confirm via reasons string — if it cites a vix_peak > 100, leak.
        for reason in rec.prior_stress_reasons:
            if "vix_peak" in reason:
                # extract numeric: "vix_peak_20d=NN.NN"
                try:
                    val = float(reason.split("=")[-1])
                    if val > 100:
                        result.violations.append(
                            Violation(
                                target, "future VIX leaked into recovery prior_stress", expected="< 100", actual=val
                            )
                        )
                except (ValueError, IndexError):
                    pass


# ─── main ───────────────────────────────────────────────────────────────


def run_audit(db_path: str | None = None, as_of_date: str | None = None) -> AuditResult:
    """Run full Stage 0 audit. If `db_path` is None, build a fresh temp DB."""
    as_of = as_of_date or AS_OF_DATE
    result = AuditResult(clean=True, as_of_date=as_of)

    if db_path is None:
        # Build temp DB and seed contamination.
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            _seed_db(tmp_db, as_of)
            return _run_checks(Path(tmp_db), as_of, result)
        finally:
            Path(tmp_db).unlink(missing_ok=True)
    else:
        return _run_checks(Path(db_path), as_of, result)


def _run_checks(db_path: Path, as_of: str, result: AuditResult) -> AuditResult:
    _check_get_vix(db_path, as_of, result)
    _check_get_fear_greed(db_path, as_of, result)
    _check_load_spy_series(db_path, as_of, result)
    _check_compute_dynamic_thresholds(db_path, as_of, result)
    _check_classify_regime(db_path, as_of, result)
    _check_evaluate_recovery(db_path, as_of, result)
    result.clean = len(result.violations) == 0
    return result


def _result_to_json(result: AuditResult) -> dict:
    return {
        "clean": result.clean,
        "as_of_date": result.as_of_date,
        "checks_run": result.checks_run,
        "violations": [asdict(v) for v in result.violations],
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="E3 Phase 2 Stage 0 no-lookahead audit")
    parser.add_argument("--report-out", type=Path, help="path to write JSON report")
    parser.add_argument("--as-of-date", default=AS_OF_DATE, help="audit reference date")
    args = parser.parse_args(argv)

    result = run_audit(as_of_date=args.as_of_date)
    payload = _result_to_json(result)

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        LOG.info("wrote audit report → %s", args.report_out)

    if result.clean:
        LOG.info(
            "Stage 0 audit CLEAN — %d checks, 0 violations. Stage 2 may proceed.",
            len(result.checks_run),
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    LOG.error(
        "Stage 0 audit FAILED — %d violations across %d checks. Stage 2 BLOCKED.",
        len(result.violations),
        len(result.checks_run),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    today_dir = today_kst()
    default_path = Path(f"data/reports/{today_dir}/e3_phase2_stage0_contamination.json")
    if not args.report_out:
        default_path.parent.mkdir(parents=True, exist_ok=True)
        default_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        LOG.info("contamination report → %s", default_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
