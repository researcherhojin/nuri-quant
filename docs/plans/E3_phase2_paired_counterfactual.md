# E3 Phase 2 — Paired Counterfactual (Plan-phase spec, P1-amended)

**Status**: Plan-phase artifact, **post Codex Round 1 verdict (2026-04-29)** — 7 P1 issues resolved below. Build pending after Round 2 GATE PASS.

**Owner / next session**: pick this up at the top — codex Round 2 GATE → Stage 0 audit (cheapest, blocks Phase 2 if fails) → paired replay engine → verdict run.

**Sources**:
- `docs/plans/E3_symmetric_amplifier_design.md` (8-week phased rollout, parent spec)
- `docs/STRATEGY.md §3.6` (E3 acceptance — Stage 0 + Stage 1 + Stage 2 protocol)
- `config/rules.yaml symmetric_amplifier` (canonical thresholds — VIX < 22 AND 3d slope < 0, etc.)
- PR #479 (Phase 1 shadow skeleton shipped 2026-04-29)
- Codex Round 1 verdict 2026-04-29 (in-session, P1 issues resolved below)

---

## Why now

Phase 1 (#479) shipped shadow skeleton with `amplifier_gate.evaluate()` and `recovery_detector.evaluate_recovery()` — but `enabled: false` everywhere. Phase 2 = STRATEGY §3.6 Stage 2 main gate; paired counterfactual must PASS for the amplifier to ever activate. Without a Phase 2 verdict, Phase 3 (alpha-amplified live) and Phase 4 (portfolio-amplified live) are gated indefinitely. Falsification path is part of the deliverable, not a failure mode to avoid.

## Acceptance — binary, falsifiable

**Precondition (not a verdict)**: Stage 0 no-lookahead audit must be clean. If Stage 0 detects contamination, **no Stage 2 verdict is produced** — a contamination report is generated and Phase 2 is blocked until the underlying lookahead bug is fixed. Stage 0 failure is a precondition failure, NOT a `FAIL` verdict (no `verdict.json` artifact).

Given Stage 0 clean, the verdict is binary:

```
PASS  iff  paired_excess_CI_lower > 0
FAIL  otherwise (i.e. CI_lower ≤ 0, including the case where CI crosses 0)
```

**Decision is binary. No INCONCLUSIVE branch.** "CI crosses 0" is mathematically `CI_lower ≤ 0` and routes to FAIL. Post-FAIL redesign options (sample extension, gate refinement, indefinite freeze) belong in `## Falsification path`, not in the verdict itself.

- **Primary metric**: mean paired excess return at **30 / 60 / 90 trading days** (treatment − baseline, same entries). NO calendar days. NO dynamic exits (no trailing stop, no opposite-signal exit).
- **CI**: 1000-iter block bootstrap (block size = **20 trading days, frozen primary**) on paired delta, 95 % interval. Sensitivity blocks `10 / 40` trading days reported as **informational only** — they cannot move the PASS/FAIL verdict.
- **Sample**: N(eligible+treated) ≥ 200 amplifier-treated entries. Frozen universe = `us_core` 85 tickers.
  - **Verified actual N = 203** under final frozen gate `recovery_confirmed AND vix_favorable AND regime_favorable` (P1#7 measured 2026-04-29 in-session via `evaluate_recovery` + `classify_regime` on 542 VIX-favorable trading days).
  - **Effective N caveat (power limit, surface honestly)**: 203 entries cluster on **9 unique trading days** (~22 entries/day cross-sectional). Ticker correlation on a single day → effective independent block count ≈ 9. Block bootstrap with block_size=20 trading days will likely resample the same day-cluster repeatedly — CI will be wide. This is documented; the PASS/FAIL verdict is reported honestly regardless of magnitude.
- **Stage 0 (no-lookahead)**: rolling-stat compute paths (`compute_dynamic_thresholds`, special-regime detectors, `classify_regime_history`) must NOT touch dates > entry_date.
- **Stage 1 (plausibility, diagnostic only)**: directional sanity check; FAIL does not block ship if Stage 2 PASS.

## Codex Round 1 verdict (2026-04-29) — questions answered

| # | Topic | Frozen answer |
|---|-------|---------------|
| Q1 | Entry signal | `close > rolling_20d_high.shift(1)` strict `>`. **No volume filter** (would confound entry quality with amplifier effect). |
| Q2 | Re-entry cooldown | **No cooldown.** Permit next eligible-bar re-entry. Bootstrap handles dependence. |
| Q3 | Exit logic | **Fixed 30/60/90 trading-day forward horizons only.** No trailing stop, no opposite-signal exit. Same exit between baseline / treatment arms. |
| Q4 | `amp_mult` | **1.5 keep.** Quarter-Kelly is later sizing work, not this legitimacy test. |
| Q5 | Forward return | **Trading days, adj_close consistently.** Split / dividend safe. |
| Q6 | Bootstrap block size | **20 trading days, frozen primary.** `10 / 40` sensitivity is informational only. |
| Q7 | Universe scope | **`us_core` 85, frozen.** Survivorship trade-off accepted (4 missing: ARM, NBIS, RDDT, TEM — recent IPO < 5Y price history). |
| Q8 | Date start | **2020-01-01, COVID included.** Skipping 2020-03 – 2020-06 = cherry-picking; amplifier must survive stressed regimes. |
| Q9 | Treatment trigger | On a 20d-breakout-only sample, `entry_strength=breakout_20d` is **tautologically always True**. Config canonical gate is `recovery_confirmed AND vix_favorable AND (regime_favorable OR macro_benign)` — but in 5Y replay the OR-branch reduces to `regime_favorable` alone (see Q10). **Phase 2 frozen gate**: `recovery_confirmed AND vix_favorable AND regime_favorable`. |
| Q10 | `macro_benign` | `abs(event_score) < 10` (matches `config/rules.yaml`). **However**: `macro_events` table has only ~1 month of history (2026-04-09+ only, schema uses `published_at` not `date`). 5Y backfill not available. **In Phase 2 the macro arm is unavailable as data**, so the canonical OR-branch `regime_favorable OR macro_benign` collapses to `regime_favorable`. macro_benign re-enters the gate at Phase 3+ (live, going forward) once macro_events accumulates. Documented in `verdict.caveats`. |
| Q11 | VIX > 30 rows | **Excluded from treatment sample entirely.** Not zero-effect; that would dilute the estimand. |
| Q12 | Verdict artifact | `data/reports/<YYYY-MM-DD>/e3_phase2_verdict.json` (gitignored). Canonical verdict cited in `docs/STRATEGY.md §3.6`. JSON keys: `spec_version, run_at_kst, git_commit, decision, decision_reason, stage0_audit, universe, date_range, entry_rule, treatment_rule, amp_mult, sample_counts, bootstrap, metrics_by_horizon, sensitivity, caveats`. |

## P1 resolution log (Round 1 → amended in this spec)

| P1 # | Codex finding | Resolution |
|------|--------------|------------|
| 1 | spec said `VIX < 25`, config canonical `VIX < 22 AND 3d slope < 0` | Spec amended to `vix_favorable` per `config/rules.yaml symmetric_amplifier.conditions.vix_favorable` (threshold_max=22, slope_must_be_negative=true). Single source of truth. |
| 2 | "2-of-3 (regime / entry_strength / macro_benign)" framing false on breakout-only sample (entry_strength tautology) | Eligibility gate rewritten as `recovery_confirmed AND vix_favorable AND (regime_favorable OR macro_benign)` — entry_strength removed from gate (already implicit in entry signal). |
| 3 | Analysis population ambiguous (all breakout / eligible / fired) | **Round 2 close**: single definition. `eligible` = `breakout_entry AND recovery_confirmed AND vix_favorable AND regime_favorable` — same as treatment trigger (no separate "fired" subset because all eligible entries are amplifier-treated; baseline arm uses identical entries with sizing=1.0× vs treatment 1.5×). macro arm dropped from gate (Q10 — no 5Y data). Reported counts in verdict: `n_breakout_total`, `n_eligible` (=`n_treated`), `n_excluded_vix_above_30` (informational, redundant since `vix_favorable` implies VIX<22). |
| 4 | Universe not actually frozen ("543 or 85") | **Frozen `us_core` 85** (P1#7 verified — 81/85 with ≥1000 price rows, 4 recent IPO unavoidable). 543 option removed. |
| 5 | Bootstrap block size dynamic ("20d, but increase if diagnostics say so") | **Frozen at 20 trading days primary.** Autocorrelation diagnostic + `10/40` sensitivity reported as informational only — cannot move PASS/FAIL verdict. |
| 6 | Exit logic still framed as design choice | Spec explicitly states "primary metric = fixed-horizon 30/60/90 trading-day forward returns only". No trailing / opposite-signal alternatives. |
| 7 | "Sample size covers either" unverified for us_core | **Round 2 close — measured under final gate, not estimated**: 81/85 us_core tickers with ≥1000 price rows × 14,728 raw 20d-breakout entries × final gate `recovery_confirmed AND vix_favorable AND regime_favorable` → **N=203 entries on 9 unique trading days**. Acceptance N≥200 PASS with 1.0× margin. **Power-limit caveat (effective N≈9, see Acceptance section)** is recorded as a binding limitation; verdict reports magnitudes honestly regardless. |
| Round 2 regression | Spec re-introduced `INCONCLUSIVE` decision and a "CI crosses 0" branch in falsification path → conflicts with binary acceptance | **Closed**: decision is binary PASS/FAIL only. "CI crosses 0" is mathematically `CI_lower ≤ 0` → routes to FAIL. Post-FAIL redesign options remain in `## Falsification path` as next-step menu (NOT verdict states). Verdict schema's `decision` field constrained to `"PASS" | "FAIL"`. |

## Scope

### IN

- `scripts/e3_amplifier_paired_replay.py` — replay engine (5Y prices, 20d breakout entries, paired baseline vs treatment, 30/60/90 forward returns, bootstrap CI)
- `scripts/e3_amplifier_stage0_audit.py` — no-lookahead verification
- `tests/quant/exits/test_amplifier_paired_replay.py` — fixture-driven invariants (same entries / exits between arms, paired delta deterministic given seed, CI math sanity)
- `tests/quant/exits/test_amplifier_stage0_audit.py` — no-lookahead lock-tests
- Verdict artifact `data/reports/<YYYY-MM-DD>/e3_phase2_verdict.json` (gitignored) with metrics + CI bounds + decision (PASS / FAIL)
- `docs/STRATEGY.md §3.6` updated with verdict outcome (canonical citation)
- `docs/TODO.md` Tier 2 P0 row updated (or row dropped if PASS → Phase 3 next-up)

### OUT (deferred — explicit non-goals)

- Phase 3 wiring (`consensus.py` integration emit_event) — separate PR after PASS verdict
- Q3 Kelly quarter cap derivation — Phase 4 concern
- Walk-forward IS / OOS Sharpe + DD — secondary metric per §3.6, deferred
- Monte Carlo regime mis-classification 5 % — secondary, deferred
- Live shadow telemetry emit (still Phase 1.5, separate PR)
- Recovery from Phase 2 FAIL into a redesigned amplifier — own multi-week effort

## Approach (frozen — post P1 amend)

```
1. Universe + price load
   - Source: prices table (already populated via collectors)
   - Tickers: us_core 85 (frozen), 81 with ≥1000 price rows; 4 recent-IPO accepted as missing
   - Validate: ≥ 1000 trading days per ticker (5Y × 252 = 1260 ideal, 1000 lenient floor)
   - Survivorship caveat: today's us_core embeds delisted-from-history bias — documented in verdict.caveats

2. Entry signal: 20d breakout
   - close > rolling_20d_high.shift(1)  (strict >, prior-day high)
   - NO cooldown (next eligible-bar re-entry permitted; bootstrap handles dependence)
   - Population: all 20d-breakout entries from 2020-01-01 onward (COVID included)

3. Eligibility gate (analysis population = "eligible" — single definition, applies to both arms):
   - recovery_confirmed (recovery_detector.evaluate_recovery → recovery_confirmed=True), mandatory
   - vix_favorable (VIX < 22 AND 3d slope < 0), mandatory  ← canonical config
   - regime_favorable: regime in {bull_low_vol, recovery} AND confidence ≥ 0.60, mandatory in Phase 2
     (canonical config has `regime_favorable OR macro_benign`; macro arm dropped because
     macro_events table has no 5Y backfill — see Q10. macro_benign re-enters at Phase 3+ live.)
   - VIX > 30 rows: excluded entirely (not zero-effect; would dilute estimand). Note: `vix_favorable` (<22) already implies this exclusion — counted only as informational `n_excluded_vix_above_30`.

   Measured under this gate (P1#7, 2026-04-29): N=203 entries on 9 unique trading days. Power caveat in Acceptance section.

4. Position sizing (frozen for Phase 2)
   - baseline arm: base_size = 1.0 (unit)
   - treatment arm: base_size × amp_mult; amp_mult = 1.5 (Phase 4 will derive from quarter-Kelly)
   - SAME entries between arms. SAME exits between arms. Only sizing differs.

5. Forward returns: trading-day close-to-close at entry + {30, 60, 90}
   - Use adj_close (split / dividend safe), consistently throughout
   - Per-entry P&L: ret × size
   - Treatment effect per entry: ret × (amp_mult − 1) = ret × 0.5
   - Aggregate metric: mean of (treatment_pnl − baseline_pnl) across entries, per horizon

6. Bootstrap CI: 1000 iterations, block size = 20 trading days (FROZEN PRIMARY)
   - Resample paired deltas with replacement in blocks (autocorrelation buffer)
   - Compute mean per iteration → 95 % percentile interval
   - PASS gate: CI_lower > 0 (per horizon — primary report 30d, secondary 60d/90d)
   - Sensitivity (informational only): block sizes 10 and 40 reported in verdict.sensitivity; cannot change PASS/FAIL.
```

## Dependencies

- ✅ Phase 1 modules (`amplifier_gate.evaluate`, `recovery_detector.evaluate_recovery`)
- ✅ Prices table 5Y (universe-sync ensures coverage; us_core 81/85 with ≥1000 rows)
- ✅ VIX history (macro indicator='vix', 1766 rows 2019-04-22 → 2026-04-29)
- ⚠️ Dynamic regime thresholds — Stage 0 must verify no-lookahead at compute time (pass `as_of_date`)

## Risks + mitigation

| Risk | Mitigation |
|------|-----------|
| Stage 0 future-row contamination (regime classifier uses full-history percentile) | Stage 0 audit script — any rolling stat reading date > as_of_date fails the test, blocks Phase 2 entirely until fixed |
| CI_lower ≤ 0 (FAIL) | Acceptable outcome per STRATEGY §3.6 kill-switch path. Document FAIL in verdict.json, keep amplifier `enabled: false` permanently or trigger redesign. Not a bug. |
| Paired metric drift (treatment ≠ baseline entries) | Lock-test asserts `entry_dates_treatment == entry_dates_baseline`; FAIL test if they ever diverge |
| Replay performance (~14k breakout × 90d × 81 tickers, ~1.7k–2.8k eligible) | Vectorized via pandas; expected < 2 min on M5 Max for us_core 85. |
| Survivorship bias (delisted tickers excluded from us_core today) | Document explicitly in verdict.caveats — universe = "currently listed", not full historical. Affects magnitude not direction (codex framing). |
| Block bootstrap autocorrelation mis-tuning | Diagnostic + 10/40 sensitivity blocks reported as informational only. Primary verdict locked at 20d block size — no post-hoc tuning permitted. |

## Verdict artifact schema (Q12 frozen)

The `verdict.json` artifact is produced ONLY when Stage 0 is clean AND Stage 2 has run. If Stage 0 fails, a separate contamination report (path TBD by Stage 0 audit script) is produced instead — `verdict.json` is not written.

```json
{
  "spec_version": "phase2-p1-amended-2026-04-29-r2",
  "run_at_kst": "YYYY-MM-DDTHH:MM:SS+09:00",
  "git_commit": "<sha>",
  "decision": "PASS | FAIL",
  "decision_reason": "<one-sentence>",
  "stage0_audit": {"clean": true, "checks_run": [...], "violations": []},
  "universe": {"name": "us_core", "n_tickers_target": 85, "n_tickers_covered": 81, "missing": ["ARM", "NBIS", "RDDT", "TEM"]},
  "date_range": {"start": "2020-01-01", "end": "<today>"},
  "entry_rule": "close > rolling_20d_high.shift(1), strict >, no volume filter",
  "treatment_rule": "recovery_confirmed AND vix_favorable(VIX<22 AND 3d_slope<0) AND regime_favorable(regime in {bull_low_vol, recovery} AND conf>=0.60); macro_benign dropped (no 5Y data)",
  "amp_mult": 1.5,
  "sample_counts": {"n_breakout_total": N, "n_eligible": N, "n_unique_eligible_days": N, "n_excluded_vix_above_30": N},
  "bootstrap": {"iterations": 1000, "block_size_primary": 20, "seed": 42, "effective_n_caveat": "eligible entries cluster on n_unique_eligible_days; effective independent block count limited"},
  "metrics_by_horizon": {
    "30d": {"mean_paired_delta": ..., "ci_lower_95": ..., "ci_upper_95": ...},
    "60d": {...},
    "90d": {...}
  },
  "sensitivity": {"block_size_10": {...}, "block_size_40": {...}},
  "caveats": [
    "us_core embeds today's survivorship — delisted tickers absent",
    "macro_benign arm of canonical gate dropped because macro_events has no 5Y backfill — re-enters at Phase 3+ live",
    "203 eligible entries cluster on 9 unique trading days — effective independent N limited; block bootstrap CI likely wide",
    ...
  ]
}
```

## Effort estimate (post P1 amend)

- Codex Round 2 GATE: **~5 min** (focused review of P1 resolutions only)
- Build (Stage 0 audit + replay engine + tests + verdict run): **1 session**
- Buffer for FAIL → redesign discussion: **0.5 session** (only if Stage 2 doesn't PASS first try)

**Total: 1.5 sessions** (Plan consult debt closed in Round 1 + this amend).

## Build artifacts

```
scripts/
├── e3_amplifier_paired_replay.py        # main replay engine
├── e3_amplifier_stage0_audit.py         # no-lookahead verification
└── e3_amplifier_stage1_plausibility.py  # diagnostic only (Stage 1, optional)

tests/quant/exits/
├── test_amplifier_paired_replay.py      # 8–12 invariants
└── test_amplifier_stage0_audit.py       # no-lookahead lock-tests

data/reports/<YYYY-MM-DD>/                # gitignored
└── e3_phase2_verdict.json                # verdict + metrics

docs/STRATEGY.md §3.6                     # verdict outcome cited (canonical)
docs/TODO.md                              # Tier 1 entry post-merge OR Tier 2 P0 promotion to Phase 3
```

## Falsification path — Stage 2 FAIL is a deliverable, not a bug

Per STRATEGY §3.6, Stage 2 FAIL has explicit outcomes documented. **The verdict itself is binary PASS/FAIL** (Acceptance section); the menu below describes *post-FAIL redesign options*, not verdict states.

**The verdict is decided ONLY by the binary acceptance rule** (CI_lower > 0 AND Stage 0 clean). Power-limit and effect magnitude are caveats / disclosures, never independent verdict triggers (codex Round 3 verdict 2026-04-29).

FAIL routes (`decision="FAIL"` already determined by binary rule; the menu below describes *post-FAIL redesign rationale* the user chooses among after seeing the run):

1. **`CI_lower < 0`** (clearly net-negative) — strongest signal. Recommended: amplifier permanently `enabled: false`; Phase 1 shadow continues telemetry collection for future redesign signals.
2. **`CI` crosses 0** (CI_lower ≤ 0 but CI_upper > 0; same FAIL verdict, weaker signal) — redesign options menu, the user picks one:
   - (a) increase sample (extend to 10Y if data available),
   - (b) widen universe (us_core 85 → us_sp500_extended 543, accepting survivorship bias),
   - (c) refine treatment trigger (e.g. loosen `regime_favorable` threshold — codex Q9 verdict would need re-consult; macro_benign arm requires Phase 3+ live accumulation),
   - (d) accept ambiguity, freeze at Phase 1 indefinitely until macro_events accumulates 5Y.

When `CI_lower ≤ 0` is driven by low effective N (the 9-unique-day power caveat), routes (a)/(b) are typically preferred; the power-limit caveat does *not* alter the verdict itself.

Edge case (still a PASS):
- **`CI_lower > 0` but small** (e.g. < 0.5 % per 30 d) — PASS verdict with effect-size disclosure in `decision_reason`. Phase 3 proceeds with caveats. Not FAIL.

Stage 0 path (precondition, NOT a verdict):
- **Stage 0 audit FAIL** — future-row contamination detected. Stage 2 does NOT run; no `verdict.json` is produced. A contamination report is emitted instead. Fix the regime classifier (or whichever rolling-stat path leaks future rows) first, then re-run Stage 0. Phase 2 is blocked entirely until Stage 0 is clean — this is precondition enforcement, not a verdict outcome.

## Next-session pickup checklist (post Round 2 GATE)

When the next session opens this spec post-amend:

1. Read this entire file (it's ~250 lines, post-amend)
2. Run codex Round 2 GATE on P1 resolutions — request brutally honest review, accept FAIL if justified
3. Apply Round 2 verdict (any P1 not closed → re-amend before code)
4. Build Stage 0 audit script first (cheapest, blocks Phase 2 if fails)
5. Build paired replay engine (us_core 85, 2020-01-01+, eligible population, 30/60/90 trading-day horizons, 20d block bootstrap)
6. Run on full universe → produce verdict artifact at `data/reports/<date>/e3_phase2_verdict.json`
7. Document outcome in STRATEGY §3.6
8. If PASS → start Phase 3 spec next session. If FAIL → document and freeze.

---

## Anti-revenge guardrails (cross-cutting, never relax)

Per parent design doc:

- **DO NOT** use `drawdown × multiplier` arithmetic (revenge trading anti-pattern)
- **DO NOT** size up "because we're behind"
- **DO NOT** skip Stage 0 audit — no-lookahead bugs make any Stage 2 verdict invalid
- **DO** log FAIL outcome as honestly as PASS — it's a deliverable, not a failure
