# Source of Truth Map

**Goal**: each operational/policy fact lives in **one canonical file**. Other files may carry a short pointer or summary, but never re-state the canonical content. This map exists to make drift-prevention mechanical: when changing a fact, you update one file, and reviewers can verify nothing else needs touching.

This file is referenced by `CLAUDE.md` and `AGENTS.md`. It is **not** auto-loaded; consult before:
- Adding a new fact / policy ("where does this go?")
- De-duplicating across files (PR 3 / PR 4 of doc refactor sequence)
- Reviewing a doc-touching PR ("did the author update the canonical source AND remove old copies?")

## Convention

- **Canonical**: the single authoritative location. Edits land here. Other files MUST link/summarize, never repeat. **Split-canonical** is allowed when one file owns the data and another owns the rationale (e.g., `config/rules.yaml` holds the values, `docs/STRATEGY.md §3.4` explains *why*) — or when policy lives in markdown but implementation lives in code (e.g., `STRATEGY.md §4.4.1` policy, `scripts/check_privacy_leak.py` pattern list). Each split fragment owns a distinct aspect; edits to one DO require updating the other when meanings shift, but day-to-day tweaks are local. Pure prose-duplication is never canonical.
- **Acceptable summary**: short paraphrase (max 2 sentences) for always-on context (e.g., root `CLAUDE.md` invariants block). Must explicitly link the canonical source. Edits propagate from canonical.
- **Forbidden duplication**: places where the fact must NOT be re-stated.

If a row's "Forbidden" column lists a file you're editing, you've found duplication that needs cleanup — open a separate issue or include in the next dedup PR.

## Policy & Decisions

| Fact / Policy | Canonical | Acceptable summary in… | Forbidden in… |
|---------------|-----------|------------------------|---------------|
| Investment rules (stop-loss / take-profit / trailing) | `config/rules.yaml` (data) + `docs/STRATEGY.md §3.4` (rationale) | `config/CLAUDE.md` (account profile pointer); `README.md` (1-paragraph public summary) | `CLAUDE.md`, scoped CLAUDE.md (use config + STRATEGY pointer instead) |
| Account strategy profiles (core / active / swing / long_term / pension) | `config/rules.yaml account_strategies` (data) + `docs/STRATEGY.md §3.5` (rationale) | `config/CLAUDE.md` (1-line pointer) | `CLAUDE.md`, `README.md` operational details |
| Escalation Ladder (Surface / Soft penalty / Hard veto / Symmetric amplifier) | `docs/STRATEGY.md §2.6` | `CLAUDE.md` Always-on Invariants (1-paragraph summary) | scoped CLAUDE.md (link to STRATEGY only) |
| 7-phase Flow gates (Think → Plan → Build → Review → Test → Ship → Reflect) | `docs/STRATEGY.md §2.7` | `CLAUDE.md` Flow section (gate table) | `AGENTS.md` (1-line pointer only) |
| 7 Harness Principles (§5.8) | `docs/STRATEGY.md §5.8` | `CLAUDE.md` Always-on (verbatim — intentional duplication for context-stability per 2026-04-29 user directive); `.claude/skills/nuri-harness-debug/SKILL.md` (7-원칙 요약 본문 인용) | scoped CLAUDE.md, `AGENTS.md` (link only) |
| Harness LLM 실패 case studies (Mock-only ship / JKHY 에피소드 등 narrative) | `docs/HARNESS.md` | `.claude/skills/nuri-harness-debug/SKILL.md` 의 "Case Studies — `docs/HARNESS.md` 참조" pointer | skill 본문에 case study narrative 인라인 금지 (drift risk) |
| Harness audit snapshot (revfactory 6 패턴 매핑 + spec compliance) | `docs/HARNESS_AUDIT.md` (single canonical, 매 audit overwrite — 이력은 git log) | `.claude/skills/nuri-flow/SKILL.md` (P1-1 origin pointer); `CLAUDE.md` (audit reference 줄) | docs/audits/{date}.md 분리 (audit이 정기화될 때만 재고) |
| Gotcha-Test Pair principle (§5.3.1) | `docs/STRATEGY.md §5.3.1` + `/nuri-harness-debug` skill | `CLAUDE.md` Always-on (rule statement + format) | scoped CLAUDE.md (cite via `**Test:**` per gotcha entry, no rule restatement) |
| Privacy enforcement (broker names, monetary literals, ticker+PnL) | `docs/STRATEGY.md §4.4.1` (policy) + `scripts/check_privacy_leak.py` (canonical pattern list) | `CLAUDE.md` Always-on (1-line pointer to scanner); Mechanical Enforcement table (1-line) | `tests/CLAUDE.md` (placeholder convention OK; no pattern enumeration) |
| External LLM egress (whitelist + Tier 0/1/2) | `docs/STRATEGY.md §4.4.3` + `nuri/llm/openai_client.py` (gateway) | `CLAUDE.md` (no entry needed); `AGENTS.md` (1-line "use the gateway") | anywhere else (direct `import openai` is hook-rejected) |
| Auto trading deferral (§7.1 permanent) | `docs/STRATEGY.md §7.1` | `CLAUDE.md` Always-on (1-line); `AGENTS.md` (1-line); `README.md` (public statement) | scoped CLAUDE.md (no relevance there) |

## Architecture & Engine

| Fact | Canonical | Acceptable summary in… | Forbidden in… |
|------|-----------|------------------------|---------------|
| SIEGE gate spec (v2 — asset-class per-expansion) | `docs/SIEGE_V2.md` (full spec) + `docs/STRATEGY.md §6` (canonical condition table) | `nuri/trading/engine/CLAUDE.md` (per-condition implementation pointer) | `CLAUDE.md` root, `README.md` (point to STRATEGY §6 / SIEGE_V2 only) |
| Confidence scoring formula | `docs/STRATEGY.md §3.3` (formula + multipliers) | `nuri/trading/engine/CLAUDE.md` (operational pointer) | `CLAUDE.md` root, `nuri/trading/agents/CLAUDE.md` (link only) |
| 10-agent consensus + risk-agent veto | `docs/STRATEGY.md §3.2` (architecture) + `nuri/trading/agents/CLAUDE.md` (impl details) | — | `CLAUDE.md` root (use Load Triggers row instead) |
| Alpha vs portfolio action axes (PR A #429) | `nuri/core/axis.py` (helpers) + `docs/STRATEGY.md §3.7` (rationale) | `CLAUDE.md` Always-on (1-paragraph); `AGENTS.md` (1-paragraph) | scoped CLAUDE.md (use axis.py helpers directly) |
| DB sole-importer rule | `nuri/core/db.py` (implementation) + `nuri/core/CLAUDE.md` (interface contract) | `CLAUDE.md` Always-on (1-line); `AGENTS.md` (1-line); Mechanical Enforcement table | nowhere else — hook blocks |
| Timezone (`kst_now()` / `today_kst()`) | `nuri/core/timezone.py` (implementation) + `nuri/core/CLAUDE.md` (interface) | `CLAUDE.md` Always-on (1-line); `AGENTS.md` (1-line) | nowhere else — hook blocks `datetime.now()` |
| 5-step pipeline coupling (DB-only between phases) | `docs/ARCHITECTURE.md` Pipeline Phases | `CLAUDE.md` (1-paragraph project intro); `AGENTS.md` (1-paragraph) | repeating phase-by-phase contracts elsewhere |
| 5-step canonical naming (`collect → analyze → consensus → certify → track`) | `README.md` Architecture (public-facing canonical) + `docs/ARCHITECTURE.md` Pipeline Phases (technical pairing with 8-phase operational view) | `CLAUDE.md` project intro (1-line); `AGENTS.md` Project (1-paragraph) | drift between 5-step and 8-phase mapping must be explicit, not silent |

## Reference & Operational

| Fact | Canonical | Acceptable summary in… | Forbidden in… |
|------|-----------|------------------------|---------------|
| Korean ticker `.KS` suffix convention | `nuri/collectors/CLAUDE.md` (data quirks) | `CLAUDE.md` Gotchas (1-line); `README.md` Tech Stack (1-line) | `docs/STRATEGY.md`, `docs/ARCHITECTURE.md` (collectors handle this) |
| KIS Open API integration (endpoints, gotchas) | `docs/KIS_INTEGRATION.md` (full integration) + `nuri/collectors/CLAUDE.md` (collector-side quirks) | `CLAUDE.md` Gotchas (1-line on TIME LIMIT only) | scoped CLAUDE.md outside `nuri/collectors/`, `docs/STRATEGY.md` (link only) |
| 2-machine deploy (MBP dev ↔ Mac mini receiver) | `docs/OPERATIONS.md` (canonical — topology, deploy_mini 6-step, scheduler control, recovery) | `CLAUDE.md` Commands section (`make` targets only); `README.md` Production deployment (1-line + link) | scoped CLAUDE.md, `docs/ARCHITECTURE.md` (operator content moved to OPERATIONS.md) |
| Mechanical Enforcement (hooks + CI rules) | `.claude/settings.json` (hooks) + `.github/workflows/main-ci-cd.yml` (CI) + `CLAUDE.md` Mechanical Enforcement table (consolidated reference) | — | restating individual rules elsewhere — point to CLAUDE.md table |
| Test conventions (DB isolation, mocks, privacy in fixtures) | `tests/CLAUDE.md` | `CLAUDE.md` Load Triggers row (pointer) | `docs/STRATEGY.md` (link only — §4.1 quality bar lives there, conventions don't) |
| Backlog / next work (Tier 2 / Tier 3) | `docs/TODO.md` | — | restating planned work in `CLAUDE.md` / `STRATEGY.md` |
| Session handoff state + cold-start checklist | `NEXT_SESSION.md` (gitignored, personal) | — | committing handoff state to public docs |
| Plan / spec drafts (split-canonical: design lives here, policy in STRATEGY.md) | `docs/plans/*.md` (gitignored 통합 — 2026-04-30 Session 8) | `docs/STRATEGY.md` 1-line decision capture only | restating spec body in public docs (broker name / financial figure 누설 위험) |
| BUY candidate emit baseline + tier validation ledger | `data/reports/buy_tracking/candidate_ledger.jsonl` (gitignored, append-only) + `scripts/compare_buy_candidates.py` (tracked infra) | `docs/STRATEGY.md §5.13` (mechanism + acceptance only) | restating ledger row counts elsewhere |
| LLM consult archives (codex / Qwen review of specs) | `data/llm_consults/<date>_<slug>.md` (gitignored) | `docs/STRATEGY.md` 또는 spec 내 1-line reference + verdict (GO/REFINE/STOP) | restating consult body in spec or commit message |
| `fastapi <0.129` pin (openbb-core 1.6.7 constraint) | `pyproject.toml` (constraint) + `dependabot.yml` (auto-ignore 0.129+) | `CLAUDE.md` Gotchas (1-line) | restating elsewhere — pyproject is the canonical pin |
| OpenBB upstream `OBBject_*` ImportError + yfinance fallback (#274/#349/#351) | `nuri/collectors/CLAUDE.md` Data source quirks (canonical narrative) + `nuri/collectors/<module>.py` (`try/except` fallback site) | `CLAUDE.md` Gotchas reference (1-line); `docs/STRATEGY.md §5` (failure-pattern catalog) | restating per-endpoint elsewhere — collectors module owns failure narrative |

## When you find duplication

1. Confirm the row in this map identifies which file is canonical.
2. If the duplicated copy is a permitted "summary", verify it links to canonical and is ≤ 3 lines.
3. If it's "forbidden", open an issue tagged `doc-dedup` and either fix in current PR (if scope allows) or queue for the next dedup batch.
4. If the fact isn't in this map, it's either (a) genuinely scoped to one file (no duplication risk yet — leave it), or (b) about to drift across files (add a row here in the same PR).

## Maintenance

- This map updates with every doc refactor PR (R3 / R4 / R5 of the 5-PR sequence).
- New canonical file? → add a row.
- Canonical move (e.g., split STRATEGY.md)? → update the row + every "Acceptable summary" location in the same PR.
- Phrase-level lint enforcement is **deferred** — codex Plan consult (2026-04-29) recommended explicit map over phrase-grep ("phrase blocking is brittle and noisy"). Reference checks (cross-doc link integrity) acceptable later.
