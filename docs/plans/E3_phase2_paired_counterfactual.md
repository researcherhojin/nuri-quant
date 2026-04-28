# E3 Phase 2 — Paired Counterfactual (Plan-phase spec)

**Status**: Plan-phase artifact. Build pending after codex consult Q1–Q12 (below).

**Owner / next session**: pick this up at the top — start with codex Plan consult, then Stage 0 audit (cheapest, blocks Phase 2 if fails), then build replay engine.

**Sources**:
- `docs/plans/E3_symmetric_amplifier_design.md` (8-week phased rollout, parent spec)
- `docs/STRATEGY.md §3.6` (E3 acceptance — Stage 0 + Stage 1 + Stage 2 protocol)
- PR #479 (Phase 1 shadow skeleton shipped 2026-04-29)

---

## Why now

Phase 1 (#479) shipped shadow skeleton with `amplifier_gate.evaluate()` and `recovery_detector.evaluate_recovery()` — but `enabled: false` everywhere. Phase 2 = STRATEGY §3.6 Stage 2 main gate; paired counterfactual must PASS for the amplifier to ever activate. Without a Phase 2 verdict, Phase 3 (alpha-amplified live) and Phase 4 (portfolio-amplified live) are gated indefinitely. Falsification path is part of the deliverable, not a failure mode to avoid.

## Acceptance — binary, falsifiable

```
PASS  iff  paired_excess_CI_lower > 0  AND  Stage 0 no-lookahead audit clean
FAIL  iff  CI_lower ≤ 0  OR  Stage 0 detects future-row contamination
```

- **Primary metric**: mean paired excess return at 30 / 60 / 90 trading days (treatment − baseline, same entries)
- **CI**: 1000-iter block bootstrap (block size = 20 trading days) on paired delta, 95 % interval
- **Sample**: N ≥ 200 amplifier-treated entries (Codex pre-verified 4,385 available from 20d breakout × 5Y price universe)
- **Stage 0 (no-lookahead)**: rolling-stat compute paths (`compute_dynamic_thresholds`, special-regime detectors, `classify_regime_history`) must NOT touch dates > entry_date
- **Stage 1 (plausibility, diagnostic only)**: directional sanity check; FAIL does not block ship if Stage 2 PASS

## Scope

### IN

- `scripts/e3_amplifier_paired_replay.py` — replay engine (5Y prices, 20d breakout entries, paired baseline vs treatment, forward returns, bootstrap CI)
- `scripts/e3_amplifier_stage0_audit.py` — no-lookahead verification
- `tests/quant/exits/test_amplifier_paired_replay.py` — fixture-driven invariants (same entries / exits between arms, paired delta deterministic given seed, CI math sanity)
- `tests/quant/exits/test_amplifier_stage0_audit.py` — no-lookahead lock-tests
- Verdict artifact `data/reports/e3_phase2_verdict_<YYYY-MM-DD>.json` with metrics + CI bounds + decision (PASS / FAIL)
- `docs/STRATEGY.md §3.6` updated with verdict outcome
- `docs/TODO.md` Tier 2 P0 row updated (or row dropped if PASS → Phase 3 next-up)

### OUT (deferred — explicit non-goals)

- Phase 3 wiring (`consensus.py` integration emit_event) — separate PR after PASS verdict
- Q3 Kelly quarter cap derivation — Phase 4 concern
- Walk-forward IS / OOS Sharpe + DD — secondary metric per §3.6, deferred
- Monte Carlo regime mis-classification 5 % — secondary, deferred
- Live shadow telemetry emit (still Phase 1.5, separate PR)
- Recovery from Phase 2 FAIL into a redesigned amplifier — own multi-week effort

## Approach

```
1. Universe + price load
   - Source: prices table (already populated via collectors)
   - Tickers: us_core 85 + us_sp500_extended 458 = 543 unique
   - Validate: ≥ 1250 trading days per ticker (5Y × 252)

2. Entry signal: 20d breakout
   - close > rolling_20d_high.shift(1)  (strict >, prior-day high)
   - Cooldown: skip if entry_date − last_entry_date < 5 trading days (avoid clustered re-triggers)
   - Result: 32,031 entries / 4,385 amplifier-treated (Codex pre-verified)

3. Treatment trigger: amplifier conditions fire on entry_date
   - recovery_confirmed (recovery_detector.evaluate_recovery → recovery_confirmed=True), mandatory
   - vix_favorable (VIX < 25), mandatory
   - 2-of-3 of (regime_favorable / entry_strength / macro_benign) — the Q2 4-of-5 gate
   - VIX > 30 → skip (hard veto, not counted as treated)

4. Position sizing (frozen for Phase 2)
   - baseline: base_size = 1.0 (unit)
   - treatment: base_size × amp_mult; amp_mult = 1.5 (Phase 4 will derive from quarter-Kelly)

5. Forward returns: trading-day close-to-close at entry + {30, 60, 90}
   - Use adjusted close (split / dividend safe)
   - Per-entry P&L: ret × size
   - Treatment effect per entry: ret × (amp_mult − 1)
   - Aggregate metric: mean of (treatment_pnl − baseline_pnl) across entries

6. Bootstrap CI: 1000 iterations, block size = 20 trading days
   - Resample paired deltas with replacement in blocks (autocorrelation buffer)
   - Compute mean per iteration → 95 % percentile interval
   - PASS gate: CI_lower > 0
```

## Dependencies

- ✅ Phase 1 modules (`amplifier_gate.evaluate`, `recovery_detector.evaluate_recovery`)
- ✅ Prices table 5Y (universe-sync ensures 543 tickers × 252 × 5)
- ✅ VIX history (macro indicator='vix')
- ⚠️ Dynamic regime thresholds — Stage 0 must verify no-lookahead at compute time (pass `as_of_date`)

## Risks + mitigation

| Risk | Mitigation |
|------|-----------|
| Stage 0 future-row contamination (regime classifier uses full-history percentile) | Stage 0 audit script — any rolling stat reading date > as_of_date fails the test, blocks Phase 2 entirely until fixed |
| CI_lower ≤ 0 (FAIL) | Acceptable outcome per STRATEGY §3.6 kill-switch path. Document FAIL in verdict.json, keep amplifier `enabled: false` permanently or trigger redesign. Not a bug. |
| Paired metric drift (treatment ≠ baseline entries) | Lock-test asserts `entry_dates_treatment == entry_dates_baseline`; FAIL test if they ever diverge |
| Replay performance (32k entries × 90d × 543 tickers) | Vectorized via pandas; expected < 5 min on M5 Max. If slow, reduce to us_core 85 (sample reduction OK if N ≥ 200 still holds) |
| Survivorship bias (delisted tickers excluded) | Document explicitly in verdict — universe is "currently listed", not full historical. Acceptable proxy per Codex Q4 acceptance |
| Block bootstrap autocorrelation mis-tuning | Run autocorrelation diagnostic on paired deltas; if effective autocorr length > 20d, increase block size and re-run |

## Codex Plan consult — 12 questions before code

| # | Topic |
|---|-------|
| Q1 | Entry signal exact spec — `close > rolling_20d_high.shift(1)` strict `>`? Volume filter (≥ 1.5× 20d avg)? |
| Q2 | Re-entry cooldown — 5 trading days OK, or next-bar immediate re-entry permitted? |
| Q3 | Exit logic — fixed 90d window, OR trailing stop / next opposite signal? Phase 2 needs SAME exit between arms. |
| Q4 | `amp_mult = 1.5` reasonable, OR pre-apply Q3 quarter-Kelly (= 0.25 × win_rate × payoff_ratio)? |
| Q5 | Forward return = close-to-close 30/60/90 calendar OR trading days? Adjusted vs raw? |
| Q6 | Block bootstrap block size — is 20d sufficient, or run autocorrelation diagnostic first to set it? |
| Q7 | Universe scope — us_core 85 (deeper history) OR full 543? Sample size already covers either — pick one. |
| Q8 | Date start — 2020-01-01 OK, or skip COVID volatility window (2020-03 to 2020-06)? |
| Q9 | Treatment trigger — Q2 multi-condition gate definition (recovery + vix + 2-of-3 of regime / entry_strength / macro_benign)? `entry_strength` precise definition (RSI threshold? momentum %?)? |
| Q10 | `macro_benign` — \|event_score\| < threshold, OR specific macro_event categories absent? |
| Q11 | Hard veto integration — VIX > 30 entries: skip from sample entirely, OR include but force treatment to baseline? |
| Q12 | Verdict artifact schema — JSON keys, retention policy (commit OR `data/` gitignored), filename convention `e3_phase2_verdict_<date>.json`? |

## Effort estimate

- Codex Plan consult (Q1–Q12 + Round 1 + Round 2 GATE): **0.5 session**
- Build (replay script + Stage 0 audit + tests + verdict run): **1 session**
- Buffer for FAIL → redesign discussion: **0.5 session** (only if Stage 2 doesn't PASS first try)

**Total: 1.5–2 sessions** (single working day on M5 Max with codex Plan + Build).

## Build artifacts

```
scripts/
├── e3_amplifier_paired_replay.py        # main replay engine
├── e3_amplifier_stage0_audit.py         # no-lookahead verification
└── e3_amplifier_stage1_plausibility.py  # diagnostic only (Stage 1)

tests/quant/exits/
├── test_amplifier_paired_replay.py      # 8–12 invariants
└── test_amplifier_stage0_audit.py       # no-lookahead lock-tests

data/reports/
└── e3_phase2_verdict_<YYYY-MM-DD>.json  # verdict + metrics

docs/STRATEGY.md §3.6                    # verdict outcome cited
docs/TODO.md                             # Tier 1 entry post-merge OR Tier 2 P0 promotion to Phase 3
```

## Falsification path — Stage 2 FAIL is a deliverable, not a bug

Per STRATEGY §3.6, Stage 2 FAIL has explicit outcomes documented:

1. **`CI_lower < 0`** — amplifier net-negative. Permanently `enabled: false`. Phase 1 shadow continues collecting telemetry for future redesign signals. Document FAIL in verdict.json; update STRATEGY §3.6 with FAIL verdict + reasoning.
2. **`CI` crosses 0** — inconclusive evidence. Three options:
   - (a) increase sample (extend to 10Y if available),
   - (b) refine treatment trigger (loosen Q2 multi-condition gate from 4/5 → 3/5),
   - (c) accept ambiguity, freeze at Phase 1 indefinitely.
3. **`CI_lower > 0` but small** (< 0.5 % per 30 d) — PASS technically but low magnitude. Document with effect-size disclosure. Phase 3 with caveats.
4. **Stage 0 audit FAIL** — future-row contamination. Fix regime classifier first, then re-run Phase 2.

## Next-session pickup checklist

When the next session opens this spec:

1. Read this entire file (it's ~250 lines)
2. Run codex Plan consult on Q1–Q12 — request brutally honest review, accept FAIL if justified
3. Apply codex Round 1 + Round 2 verdicts
4. Build Stage 0 audit script first (cheapest, blocks Phase 2 if fails)
5. Build paired replay engine
6. Run on full universe → produce verdict artifact
7. Document outcome in STRATEGY §3.6
8. If PASS → start Phase 3 spec next session. If FAIL → document and freeze.

---

## Anti-revenge guardrails (cross-cutting, never relax)

Per parent design doc:

- **DO NOT** use `drawdown × multiplier` arithmetic (revenge trading anti-pattern)
- **DO NOT** size up "because we're behind"
- **DO NOT** skip Stage 0 audit — no-lookahead bugs make any Stage 2 verdict invalid
- **DO** log FAIL outcome as honestly as PASS — it's a deliverable, not a failure
