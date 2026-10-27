# Nuri-Quant Strategy Definition

*Korean edition: [ko/STRATEGY.md](ko/STRATEGY.md)*

> Reading rule (2026-10-23): policy, implemented behavior and dated experiment records are distinct. Historical results and external research/model-price claims are not newly validated by a documentation update. Current runtime wiring is described in ARCHITECTURE; §3.11/§3.12 pre-registered criteria remain unchanged.

*§3.11 and §3.12 hold pre-registered criteria written in Korean. If the two editions ever differ there, the Korean text is the record.*

This document defines why the project exists, the rationale behind its core design decisions, and its development quality standards. Before building a new feature or changing an existing structure, first check that the change conforms to the principles in this document.

<!--
Maintainer note: this file is not imported from `CLAUDE.md`; it is only pointed to as "load on demand" (on-demand load). Following the official Claude Code guidance ("target under 200 lines per CLAUDE.md", "imports do not reduce context"), the body holds only canonical policy + the "why" of each decision. Detailed methodology / narrative / case studies are delegated to separate files (data/llm_consults/, scripts/*.py docstrings, git log). Additional narrative that breaks this principle is wrapped in a stripped HTML comment or extracted into an external file, which keeps its context cost at 0.
-->

---

## 1. Why This Project Was Built

**Problem**: in personal investing, relying on emotion and intuition leads to the disposition effect (Shefrin 1985) — selling winners too early and holding losers too long.

**Hypothesis**: a system that proves with data "why to buy / why to sell" removes emotional interference and makes consistent decision-making possible.

**Core differentiator**: the goal is not to issue recommendations but to prove the evidence behind them.

- Win rate / profit factor (PF) validated by the signal backtest (19 actionable signals; historical trade counts depend on the input window)
- Independent analysis by 10 agents, then weighted consensus (risk agent veto)
- Mechanical verification of prudential constraints (weight, sector and leverage limits) — `rebalance_advisor` surfaces violations as REBALANCE (the portfolio-wide CERTIFIED/REJECTED verdict was retired in 2026-10 per §6)
- 5 Plotly charts visualize the final evidence

## 2. Design Principles

### 2.1 Evidence-first — 3-tier bucket split

Every BUY/SELL judgment is **classified by evidence quality**. When a number is missing, no "average" is assumed (an assumed fallback caused past user losses — 2026-04-17 codex audit).

**Tier definitions** (`nuri/trading/recommend/candidates.py` `TIER_*` constants)

| Tier | Condition | System behavior |
|---|---|---|
| **actionable** | validated (≥ 30 trades) + positive edge (PF ≥ 1.0) | Formal recommendation. Full confidence formula applied. Main UI list. |
| **advisory** | unscored (not covered by backtest) OR low-sample (< 30 trades) | confidence = 0. Disclosed only in a separate section. "For reference only" wording. |
| **avoid** | validated but negative edge (PF < 1.0) | confidence = 0. Shown with a "no independent action" warning. |

**Rule**: signal → scorecard statistics lookup → tier classification. A signal with no statistics or a negative edge is not mixed into the recommendation list (it is shown in the advisory/avoid sections). Price targets are mechanical regardless of tier (§2.2). "It looks good" is not a reason — no statistics means advisory.
Past failure modes (archived 2026-04-17):

- The win_rate=0.5, pf=1.0 fallback at `candidates.py:203` emitted at confidence ~45 (removed in B-2)
- A bug that measured SELL signals in the reverse direction made all of them PF>1 (the B-1 sign-flip fix revealed 0.52–0.60; B-2-ext classifies them as avoid automatically)
- Learning Memory warming up: recommendations.agent_verdicts has accumulated 144 rows; the weights read recommendations.outcome_30d, so the first weight drift is expected ~2026-05-17 (TODO.md Tier 1 row 20). Until then, DEFAULT_WEIGHTS is static.

### 2.2 Mechanical execution

Rules are defined in `config/rules.yaml`; code only executes them.

- Stop-loss -7% (growth) / -10% (value), take-profit +20%/+40%, trailing -15% — no exceptions
- VIX > 30 blocks new buys — "this time is different" is not accepted
- `rebalance_advisor` surfaces limit violations mechanically, with no manual override (the old SIEGE gate's REJECTED verdict was retired per §6)
- **execution_priority** (PR #200, ⚠️ not wired — no module reads this order, §3.4): stop-loss → take-profit → set trailing stops → new buys. Stopping the bleeding comes before locking in gains. Within stop-losses, the largest loss rate goes first; within take-profits, the largest overshoot of the target goes first.
- A rule change is a YAML edit + backtest validation. No exception branches in code.

### 2.3 Loose coupling via data

The 5 pipeline stages communicate through DB/CSV **as far as possible**. The principle stands, but what is written here is measured fact (#920/#922 — the earlier wording "the 8 phases do not import each other" was false, and without a stage→directory mapping it could not even be verified).

- **Why**: when an upstream stage re-runs, downstream stages use the new data automatically. Direct imports complicate the management of execution order and state.
- **Stage mapping** (the precondition for verifiability): `collect`=`nuri/collectors` · `analyze`=`nuri/analysis` · `consensus`=`nuri/trading/agents` · `decide`=`nuri/trading/engine` (`certify` until 2026-10) · `track`=`nuri/trading/recommend`. `nuri/quant` and `nuri/core` are shared libraries, not stages.
- **Principle**: a new module does not call another stage's functions directly. It passes data through DB tables/CSV.
- **What is actually enforced**: a cross-stage import is allowed **only inside a function body (deferred)** — never at module level — and must be listed in the allowlist with a reason. Measured: **13 imports / 12 pairs / 0 at module level** (2026-10-07 — 3 pairs fewer after the SIEGE removal in #1624). The mutual dependency `engine/conflicts.py` ↔ `recommend/candidates.py` loads only because of the deferral; hoisting even one of them breaks import.
- **2 exceptions**: imports within the same stage are allowed. For the consensus→decide hand-off, `scheduler.py` passes objects **in memory** (not through the DB). The receiver is `record_decisions()` in `nuri/trading/engine/decisions.py` (the SIEGE certifier was removed in #1619).
- **Test**: `tests/core/test_cross_stage_imports.py` — FAILs in **both directions**: on a new cross-stage dependency and on an allowlist entry that has disappeared.

### 2.4 Observability

Every state change must be traceable.

- `pipeline_events` table: append-only event journal. Event chains are traced through `causation_id`.
- Freshness SLA: warn/fail thresholds per data source. Anything other than PASS raises a dashboard warning.
- Decision records: each consensus decision records its market context and evidence in `decisions` / `decision_evidence` (the old SIEGE certification records were retired per §6 — the `certifications` table remains only as a historical record).
- **Bar for new features**: first answer "if this feature fails, how will we know?"

### 2.5 Cost minimization + data sovereignty (Lean-cost stack)

Minimize dependence on paid APIs / cloud / commercial software. This is not a 100%-free dogma — adoption is allowed when the quality gain is quantified, the annual cost is negligible, and the §4.4.3 sovereignty rule can be kept.

| Choice | Why |
|------|------|
| SQLite (not Postgres) | No separate server needed. Concurrent reads in WAL mode. Test isolation through `tmp_path`. |
| **Hybrid LLM stack** | Public RSS classification → OpenAI `gpt-6-luna` (Tier 0). Portfolio reports (Tier 2) are **local only**; external user narrative (Tier 1) is not allowed. Interactive/report inference runs on request; the scheduled thesis pilot (#1964) is separate local research. Strata question-and-answer and the Ollama multi-stage path are distinct. Neither supplies local-LLM input to trading consensus, and operating a pilot does not establish investment contribution. Sovereignty (§4.4) is unchanged. Details in §4.4.3. |
| yfinance | Free data. openbb was removed in #1477 — a lower-bound override erased the exact pin, leaving it dead with no signal for 7 days, and yfinance alone has no gaps. |
| GitHub Actions | Free for open source. Automates lint + test + coverage + security. |

### 2.6 Escalation Ladder (evidence-based → mechanical intervention in 4 rungs)

§2.1 (Evidence-first) and §2.2 (Mechanical) are the two ends of one spectrum. For any evidence, a 4-rung ladder decides how far to intervene mechanically. **3 rungs are downside-block, 1 rung is upside-amplify**. When designing a new feature, choose the level explicitly and record it in the PR/STRATEGY.

| Rung | Direction | Action | When | Example |
|------|------|------|------|------|
| **Surface** | — | Exposes evidence only (UI/reasoning/log). action and confidence unchanged. | Noisy, sparse, insufficient outcome validation. Leaves room for judgment. | PR #301 `divergence_flag`, PR #302 UI badge |
| **Soft penalty** | down | Deterministic downgrade/reweight (switch to HOLD, confidence cap). Not a block. Config-tunable. | The same opposing signal repeats + clear downside skew, but not universally fatal. | PR #303 `divergence_technical_threshold` (default 80) |
| **Hard veto** | down | Forces a change of action or blocks it. Config made hard to touch. | Policy level, risk-of-ruin grade. | Risk agent veto, VIX>30 block |
| **Symmetric amplifier** | up | Post-veto sizing — only for eligible candidates that passed veto/penalty, raises size/confidence when multiple favorable conditions hold at the same time. Cap enforced (baseline × 1.5). | regime + momentum + VIX all favorable. Never fires on a single condition. | On hold with E3 Phase 3 (§3.6; `symmetric_amplifier.enabled: false`) |

**Operating principles**:

1. Moving from Surface → Soft penalty is **data-driven** (firing frequency + hit rate measured first; audit of `consensus_penalty_applied` in `pipeline_events`).
2. Moving from Soft penalty → Hard veto is **policy/theory-driven** (STRATEGY amendment PR + backtest).
3. Moving up a rung is easy; moving down is hard (going from mechanical → informational makes past cases ambiguous to interpret).
4. **Amplifier evaluation order**: always after veto/penalty. A candidate blocked by a Hard veto is not eligible for the amplifier — a path in which reward amplification bypasses loss avoidance is structurally impossible. Before it fires, it is measured at the Surface rung (§3.6 minimum sample/positive-outcome).
5. **Promotion gate — champion-challenger sequential control (#1307, 2026-08-29)**: the promotion-eligibility verdict for an investment-rule variant (challenger) goes through `nuri/quant/validation/champion_gate.py`. Multiple comparisons within one campaign are controlled by the existing walk-forward gate (Bonferroni + frozen holdout, #706); **sequential search across repeated campaigns** is controlled by this gate — (a) every attempt, rejections included, is recorded in the `challenger_attempts` ledger (with #1305 evidence binding, append-only), (b) the alpha allocated to campaign j = `alpha_total / 2^j` halving spending (the family's lifetime budget stays fixed even under unlimited repetition), (c) a holdout generation is retired after it has been opened `holdout_max_uses` times — a reused sealed window is no longer sealed, so after that no promotion can be proposed until a new `holdout_version` pre-registration PR. Parameters are in `config/walkforward.yaml champion_gate:` (a change = a STRATEGY PR). **The machine automates only rejection** — `promotion_candidate` is a proposal, and promotion is always a human STRATEGY PR (the same axis as operating principle 2). Separate evidence axes: this gate is for research (walk-forward) only — it is not mixed with the §3.11 live decision-ledger verdict within one verdict (this stops a promotion narrative from picking whichever axis favors it).

**Anti-pattern**: overusing Surface → "performative warnings" (the JKHY ⚠ badge changed no behavior). Overusing Hard veto → lost opportunities + the right to judge taken away. Firing the Amplifier on a single condition as a symmetric mirror of Soft penalty → noise pumping. **Change procedure**: rung moves go through a config/docs PR. No magic numbers in code.

**When a gate input is missing (adopted 2026-08-10)** — the ladder specified only what to do when a signal *is present*, and was silent when the input is **absent**. `buy_candidate_emitter._get_regime` was filling that gap with `vix = 20.0`. 20.0 sits **below** the block (>30) and caution (≥25) thresholds, so "unmeasurable" quietly earned a pass, and the briefing printed `VIX=20.0` as if it were a measured value. #753 is a record of the same family (reading the uncollected `prices.VIX` and always falling back) having already disabled the gate once.

Principle: **a missing input to a risk gate is treated at the same grade as that gate's most conservative observation.** An unknown or stale VIX (`entry_rules.vix_gate.max_age_business_days`, default 2 **business** days — counting calendar days would turn normal data after a market holiday into "unknown") is a **Soft penalty** (half position), the same as the caution band. It was not raised to Hard veto because the cost of losing a whole bull-market entry opportunity to a one-day collection outage has not been measured; it was not lowered to Surface because committing the full amount without evidence is exactly the shape §2.6 exists to prevent. It is displayed as `미상` ("unknown"), not as a number — a measurement that does not exist is not written down as if it did.

**Score components follow a different rule (2026-08-10)** — the clause above is about *gates* (pass/block). When a **score component** is missing, like the sentiment in `factors/composite`, "the most conservative observation" is undefined. In that case, do not invent a value: **drop the component and renormalize the remaining weights proportionally** (the sum stays 1.0). Previously, `0.5` was filled in when Fear & Greed was missing; 0.5 is neutral and looks harmless, but against the measured 0.637 it is 2.74 points on the 0-100 scale, and in front of `quality_bar.base_threshold: 70` it moved the **number** of passes. Renormalization keeps "we don't know" from pushing the score either up or down. The ranking is unchanged anyway — it is a market-wide value, so the same amount goes into every ticker.

**2nd application: `regime/macro_score` (2026-08-11, #1026)** — the same clause was applied to the 9-component macro score. Filling missing components with `50.0` and taking the weighted sum was replaced with **dropping the component + proportional renormalization**, and `coverage` (the sum of the measured weights) is emitted alongside. The measured impact is large: with `FRED_API_KEY` unset, **all 8 FRED-only indicators have 0 rows**, so 3 components (3M-10Y · unemployment · CPI) are missing, and the total score goes from **64.4 "Neutral" → 71.3 "Favorable"**, **crossing an interpretation boundary**. The invented neutral had been suppressing a favorable reading. The code already detected the missing values and put them in `warnings`, but **0 consumers read them** — a detection that reaches nothing is the same as no detection. So that a thin sample does not carry a confident label, coverage below `macro.min_coverage` (default 0.6) yields `interpretation="Insufficient"`.

**The same principle was applied to the SIEGE gates (2026-08-10, #1022 — SIEGE certification was removed in #1619; this remains only as an application of the principle)** — §6 gate 7, `volatility_gate`, emitted `passed=True, "데이터 없음 — 스킵"` ("no data — skip") when its indicators were missing. This gate's most conservative observation is **its own failure state** (warning), so a missing input is emitted as `passed=False, severity=warning`. The scope is the gate's **verdict input** (primary) — auxiliary spillover indicators (secondary) create no condition at all when their value is missing, so they neither claim "normal" nor inflate the score, and they are left as they are. Raising a warning for every missing reference indicator falls on the side of the performative warnings §2.6 guards against. A secondary that is permanently uncollected is caught by a contract test at PR time, not at runtime. `data_fresh`, 30 lines above, behaved this way from the start — two gates in the same file were answering the same situation in opposite ways. Because it is a warning, it does not block `certified` — **trading behavior does not change** (Surface rung). It is not "no change", though: since `score = passed/total`, the certificate score goes down, and that value is loaded into the `certifications` table, from which `/api/engine` computes a rolling average. In other words, **the score time series before and after this commit has a different definition and must not be compared directly** (measured 63 → 56). The earlier period was higher not because of an improvement but because unevaluated gates were counted as passes. The E4-0b predictivity audit must separate any span that crosses this boundary. Measured impact: the primary indicators of `kr_index` · `bond` (`kospi` / `yield`) had n=0 in production `macro`, so since their introduction (#248) the two gates had never once been evaluated, yet were stamped green on every certificate. **This is a plumbing problem, not a collection gap** — `prices.KOSPI` has 419 rows, and the freshness gate on the same certificate already reads it. Only the volatility gate uses a `macro`-only path and so cannot see it. So this PR fixes only the semantics (removing the lie) and splits off connecting the input path and re-deriving the bond threshold — for the latter, `_compute_3d_change` returns pct while the 0.3 threshold is written with a bp meaning, so changing only the pointer would turn a dead gate into an always-firing gate. Follow-ups: `kr_index` connected a lookup through `prices` in #1032 (2026-08-11), and `bond` was redefined with a bp-unit indicator (`us_10y_yield_3d_bp`) in #1067 (2026-08-18). **With the §6 retirement on 2026-10-06, this gate and the score time series are no longer produced** — the description above remains valid only as a caution when reading the records left in the `certifications` table (#1619).

No backtest is attached to this clause. Its trigger is a **data outage**, not a market signal, so replaying "what if VIX had been missing" against past markets is not meaningful evidence. To raise or lower its rung, first measure the actual outage frequency and the market distribution at those times.

### 2.7 Development Flow (gstack 7-phase, adopted 2026-04-16)

All work goes through the 7 phases **Think → Plan → Build → Review → Test → Ship → Reflect**. No phase is skipped. Work that does not pass a gate cannot move on to the next phase.

| # | Phase | Input | Action | Output | Pass gate |
|---|------|------|------|-------|-----------|
| 1 | **Think** | Issue/observation/pain point | Problem framing, root cause, literature check (§2.1) | Issue body or `docs/plans/*.md` problem + evidence + constraint | Can "why now" be answered in 1 sentence? |
| 2 | **Plan** | Think output | Scope, touched files, acceptance, Escalation Ladder (§2.6) level | Draft PR description / `/plan` output; `## Done when` + `## Out of scope` in the issue | No scope creep? 1 issue = 1 PR? Commits ≤ 3? Does the issue carry `Done when` items, each checkable by a command or a measurement, and an `Out of scope` list? |
| 3 | **Build** | Plan | Minimal implementation. `config/*.yaml` first (§2.2), cross-stage imports deferred + allowlisted (§2.3), `kst_now()` enforced | Commits on a feature branch | No hardcoding? hook/lint pass? `git branch --show-current` checked? |
| 4 | **Review** | Feature diff | Codex `/codex review` + Claude self-review. P1 must be resolved | Review log, GATE verdict, per-item verdict against `Done when` | All P1 resolved? Reasons for disagreement stated? Every `Done when` item met, or the gap stated? |
| 5 | **Test** | Reviewed branch | `make test-fast` + live run of the user workflow (§5.8 #3). Browser QA for UI | Green CI + manual QA log | User command run directly at least once? |
| 6 | **Ship** | Tested branch | `gh pr merge --squash --auto` (the repository deletes the head branch on merge). Close the issue. Clean up the local branch. Update TODO Tier 2 / 3 if the scope shifted | MERGED PR, CLOSED issue | Tier 2 / 3 updated? Local branch cleaned up? |
| 7 | **Reflect** | Ship result | Surprises, new gotchas, memory update, NEXT_SESSION refresh | NEXT_SESSION updated + fix-pattern gotchas cite `**Test:**` (§5.3.1) | Can the next session start running right away? |

**A failed phase = regress to the previous phase**. When Codex is unavailable, Claude self-review + recovery in the next PR's Review. A trivial chore may compress Think/Plan inline (from Build onward, every phase is followed).

**Next-session entry artifact Plan gate** (2026-04-22): `NEXT_SESSION.md` is a Reflect output even though it is docs-only/gitignored. **Inline OK**: typo/format/self-note/HEAD append. **Plan consult required** (batched into the next primary PR's Plan consult): a change of next primary, priority reordering, new risk framing, a replaced live command, an acceptance change. Re-consult triggers: (a) a change of next primary, (b) 2+ competing candidates, (c) a possibly stale handoff, (d) cadence reflection after 5 accumulated PRs or a 48h burst, (e) new legal/TOS/production risk.
Burst ship cadence (measured 2026-04-22, 48h: 6 functional + 3 docs PRs): the conditions to reproduce it are independent scope + a clear queue + a prior codex Plan consult. It is not a sustainable default — frequent codex Round 2 skips, docs PRs at the edge of scope discipline, reviewer fatigue, handoff drift. After a burst of 48h or more, always run a handoff Plan consult + lower the cadence of the next cycle.

## 3. Core Architecture Decision Records

Changing any of these decisions in the future requires evidence that refutes the "why" given below.

### 3.1 The DB is the single integration point

Only `nuri/core/db/` imports `sqlite3`. Other modules use only `query()`, `query_df()`, `upsert_*()`, `get_db()`.

**Why**: a single point of control over DB access patterns → prevents WAL conflicts, manages transactions, keeps migrations safe. Tests are fully isolated by injecting `db_path`.

### 3.2 10-agent weighted consensus

Independent analysis by 10 agents + a weighted vote. Risk agent veto (`alpha_action=FLAT` with confidence ≥ `consensus.risk_veto_threshold`, 80 by default → overrides the whole result; a risk verdict without an alpha action vetoes only when its action is SELL).

**Why**: reduces single-model bias. Loss avoidance takes priority over profit seeking.

**Weights**: the defaults are in `nuri/trading/agents/consensus/registry.py::DEFAULT_WEIGHTS` (code); the adjustment range and floor are in `config/agents.yaml` (`adjustment_range` · `min_weight_floor`). Learning Memory adjusts the weights dynamically within a ±30% range based on past hit rates.

**Agent input alignment (2026-10-08)** — a change that fixed errors in input interpretation, not in the verdict rules. Read the debt ratio as a percentage (the DB/yfinance unit; it used to be read as a multiple, which penalized 634 of 664 tickers); do not count insider `other` transactions as buys; for 13F, use only each manager's latest filing; date windows on the rating, insider and earnings caches; PCR abstains after 132 hours and does not mix series whose source has changed; the risk veto fires only on a stop-loss breach (invariant — removes the path in which losses and volatility summed alone produced FLAT); weights are based on USD market value and real accounts; KOSDAQ is identified by the `.KQ` suffix. **Impact measurement**: consensus for the 17 held tickers was recomputed with the pre- and post-change code on the same copy of the operating ledger (received 2026-10-08) — final-verdict changes **0**, agent-vote changes 2 (fundamental), confidence +1.3 and +3.6 in two cases, increase in abstentions and live yfinance calls 0. This is a one-day snapshot, not a replay of past verdicts. The CBOE-only PCR source condition was not included, because the operating PCR is `yfinance_SPY` only, so it would have made the options vote abstain for every ticker every day — the scale problem of SPY's single-expiry value was a separate issue → **resolved in #1739 (2026-10-08)**: the official CBOE daily statistics file (`cdn.cboe.com/data/.../{date}_daily_options`, TOTAL put/call) is restored as the primary source and scored on the same scale as the thresholds. Impact (same ledger copy, only the input changed SPY→CBOE, same code): final-verdict changes for the 17 held tickers **0**, options-vote direction changes 0 (stays HOLD — 'mild fear' PCR 1.13 → 'neutral' 0.84), confidence −2.2 to +2.1 (14 tickers). `agents.yaml` is unchanged, so `execution_config_sha_v1` stays the same, and the boundary is marked by the `code_rev` · `macro.source='CBOE'` rows. The SPY fallback is used only on days when CBOE is down, and it is still on a different scale — a known limitation. **Test:** `tests/trading/agents/test_audit_regressions.py` (per-input regressions), `tests/scripts/test_placeholder_vote_impact.py` (ledger reconstruction of the new abstention exit).

### 3.3 Confidence scoring pipeline

```
base = regime_win_rate × 60% + profit_factor × 40%
     × drift_multiplier (0.3 ~ 1.1)        ← Learning Memory
     × conflict_penalty (0.5x if high)     ← Conflict Detection
     × regime_fit_penalty (0.4x if avoid)  ← Strategy Map
     × position_penalty (0.3x if minimal)  ← Regime position sizing
     × vix_gate (0x if blocked, 0.5x caution)
```

**Why**: a plain win rate is not enough. A trustworthy score must reflect current-regime performance, drift and conflicts.

### 3.4 Sources of the investment rules

Every rule has an academic/empirical basis. Adding a rule without a basis is prohibited.

| Rule | Basis | Source |
|------|------|------|
| Stop-loss -7% | CAN SLIM + in-house validation PR F (2026-04-22). us_core 85 × SMA golden cross 250 entries paired counterfactual: the ATR shadow surface fell short of acceptance at 3/6 on the 6 metrics → **PR F2 deferred**, -7% kept. Details: `scripts/episodes/pr_f_atr_validation.py` docstring + commit `c834049` (a commit on a squashed PR branch — it never resolved in a clone in the first place). | O'Neil, *How to Make Money in Stocks* |
| Take-profit +20%/+40% | Maintains a 3:1 reward-to-risk ratio | Minervini, *Trade Like a Stock Market Wizard* |
| Trailing -15% | Optimal in an 11-year backtest (73.9% cumulative) | In-house backtest |
| VIX > 30 buy block | Verified collapse of the win rate in fear zones | In-house signal backtest |
| Superinvestors ≥ 3 | Excess returns of 13F holdings | SEC EDGAR analysis |
| Disposition-effect warning | Bias toward selling winners early | Shefrin & Statman, 1985 |
| **execution_priority** | A 1h delay during downward momentum = an additional loss locked in | In-house financial logic (PR #200) — ⚠️ **not wired**: no code reads the config (§3.5 note) |
| **trailing_stop_arm +15%** | Prevents giving back gains | PR #202 — ⚠️ **not wired**: trailing works from the HWM with no arming condition (§3.5 note) |
| **decisions outcome tracking** | Dynamic weight adjustment from per-agent hit rates | PR #181, #183 |
| **Kelly f\* = (bp−q)/b** | Position size reflecting edge, win rate and payoff. Fractional Kelly (full Kelly is unsuitable because of estimation error and DD). Actual wiring in E3. | Kelly (1956); MacLean/Thorp/Ziemba (2011) |
| **Mean-variance frontier** | The intent behind the sector cap. `max_sector_exposure: 35%` is a prudential default, not derived from the frontier. Regime re-evaluation is an E3 candidate. | Markowitz (1952) |
| **Trend-following regime filter** | Long-term SMA risk-on/off switch. The empirical starting point for §3.6. | Faber (2007) |

### 3.5 Per-account strategy profiles

Defined in `config/rules.yaml account_strategies`. Matched against the account `strategy` field in `portfolio.yaml`.

| Strategy | Stop-loss | Single position | Sector | Notes | Intent |
|------|------|--------|------|---------|------|
| **core** | -7% | 15% | 35% | — | By the book. Main default |
| **active** | -10% | 25% | 45% | `trailing_stop_arm: 15` | Cut losses short, let gains run (PR #202) |
| **swing** | -15% | 30% | 50% | — | Short term, 5–20 days |
| **long_term** | -20% | 25% | 50% | — | Long-term holding |
| **pension** | -30% | 40% | 60% | — | Pension ETFs, very long term |

**Choice**: Core is conservative, Active cuts aggressively + protects winners, Swing is genuinely short term, Long_term/Pension are long-term ETFs. A rule change takes YAML + backtest + PR.

> ⚠️ **Of the table above, only the stop-loss and single-position limits are actually enforced (2026-08-02 audit).**
> - **The sector column is decorative.** No code reads `account_strategies.*.max_sector_exposure`; every sector check (rebalance_advisor · execution_firewall) uses the global `position_limits.max_sector_exposure` (35%). So even if a pension account is written down as 60%, it trips at 35%.
> - **No code reads `trailing_stop_arm: 15` either.** A trailing stop exists, but it is neither per-account nor subject to an arming condition — `check_trailing_stop_signals()` judges every held ticker by its decline from the post-entry high (HWM) (-15% growth/value, -20% volatile/swing). The statement "it turns on only after reaching +15%" was not true.
>
> Wiring them up is a change in trading behavior and therefore needs a separate STRATEGY PR. This paragraph **aligns the document with the code**; it does not weaken the rules.

### 3.6 Regime-adaptive framework (E3)
**Status (2026-04-29)**: Phase 1 shadow shipped (#479). **Phase 2 paired counterfactual: FAIL by binary rule** — 30d horizon CI_lower=-1.06% ≤ 0. The 60d/90d horizons are a robust PASS (CI_lower=+1.95% / +2.60%). See "Phase 2 verdict" below for details. **Phase 3 permanently shelved (2026-04-29 3-LLM consensus)** — Codex(gpt-5.4) Round 1 B → Round 2 A, Qwen3.5-122B Round 1 D → Round 2 A, Claude consistently A. Phase 1 shadow telemetry is kept permanently (`enabled: false`, indefinitely). Reopen trigger: §7.1 auto-trade reversal only. Detailed Round 1/2 verdicts: `data/llm_consults/2026-04-29_e3-phase2-shelve-decision.md` + `..._round2-three-way.md` (gitignored, local on the user's machine).
**Phase 2 verdict (2026-04-29, branch `feat/e3-phase2-paired-counterfactual`)**:
- Spec: `docs/plans/E3_phase2_paired_counterfactual.md` (local-only, gitignored; post Round 5 codex GATE PASS)
- Universe: us_core 85 frozen (81/85 with ≥1000 price rows), 2020-01-01+
- Gate: `recovery_confirmed AND vix_favorable(VIX<22 AND 3d_slope<0) AND regime_favorable(in {bull_low_vol, recovery} AND conf≥0.60)`. macro_benign dropped — no 5Y backfill.
- Sample: 14,728 raw 20d-breakouts → 166 eligible (post-90d-window) on 7 unique trading days. Effective N≈7 (binding power-limit caveat).
- Bootstrap: 1000 iter × block_size=20 trading days (frozen primary), seed=42.
- Metrics:
| Horizon | N | Mean Δ | CI95 Lower | CI95 Upper | Verdict signal |
|---------|---|--------|-----------|-----------|----------------|
| **30d (primary)** | 166 | +0.54% | **−1.06%** | +2.59% | **FAIL** |
| 60d | 166 | +4.46% | +1.95% | +7.75% | (would PASS) |
| 90d | 166 | +6.76% | +2.60% | +12.53% | (would PASS) |
- Sensitivity (block 10/40 informational): 60d/90d remain robust PASS across all block sizes; 30d remains FAIL.
- Decision: **FAIL** by spec acceptance rule (PASS iff 30d CI_lower > 0).
- Honest framing: amplifier effect is real and large at 60d/90d but power-limited at 30d.
- **Final disposition (2026-04-29 3-LLM consensus)**: Phase 3 (alpha-amplified live) **permanently shelved**. Decisive argument: §7.1 auto-trade is permanently deferred → E3 effect path collapses to conf-boost-only on recommendations, which user manual judgment already moderates → Phase 3's product value chain is broken. Redesign options (a/b/c/d) were all **rejected** — (a) sample extension does not resolve the effective N≈7 power limit, (b) universe widening carries a survivorship-bias trade-off that is excessive relative to the value of conf-boost-only, (c) relaxing the regime threshold is a result-fitting risk, (d) for retrying after macro_events accumulate, the §7.1 deferral does not change the product-layer answer. **Spec amend (D-style 30d→60d primary) rejected** — a post-hoc amendment after a 5-round GATE PASS damages process credibility. The 60d/90d PASS is recorded only as "supportive horizon evidence" (not grounds for Phase 3 promotion).
- **Reopen trigger**: only on a decision to reverse STRATEGY §7.1 (resume auto-trade). At that point, rewrite a fresh spec (tied to a real execution path), then re-run Phase 2.
- Phase 1 shadow telemetry kept permanently: amplifier `enabled: false` indefinitely, only gate evaluation is logged.
- Verdict artifact: `data/reports/<YYYY-MM-DD>/e3_phase2_verdict.json` (gitignored).
- Lock-tests: `tests/quant/exits/test_amplifier_paired_replay.py` (24 invariants), `tests/quant/exits/test_amplifier_stage0_audit.py` (13 invariants).
**Original framework intent**: wire §3.4 Kelly · Markowitz · Faber + the §2.6 Symmetric amplifier into config + code. The `siege_gates.regime_overrides` schema + the `certification.py` branch (both removed with the §6 retirement, 2026-10). **Overriding the Hard veto (VIX>30, risk-of-ruin) is prohibited**.
**E3 acceptance (2026-04-19 codex Plan consult)**: 3-stage validation — **ship when both Stage 0 and Stage 2 pass** (Stage 1 is a diagnostic signal). Order: Stage 0 → 1 (in parallel) → 2.
- **Stage 0 — No-lookahead audit**: verify that no future row flows into the rolling stats when the classifier is called historically (`compute_dynamic_thresholds()`, `_load_spy_series()`, special-regime detectors, and a check that `classify_regime_history()` does not hide intra-month flips).
- **Stage 1 — Classifier plausibility (diagnostic)**: N=24–36 date samples → regime label → directional sanity of the forward 30d return distribution. Even if it fails, ship when Stage 2 PASSes (codex Round 1 P1: even without raw sign predictivity, a sizing rule has loss-attenuation value).
- **Stage 2 — Paired counterfactual (main gate)**: a single source of frozen entry signals (candidates: SMA crossover / momentum top-decile / BUY signal historical replay). prices 5Y × N≥200 entries. (a) baseline vs (b) regime-adaptive sizing → forward 30/60/90d return. **Same entries, only sizing differs**.
**Primary metrics** (paired, not Sharpe — 50-200 samples lack the power to detect Δ0.1): mean paired excess return 30/60/90d, bootstrap CI on mean/median paired delta, downside rate / MAE, CVaR / drawdown, sign test (auxiliary).
**Secondary (deferred)**: walk-forward 5Y IS / 1Y OOS Sharpe+DD, Monte Carlo regime mis-classification 5%.
**Amplifier firing condition**: promoted after accumulating 70%+ positive outcomes (paired excess return > 0 at 30d) across 20+ Surface firings.

### 3.7 SIEGE's limits and equity-context re-evaluation (E3 hypothesis)

**Label**: hypothesis for E3 validation. The diagnosis is valid — "0 upside / opportunity-cost gates". Quantitative acceptance is in §3.6.

**Diagnosis** (2026-04-18, `certification.py:553`): the 11 base `ALL_CERT_CHECKS` (variable from 11 to 30+ depending on portfolio composition) are **all downside-block** — position/sector cap, stop-loss, leverage ban, freshness, volatility, external, conflict, drift, macro, rules. **0 upside / opportunity-cost gates**. Result: only "is a new buy safe?" is judged, and "the opportunity cost of holding cash" is invisible. It stays silent even when VIX 12 + bull + momentum top-decile line up favorably. This is the structural cause of the user's pain point ("too conservative").

**Update 2026-04-21 (PR A #429)**: a structural fix shipped for the "SIEGE REJECT → sell surface" path. §2.6 Soft penalty implemented — concentration/sector_limit are split off into `portfolio_action=REBALANCE`, and the alpha (SELL) path is blocked. Live verify (production DB): BAC/TSLA concentration → `portfolio` bucket, urgent 0. **The original diagnosis (no upside gate) is still open** — PR A only stops "the wrong increase-risk emit of downside-only".

**Update 2026-10-06 (#1619)**: SIEGE certification itself was retired per §6. This section's hypothesis (two-sided balance · amplifier) hangs on the §2.6 ladder and the §3.6 paired-counterfactual path, not on the certificate, so it remains open — however, the phrase "SIEGE two-sided balance" is historical, and the implementation target is `nuri/trading/engine/amplifier_gate.py`.

**Update 2026-04-22 (§3.8)**: "downside-block direction" is a structural truth, but the premise "works as effectively downside-predictive" was tentatively refuted in the synthetic audit (repeated wrong-sign position_limit Δ). Valid as a prudential constraint, unproven as a predictive gate. In upside-gate discussions, do not leave "the existing gates work as intended" as an assumption.

**Hypothesis** (validated in E3, §3.6 3-stage): on top of the §2.6 4th rung (amplifier) + the §3.4 Kelly/Markowitz/Faber basis, does introducing SIEGE two-sided balance (measuring favorable conditions, not only REJECT) improve paired outcomes versus the baseline? Priority in a conflict between the Amplifier and the Hard veto follows §2.6 operating principle 4 (post-veto sizing).

**Warning**: do not cite this §3.7 diagnosis/hypothesis as prescriptive to make a config/code PR. It stays at hypothesis grade until the §3.6 backtest PASSes. PR A #429 is not an exception (it shipped only the alpha/portfolio data-structure split, not an upside gate).

### 3.8 SIEGE predictivity measurement (E4-0b v2) — audit route closed

**Status**: v1 #417 → v2 redesign → 60-month production rerun complete (2026-04-22, Mac mini). Result: acceptance `CI_upper < 0` not met; the `position_limit` Δ point estimate is repeatedly wrong-sign (fired > not_fired, at all of 30/60/90d). **The variant ladder × momentum-based snapshot audit route did not prove the §3.7 downside-predictive framing with the 2026-04-22 data/design — closed**. The §3.7 hypothesis as a whole is not closed (real-portfolio replay, `recommendations.outcome` accumulation, and measurement dedicated to the Symmetric amplifier remain open).

**Separating the prudential and predictive axes (mandatory citation rule)**: `position_limit` / `sector_limit` / `leverage_ban` are valid as **prudential portfolio constraints + user-preference defaults** — emotional control, §7 auto trading deferred, O'Neil/Minervini lineage. **However, the synthetic audit did not prove the claim that they function as forward-downside-predictive gates**. Do not conflate the two — cite the rules only on prudential grounds; the downside-predictive framing was tentatively refuted in §3.8.

**2026-10-06 (#1619)**: the certifier was retired (§6). This section's verdict remains valid — `rebalance_advisor` enforces the prudential axis, and the predictive axis stays refuted. The audit tools (`siege_predictivity_audit.py` · `/nuri-siege-audit`) are deleted in a cleanup PR and pinned at revision `d8a89ede`.

**E4-0c (re-grading after measurement consume) invalidated** — there is no durable evidence to consume. The §3.7 upside-gate hypothesis is validated on a path separate from the §3.6 paired counterfactual (sizing-rule legitimacy, E3-3b PASS) (user actual portfolio replay, real history after `recommendations.outcome` accumulates).

**Detailed methodology / gate eligibility matrix / 60-month gate-level table / deferred extensions / re-run commands**: in the last revision, `d8a89ede`, of the deleted `/nuri-siege-audit` skill and `scripts/analysis/siege_predictivity_audit.py` (`git show d8a89ede:.claude/skills/nuri-siege-audit/SKILL.md`, #1619). The STRATEGY body holds only the canonical verdict.

### 3.9 Provisional vs canonical Learning Memory (#468)

Extended from a single-horizon structure, in which `_compute_weights` read only `recommendations.outcome_30d`, to a **per-agent multi-horizon precedence** structure. 30d is canonical, 21d is a provisional warm-start. 7d/14d are readiness/monitoring only.

**Why 30d is canonical, not changeable**: it is consistent with the holding windows of O'Neil's 8-week hold (CAN SLIM) and Minervini's 3:1 reward-to-risk (SEPA). The trailing -15% trigger (PR #202) is also measured within 30d. The hit/hit_quality criteria (BUY +5% / SELL -2%) are limited to 30d.

**Why 21d is the only provisional source (no 7-14-21 blend)**: a blend has to set horizon-specific decay weights arbitrarily → "heuristic disguised as learning". 21d is 70% of the way to 30d + its sample distribution is relatively stable. 7d/14d are noisy (intraday/short-term effects) — used only for readiness/monitoring.

**Why per-agent precedence, not global**: verdict frequency is asymmetric across agents. 2026-04-28 production: technical 158 BUY+SELL / risk 5 / retail+crypto 0. A global label (single weight source) cannot express the simultaneous state "some canonical, some provisional, some default". Per-agent is the accurate model.

**Why `0.10` provisional cap (vs canonical `0.30`)**: weaker evidence (shorter window + the same min_agent_records gate) gets a conservative cap. Exact calibration is separate work (statistical shrinkage, Bayesian posterior). At this stage it is a **policy cap, not inference**.

**Why structural separation, not spy-test**: `compute_canonical_weights` and `compute_provisional_weights` are separate functions, and each reads only its own outcome column. The import graph guarantees the contract — the Hard veto / amplifier (§2.6) path calls only `compute_canonical_weights` (no access to provisional). A spy-test (mock + assert_not_called) is brittle, so it was not adopted.

**Why retail/crypto are `structurally_unsaturating`** (not "underpowered"): under their current behavior pattern, the two agents fire BUY+SELL with a frequency of 0. Even a natural wait will never saturate them. The intent is to use `default_weight` permanently. Changing the agents' emit policy is a separate issue (outside the PR scope).

**Implementation update 2026-10-28 (#1979)**: the retail rationale above records the original weight-selection design. Retail is now a retired compatibility slot: it never reads historical Reddit rows and always returns `abstained=True`. Its configured weight is retained, but it contributes no vote. The existing crypto readiness classification and weight policy are unchanged.

**API surface**: `/api/learning-memory/readiness` responds with a per-agent source list (canonical_30d / provisional_21d / default / structurally_unsaturating + per-horizon sample_count + eligible). 5-minute cache.

**References**: `nuri/trading/agents/consensus/learning_memory.py` (`compute_canonical_weights` / `compute_provisional_weights` / `select_weight_source`) + `nuri/trading/agents/consensus/__init__.py` (`agent_readiness`), Migration 23 (`outcome_7/14/21d` columns), `nuri/trading/recommend/tracker.py::TRACK_HORIZONS`.

### 3.10 Strategic Asset Allocation (SAA) — long-term policy mix

> Implementation scope (2026-10-23): targets exist in `config/rules.yaml`; `nuri/trading/strategy/strategic_allocation.py` computes drift on demand. It aggregates quantity × average cost across the portfolio without currency conversion or per-account filtering. It does not implement an automatic quarterly rebalance or a lifecycle glide path. The cadence and combination rules below express design intent, not an implemented scheduler contract.


**Basis (modern academic + authoritative sources, 2020+)**:

- **Ibbotson & Kaplan** (_FAJ_ 2000, correcting the reading of Brinson's "93%"): the answer depends on the question. Policy (asset allocation) explains about 90% of a fund's **return variability over time** and about 40% of the **variation in returns among funds**, and on average about 100% of the **return level** is explained by the policy return level.
- **Vardharaj & Fabozzi** (_J. Portfolio Mgmt_ 2007): replication on modern data — confirms the dominance of asset allocation. A Brinson follow-up.
- **Andrew Ang** (_Asset Management_, Oxford University Press 2014, written at Columbia Business School; he later led BlackRock's Factor-Based Strategies Group): what matters is not asset-class labels but the bundles of overlapping risks (factors) they represent — so momentum / value / quality factor weights are also an asset-allocation dimension.
- **Antti Ilmanen** (AQR, _Investing Amid Low Expected Returns_ **2022**): the low-rate, high-valuation environment of the 2020s → 60/40 expected return falls to 4-5% a year. Recommends factor diversification + a global tilt.
- **Vanguard** _Principles for Investing Success_ 4th ed (**2024**) + Capital Markets Model (**VCMM 2024**): 4 principles (goals/balance/costs/discipline). Expected return over the next 10 years — US equity 3-5% / Intl 7-9% / US bond 4-5%/yr.
- **Morningstar** _Mind the Gap_ (**2024**) + DALBAR QAIB (**2024**): gap between investors' realized returns and fund returns -1.7%/yr (Morningstar). Cumulative gap between retail equity and the S&P 500 ~3%/yr (DALBAR, 1994-2023). **Discipline (manual rebalance) has a bigger impact than alpha**.
- **Damodaran** (NYU, ERP 2024 update): equity risk premium implied 4.6% (mid-2024) — valuation context.
- **CFA Curriculum** Asset Allocation reading: recommends running SAA (long-term policy mix) and TAA (market-view overlay) as **separate layers**.
- **Bernstein** _Intelligent Asset Allocator_ (2000, still a reference): equal-weight rebalancing approximates the mean-variance optimum — robustness comes first because of cov matrix instability.

**Key corrections (to prevent misuse)**:

1. Brinson "93%" = **variance (over time)**, NOT return level. "Get asset allocation right and you get 100% alpha" is a misreading.
2. The 2020s environment = **low expected return** (Ilmanen 2022). **Cost minimization + suppressing the behavior gap** make up a larger part of expected return than a simple weight mix.
3. Factors (momentum/value/quality) are asset classes too — our `quant/factors/` module already has them (consistent with the Ang 2014 framework).

**Current state (2026-05-04 audit)**:

- TAA ✅: `REGIME_ALLOCATION` (`nuri/trading/strategy/longshort.py:24`) — dynamic mapping of 10 regimes × long/short/cash weights.
- SAA ❌: **long-term target weights** for asset classes (equities/bonds/commodities/REITs) are undefined. `account_strategies` has only single-position / sector caps; there is no asset-class weight rule. (Since then defined as `strategic_allocation_targets` in `config/rules.yaml`, read by `nuri/trading/strategy/strategic_allocation.py`.)

**Adopted framework** (Vanguard 2024 + Bernstein equal-weight robustness + Ang factor):

- Strategic weights that are equal-weight or based on risk tolerance. Avoids the cov matrix instability of mean-variance optimization.
- A different SAA target per account_strategy (core / active / swing / long_term / pension) — reflects differing risk tolerance.
- Lifecycle glide path (Vanguard target-date model): 100 - age = equity % (rough anchor). Applied through a `target_age` option in the user's portfolio.yaml (follows in Phase 2).
- Factor tilt (Ang 2014): momentum/value/quality weights are an overlay on top of SAA (currently reflected by our `quant/factors/` signals).

**SAA target definition** (new config/rules.yaml `strategic_allocation_targets`, user review needed):

| account_strategy | us_equity | kr_equity | bond | commodity | cash minimum | Basis |
|---|---|---|---|---|---|---|
| `core` | 50% | 20% | 20% | 5% | 5% | Vanguard 3-fund variant (KR added, based on US 60%) |
| `active` | 60% | 20% | 10% | 5% | 5% | Aggressive — equity weight ↑, pursues the risk premium even in Ilmanen's low-return environment |
| `swing` | 50% | 30% | 5% | 5% | 10% | Short-term turnover — cash buffer ↑ |
| `long_term` | 40% | 20% | 30% | 5% | 5% | Long-term stability — bond weight ↑ |
| `pension` | 30% | 15% | 45% | 5% | 5% | Pension — Vanguard target-date glide path (for investors in their 60s) |

**Drift threshold**: a deviation of ±5% or more from target → emit a REBALANCE recommendation (never alpha_action=FLAT — the STRATEGY §3.7 portfolio_action axis-separation rule).

**Rebalance cadence** (Morningstar/Vanguard 2024 recommendation: discipline first):

- Scheduled: once a quarter (first business day of months 3/6/9/12).
- Unscheduled: recommend immediately on drift > 10% or a regime change (in sync with TAA).
- **Suppressing the behavior gap**: no attempts at market timing — mechanical rebalancing is the long-run alpha (DALBAR/Morningstar 2024 data).

**TAA × SAA combination rules**:

- SAA = asset-class weights (long-term anchor)
- TAA = `REGIME_ALLOCATION` long/short/cash weights (short-term overlay)
- On conflict: for a regime-driven cash increase, TAA **temporarily** overrides SAA (defense first). When the regime normalizes, allocation returns to SAA.
- Factor tilt (Ang 2014): within the SAA weights, factor signals (`quant/factors/momentum.py` etc.) guide security selection.

**Not applied (deliberately deferred)**:

- Mean-variance optimization (not used on the system's default path) — avoids cov matrix instability, as Bernstein/Ilmanen recommend. `nuri/analysis/rebalance.py` implements both Riskfolio-Lib-based MVO (max Sharpe) and Risk Parity, and the system path (`regime_aware_rebalance` — the `GET /api/rebalance` default · tracker) uses Risk Parity (`rp`). MVO is selected only through `?method=mvo` or the analysis CLI (`python -m nuri.analysis.rebalance`, default `mvo`).
- All Weather risk parity (Dalio) — requires leverage (4-environment hedge); incompatible with STRATEGY §7.1 auto trading deferred.
- Yale model (Swensen) — limited access to non-traditional assets (PE / hedge funds).

**References**: `config/rules.yaml strategic_allocation_targets` (canonical values, Phase 1 skeleton), `nuri/analysis/rebalance_advisor.py` (drift calculation — to be extended in Phase 2).

### 3.11 Small-stake + measurement mode — the system's burden of proof for alpha (#824/#828, 2026-07-07)
**Decision**: capital actually executed on system recommendations is limited to an "experiment sleeve" sub-cap **inside** the account's equity allocation, and the rest of the equity is held as a broad-index passive core based on the §3.10 SAA. The sleeve cap is raised only by passing the pre-registered adjudication criteria below + a STRATEGY PR (by analogy with §2.6 operating principle 2). Lowering/freezing is always allowed (prudential). The burden of proof lies with the system — the default value of the edge is "none".
**Why now**: the 2026-06 Edge Reality Check. Live results (#675, 116 picks / 7wk in a single bull market): BUY alpha vs SPY +2.8/+5.0/+19.8%p (7/14/30d), but a ~56% beat rate against the growth peer QQQ (30d) — a sample dominated by style effects. Permutation tests rejected the momentum/RS edge (#709: p=0.791 after the degeneracy-bug fix) and rejected the exit improvement (#715: Δ−0.318, p=0.552 → #800 leader-exit disabled). The measurement infrastructure (#674/#675) is running, but if the adjudication criteria are not fixed in advance, post-hoc interpretation keeps recurring (the same principle as the §3.6 rejection of the spec amend).
**Escalation Ladder (§2.6)**: scorecard ledger = **Surface** (evidence exposure only). Sleeve cap = **Surface** — consumption wiring was completed by ⑤ (#834/#909, status updated 2026-10-07): a cap breach is surfaced every day as a REBALANCE in the market-close brief. The "block new buys when the sleeve's remaining room is used up" face is wired into ExecutionFirewall, but that actor is called only from the manual phase-2 chain (last run in the operating ledger: 2026-08-18) — until it enters the everyday path, it is not treated as a **Hard veto** (once it does, it belongs to the VIX>30 new-buy-block family). **Resolving an over-cap state** is surfaced only as `portfolio_action=REBALANCE` (§3.7/#429 axis — must not be expressed as an alpha SELL). The §3.8 axis separation is observed — the sleeve cap is cited only as a prudential constraint, not as a downside-predictive claim. The measurement target of this section is putting into actual measurement the "real-portfolio replay + `recommendations.outcome` accumulation" path that §3.8 left open.
**1) Single scorecard ledger (ledger of record)**: the ledger for the measurement records used in adjudication (`decision_outcomes` etc.) is **the production (Mac mini) DB alone** (#824) — the dev machine's DB is a read-replica, and verdicts and reports cite only ledger queries (prompted by a 2026-07-07 false positive from mixing two ledgers). Operating details (sync direction, writer-job prohibition) are in `docs/SOURCE_OF_TRUTH.md` (local); ledger snapshots/backups were built by ⑥ (#835/#896 — a verified WAL-safe backup daily at 00:00 + an off-machine copy + an age watchdog).
**2) Sleeve × SAA combination rule** (by analogy with the §3.10 TAA×SAA pattern): the sleeve is not an asset class but a compartment **inside** the equity bucket (cap denominator = % of us_equity+kr_equity **combined**) — the SAA target/drift ±5% calculation is the usual calculation with the sleeve included (no double counting). The cap value is `config/rules.yaml measurement_mode.sleeve_max_equity_pct` (per account_strategy, canonical). Execution is manual by the user, per §7.1 — this section is not a back-door revival of §3.6 Phase 3 (alpha-amplified live).
**3) Adjudication criteria (pre-registered 2026-07-08 — no post-hoc amendment, §3.6 precedent)**:

**The only kind of post-hoc addition allowed — prudential invalidator** (2026-08-18, codified following #1068):
A condition that **can only put the verdict on hold and can never cause a promotion** may be added even after pre-registration.
This is because the purpose of pre-registration is to prevent *post-hoc justification of a positive result*, and a condition
that works in one direction only, merely withholding the verdict, cannot be used for that abuse (the same logic as §2.6
"lowering/freezing is always allowed"). Relaxing a condition, changing the sample protocol or modifying the 3 conditions does not fall under this; as before, they require a STRATEGY PR +
re-approval. **Obligations when adding one**: (a) record the condition and its introduction date in this section, (b) put the threshold in `config/rules.yaml
measurement_mode` and lock it with a lock test to prevent accidental relaxation, and (c) pin the scenario in which the condition produces invalidation
with a regression test. The first case is `max_settlement_lag_days` below.
| Item | Value | Basis |
|---|---|---|
| Adjudication date | 2027-06-30. No early promotion (lowering is always allowed). Sample emit cutoff = 2027-05-15 (guarantees the 30d window completes) | pre-registration — Harvey, Liu & Zhu (2016) multiple testing / p-hacking |
| Sample protocol | Only **US BUY** decisions emitted from `declared_date` (2026-07-08) to the emit cutoff (distinct `decision_id`). The 30d window is the single adjudication window — 7/14d are diagnostic (30d was chosen based on the exploratory results of pilot #675; the adjudication sample, from declared_date onward, is disjoint). n ≥ 200. SELL is diagnostic only (ledger alpha is stored direction-adjusted — the tracker flips the sign) | Measured ledger σ≈25.0%p (US BUY 30d, n=62, #828 comment query): minimum detectable effect at n=200 ≈ +4.4%p/30d (one-sided α=0.05, 80% power); measured accrual ~43/month → expected n≈400 at adjudication → ≈ +3.1%p. **Not detected ≠ no edge** (power limit stated explicitly). The §2.1 30-trade threshold is a per-signal tier; this n is system-level (a separate axis) |
| Benchmark | SPY (`forward_outcome_tracker.py` `DEFAULT_BENCHMARK_TICKER` = `measurement_mode.benchmark`). **This adjudication is fixed as US-only.** After #833 landed, the **recording basis** for KR decisions is per underlying asset (`measurement_mode.benchmark_by_asset_class`, classification = `asset_class_rules`, self-described in each outcome row's `benchmark_ticker`; KRX-listed US-tracking ETFs → SPY, bonds and commodities → no benchmark = alpha NULL, other KR → KOSPI. #833 used the listing market as the basis, and #1459 changed it to the underlying asset) — only the recording basis changed; **whether a decision is subject to adjudication stays the same**, and KR is diagnostic only until a **separate pre-registration** | #675 caveat: SPY overstates alpha compared with growth. Measuring KR against SPY mixes FX + market style into alpha and even flips its sign |
| Promotion conditions (all 3 at once) | mean 30d alpha > 0 · permutation p < 0.05 (**ticker-block placebo**: keeps the real sample's ticker→emit-date structure, substitutes tickers from the same market's eligible universe, N=1000, statistic = mean 30d alpha, one-sided — the null inherits the dependence from overlapping windows, same-day batches and repeated tickers) · mean alpha > 0 in both halves of a **2-way equal split at the median decision date** (guarantees balanced n per half) | The spirit of López de Prado (2018) PBO/deflated Sharpe — requires robustness, not a single statistic. A naive iid permutation is anti-conservative because of clustering |
| Regime axis | The internal 10-regime classification is for diagnostic Surface only and is not used in adjudication — ledger label coverage 3% (12/383, #828 comment query), 1 transition since 2026-04 (risk of adjudication deadlock), circularity of our own classifier | Measured 2026-07-07 (production ledger) |
| Contamination control | Ad-hoc fills without a `decision_id` are excluded from the sample (the capital version of the #715 pre-registration principle). Missing outcomes (tracking failure/missing price) are excluded, but their rate is disclosed in the adjudication report — **above 15%, the adjudication is invalid (measurement extended)** **Missing outcomes are counted only for *settled* windows** — the state in which the benchmark has a close on or after the maturity date (#1068, 2026-08-18). A bar that has not arrived yet is neither a tracking failure nor a missing price; measured in production: calendar 50.0% vs settled 9.1%. The emit cutoff is 46 days before the adjudication date, so **on the adjudication date the two bases agree**, and this is therefore not an amendment of the pre-registration — what changes is the monthly progress report during measurement. Companion guard: if the settlement frontier falls behind by more than `max_settlement_lag_days` (7 — the first case of the prudential invalidator policy above, introduced 2026-08-18), adjudication is blocked with `INVALID_STALE_BENCHMARK` (the missing rate counts only settled windows, so when collection stops it actually looks cleaner) | Shefrin & Statman (1985) — ad-hoc intervention is a path for the disposition effect to re-enter. Missing-data bias (dropouts can correlate with bad outcomes) |
**Handling the adjudication result**: 3 conditions pass → a STRATEGY PR raising the cap **for the US-executed sleeve only** (the new cap is also pre-registered by amending this table). Not met → keep/shrink the sleeve + extend measurement, or converge to the §3.10 passive core — no "just a little more"; this table is the answer. What is pre-registered is the adjudication **criteria**, not the initial cap value — the sleeve's initial value has no effect on the adjudication sample, so it stays a placeholder until the first user-confirmed PR and can be corrected by an ordinary PR. From confirmation onward, raise-sticky takes effect.
**Prerequisites before adjudication (follow-up issues — as of 2026-10-07, ①–⑥ have all landed, adjudication criteria unchanged)**: ① regime label backfill — #832 implemented (`scripts/ops/backfill_regime_labels.py` + canonical-or-NULL on the emit path, for diagnostics) ② permutation adjudication tool — #842 implemented (`nuri/quant/validation/decision_alpha.py`, design pre-registered in this table; the existing 3 tools in `nuri/quant/validation/` are for portfolio Sharpe only) ③ integrated 3-condition adjudication — implemented: #842 `decision_alpha.adjudicate()` puts the three conditions in one report, and the #856 monthly report (1st of every month, production ledger, `PROGRESS_REPORT` before the adjudication date) posts it to #brief (`/api/alpha` is a tracking-completeness endpoint, so by design it is always NOT_MEASURABLE — it does not adjudicate) ④ KR benchmark separation — #833 implemented (`decision_outcomes.benchmark_ticker`, recording basis only; KR adjudication pre-registration not started). #1459 (2026-09-08): the recording basis moves from the listing market to the **underlying asset** — `measurement_mode.benchmark_by_asset_class` (classification = `asset_class_rules`). KRX-listed US-tracking ETFs → SPY, bonds and commodities → no benchmark (alpha NULL). Measured in the ledger: of 1,200 KOSPI rows, 525 had non-Korean underlying assets, and the 30d "alpha" of −15%p on US index ETFs was the KOSPI−S&P spread. **US-listed decisions (the adjudication sample) stay fixed to SPY** — they do not look at this map. **The next daily scan re-measures the accumulated rows under the new rule** — `scheduler.py` `alpha_tracking` (17:00 KST) runs with `max_decisions=2000`, and 1,247 decisions have been emitted, so all of them are picked up; the scan query has no 'already measured' filter, and the upsert is `ON CONFLICT … DO UPDATE SET benchmark_ticker = excluded.benchmark_ticker, alpha = excluded.alpha`. Which rule produced a row is told apart by `decision_outcomes.code_rev` · `tracked_as_of_date` (#1305), which the same upsert updates. The adjudication sample is unchanged — `is_kr_ticker → continue` in `decision_alpha.py` comes **before both** alpha collection and the `n_missing_closed` count, so the new NULL rows cannot move the 15% invalidation metric ⑤ sleeve-cap consumption wiring — implemented (#834/#909; for the call scope of the new-buy-block face, see Escalation Ladder above) ⑥ ledger snapshot/backup policy — implemented (#835/#896). Monthly alpha progress report posting = #856.
**References**: `config/rules.yaml measurement_mode` (canonical values), `nuri/agents/actors/forward_outcome_tracker.py` (measurement pipeline, daily at 17:00 KST), `docs/SOURCE_OF_TRUTH.md` (ledger mapping, local-only).
### 3.12 Forward measurement of the held_add threshold grid (#1173 = #788 Stage 1, pre-registered 2026-08-29)
**Decision**: the held_add thresholds (75/75/80) are not changed; instead, "would it have fired if the threshold were X" is recorded daily in the `held_add_would_fire` ledger for the entire candidate grid (Stage 1). Adjudication (Stage 2) uses only the pre-registered criteria below — on the same principle as §3.6/§3.11, they are fixed **before records accumulate**, and the only post-hoc amendment allowed is §3.11's prudential invalidator (withhold-only conditions).
**Why now**: the `held_add_shadow` job had 0 emits / 19 skips for 6 consecutive weeks — there is no data on whether the thresholds are excessive. A retroactive backtest (v1) was rejected for survivorship (#788 Codex 2026-08-21) → v2 = forward measurement. The grid and adjudication criteria went through 1 round of codex design review (NEEDS_REWORK → incorporated) (`data/llm_consults/2026-08-29_held-add-would-fire-design-1173.md`).
**Canonical values**: `config/buy_signals.yaml held_add_mode.would_fire_logging` (grid + `stage2_adjudication`) — a lock test blocks drift; changes go only through a PR amending this section.
**Adjudication spec (canonical prose)**:
1. **Event row** = (as_of_date, ticker, account). eligible = `earnings_blackout=0 ∧ headroom_pct>0`.
2. **Variant fires** = would_fire_json[V] ≠ null — regardless of which mode V picks (a relaxed threshold can pick a higher-precedence mode different from current, and that too is within the measurement scope).
3. **incremental(V)** = eligible rows where V fires ∧ current does not fire.
4. **dedup**: within (ticker, account, V), the **first firing row** of each 7-calendar-day cluster survives — had it been executed, it would have been on the first signal (prospective discipline).
5. **Outcome metric**: 30-calendar-day forward alpha = ticker return − SPY return. entry = close on as_of_date, exit = close on the last trading day ≤ as_of_date+30d (same dates on both sides).
6. **Estimator**: the **sample median** of incremental(V) (not paired — the incremental set has no pairs). qualifying = median alpha > 0 ∧ n ≥ 20 ∧ the firing-rate constraint is met.
7. **Firing-rate hard constraint**: weekly deduped firings ≤ 25% of that week's unique eligible (ticker, account) rows — scales with book size and can be computed from the ledger alone (a fixed-count cap would bake today's number of holdings into the rule). A variant that exceeds it is eliminated regardless of alpha.
8. **Ranking across variants**: sort the qualifying variants by median alpha; if the top 2 differ by ≤ 0.5%p, take the more conservative one (higher effective threshold).
9. **settlement**: adjudication only on or after logging start + 8 weeks, and events only from rows with `as_of_date ≤ adjudication_date − 30d` (blocks opportunistic inclusion/exclusion of a partially matured tail — by analogy with the §3.11 emit cutoff).
10. **Inference limits (explicitly pre-registered)**: overlapping windows + repeated tickers break iid — this adjudication is a **descriptive screening**. A PASS grants only eligibility to start the #519 calibration backtest; a threshold change still requires a STRATEGY PR + the Escalation Ladder.
11. **No days_held covariate**: its source is a hardcoded fallback of 30 (portfolio has no entry_date) — it is not recorded in the ledger and must not be used in Stage 2. The fallback effect that remains in the gates is shared by all variants, so it cancels out in comparisons between variants. Fixing the source is a separate issue.
**References**: `nuri/trading/recommend/held_add_would_fire.py` (grid calculation and recording), `nuri/trading/recommend/held_add.py::evaluate_mode_gates` (gate evaluation shared by measurement and live).

## 4. Development quality standards

Check these before opening a PR.

### 4.1 Tests

| Item | Standard | Current |
|---|---|---|
| Backend tests | Codecov project 1%p threshold vs `target: auto` — not required, report-only (target ≥ 95%) | 9,661 tests, 463 files (statement coverage **100%**, branch coverage **100%**; fast suite 9,606 passed / 0 skipped, `make test-fast`, 2026-10-28) |
| Frontend tests | target ≥ 90% | 1,449 tests, 117 files (2026-10-12 full run, after the pipeline Run buttons were removed) |
| E2E | Core flows | 10 spec files · 93 Playwright tests (`playwright test --list`, 2026-10-12) |
| CI | Required | lint + test + coverage + security + privacy |
| Network | Forbidden | conftest.py mock |

The historical 2026-09-29 `make ci-cov` baseline was 99% statements (150/25,528 uncovered), with 123/7,888 partial branches. The current measurement above is the fast-suite scope. The collection count also includes excluded slow/integration tests; fast-suite 100% does not establish their execution.

### 4.2 Code

| Item | Standard |
|---|---|
| Linter | `ruff check` (E/F/W/I) |
| Commits | Conventional Commits (in English) |
| PR | 1 issue = 1 PR, ≤ 3 commits |
| New rules | `config/rules.yaml`; no hardcoding |
| New thresholds | `config/agents.yaml` |
| Time | `kst_now()` / `today_kst()`; `datetime.now()` is forbidden |

### 4.3 Data

| Item | Standard |
|---|---|
| DB access | `nuri/core/db/` only |
| Schema changes | `_MIGRATIONS` list; no direct ALTER |
| Exchange rate | DB → yfinance `KRW=X` → `StaleExchangeRateError` (no hardcoded fallback) |
| External data | Cross-checked against at least 10 external sources |

### 4.4 Security

| Item | Standard |
|---|---|
| Secrets | `.env`; never committed to git |
| Authentication | When DASHBOARD_PASSWORD is set, an HMAC-SHA256 keyed token cookie, checked by `frontend/src/proxy.ts` |
| CI | Trivy CRITICAL → merge blocked |
| LLM | Sending data to an external LLM is limited to the §4.4.3 whitelist: only public data (Tier 0) is allowed; portfolio (Tier 2), narrative and decision-making (Tier 1) data are forbidden. Everything else uses a local LLM (Ollama / llama.cpp). |
| **Personal financial data** | Never exposed in commits, PRs, issues, comments, fixtures or CI logs. `config/portfolio.yaml` is gitignored, and its contents must not be tracked either. This covers brokers, quantities, average costs, balances and trade history. |

#### 4.4.1 Personal financial data enforcement (#138)

**Authoritative blocking criteria**: `scripts/verify/check_privacy_leak.py` is the ground truth.

<!-- cspell:disable -->

| Category | Blocked | Allowed placeholder |
|---|---|---|
| Korean broker name | 카카오페이, 미래에셋, 키움증권, 삼성증권, NH투자증권, 토스증권, KB증권, 신한투자증권, 하나증권, 메리츠증권, 유안타증권, 대신증권, 이베스트투자증권, 흥국증권, IBK투자증권, 신영증권, 교보증권, 현대차증권, SK증권, DB금융투자, LS증권, 다올투자증권, iM증권, 부국증권, 유진투자증권, 한양증권, 케이프투자증권, 상상인증권, BNK투자증권, 하이투자증권, 한화투자증권 | `Brokerage Alpha/Beta`, etc. | <!-- privacy-allow: broker_name — §4.4.1 패턴 표 자체 (#981) -->
| Romanized broker | kakaopay, mirae, kiwoom, samsung_securities, nh_invest, toss_securities, shinhan_invest, hana_securities, meritz_securities (case-insensitive substring) | `brokerage_alpha`, etc. | <!-- privacy-allow: broker_name — §4.4.1 패턴 표 자체 (#981) -->
| Suspect monetary literal | An integer of 7 or more digits + a `total_invested`/`cash_balance`/`deposit`/`withdraw`/`principal`/`net_worth`/`buying_power` key | Round millions (`1_000_000`...`100_000_000`) are allowed automatically |
| **Ticker + PnL combination** (PR #202) | (a) `[-+]\d+(\.\d+)?%\s*(TICKER)` (`-34% (TEM)`) (b) adjacent `TICKER <signed %>` (`PL +43%`). Scans source + unpushed commit messages. | Rule threshold text (`손절 -7%`, i.e. "stop-loss -7%") passes when there is no ticker context. `TICKER_FALSE_POSITIVES` frozenset (120 entries, including HWM/SL/MDD/CPI/VIX/BTC/ETH). | <!-- privacy-allow: ticker_pnl — §4.4.1 패턴 표 자체 (#981) -->
| **Personal identifiers** (#1557) | Shape only: `<name>ui-Macmini` (romanized Korean default hostname) · `<account>@<host>.local` · `/Users/<account>/` · `-Users-<account>-` (Claude project path). The values are written neither in the scanner nor in the tests — `tests/test_no_personal_identifiers.py` locks the exact names by assembling them at runtime. Scans source + `--message` + unpushed commits. | `user@macmini.local`, `/Users/USER/`, `Test-Macmini` |

<!-- cspell:enable -->

**Intentional exclusion**: `한국투자증권` (KIS) is an Open API integration target (`nuri/collectors/kis_*`, `docs/KIS_INTEGRATION.md`). Credentials are in `config/kis/kis_devlp.yaml` (gitignored by `config/kis/*`; `~/KIS/` is legacy-compatible).

**Plan / spec note protection (consolidated 2026-04-30, Session 8)**: the whole `docs/plans/` directory is covered by `.gitignore`. Previously only individual files (`E3_symmetric_amplifier_design.md`, `507_buy_candidate_emitter_phase1.md`) were listed, with a risk of omission whenever a new spec was added — consolidated at the directory level. The 3 previously tracked files (`E3_phase2_paired_counterfactual.md`, `E3_symmetric_amplifier_design.md`, `e4_0b.md`) were handled with `git rm --cached`. This defends against leaking broker names / financial figures from the user's own spec notes. **Use broker name placeholders when writing a new spec** (`Brokerage Alpha Main`, etc.) — even though the directory is gitignored, this avoids accidents in a future commit.

**4 defense layers** (defense in depth):

1. `scripts/verify/check_privacy_leak.py` — the core scanner (stdlib only).
2. `scripts/verify/pre_push_check.sh` Section 4 — the local pre-push gate.
3. `.github/workflows/main-ci-cd.yml` `privacy-scan` — the CI gate on every PR (no frontend-only exception).
4. `.claude/settings.json` PreToolUse hook — checks the `new_string` of an Edit/Write at edit time via `--message`. Paths outside the repo and gitignored paths are exempt (the invariant concerns the **public tree**, #1567 — a local handoff must be able to contain its own hostname). Locked by: `tests/test_hook_guard_execution.py::TestPrivacyGuard`.

**Adding a new broker**: update the `scripts/verify/check_privacy_leak.py` `BROKER_NAMES_KO`/`BROKER_NAMES_EN` tuples + `tests/scripts/test_check_privacy_leak.py` + the table above together.
Commit message scan (to prevent another PR #202):

- pre_push_check.sh Section 4b: scans the unpushed commits in `origin/main..HEAD` with `--unpushed-commits` → blocks the push (ticker+PnL + personal-identifier shapes, #1567)
- The local hook is the right place — once pushed, it is baked into history (Stage 2 needed)
- CLI: `git log -1 --format=%B | python scripts/verify/check_privacy_leak.py --message`

**History cleanup (Stage 2) — completed 2026-09-29** (explicit user approval + direct execution, 1 force push):

All 1,471 commits on `main` were rewritten with `filter-branch` to remove **all 4 categories**. The basis is a full scan run with the scanner
before starting — brokerage names: 7 names, 39 occurrences (18 commits) · personal identifiers: 9 commits · ticker+PnL: 2 commits · monetary literal: 1 commit,
plus 626 historical blobs. The `계정명@실명기기.local` (account name @ real-name machine) identity on 239 author/committer entries was also changed to noreply.

- **No human enumerated the verdicts**: the replacer iterated until `check_privacy_leak.gate_text()` reported 0 findings,
  and after it finished, 1,471 commit messages + 6,632 (path,blob) pairs were scanned again with the same scanner, confirming 0 findings.
- **The HEAD tree was byte-for-byte identical** (`7abf77eb`) — evidence that not a single character of the current code changed.
- **Legitimate exceptions were preserved**: the 10 paths that contain brokerage names by design — the scanner itself, its tests, this document's pattern table, etc. — were
  excluded, and `test_held_add_mode.py` kept only its ticker+PnL fixtures while its past brokerage names were removed.
- **Side effects**: every commit SHA changed. The 8 short-SHA references in docs and code were updated to the new values; the pre-cleanup SHAs recorded in the production ledger's
  `backtests.params.code_rev` were **left untouched because they are records** (see the `provenance.py` comment).
  1 fork keeps the old history as-is, and removing GitHub's cache of unreachable objects requires a Support request.
- The commit message body of PR #202 (squash) was the origin of this leak. Since then, enforcement has blocked ticker+PnL
  at the commit stage (§4.4.1 table), and now the history side is closed too.

#### 4.4.2 External data handling principles

Every external service follows a **per-data-class whitelist**.

| Data class | Default policy | Conditions for allowing |
|---|---|---|
| **Tier 0** public (RSS, disclosures, market prices, 13F) | May be sent externally | A provider listed in §4.4.3 |
| **Tier 1** user narrative | Must not be sent externally | STRATEGY revision + the user's own approval + a retention policy |
| **Tier 2** user portfolio | **Never sent externally** | A separate STRATEGY revision + measured ZDR + the user's own approval. No exceptions — the OpenAI path for the LLM report was retired on 2026-10-08 (§4.4.3). |

§4.4.1 prevents Tier 2 leaks; §4.4.3 is the Tier 0 whitelist.

#### 4.4.3 External LLM Egress Policy (#152, revised 2026-04-14)

A **whitelist** approach. Every external call must go through the single gateway, `nuri/llm/openai_client.py`.

| Provider | Model | Allowed Tier | Unit price (in/out per 1M) | ZDR | Notes |
|---|---|---|---|---|---|
| OpenAI | `gpt-6-luna` | Tier 0 (RSS classification) | $0.10 / $0.50 | Recommended | 100 headlines per day. ~$3.51 per year at nano rates → unit price: input 1/2 · output 2/5 |
| OpenAI | `gpt-5.4` | Tier 0 (public company briefing) | $2.50 / $15.00 | Recommended | Requested by the user on 2026-10-07. An explicit generate button; official sources and verified articles only; sending accounts, holdings, PnL or user narrative is forbidden. Generating trade verdicts is forbidden. However, **which stocks are requested** becomes a sample of the watched and held stocks — even when the content is public material, the request list is a user signal. |

**Model replacement (2026-10-08, user request)**: `gpt-5.4-nano` → `gpt-6-luna`. It is the next generation in the same usage tier (classification and extraction), and its unit price is lower. Calls set `reasoning_effort="none"` explicitly — at luna's default (`medium`), `temperature` 0 is rejected with a 400 and classification silently falls back (measured).

**Public company briefing implementation record (2026-10-08)**: the prompt `public-briefing-v9` uses fictional
explanatory examples only as a style reference, and keeps verification of real evidence IDs, legal entities, dates and numbers.
The application displays stored system verdicts separately. Acceptance of the strict JSON schema by the real API and
report generation have been confirmed, but this does not mean that the quality for every stock or the effect on agent verdicts has been verified.
This is not a change to the allowed egress scope, the investment rules or the measurement criteria. For the implementation and the open merge conditions,
see the [stock research guide](RESEARCH_BRIEFING.md).

**Tier 2 OpenAI path retired (2026-10-08)** — this supersedes the Tier 2 allowance of 2026-04-14 (the LLM portfolio report) and
the "cloud primary" decision of #854. Rationale:

1. **There is no ZDR** — Responses API `store=true` responses could be retrieved again afterwards for both `gpt-5.4-nano` and `gpt-6-luna` (measured).
2. **The protection was a single environment variable** — `OPENAI_ZDR_APPROVED=1` was a truthy flag that checked no contract,
   and the report input is per-stock PnL % and sell amounts. That one line was the only mechanism sending this data to a provider that retains it.
3. **It does not contribute to decisions** — verdicts call no LLM, and the report is narrative. In production the flag
   was commented out, so it was already blocked.

The report is generated only with a local backend (llama.cpp → localhost Ollama); if none is available, setup instructions are shown. The gateway
refuses anything other than `data_tier="tier0"` before the SDK client is created. Verdict: the Codex (`gpt-6.1-sol`) and Claude cross-reviews agreed.
**Test:** `tests/llm/test_report.py::TestGenerateLLMReportFallbackChain::test_portfolio_report_never_reaches_the_external_gateway`,
`tests/llm/test_openai_client.py::TestChatTextTierGate::test_tier2_is_refused_even_with_the_old_zdr_flag`.

**Mandatory operating rules**:

1. Every external LLM goes through the wrapper (`openai_client.get_client()`). Direct `import openai` is forbidden.
2. Per-call audit log — `external_llm_calls` table: `timestamp, provider, model, endpoint, prompt_tokens, completion_tokens, latency_ms, success, error_type`. No content.
3. `NURI_DISABLE_EXTERNAL_LLM=1` → raises `ExternalLLMDisabled`.
4. Failure loud — no silent fallback. The caller is responsible for graceful degradation.
5. Adding a provider / extending a data class requires a STRATEGY revision + the user's own approval.

Deferred (added when needed):

- Narrative input UI (after the Tier 1 policy decision)
- External LLM cost monitoring dashboard (based on the `external_llm_calls` table)
- ~~Tier 2 → local LLM migration~~ — completed 2026-10-08: Tier 2 is local-only (see the retirement record above)

Monitoring trigger: in effect from the merge of #152. If costs exceed 10× the estimate, notify the user + revert to `NURI_DISABLE_EXTERNAL_LLM=1`.

## 5. LLM agent harness (Harness Engineering)

In this project, an LLM (Claude Code) is the main development tool. LLMs have patterns of systematic failure. This section holds the canonical principles — real cases, diagnostic procedures and the details of the Gotcha-Test Pair protocol are loaded on demand by the `/nuri-harness-debug` skill (`.claude/skills/nuri-harness-debug/SKILL.md`). The case study narratives are preserved in `git log` (PR #272, #300-#307).

### 5.1–5.6 Failure patterns (canonical list)

6 patterns recur systematically. The symptoms, real cases and defense procedures for each pattern are in the `/nuri-harness-debug` skill.

| # | Pattern | Core point in 1 line |
|---|------|----------|
| 5.1 | **Hallucination** | Confidently states functions/parameters/paths that do not exist — grep the signature before calling |
| 5.2 | **Confirmation bias** | Repeats the same failure in the same way — after 2 failures, question the approach itself |
| 5.3 | **Phantom fix** | Says "fixed" but actually fixed somewhere else — after a fix, confirm the intended lines with coverage |
| 5.4 | **Scope creep** | "Improvements" beyond the request — 1 issue = 1 PR, ≤ 3 commits |
| 5.5 | **Test illusion** | Tests pass but the target code never runs — confirm actual line coverage with the coverage report |
| 5.6 | **Number propagation error** | Changes one place and leaves the other references stale — exhaustive `grep -ri "이전값"` ("old value") + `make verify-doc-counts` |

#### 5.3.1 Gotcha-Test Pair principle (PR #307)

**Every fix-pattern gotcha must name and cite a test that fails when the fix disappears.** Plain facts/quirks need no Test: (state "no fix, just facts" in the PR body). If only folklore remains, nothing can stop the next reviewer from removing the defensive code as "unnecessary" (the lesson of the `df.copy()` recurrence). Protocol details and enforcement stages (1st: review checklist; 2nd: Tier 3 `scripts/audit_phantom_fixes.py` — planned, not implemented) are in the `/nuri-harness-debug` skill.

### 5.7 Harness components

| Layer | Role | Implementation |
|--------|------|------|
| **Context Files** | Project rules | Root `CLAUDE.md` + 13 scoped + `AGENTS.md` + `docs/STRATEGY.md` |
| **MCP Servers** | External tool connections | `.mcp.json` → `nuri-read` read-model (stdio · engine-enforced `readonly=True` on every query · ALLOWED columns only, #1306). The raw SQLite registration was removed from the committed default — arbitrary SQL reaches portfolio/trades (§4.4 Tier 2). |
| **Skill Files** | Repeated tasks | `scripts/deploy/deploy_remote.sh`, `scripts/verify/verify.py`, `scripts/db/migrate.py` |
| **Mechanical Enforcement** | System enforcement | ruff · main-ci-cd.yml · pr-discipline.yml · `make verify-*` · `scripts/verify/gate_check.py` (Makefile stage gate) |

**Entropy GC**:

| Type | Detection | Defense |
|---|---|---|
| Dead code | `ruff` (F401/F841) | CI block |
| Stale data | Freshness SLA | WARN/FAIL dashboard |
| Stale tests | Codecov PR comment | Coverage-drop warning |
| Schema drift | `schema_version` + `_MIGRATIONS` | Automatic via `init_db()` |
| Config drift | Centralized in `config/*.yaml` | No hardcoding |
| Number drift | Exhaustive `grep -ri` | State numbers explicitly in commit messages |

**Context Files design**: one giant file ✕ → scoped per directory ✓ (root + 13). Information that can be inferred from the code ✕ → only the "why" of decisions. `CLAUDE.md` points to `STRATEGY.md` as an on-demand load target.

### 5.8 Harness principles summary (reflects #272 of 2026-04-14; 7 principles)

1. Read when you don't know          — do not assume
2. Change approach after 2 failures  — no 3rd identical attempt. If the same fix gives a partial resolution 3 times, suspect the root cause
3. Verify through the user workflow  — mock test ≠ verification. Run `make X --flag` yourself before shipping
4. Keep to the scope                 — do only what was requested
5. Grep the numbers                  — do not fix just one place
6. The system blocks                 — linters/CI/gates enforce, not documents
7. Measure external APIs             — do not guess concurrency/timeout/rate-limit. yfinance 10-thread OK ≠ KRX 10-thread OK

**Change history**: 2026-04-14 — #3 strengthened ("run" → "verify through the user workflow"), #7 added (measure external APIs). Made after falling into the mock-only ship trap 3 times (`#272` session, git log).

### 5.9 Case Studies (on-demand reference)

The `/nuri-harness-debug` skill is canonical for the concrete lessons from real failed sessions. When debugging a similar pattern, it auto-triggers, or you invoke `/nuri-harness-debug` manually.

- **Case #1** — the #272 session (2026-04-14, 12 PRs): mock-only tests, API concurrency asymmetry, ThreadPool timeout, verification from the user's perspective, multi-role flow. Narrative → `git log --grep '#272' --since 2026-04-13 --until 2026-04-16`.
- **Case #2** — the JKHY episode (PR #300-#303, #306, #307): dissent overwhelmed, mechanical divergence penalty, correction of a misread initial diagnosis. Narrative → `gh pr view 300/301/302/303/306/307`.

### 5.10 Frontier Alignment + Improvement Roadmap (2026-04-30)

> Historical design/session record. Pending items and commands in this section are not the current work queue. Use the current implementation, §3.12 for held-add measurement, and the local TODO for status.

The 7 principles of §5.8 are **essentially aligned** with **the 2026-02 OpenAI publication ("Harness engineering: leveraging Codex in an agent-first world", <https://openai.com/index/harness-engineering/>) + Anthropic Claude Code Best Practices (<https://www.anthropic.com/engineering/claude-code-best-practices>) + academic evidence (HAL Kapoor et al. 2026 / AgencyBench Li et al. 2026)**. However, there are **3 measurable gaps** relative to the frontier. This sub-section pins down the quantitative spec + acceptance + risk of each gap (kept separate from TODO — the policy layer).

#### Gap A. Expanding agent autonomy (OpenAI 1M LOC pattern)

**Frontier example**: OpenAI Codex team — a `1,000,000+ LOC` production app, `사람 손 0줄` (0 lines by human hands) (2026-02 OpenAI blog). Enabled by AGENTS.md + mechanical CI invariants + a layered architecture (Types → Config → Repo → Service → Runtime → UI).

**Current state (nuri-quant)**: Build/Review/Test/Ship/Reflect 7-phase Flow (§2.7) — the human review stage is mandatory. Hooks on both sides: Codex consult + Claude self-review. Merges require explicit user approval. **agent-only PR merge rate ≈ 0%**.

**Two sides of the gap (honest assessment)**:

- *Case for expansion*: harness invariants (privacy-scan, doc count drift, hooks, ruff, conventional commits, ≤3 commits/PR) already block deterministically and effectively. There are PR classes for which autonomous merge is safe (e.g., doc-only, lint-only).
- *Case against expansion*: the same ethos as the permanent deferral of automated trading in STRATEGY §7.1 — **financial-impact code requires user review**. In an ecosystem that acknowledged system responsibility after directly experiencing a loss cascade, growing autonomy runs against the trust budget.

**Acceptance criterion** (research, no commit by default):

- Phase α: define a PR class taxonomy (doc-only / lint / test / src / config / strategy) + specify autonomy_safe_class (initial: `doc-only` only, ≤ 5% of merged PRs).
- Phase β: post-hoc measurement of `autonomy_safe_class` PRs — regression rate after 4 weeks (frequency of post-merge revert or fix-forward) < 10%.
- Phase γ: **strategy / src / config stay under permanent human review** (a STRATEGY change is required).

**Priority**: Tier 3 research. Low priority. Human review remains a policy requirement; no monetary value is inferred here.

#### Gap B. Measuring harness-model coupling (AgencyBench-style)

**Frontier evidence**: AgencyBench (Li et al. 2026, 138 real-world tasks, <https://www.preprints.org/manuscript/202604.0428>) — quantitatively demonstrates **"for agent task reliability, model capability < harness layer (infrastructure)"**. Same harness × different model = different success rate. HAL (Kapoor et al. 2026, 21,000+ rollouts) reaches the same conclusion.

**Current state (updated 2026-08-13)**: multiple LLM consumers (`nuri/llm/openai_client.py` gpt-6-luna cloud + `scripts/dev/llm_consult.py` codex + local-LLM dual consult). **The local-model axis is measured** — `scripts/dev/llm_ab_eval.py` runs two models paired over 50 frozen prompts, and `scripts/dev/llm_ab_stats.py` decides with a Clopper-Pearson exact CI + McNemar exact. Its first application (2026-08-13) was the basis for replacing `qwen3.5-122b-a10b` → `muse-glimmer-30b` (#1038). **The cloud axis still has 0 measurement** — which phase breaks on a downgrade from Codex GPT-5.4 → GPT-4-class is unknown, and the `openai_client.py` path has no corresponding harness.

**Acceptance criterion**:

- Phase 1: create `data/harness_telemetry.jsonl` — record every LLM call (timestamp / model / phase / outcome / token_count). Wired into both `nuri/llm/openai_client.py` and `scripts/dev/llm_consult.py`.
- Phase 2 (planned, not implemented): weekly aggregation script — proposed `make harness-quality-report` → per-model success rate / failure pattern / phase breakdown. After 4 weeks of data, a model swap recommendation (cost-quality tradeoff of the classification model `gpt-6-luna` vs a higher-tier model — the 2026-10-08 nano→luna replacement was made without this measurement, on unit price and generation grounds, #1737).
- ✅ Phase 3 (2026-08-13, #1038): nuri-specific eval suite — **50** frozen prompts in `config/eval/thesis_prompts.yaml` (v1 10 + adversarial 40, families a-j), limited to the `thesis_query` path. The primary metric is `unsafe_price_level` (fabricated/phantom price levels); the secondary is IFEval-style instruction following. No LLM judge is used — if the judge wobbles, the A/B is meaningless.
  - **Limits (do not over-cite)**: the prompts are synthetic and self-written, so they have no external validity, and they do not measure whether investment judgments are right or wrong (no ground-truth labels). Each prompt is run only 1 time, so the noise floor is unmeasured — there have been cases where the same prompt gave different answers from run to run even with `temperature=0.0`. Add k repetitions before the next swap.

**Priority**: Phase 1-2 (telemetry) remains at **Tier 2 P2** — the harness covers only **replacement decisions** for local models; it is not continuous observation of every LLM call.

#### Gap C. Reviewing adoption of the HAL evaluation framework

**Frontier evidence**: HAL (Holistic Agent Leaderboard, Kapoor et al. 2026, 21,000+ agent rollouts) — an industry-standard evaluation protocol. Together with SWE-bench (Jimenez et al. ICLR 2024) + AgencyBench, it forms the frontier benchmark trio.

**Current state**: nuri-quant is a domain-specific (quant investing) repo. HAL benchmark tasks (e.g. SWE-bench code editing tasks) do not apply directly.

**Nature of the gap**:

- *Hard to apply directly*: HAL/SWE-bench are generic — they do not measure quant investment decisions.
- *Usable indirectly*: adapt the HAL methodology (rollout sampling, a standard evaluation harness) to nuri — create `nuri-eval-suite`.
- *Cost*: HAL-style evaluation, 1 run ~ \$50-200 (token cost, 1000+ rollouts). Regular use requires evaluating the cost-quality tradeoff.

**Acceptance criterion** (research):

- Phase 1: review the HAL methodology — classify the generic parts vs the parts that can be adapted nuri-specifically.
- Phase 2: create `nuri-eval-suite` (e.g., 50 fixed test cases on portfolio analysis / signal scoring / earnings preview) — integrated with the Gap B telemetry.
- Phase 3: Quarterly evaluation report → input to model swap / harness change decisions.

**Priority**: **Tier 3 research**. Gap B comes first (Gap C is built on Gap B's data). Building it alone has low EV.

#### Frontier alignment summary

| Frontier recommendation | nuri-quant application | Gap |
|---|---|---|
| AGENTS.md + machine-readable instructions | ✅ `AGENTS.md` + `CLAUDE.md` + `STRATEGY.md` | 0 |
| Mechanical CI invariants | ✅ privacy-scan, doc count drift, ruff, hook | 0 |
| Layered architecture | ✅ `nuri/core/` → `collectors/` → `quant/` → `trading/` → `api/` | 0 |
| Pre-commit deterministic hooks | ✅ `.claude/settings.json` PreToolUse/PostToolUse | 0 |
| Conventional commits + scope discipline | ✅ ≤3 commits/PR, 1 issue = 1 PR | 0 |
| Subagents (parallel, context isolation) | ✅ codex consult + local-LLM dual | 0 |
| Skills (reusable templates) | ✅ `make` targets + `nuri-*` skills | 0 |
| **Agent autonomy (OpenAI 1M LOC)** | ⚠ Human review required (intentionally conservative) | **Gap A** |
| **Harness-model coupling measurement** | ◐ Local-model axis measured since 2026-08-13 (Gap B) | **Gap B** (Tier 2 P2) |
| **Standardized eval framework (HAL)** | ❌ None | **Gap C** (Tier 3 research) |

**Conclusion**: 7 of 10 frontier recommendations applied. The 3 gaps are in the measurement + decision layer (autonomy / coupling / eval) — **not system code, but a system about the system**. Only Tier 2 P2 (Gap B) has **immediate build value**; the rest are research / policy decisions.

### 5.11 BUY Signal Asymmetry — #507 Phase 1 ship + Phase 2 v2 sequence (2026-04-30 Session 8)

> Historical design/session record. Pending items and commands in this section are not the current work queue. Use the current implementation, §3.12 for held-add measurement, and the local TODO for status.

**Problem (found 4-29, escalated as #507)**: throughout `Collect → Analyze → Consensus → Certify → Track`, the system ran **7 sell-side gates** and **0 buy-side emitters**. SIEGE / stop-loss / take-profit / position-limit / VIX / holdings_monitor all produced SELL or a block. Detailed inventory: `data/llm_consults/2026-04-30_507-system-audit.md`.

**Phase 1 ship (PR #508 / #512)**:

- `nuri/trading/recommend/buy_candidate_emitter.py` — factor + momentum + RSI + breakout fusion → BUY candidate stream + entry/stop/TP1/TP2.
- `_get_held_tickers()` SELL/TRIM/REDUCE filter + a single `_get_cooldown_tickers(days=5)` cooldown (as of the PR #508 ship).
- API + read-side dual-layer guard (PR #512): for `recommendations.action ∈ {SELL,TRIM,REDUCE}`, a portfolio JOIN blocks 0-share tickers.
- Registered the `FRESHNESS_POLICIES["portfolio"]` 24h warn / 72h fail policy.
- 4-30 brief verification: 0 SELL leaks for 0-share GOOGL/TSM; after the new MSFT/GOOGL buys, the brief surfaced them normally.
- **Remaining gaps**: held=skip 100% / threshold 70 floor / cooldown 5d uniform / freshness not surfaced in the brief / consensus called manually after a new buy / stale 0-share HOLD rows.

**Phase 2 spec v2 sequence (Session 8 codex+Qwen consult REJECT v1)**:

1. **#517 (2b)** — Cooldown SELL-type split + unified event taxonomy. Forward-only ALTER (no backfill). `payload.action_type ∈ {hard_sell, trim_action, position_reduce, divergence_alert}`. hard_sell 21d / trim 0d (re-add allowed) / reduce 7d / divergence 3d / legacy fallback 5d. Session-level dedup lock for trim 0d spam.
2. **#518 (2a)** — Held add-mode + multi-account cap + earnings blackout. 3 modes precedence (`tp1_residual_add` > `ride_winner` > `average_down`) — only 1 emit per (ticker, account, session). Per-account cap: derived from `account_strategies.<acct>.cap_max` (active=25%, core=15%, no hardcoding). Avg_down window: derived from `account.stop_loss × [0.3, 0.7]`. **Earnings blackout: held_add is blocked within earnings_date ± 5d** (binary event risk). **Shadow mode 14d mandatory** — not surfaced in the brief for the first 14 days; generates calibration samples.
3. **#519 (2c)** — Threshold backtest 104 weekly (2024-04 ~ 2026-04). In-sample 60% / OOS 40% (no peeking). Objective: max profit_factor s.t. MaxDD ≥ -10% AND n_emit ≥ 1.5/session. Liquidity-tier slippage. Tie-break: when within 1σ of T*, choose the conservative one. **3-LLM consult mandatory**.

**v1 → v2 changes (STOP/REFINE consensus of 8 LLMs)**:

- Sequence: ~~2b → 2c → 2a~~ → **2b → 2a (shadow) → 2c** (threshold tuning is calibrated after held-add is active)
- C1 sample: ~~13 weekly Q1-2026~~ → **104 weekly, 2 years**
- A3 hardcoded [-3,-10] → account-derived
- A4 cap hardcoded 5%p → account_strategy derive
- A2 mutual exclusion: block the 3 modes from emitting for the same ticker at the same time
- B2 backfill dropped (heuristic risk)
- E2 multi-account cap separated
- G quantitative figure ~₩1.2-2.3M dropped → derive it by backtest from the April audit replay

**Spec**: `docs/plans/507_buy_candidate_emitter_phase2_spec.md` (gitignored, v2 written)

**Consult archive**: `data/llm_consults/2026-04-30_507-phase2-spec-review.md`

### 5.12 Session 8 defect escalations (2026-04-30, #513–#516)

> Historical design/session record. Pending items and commands in this section are not the current work queue. Use the current implementation, §3.12 for held-add measurement, and the local TODO for status.

4 items found while verifying the Phase 1 ship + brief re-run — fix each in a separate PR:

| # | Finding | Priority |
|---|---|---|
| **#513** | `premarket_brief.py` does not surface the `FRESHNESS_POLICIES["portfolio"]` result in the brief body (the backend works, user visibility 0) | P1 |
| **#514** | `recommendations.action='HOLD'` rows do not get the portfolio JOIN filter → HOLD noise surfaces for 0-share tickers (TSM, etc.) | P2 |
| **#515** | Operational burden of calling `make consensus` manually after a new buy — `scripts/ops/import_portfolio.py` needs newly-added ticker detection + auto-trigger | P1 |
| **#516** | Re-entry into 3 stocks sold in April in the Pension account — need to verify whether the brokerage auto-buy setting was intended | P3 |

### 5.13 BUY candidate backtracking ledger (introduced in Session 8)

> Historical design/session record. Pending items and commands in this section are not the current work queue. Use the current implementation, §3.12 for held-add measurement, and the local TODO for status.

**Goal**: verify the reliability of the Phase 1 emitter score + automatically accumulate samples for the Phase 2c threshold backtest.

**Mechanism**:

- Record the BUY candidates emitted in each session as a baseline in `data/reports/buy_tracking/candidate_ledger.jsonl` (gitignored, append-only).
- On entering the next session, run `scripts/analysis/compare_buy_candidates.py --session N` (tracked infra) → baseline vs current close + average return per tier.
- Accumulate over 4 weeks ~~→ 13 weekly samples~~ → strengthen the Phase 2c threshold backtest input (13 weekly was the v1 C1 sample; v2 uses 104 weekly, §5.11).

**Tier definitions**:

- `A_high`: high conviction (directly tied to AI capex, strong fundamentals)
- `B_mid`: medium conviction (enter after a catalyst)
- `C_chase`: avoid chasing (5d momentum overheated; only after breakout+RVOL)
- `ADD_ride`: held ride-winner (manual judgment while Phase 2a is unshipped)
- `ADD_held`: held add (manual judgment while Phase 2a is unshipped)

**Verification items (acceptance — measuring score function reliability)**:

- A_high average 1d return > 0 → score signal valid
- A_high − C_chase spread > 0 → score differentiation valid (guards against the abnormal case where overheated 5d momentum does better)
- ADD_ride path relative to its peak → quantitative check of the ride-winner rationale
- B_mid average → measures catalyst transmission

**Session 8 baseline**: 11 names (A_high 3 / B_mid 3 / C_chase 2 / ADD_ride 1 / ADD_held 2). As of the 4-29 close. Run the verification as the first task of the next session (`NEXT_SESSION.md` cold-start checklist).

**Action on a negative result**: A_high avg < 0 → immediate escalation to P0 + raise the priority of the Phase 2c threshold backtest + escalate a score function recalibration issue.

### 5.14 Conversational / Reasoning Failure Patterns (observational, introduced 2026-05-27)

§5.1-5.6 = **code/tool-level** mechanical failure patterns. §5.14 = **conversation/reasoning-level** behavioral patterns (arising in the flow of responses with the user). Why the separate numbering: a different class with a different defense mechanism (hard to enforce with a gate; 1st line = human discipline + cross-session preservation in memory).

| Pattern | Symptom | Defense |
|---|---|---|
| **5.14.1 Data→Recommendation Slide** | Silently turns a request to share data collection/analysis results into a stock/action recommendation (arbitrary advice without an explicit user request) | Recommend only after confirming that the user explicitly asked for a recommendation ("what do you think of X", "where should I deploy", "recommend something"). Data presentation goes only as far as ranking / facts / freshness. Pause 1 step before starting a recommendation: "Did the user ask for a decision recommendation, or only for information?" |
| **5.14.2 Cross-context Inconsistency** | Applies the same quantitative filter / rule differently by market / domain (e.g., holding off on a KR-universe blow-off → recommending entry into a US-universe blow-off) | **Explicitly declare** the filter criteria (60d return cap, vol threshold, blow-off exclusion), then apply them identically to every market. Self-check before recommending: "If I apply the rule I used in context A identically to B, does it pass?" |

**Case studies**: `.claude/skills/nuri-harness-debug/SKILL.md` Part B (canonical narrative — the session 2026-05-27 correction case + git log reference). This section holds only the pattern definitions.

**Enforcement layer**: 1st = always-on rules (`.claude/rules/invariants.md` "No ad-hoc buy/sell calls" · "Data ≠ recommendation"; for Codex, `AGENTS.md` Recommendation boundary). 2nd = `/nuri-harness-debug` skill diagnosis. 3rd (not implemented) = hard to enforce mechanically with a hook (LLM response layer, no structured detection metric).

**Gotcha-Test Pair**: N/A — a behavioral pattern, not a code fix. Marked `*(facts, no fix)*`.

## 6. SIEGE Gate specification (v2) — retired (2026-10-06, #1619)

**Decision**: the SIEGE certification (`certify()` · writes to `certifications` · remediation) that judged the whole portfolio as CERTIFIED / REJECTED is **removed**. It is not kept in a weakened form — code left half in place becomes "code nobody knows why it is there" in the next session (the lesson of §5.3.1). #1619 tracks the removal work as 5 PRs.

**Rationale** (each of the 3 holds independently):

1. **There is no signal.** Production ledger (Mac mini), 2026-09-01 ~ 10-05: 50 certifications, 0 CERTIFIED. The callers are only `cli:premarket_brief` 25 · `api:actions:violations` 25. The error-severity failures are `stop_loss` 50 + `position_limit` 2 — if a single holding is below its stop-loss line, the whole portfolio is REJECTED every day. The Tier-1 stop-loss card (`nuri/alerts/risk_signals.py`, per-account `get_stop_loss_for_account`) already reports the same fact per stock.
2. **Nothing branches on it.** All code that reads the verdict is display-only — brief status color and fields, dashboard health score and violations, the `/engine` card, MCP `siege_status`, `/api/certify` (the dashboard home uses it for the footer quality line) · `/api/remediate` (the remediation plan emits `SELL_ALL`/`REDUCE` and quantities per failed gate but has no frontend consumer — it is exactly the SELL surface the axis invariant is meant to prevent, so it is deleted along with the rest). `config/rules.yaml amplifier.portfolio.requires_certify_pass` has 0 readers, so it was dead config, and the cleanup PR deleted it. The removal tears down a Surface rung of the Escalation Ladder, so there is **0 change in trading behavior**.
3. **It has no predictive power.** The 60-month audit in §3.8 closed by failing `CI_upper < 0`, and `position_limit` had the opposite sign. What remains valid is only the weight, sector and leverage limits as prudential constraints, and `rebalance_advisor` — not the certificate — already handles their enforcement.

Codex design consult (2026-10-06, `siege-retire-design-consult`): PROCEED_WITH_CHANGES — agreed to retire the aggregate verdict; do not build a replacement report; detach the frontend before the backend to prevent false REJECTED renders; move the non-SIEGE data under the `siege_gates` key elsewhere.

### Disposition by gate

| Gate (severity) | Disposition | Replacement source · semantics |
|---|---|---|
| `position_limit` (error) | Replaced | `rebalance_advisor` `position_limit_exceeded`. **The meaning changes**: SIEGE compared a stock's weight summed across all accounts against the most lenient limit among the accounts holding it × the regime multiplier. The advisor compares the in-account weight of an (account, stock) pair against that account's strategy limit — a core-account violation is not masked by an active limit, and there is no regime relaxation. Surfaced only as `portfolio_action=REBALANCE` (axis invariant). |
| `sector_limit` (error) | Replaced | `rebalance_advisor` `sector_limit_exceeded`. Same meaning — both sum the portfolio-wide `weight_pct` per sector and compare it against `max_sector_exposure`. Surfaced only as REBALANCE. |
| `stop_loss` (error) | Replaced | Tier-1 stop-loss card (`risk_signals.py`) + `rebalance_advisor` `stop_loss_exceeded` (per-account strategy). The mechanical `alpha_action=FLAT` path (`nuri/core/axis.py`) is unchanged. |
| `leverage_ban` (error) | Replaced | `rebalance_advisor` `leverage_etf`. The advisor row carries `SELL_ALL` and a quantity, so the violations surface **strips the execution fields** and emits it only as REBALANCE — no urgent SELL (axis invariant). |
| `rules_loaded` (error) | Retired | No replacement. The gate that turned a `config/rules.yaml` load failure into a REJECTED for the whole certificate. `remediation.py` already classified it under `_UNRESOLVABLE_GATES` and assigned no action. However, `nuri/core/rules.py::_load_rules` **silently** fell back to a 3-section hardcoded fallback when the file was missing — that fallback is exactly what this gate caught. The backend PR removes the fallback and turns a missing file into an exception at startup — removal done (#1619, `_load_rules` raises `FileNotFoundError`). |
| `data_fresh` (warning) | Replaced | `nuri/core/freshness.py` SLA (`config/freshness.yaml`, the dashboard verdict stale gate). The freshness-tracked ticker list moves from `siege_gates.asset_classes.*.freshness_*` to a neutral key. |
| `volatility_gate` (warning) | Retired | No replacement. The brief indicators and MCP `macro_facts` continue to report the VIX facts. |
| `external_data` (warning) | Retired | No replacement. |
| `conflict_free` (warning) | Retired | Only the gate is retired. `recommend/candidates.py` continues to use `engine/conflicts.py`. |
| `drift_safe` (warning) | Retired | Only the gate is retired. |
| `macro_event_alignment` (warning) | Retired | No replacement. |
| `regime_overrides` (regime multiplier for weight limits) | Retired | Its only reader was `certification.py`. `nuri/quant/exits/atr.py` merely uses the same **pattern** and does not read this key. |

### What stays and what moves

- **The `certifications` table stays** — migrations are forward-only. It is a historical record whose writing code is gone, and the description of the score time-series boundary in §2.6 is kept as an explanation of that record.
- **`asset_class_rules`** is not SIEGE's: it is the canonical benchmark classification for measurement mode (§3.11) (`forward_outcome_tracker` · `strategic_allocation`). PR 2 moved it to a top-level key outside `siege_gates`, and moved the classifier to `nuri/core/asset_class.py`. Deleting it would silently contaminate the pre-registered alpha measurement. The cleanup PR moved the freshness-tracked tickers to `freshness_tickers` (read by `collectors/stock.py` · `alerts/data_sanity.py`).
- **The Stage 4 boundary stays; the name changes.** The `decisions.py` · `gate.py` · `amplifier_gate.py` · `conflicts.py` · `memory.py` · `thesis_criteria.py` that remain in `nuri/trading/engine` are the decision record, the data-readiness gate, the §2.6 amplifier shadow and their helpers, not a certifier. With the certificate writer gone, `certify` is a false name, so a follow-up PR renamed it to `decide`, and §2.3 · `invariants.md` · `AGENTS.md` · `pipeline.py` · `events.py` · the cross-import test moved with it. Past rows in `pipeline_events` keep `certify` as-is. `certify_position()` in `nuri/trading/strategy/position.py` is the paper `positions` table's own gate, unrelated to the certifier, and outside the scope of the rename.
- **The audit tools are pinned to a revision.** The last revision of `scripts/analysis/siege_predictivity_audit.py` and the `/nuri-siege-audit` skill is `d8a89ede` (main, 2026-10-06). If §3.8 needs to be re-run, retrieve them with `git show d8a89ede:<path>`.
- **The backend PR deleted the `certification` policy in `nuri/core/freshness.py` (`config/freshness.yaml` warn 24h / fail 48h).** It is not in `verdict_gate`, so the dashboard verdict is unaffected, but `get_freshness_summary` iterates over every policy and `premarket_brief._brief_color` returns RED if there is even one FAIL — from 48 hours after writes stop, every brief becomes permanently RED with "Certification FAIL". Even if the frontend is detached first, this policy was removed in **the same PR** that cut the calls to the certifier.
- **The regime in MCP `macro_facts`** now reads from `candidate_runs.regime` (daily, a Tier-1 allowed column) instead of `certifications.regime` — continuing to read a table whose writes have stopped silently freezes the value (the same shape as #1617).

**No replacement gate is built.** If a portfolio-level verdict becomes necessary again, do not copy SIEGE's shape; start from a STRATEGY PR that pre-registers the verdict criteria, following the §3.6 precedent.

## 7. Work policy

The operational backlog (Tier 1/2/3) is in `docs/TODO.md`. STRATEGY holds only **policy that does not change**. When a new session starts: `NEXT_SESSION.md` → `docs/TODO.md`.

### 7.1 Automated trading — permanently deferred (user opt-out)

| Item | Issue | Reason for the decision |
|------|------|---------|
| Alpaca live trading (Paper → Live) | [#17](https://github.com/researcherhojin/nuri-quant/issues/17) | **Permanently on hold**. User decision of 2026-04-11 — accountability for losses from automated trading. Prevents blurring the boundary between system recommendations (probabilistic) and actual trades (deterministic). |
| KIS Open API trading endpoint | — | **Permanently on hold** (same reason). The `kis_realtime.py` **read** endpoint (balance/price/drift) is kept. |

**Principle**: the system only recommends and alerts. The user places actual orders manually in the brokerage app. `DryRun` / paper trading are kept for backtesting/verification. Reversing this requires a STRATEGY revision PR + re-approval.

### 7.2 Work rules (PR discipline)

- 1 issue = 1 PR, ≤ 3 commits
- New finding → a separate issue; do not bundle it into the same PR
- Do not skip Tiers (close Tier 1 before starting Tier 2)
- Update `docs/TODO.md` alongside; an issue number is required

## 8. Open-source references

### Investment theory

| Source | Application | Location |
|---|---|---|
| O'Neil, *CAN SLIM* | Stop-loss -7%, take-profit +20%/+40%, 8-week hold | `config/rules.yaml` |
| Minervini, *SEPA* | Trailing -15%, 3:1 reward-to-risk ratio | `config/rules.yaml` |
| Shefrin & Statman 1985 | Disposition-effect warning | Basis for the take-profit rule |

### Architecture/engine

| Source | Application | Location |
|---|---|---|
| SIEGE Engine (`nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution`) | Gate-based certification, event journal (external v1; this project's v2 asset-class expansion) — **removed by #1619** (disposition table in §6; the original repo returns 404) | — |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, Decision Intelligence (#178) | `nuri/core/freshness.py`, `events.py`, `decisions` |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA | `nuri/core/freshness.py` |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent consensus | `nuri/trading/agents/` |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | Risk Parity | `nuri/analysis/rebalance.py` |
| [López de Prado](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086) | Walk-forward · permutation-test null-safe gate (#701/#702) | `nuri/quant/validation/strategy_walkforward.py` |

### UX

| Source | Reference |
|---|---|
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | Minimal dashboard, progressive disclosure |
| [React Flow](https://reactflow.dev/) | Pipeline DAG |
| [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) | Backtest signal markers |
