# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Nuri-Quant (누리퀀트) — Open-source quant investment platform. Python 3.12 / `uv` / SQLite / 100% free OSS stack. Canonical pipeline: **Collect → Analyze → Consensus → Certify → Track**. 2-machine setup: M5 Max MacBook (dev) ↔ M2 Pro Mac mini (24/7 production).

**Session start**: read `NEXT_SESSION.md` first (gitignored) — carries previous session's checklist + next work item, supersedes stale "next task" recall.

## Working Style — Karpathy 4 + nuri 7 (§5.8)

LLMs fail systematically — these behavior cues catch failure BEFORE hooks/CI fire. [Karpathy's 4 principles](https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md) frame nuri's 7 mechanical sub-rules.

**1. Think before coding** — state assumptions explicitly. If uncertain, **ask** (don't guess UI flows, function signatures, API behavior). Multiple interpretations? **Present them**, don't pick silently. Simpler approach exists? Surface it; push back when warranted.
- *모르면 읽는다* — grep/Read function signatures + source before calling. No hallucinating parameter names.
- *외부 API는 측정한다* — concurrency / rate-limit / timeout probe before parallelizing (yfinance 10-thread OK ≠ KRX 10-thread OK).

**2. Simplicity first** — minimum code that solves the asked problem. **No** speculative features, configurability, abstractions for single-use code, or error-handling for impossible scenarios. 200 lines that should be 50 → rewrite. Senior-engineer test: "Is this overcomplicated?" → if yes, simplify.

**3. Surgical changes** — touch only what the user asked. **Don't** "improve" adjacent code, comments, formatting. Match existing style even if you'd do it differently. Notice unrelated dead code → mention it, don't delete it. Every changed line traces directly to the user's request.
- *스코프를 지킨다* — 1 issue = 1 PR, ≤ 3 commits. New finding → separate issue. Never bundled.
- *숫자를 grep한다* — when changing count/version/threshold, `grep -ri "old_value"` first. `make verify-doc-counts` catches drift in CI.

**4. Goal-driven execution** — define verifiable success criteria, loop until met. Multi-step task → state plan as `1. step → verify: check / 2. ...` BEFORE starting. "Make it work" is not a criterion.
- *사용자 워크플로로 검증한다* — mock test ≠ verification. Run `make X --flag` directly before claiming ship-ready (Mock-only ship 함정 3회 반복 후 추가, 2026-04-14).
- *2번 실패하면 접근을 바꾼다* — same approach 3 times = stop, reframe (root cause is usually the premise, not the impl).
- *시스템이 차단한다* — ruff / hooks / CI / SIEGE do mechanical work; don't substitute "I checked" for those gates.

**Working ✅**: clarifying questions before mistakes; fewer unnecessary lines per diff; explicit "I assume X — confirm?" before non-trivial work.
**Working ✗**: silent assumptions on UI / API; "I'll just refactor while I'm here"; pushing recommendations without showing tradeoffs; scope creep dressed as "while we're at it".

## Always-on Invariants

These are mechanically enforced (hooks/CI/code). Violating any means a hook block, CI fail, or design regression. STRATEGY.md is canonical — load it on demand for the "why" / full spec.

- **DB sole importer**: `nuri/core/db.py` is the ONLY `sqlite3` importer (PreToolUse hook blocks). All other modules use `query()` / `query_df()` / `upsert_*()` / `get_db()` with optional `db_path=` for test isolation.
- **Timezone**: always `kst_now()` / `today_kst()` from `nuri.core.timezone` — `datetime.now()` blocked by hook.
- **Conventional commits (English)** + **PR discipline**: 1 issue = 1 PR, ≤ 3 commits, scope = what was asked. New findings → separate issue. Format: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: msg`. Korean comments in code, English variable/function names.
- **Escalation Ladder** (§2.6 summary): **Surface** exposes evidence only (no action change) → **Soft penalty** deterministic downgrade/cap (config-tunable) → **Hard veto** action-block on downside (risk-of-ruin) → **Symmetric amplifier** post-veto upside sizing (multi-condition, never single-trigger). Promotion between rungs requires STRATEGY PR + evidence/backtest.
- **Alpha vs portfolio axis** (PR A #429): `alpha_action ∈ {LONG, SHORT, FLAT}` ≠ `portfolio_action ∈ {REBALANCE, TRIM, HEDGE}`. Concentration / sector-cap → `portfolio_action=REBALANCE` only (never urgent SELL). Stop-loss breach is the **only** mechanical → `alpha_action=FLAT`. Veto fires on `alpha_action==FLAT`, not portfolio violations. See `nuri/core/axis.py`.
- **Auto trading deferred** (§7.1, permanent): system emits recommendations + alerts only; user executes orders manually. `DryRun` / paper trading kept for backtest only. Reverting requires STRATEGY PR + re-approval.
- **Privacy in commits** (§4.4.1, hook + CI blocked): personal financial data must never enter the public repo. `scripts/check_privacy_leak.py` (canonical rule list) runs pre-push and in CI `privacy-scan`, blocking 4 categories — Korean broker names, romanized broker substrings, suspect 7+ digit monetary literals near sensitive keys (`total_invested` / `cash_balance` / etc), and ticker+signed-% combinations. Use placeholders (`Brokerage Alpha/Beta`, round-million values). When documenting the rule itself, reference the scanner — never inline the patterns it blocks.

### Gotcha-Test Pair (§5.3.1)

Every fix-pattern gotcha (saved defensive code) MUST cite a regression test (`**Test:** path::TestClass::test_name`) that fails if the fix is reverted. Otherwise it's "folklore" — defensive code gets removed in 3 sessions when nobody remembers why (e.g., `df.copy()` recurrence, PR #294→#306). Plain facts/quirks (*"library X doesn't support Y, no fix"*) need no test, mark as `*(facts, no fix)*`.

## Load Triggers (read these BEFORE editing scoped files)

| Working on... | Read first |
|---------------|-----------|
| `nuri/core/` (db, timezone, events, freshness) | `nuri/core/CLAUDE.md` |
| `nuri/collectors/` (data sources) | `nuri/collectors/CLAUDE.md` + `docs/STRATEGY.md §4.4` (privacy / external LLM egress) |
| `nuri/trading/agents/` (consensus / veto) | `nuri/trading/agents/CLAUDE.md` + `docs/STRATEGY.md §3.2-§3.3, §3.9` |
| `nuri/trading/engine/` (SIEGE) | `nuri/trading/engine/CLAUDE.md` + `docs/SIEGE_V2.md` + `docs/STRATEGY.md §6` |
| `nuri/trading/recommend/` (BUY/SELL emitters, price targets, tracker) | `nuri/trading/recommend/CLAUDE.md` + `docs/STRATEGY.md §7.1` (recommend-only, never execute) |
| `nuri/trading/swing/` (≤7d swing scanner / rules) | `nuri/trading/swing/CLAUDE.md` + `config/rules.yaml` swing ladder |
| `nuri/trading/strategy/` (longshort, mean-rev, pairs, position) | `nuri/trading/strategy/CLAUDE.md` — `REGIME_ALLOCATION` lives in `longshort.py` (not config); changes require STRATEGY PR + backtest |
| `nuri/trading/execution/` (broker adapter) | `nuri/trading/execution/CLAUDE.md` — paper-only (Alpaca paper endpoint), live execution out of scope per §7.1 |
| `config/rules.yaml`, `config/agents.yaml`, `config/signals.yaml` | `config/CLAUDE.md` + `docs/STRATEGY.md §2.6, §3.4-§3.5` |
| `frontend/` | `frontend/CLAUDE.md` (Next.js 16 breaking changes — read `node_modules/next/dist/docs/` first) |
| `tests/` | `tests/CLAUDE.md` (DB isolation, mock pitfalls, privacy in fixtures) |
| `nuri/api/` (FastAPI routes) | `docs/ARCHITECTURE.md` §"Dashboard API" + this file's "API Access Pattern" + source convention from existing `nuri/api/routes/` |
| `scripts/` (shell automation, no scoped CLAUDE.md) | source docstring; `make lint-sh` (shellcheck); `scripts/pre_push_check.sh` for safety contract |
| DB migrations / schema changes | `nuri/core/CLAUDE.md` + `_MIGRATIONS` list in `nuri/core/db.py` (forward-only, never edit existing migration) |
| Investment-rule / strategy / regime decisions | `docs/STRATEGY.md` §2 (principles) + §3 (decisions) |
| Harness debugging (mock fail / phantom fix / scope creep) | `/nuri-harness-debug` skill + `docs/STRATEGY.md §5` |
| SIEGE predictivity audit / E4-0b methodology | `/nuri-siege-audit` skill + `docs/STRATEGY.md §3.8` |
| Pipeline backlog / next work | `docs/TODO.md` (forward-only — Tier 2 next, Tier 3 research) |

**Precedence on conflict**: repo truth (code/config) > `NEXT_SESSION.md` > auto-memory. If recalled memory contradicts what you read now, trust the code and update the stale memory. Historical commits → `git log` (do not re-document in markdown).

## Flow (Think → Plan → Build → Review → Test → Ship → Reflect)

`docs/STRATEGY.md §2.7` is canonical. 7 phases, no skipping. Failed gate → regress prior phase. Trivial chores may inline Think+Plan; Build onward is mandatory. Codex unavailable → self-review + recover in next PR.

| # | Phase | Output gate (must answer YES to advance) |
|---|-------|-----------------------------------------|
| 1 | **Think** | Can I state "왜 지금" in 1 sentence? Literature / root-cause checked? |
| 2 | **Plan** | Scope unchanged from issue? 1 PR / ≤ 3 commits? Escalation Ladder rung named? |
| 3 | **Build** | No hardcoded values (config/yaml-driven)? Hook + lint pass? `kst_now()` only? |
| 4 | **Review** | Codex `/codex review` + Claude self-review. P1 all resolved? Codex unavailable → self-review + recover next PR |
| 5 | **Test** | `make test-fast` green + at least 1 user-workflow live execution? UI → browser QA |
| 6 | **Ship** | `gh pr merge --squash --delete-branch`. Issue closed. Branch cleaned. TODO Tier 2 / 3 updated if scope shifted |
| 7 | **Reflect** | NEXT_SESSION refreshed. New gotcha → Gotcha-Test Pair (§5.3.1) cite. Memory updated if surprising |

## Commands + Architecture

`make help` for full target inventory. Daily essentials: `make setup` (1회) → `make quick-scan` (~2분 4-step) / `make full-scan` (8-phase + SIEGE) / `make consensus` / `make buy-candidates` / `make thesis ticker=<T>` / `make earnings-preview ticker=<T>`. Lint+test: `make lint` / `make test-fast` / `.venv/bin/python -m pytest <path>::<test> -v`. Deploy: `make start` (API :8001 + Dashboard :3000) / `make deploy-mini` (MBP → Mac mini 6단계). Frontend-only commands → `frontend/CLAUDE.md`.

Code layout: `nuri/core` (sole sqlite3 importer) / `nuri/collectors` (26 collector modules) / `analysis` / `quant` / `trading` (agents · engine · strategy · recommend · swing · execution) / `api` (69 endpoints, routes/) / `alerts` / `llm`. Plus `tests/` mirror + `scripts/` automation + `frontend/` (Next.js). Detailed map (DB schema, migrations, env vars, CI/CD): `docs/ARCHITECTURE.md`.

## API Access Pattern (frontend)

- **Server Components**: `fetchAPI("/api/...")` from `@/lib/api` (absolute, server-to-server)
- **Client Components**: `fetch("/api/...")` (relative, proxied by Next.js `rewrites` in `next.config.ts`)
- **Never** `${API_BASE}/api/...` in Client Components — breaks on network access (CORS/CSP)

Backend: FastAPI on `:8001`. Frontend: Next.js on `:3000`. Next.js proxies `/api/*` to backend.

## Mechanical Enforcement

Hook config: `.claude/settings.json`. CI workflows: `.github/workflows/main-ci-cd.yml`. Pre-push: `scripts/pre_push_check.sh`.

**PreToolUse hook** blocks: `import sqlite3` outside `db.py`, `git push --force` / `reset --hard` / `clean -f`, privacy ticker+PnL inline writes (`scripts/check_privacy_leak.py --message --quiet`). **PostToolUse**: `datetime.now()` block (exit 1 surfaces to Claude), ruff advisory. **CI gates** (every PR): `privacy-scan`, `pr-discipline` (commits ≤ 3 — escape `scope-expand-approved` label), test regression + Codecov 1% relative, `security-scan` (Trivy CRITICAL), `Doc Count Drift Check` (`make verify-doc-counts`).

## .claude/ (4-Layer Architecture, STRATEGY §5.10)

L1 CLAUDE.md (12 scoped + global) → L2 Skills (`.claude/skills/nuri-*/`, 6) → L3 Hooks (`.claude/settings.json` PreToolUse + PostToolUse) → L4 Agents (`.claude/agents/nuri-*.md`, 2). Slash commands: `.claude/commands/nuri-*.md` (8). `nuri-` prefix 만 git tracked — 머신별 개인 설치는 `.gitignore` 로 자동 ignored.

## Gotchas

Most gotchas live in scoped CLAUDE.md or in code lock-tests (Gotcha-Test Pair). Cross-scope ones:

- **fastapi < 0.129 pinned** (`openbb-core 1.6.7` constraint, dependabot.yml ignores 0.129+)
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS`). yfinance returns most fundamentals but **`trailingPE` is missing for KR individuals** — use `forward_pe`. ETFs return empty `info`. Full quirks: `nuri/collectors/CLAUDE.md` "Korean Ticker `.KS` Suffix Convention".
- **Concurrency asymmetry**: yfinance 10-thread OK; pykrx/KRX **must be sequential** + `time.sleep(0.1)`. New external APIs require concurrency measurement before integration.

For framework / test-mocking / data-source / pipeline-policy gotchas → scoped CLAUDE.md or `/nuri-harness-debug` skill.

## Reference

- `docs/STRATEGY.md` — canonical policy (load on demand): 8 sections + §5.10 frontier alignment
- `docs/SOURCE_OF_TRUTH.md` — file-ownership map (consult before adding/de-duplicating any doc fact)
- `docs/ARCHITECTURE.md` — code/DB layout (env vars, CI/CD, schema)
- `docs/OPERATIONS.md` — operator runbook (2-machine deploy / scheduler / recovery)
- `docs/TODO.md` (gitignored) — forward-only backlog
- `docs/SIEGE_V2.md` — 3D certification spec
- `docs/KIS_INTEGRATION.md` — KIS Open API integration
- `AGENTS.md` — **cross-tool** rules (Cursor / Copilot / Codex CLI), not auto-loaded by Claude Code. `.claude/agents/` 와 별개 메커니즘 — 이름 비슷해도 혼동 금지
- `docs/HARNESS_AUDIT.md` — 하네스 감사 보고서 (매 audit overwrite, 이력은 git log)
- `NEXT_SESSION.md` (gitignored) — handoff (read first per session)
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/` — user-scoped auto-memory
