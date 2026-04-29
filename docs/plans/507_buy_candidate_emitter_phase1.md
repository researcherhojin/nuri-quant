# #507 BUY Candidate Emitter — Phase 1 Spec

**Status**: Draft (2026-04-30 KST)
**Issue**: [#507](https://github.com/researcherhojin/nuri-quant/issues/507)
**Predecessor**: PR #497 (`holdings_monitor` — sell side analog)
**Phase**: 1 of 3 (Phase 2/3 deferred to follow-up issues)
**LLM consult**: `data/llm_consults/2026-04-30_507-buy-candidate-emitter-architecture.md` (gitignored)

---

## 1. Why this spec exists (UX Process Enforcement)

Per memory `feedback_ux_process.md`: PM → wireframe → user approve → implement. Skipping wireframe = scope creep + emotional rebuilds (#137 case 2026-04-29). #507 is high-stakes (system core-purpose). Spec **before** code.

## 2. Problem reframed

| Current state | Required state |
|---|---|
| Sell-only loops: SIEGE / take-profit / stop-loss / position-limit / VIX / holdings_monitor | Same + **active BUY candidate emitter** |
| Cash deploy decisions = user discretion (= "홀짝 게임") | Cash deploy decisions = system-emitted candidate ranked + entry/stop/TP |
| `Opportunities` block is raw top-5 momentum screen — not a deploy decision | `BUY Candidates` block with allocation + why-now |
| 0 candidates ever emitted from system in April | 0-5 candidates per session, opinionated quality bar |

## 3. Wireframe (target brief output)

```markdown
# Pre-market Brief — 2026-05-01

Generated: 2026-05-01T07:00:00+09:00

## Regime: sideways_high_vol
- ...

## Indicators
- VIX 17.89 · F&G 64 · USD/KRW 1477

## SIEGE: REJECTED 59.1%
- ❌ position_limit: SOXL 32.2% (swing 의도 — 사용자 confirmed)

## SHADOW crash precursor (0/2 fired)
- ...

## ★ BUY Candidates (3 emitted — recommended deploy 28% of cash, est ₩X.XM)
**Regime gate: PASS** (VIX 17.89 < 25, sideways_high_vol allows selective entry)
**SIEGE per-account: kakaopay REJECT (concentration), kakaopay_sub PASS, toss PASS, pension PASS**

1. **MSFT** — score 82/100, deploy 12% (~₩4.5M)
   - **Why now**: AI capex confirmed via STX/MU/WDC sector rally (+11~18% AH 4-28). Azure 38% CC growth thesis intact. Strong Buy 33B/2H/0S, avg PT $565 (+33%).
   - **Entry**: $425.07 → trigger if breaks $432.50 (5d high) on RVOL > 1.5×
   - **Stop**: $395.31 (-7%, O'Neil) | **TP1**: $514.33 (+21%, sell 50%) | **TP2**: $603.60 (+42%, sell 25%)
   - **Sources**: factor=78 · agent_consensus=85 · momentum=72 · macro_tailwind=80 · superinvestor=88
   - **Account**: kakaopay_sub or toss (not kakaopay due to SIEGE REJECT)

2. **META** — score 76/100, deploy 10% (~₩3.8M)
   - **Why now**: ...
   - ...

3. **NVDA add (ride winner)** — score 71/100, deploy 6% (~₩2.3M)
   - **Why now**: 보유 NVDA +59% momentum, sector tailwind from STX/MU rally. SEPA "ride winners" — extend cap from 15% to 20% per `account_strategies.active.trailing_stop_arm`.
   - **Allocation note**: User's NVDA is currently 11.9% portfolio-wide → +6% deploy = 17.9% within active strategy cap.
   - ...

### Skipped (below quality bar — explicit reasons)
- **QCOM**: IV 9.1% (highest), OpenAI partnership unconfirmed → headline risk > signal quality
- **AMD**: 5d cooldown (just realized loss-pattern — wait for momentum re-confirmation)
- **GOOGL**: 5d cooldown (recently trimmed at +26%, cannot re-recommend within cooldown)
- **AMZN**: held but only 2주 ($527) — micro position, no deploy logic

### If 0 candidates emit
> **BUY: no qualifying candidate today.** Reason: sideways_high_vol regime, top scorer 64/100 below threshold 70. Cash hold appropriate.

## Portfolio (...)
## Hold (...)
## Opportunities (raw screen, top-5 — secondary signal)
## Macro Events
```

## 4. Source fusion algorithm

**Decision (pending LLM consult)**: Multiplicative gate cascade with linear weighted core (option a + b hybrid).

### 4.1 Core score (linear weighted, 0-100 scale per component)

```python
core_score = (
    0.25 * factor_percentile     # multi-factor composite (value+quality+momentum+lowvol)
  + 0.25 * agent_confidence       # 10-agent BUY consensus (avg confidence among BUY votes)
  + 0.20 * momentum_signal        # signals.yaml momentum/breakout/divergence (binary fired → 100, else 0; clipped)
  + 0.15 * macro_tailwind         # macro_events sentiment + regime alignment
  + 0.15 * superinvestor_score    # 13F count weighted by quality
)
```

Weights in `config/buy_signals.yaml` (new file, tunable without code change).

### 4.2 Gates (multiplicative, cascade)

```python
final_score = core_score
final_score *= regime_gate(regime)         # 1.0 if pass, 0.0 if VIX > 30 or extreme_fear
final_score *= cooldown_gate(ticker, 5d)   # 0.0 if recently trimmed, else 1.0
final_score *= held_gate(ticker, account)  # 0.0 if at position cap, else 1.0
final_score *= buy_checklist_gate(ticker)  # 1.0 if passes (TipRanks ≥ Moderate Buy + superinvestors ≥ 3 + PE < 100 + revenue > 0 + factor top 50%), else 0.0
```

If any gate = 0.0 → ticker excluded with explicit reason in Skipped block.

### 4.3 Quality bar (when to emit)

- `final_score >= 70` for inclusion
- Per-regime adjustment: `sideways_high_vol` adds +5 to threshold (= 75); `momentum_uptrend` subtracts 5 (= 65)
- Max 5 candidates emitted (top-5 by score)
- Min 0 (better silent than noise)

## 5. Allocation sizing (Phase 1: simple)

```python
total_cash_deploy_pct = regime_total_pct(regime)
# sideways_high_vol = 30%, neutral = 40%, momentum_uptrend = 60%, extreme_fear = 0%

per_candidate_pct = total_cash_deploy_pct * (score / sum_of_emitted_scores)
# score-weighted, normalized
```

Phase 1: single global cash pool calculation (sum across all account `cash_krw + cash_usd`). Phase 2 will add per-account gating.

## 6. "Why now" sentence generation (Phase 1: template)

Phase 1 = template (no LLM call). Pick highest-contributing source, use its template:

| Top source | Template |
|---|---|
| momentum | "5d +N%, breakout above $X, RVOL N×" |
| factor | "Multi-factor top N%, PE Y, revenue growth +Z%" |
| agent_consensus | "10-agent BUY (N of 10), avg confidence X" |
| macro_tailwind | "<event_name> 호재 + regime <regime> 일치" |
| superinvestor | "N superinvestors holding (Cathie Wood added $Xm 4-28)" |

Phase 3 (deferred) = LLM-generated for human-readable polish.

## 7. Cooldown rules

5 trading days hard suppression after:
- take_profit trim (any TP1/TP2 trigger)
- holdings_monitor SELL alert
- stop-loss execution

Stored in `pipeline_events` as `buy_signal_cooldown_set` event with `until_date` field. Read on every brief generation.

## 8. File touches (Phase 1)

```
NEW:
  config/buy_signals.yaml                              # weights + thresholds
  nuri/trading/recommend/buy_candidate_emitter.py      # core logic ~250 LOC
  tests/trading/recommend/test_buy_candidate_emitter.py # ~15 lock tests
  docs/plans/507_buy_candidate_emitter_phase1.md       # this file

EDIT:
  nuri/alerts/premarket_brief.py                       # +50 LOC for new block
  nuri/core/signal_config.py                           # buy_signals.yaml loader (DRY pattern)
  config/CLAUDE.md                                     # +1 row for buy_signals.yaml
  docs/STRATEGY.md §2.6                                # buy-side rung in Escalation Ladder
  docs/TODO.md                                         # mark P0 in_progress
  Makefile                                             # add `make buy-candidates` standalone CLI
```

LOC estimate: ~400 net add (core) + ~250 test = ~650.

## 9. Commit plan (≤ 3 commits per PR Discipline)

1. **`feat(signals): add buy_candidate_emitter — core fusion + gates`**
   - `nuri/trading/recommend/buy_candidate_emitter.py` (core)
   - `config/buy_signals.yaml` (weights config)
   - `nuri/core/signal_config.py` (loader)
   - 8 unit tests (algorithm correctness)

2. **`feat(alerts): premarket_brief surfaces BUY Candidates block`**
   - `nuri/alerts/premarket_brief.py` edit
   - `Makefile` `buy-candidates` target
   - 5 integration tests (brief output shape, 0-candidate path, regime gate)
   - 2 lock tests (cooldown, held_gate)

3. **`docs(strategy): document buy-side Escalation Ladder rung + #507 close`**
   - `docs/STRATEGY.md §2.6` add buy-side surface rung
   - `docs/TODO.md` close #507 P0
   - `config/CLAUDE.md` register buy_signals.yaml
   - Update `docs/plans/507_buy_candidate_emitter_phase1.md` to "Shipped" status

## 10. Acceptance criteria (Phase 1 only)

- [ ] `make report` includes `## BUY Candidates` block
- [ ] Block emits 0-5 candidates with explicit reason if 0
- [ ] Each candidate has: ticker / score / deploy % / entry / stop / TP1 / TP2 / why-now / sources
- [ ] Held tickers at cap excluded
- [ ] Recently-trimmed (5d) tickers in Skipped block with reason
- [ ] VIX > 30 → 0 candidates with "blocked: VIX X.X" reason
- [ ] SIEGE per-account REJECT respected (other accounts can still deploy)
- [ ] Per-regime quality threshold variation working (sideways_high_vol stricter)
- [ ] 15+ lock tests pass; 0 hooks/lint violations
- [ ] No regression: existing brief blocks (Portfolio/Check/Hold/Opportunities) unchanged

## 11. Phase 2 / 3 deferred (do NOT do in Phase 1)

| Phase | Scope | Trigger |
|-------|-------|---------|
| **Phase 2** | Per-account cash gating, USD↔KRW FX, kakaopay vs sub vs toss vs pension differentiation | After Phase 1 user feedback (1-2 weeks live use) |
| **Phase 3** | LLM-generated "why now" + audit trail in `data/llm_consults/`, backtest validation, score calibration via `recommendations.outcome_30d` | After Phase 2 + sufficient `recommendations` outcome data |

## 12. Risks / mitigations

| Risk | Mitigation |
|------|------------|
| **System emits BUY candidate, user buys, stock drops** → user blames system again | Phase 1 silent-default ("better 0 than noise"). Quality bar 70/100 strict. Stop-loss -7% mandatory in every emit. User sees explicit "why now" — informed decision. |
| **Score calibration wrong** (false positive rate too high) | Phase 1 weights in YAML for fast tuning. Phase 3 backtest will calibrate against `outcome_30d`. |
| **Cooldown logic too aggressive** → never re-recommends quality stock | 5d hard cooldown is short. Phase 2 may add price-based reset (drop > 7% from trim → re-eligible). |
| **Component score scale mismatch** (factor percentile vs agent confidence vs binary signal) | Algorithm normalizes all to 0-100 before weighted sum. Tests assert score bounds. |
| **STRATEGY §7.1 violation accusation** | Phase 1 emits **recommendations + REVIEW CTA**, never executes orders. Same pattern as `holdings_monitor` (PR #497). |

## 13. References

- Issue: <https://github.com/researcherhojin/nuri-quant/issues/507>
- Sell-side analog (PR #497): `nuri/trading/recommend/holdings_monitor.py`
- Memory: `feedback_alpha_portfolio_conflation.md` (PR A #429), `feedback_proactive_judgment.md`, `feedback_ux_process.md`
- STRATEGY §2.6 Escalation Ladder, §3.4-3.5 strategy decisions, §7.1 auto-trade deferral
- HARNESS.md §2 (lessons from past sell-side cascade)
