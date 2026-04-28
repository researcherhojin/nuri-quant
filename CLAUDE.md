# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Nuri-Quant (누리퀀트) — Open-source quant investment platform. Python 3.12 / `uv` / SQLite / 100% free OSS stack. Canonical pipeline: **Collect → Analyze → Consensus → Certify → Track**. 2-machine setup: M5 Max MacBook (dev) ↔ M2 Pro Mac mini (24/7 production).

**Session start**: read `NEXT_SESSION.md` first (gitignored) — carries previous session's checklist + next work item, supersedes stale "next task" recall.

## Always-on Invariants

These are mechanically enforced (hooks/CI/code). Violating any means a hook block, CI fail, or design regression. STRATEGY.md is canonical — load it on demand for the "why" / full spec.

- **DB sole importer**: `nuri/core/db.py` is the ONLY `sqlite3` importer (PreToolUse hook blocks). All other modules use `query()` / `query_df()` / `upsert_*()` / `get_db()` with optional `db_path=` for test isolation.
- **Timezone**: always `kst_now()` / `today_kst()` from `nuri.core.timezone` — `datetime.now()` blocked by hook.
- **Conventional commits (English)** + **PR discipline**: 1 issue = 1 PR, ≤ 3 commits, scope = what was asked. New findings → separate issue. Format: `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(scope)?: msg`. Korean comments in code, English variable/function names.
- **Escalation Ladder** (§2.6 summary): **Surface** exposes evidence only (no action change) → **Soft penalty** deterministic downgrade/cap (config-tunable) → **Hard veto** action-block on downside (risk-of-ruin) → **Symmetric amplifier** post-veto upside sizing (multi-condition, never single-trigger). Promotion between rungs requires STRATEGY PR + evidence/backtest.
- **Alpha vs portfolio axis** (PR A #429): `alpha_action ∈ {LONG, SHORT, FLAT}` ≠ `portfolio_action ∈ {REBALANCE, TRIM, HEDGE}`. Concentration / sector-cap → `portfolio_action=REBALANCE` only (never urgent SELL). Stop-loss breach is the **only** mechanical → `alpha_action=FLAT`. Veto fires on `alpha_action==FLAT`, not portfolio violations. See `nuri/core/axis.py`.
- **Auto trading deferred** (§7.1, permanent): system emits recommendations + alerts only; user executes orders manually. `DryRun` / paper trading kept for backtest only. Reverting requires STRATEGY PR + re-approval.
- **Privacy in commits** (§4.4.1, hook + CI blocked): personal financial data must never enter the public repo. `scripts/check_privacy_leak.py` (canonical rule list) runs pre-push and in CI `privacy-scan`, blocking 4 categories — Korean broker names, romanized broker substrings, suspect 7+ digit monetary literals near sensitive keys (`total_invested` / `cash_balance` / etc), and ticker+signed-% combinations. Use placeholders (`Brokerage Alpha/Beta`, round-million values). When documenting the rule itself, reference the scanner — never inline the patterns it blocks.

### Harness Engineering — 7 Principles (§5.8)

This project's primary developer is an LLM (Claude Code). LLMs fail systematically. These rules are how we enforce non-failure. Most are mechanically enforced (hooks/CI); a few are self-enforced.

1. **모르면 읽는다** — assume nothing. Grep function signatures / class definitions before calling. No hallucinating parameter names.
2. **2번 실패하면 접근을 바꾼다** — same approach 3 times = stop. Reframe — root cause is usually the premise, not the impl detail.
3. **사용자 워크플로로 검증한다** — mock test ≠ verification. Run `make X --flag` directly before claiming ship-ready (Mock-only ship 함정 3회 반복 후 추가, 2026-04-14).
4. **스코프를 지킨다** — 1 issue = 1 PR, ≤ 3 commits. New finding → separate issue. Never bundled.
5. **숫자를 grep한다** — when changing count/version/threshold, `grep -ri "old_value"` to catch all references. `make verify-doc-counts` enforces drift check on each PR.
6. **시스템이 차단한다** — ruff / hooks / CI / SIEGE gates do mechanical work. Don't rely on documentation reminders.
7. **외부 API는 측정한다** — yfinance 10-thread OK ≠ KRX 10-thread OK. Probe concurrency / timeout / rate-limit before parallelizing.

### Gotcha-Test Pair (§5.3.1)

**Every fix-pattern gotcha** (saved defensive code) MUST cite a regression test:

```
**Test:** path/to/test_file.py::TestClass::test_name
```

…that fails if the fix is reverted. Otherwise it's "folklore" — defensive code gets removed in 3 sessions when nobody remembers why (e.g., `df.copy()` recurrence, PR #294→#306). Plain facts/quirks (*"library X doesn't support Y, no fix"*) need no test, but mark as `*(facts, no fix)*`.

## Load Triggers (read these BEFORE editing scoped files)

| Working on... | Read first |
|---------------|-----------|
| `nuri/core/` (db, timezone, events, freshness) | `nuri/core/CLAUDE.md` |
| `nuri/collectors/` (data sources) | `nuri/collectors/CLAUDE.md` + `docs/STRATEGY.md §4.4` (privacy / external LLM egress) |
| `nuri/trading/agents/` (consensus / veto) | `nuri/trading/agents/CLAUDE.md` + `docs/STRATEGY.md §3.2-§3.3, §3.9` |
| `nuri/trading/engine/` (SIEGE) | `nuri/trading/engine/CLAUDE.md` + `docs/SIEGE_V2.md` + `docs/STRATEGY.md §6` |
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

## Commands

```bash
# Setup (Python 3.12, uv, brew install ta-lib, Node 22 for frontend)
make setup                              # venv + deps (--extra dev) + DB init + portfolio import
cd frontend && npm ci                   # frontend deps (separate from make setup)
uv sync --extra dev                     # manual: install with test/lint tools

# Data collection
make collect                            # Phase A daily collectors
make collect-kis                        # KIS Open API 실시간 잔고/시세
make collect-kis-check                  # KIS 연결 상태 확인
python -m nuri.collectors.stock --period 5y          # US stocks 5Y (OpenBB)
python -m nuri.collectors.stock_kr --days 1825       # Korean stocks 5Y (pykrx)
python -m nuri.collectors.fundamental                # PE/ROE/margins
python -m nuri.collectors.superinvestors             # 13F (edgartools)
python -m nuri.collectors.estimates                  # Analyst consensus
make wallstreet                         # ratings, earnings, insider
make filings                            # SEC filings

# Universe (#272)
make universe-sync / universe-sync-us / universe-sync-kr / universe-sync-apply
make collect-universe                   # ALL universe data (US+KR)
make verify-universe-sync               # smoke test universe APIs

# Analysis + Quant
make analyze                            # portfolio + sector + risk
python -m nuri.analysis.charts --all    # interactive HTML charts
python -m nuri.quant.factors.composite       # multi-factor scores
python -m nuri.quant.regime.classifier       # current regime
python -m nuri.quant.regime.strategy_map     # regime + macro + strategy

# Validation / Regime / Recommendations
make validate                           # signal + superinvestor + analyst + scorecard
make regime                             # 6 base + 4 special regimes
make recommend                          # candidates + tracker

# Multi-Agent Consensus (10 agents)
make consensus                                         # 보유 종목 analysis
python -m nuri.trading.agents.consensus --ticker TSLA  # 단일 종목

# Strategies / Backtest
make strategy / strategy-execute / positions
make backtest / backtest-ls / backtest-stress / backtest-rules
make optimize / mean-reversion / pairs

# Swing / Market Scan
make scan / scan-extended / scan-kr / swing / swing-check

# Full Pipeline
make full-scan        # 8-phase: collect→analyze→validate→regime→recommend→certify→evidence→notify
make quick-scan       # 4-step: collect→analyze→consensus→targets (~2분)

# SIEGE Certification
make certify          # SIEGE v2 (asset-class per-expansion) → CERTIFIED / REJECTED
make remediate        # REJECTED → 진단 + 매도 처방
make gate             # Pipeline gate verifier (exit 1 if BLOCKED)

# Targets / Rebalance / Evidence / Reports
make targets / rebalance / evidence / external
make report           # Daily report (Discord/stdout)
make report-llm       # LLM 리포트 (gpt-5.4-nano, OPENAI_ZDR_APPROVED=1 필수, STRATEGY §4.4.3)

# Lint + Test
make lint / lint-fix / lint-sh
make test / test-fast / test-slow
make verify-quick / verify-fast / verify-all
make validate-portfolio
# Single test (no make target — invoke pytest directly):
.venv/bin/python -m pytest tests/test_db.py::TestUpsertPrices::test_insert_and_query -v

# Interface
make start            # API(:8001) + Dashboard(:3000)
make api / dashboard

# Verification
make verify           # Master orchestrator → data/reports/YYYY-MM-DD/

# Deploy (2-Machine: MBP dev ↔ Mac mini 24/7 receiver)
make deploy-mini      # ★ 권장 — MBP→Mac mini 6단계 동기화 (~30초)
make deploy           # 레거시 rsync
make pre-deploy / backup
make sync-start / sync-end / sync-status
make scheduler-reload-remote
scripts/sync_dev.sh push|pull          # 저수준
bash scripts/auto_deploy.sh            # Mac mini receiver (launchd 5분 간격)

# Decision tracking + utilities
make track-decisions
make ports / ports-kill
make sync-doc-counts / verify-doc-counts
make demo / clean / clean-all / clean-deep
```

All `make` targets use `.venv/bin/python` — activate the venv or use the full path. Frontend-only commands (`npm run dev/build/test/lint/type-check`) → `frontend/CLAUDE.md`.

## Architecture

```
nuri/
├── core/              # DB (sole sqlite3 importer), rules, signal_config, timezone, events, freshness, axis
├── collectors/        # 25 collector modules (BaseCollector + KIS Open API)
├── analysis/          # portfolio, risk, sector, charts, rebalance_advisor, evidence_charts
├── quant/             # regime / validation / backtest / factors / chart_analysis
├── trading/           # agents (10) / engine (SIEGE) / strategy / recommend / swing / execution
├── api/               # FastAPI (69 endpoints, routes/)
├── alerts/            # Discord / Telegram
└── llm/               # openai_client gateway (sole external LLM entry) + Ollama fallback
```

Detailed architecture: `docs/ARCHITECTURE.md` (DB schema, migrations, env vars, CI/CD, testing).

## API Access Pattern (frontend)

- **Server Components**: `fetchAPI("/api/...")` from `@/lib/api` (absolute, server-to-server)
- **Client Components**: `fetch("/api/...")` (relative, proxied by Next.js `rewrites` in `next.config.ts`)
- **Never** `${API_BASE}/api/...` in Client Components — breaks on network access (CORS/CSP)

Backend: FastAPI on `:8001`. Frontend: Next.js on `:3000`. Next.js proxies `/api/*` to backend.

## Mechanical Enforcement (Hooks + CI)

| What | How | Enforcement |
|------|-----|------|
| `import sqlite3` outside `db.py` | PreToolUse hook | **Blocking** (exit 2) |
| `git push --force` / `reset --hard` / `clean -f` | PreToolUse hook | **Blocking** (exit 2) |
| `datetime.now()` usage | PostToolUse hook | **Blocking** (exit 1, surfaces to Claude) |
| Ruff lint violations | PostToolUse hook | Advisory (pipes `ruff check` output) |
| Privacy leaks (broker names, monetary literals, ticker+PnL) | CI `privacy-scan` + `pre_push_check.sh` | Every push + PR (STRATEGY §4.4.1) |
| Test regression | CI + Codecov 1% relative gate | Every PR |
| Trivy CRITICAL | CI `security-scan` | Every push |
| Doc count drift (collectors/endpoints/tests/e2e) | CI `Doc Count Drift Check` | Every PR (`make verify-doc-counts`) |

Hook config: `.claude/settings.json`. CI workflows: `.github/workflows/main-ci-cd.yml`.

## Gotchas

Most gotchas live in scoped files (the right CLAUDE.md fires when you edit that directory) or in code lock-tests (STRATEGY §5.3.1 Gotcha-Test Pair). Don't list them here — they drift. The few that span scopes:

- **fastapi < 0.129 pinned** (`openbb-core 1.6.7` constraint, dependabot.yml ignores 0.129+)
- **Korean stock tickers**: `.KS` suffix (e.g., `005930.KS` for 삼성전자). yfinance `.KS` fundamentals work for individuals (PE/ROE/margins) but `trailingPE` missing — use `forward_pe`. ETFs return empty (expected).
- **Concurrency asymmetry**: yfinance 10-thread parallel OK; pykrx/KRX **must be sequential** + `time.sleep(0.1)` (rate-limit). New external APIs require concurrency measurement before integration.
- **Files structure**: `nuri/` directory layout above. New module → matching `tests/` mirror + import path verification.

For framework / test-mocking / data-source / pipeline-policy gotchas → see scoped CLAUDE.md or `/nuri-harness-debug` skill.

## Reference

- `docs/STRATEGY.md` — canonical policy (load on demand): 8 sections (why / principles / architecture decisions / quality / harness / SIEGE spec / work policy / OSS refs)
- `docs/SOURCE_OF_TRUTH.md` — file-ownership map. Consult before adding/de-duplicating any doc fact.
- `docs/ARCHITECTURE.md` — detailed code/DB layout
- `docs/TODO.md` — forward-only backlog (Tier 2 next, Tier 3 research)
- `docs/SIEGE_V2.md` — 3D certification spec
- `docs/KIS_INTEGRATION.md` — KIS Open API integration details
- `AGENTS.md` — cross-tool rules (Cursor / Copilot / Codex CLI), not auto-loaded by Claude Code
- `NEXT_SESSION.md` — gitignored handoff (read first per session)
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/` — user-scoped auto-memory
