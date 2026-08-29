# Load Triggers (read these BEFORE editing scoped files)

| Working on... | Read first |
|---------------|-----------|
| `nuri/core/` (db, timezone, events, freshness) | `nuri/core/CLAUDE.md` |
| `nuri/collectors/` (data sources) | `nuri/collectors/CLAUDE.md` + `docs/STRATEGY.md §4.4` (privacy / external LLM egress) |
| `nuri/trading/agents/` (consensus / veto) | `nuri/trading/agents/CLAUDE.md` + `docs/STRATEGY.md §3.2-§3.3, §3.9` |
| `nuri/trading/engine/` (SIEGE certification) | `nuri/trading/engine/CLAUDE.md` + `docs/CERTIFICATION_SPEC.md` + `docs/STRATEGY.md §6` |
| `nuri/trading/recommend/` (BUY/SELL emitters, price targets, tracker) | `nuri/trading/recommend/CLAUDE.md` + `docs/STRATEGY.md §7.1` (recommend-only, never execute) |
| `nuri/trading/swing/` (≤7d swing scanner / rules) | `nuri/trading/swing/CLAUDE.md` + `config/rules.yaml` swing ladder |
| `nuri/trading/strategy/` (longshort, mean-rev, pairs, position) | `nuri/trading/strategy/CLAUDE.md` — `REGIME_ALLOCATION` lives in `longshort.py` (not config); changes require STRATEGY PR + backtest |
| `nuri/trading/execution/` (broker adapter) | `nuri/trading/execution/CLAUDE.md` — paper-only (Alpaca paper endpoint), live execution out of scope per §7.1 |
| `config/rules.yaml`, `config/agents.yaml`, `config/signals.yaml` | `config/CLAUDE.md` + `docs/STRATEGY.md §2.6, §3.4-§3.5` |
| `frontend/` | `frontend/CLAUDE.md` (Next.js 16 breaking changes — read `node_modules/next/dist/docs/` first) |
| `tests/` | `tests/CLAUDE.md` (DB isolation, mock pitfalls, privacy in fixtures) |
| `nuri/agents/` (actor fleet + discord bot) | `nuri/agents/CLAUDE.md` — actor contract (Layer A/B/C), `CANONICAL_ACTORS`/`DORMANT_ACTORS` 2-tier roster, single-writer Discord invariant, `SCHEDULES` wiring |
| `nuri/api/` (FastAPI routes) | `nuri/api/CLAUDE.md` — router registration, no-`response_model` convention, error-handling split, cache TTL gotchas |
| `scripts/` (shell automation, no scoped CLAUDE.md) | source docstring; `make lint-sh` (shellcheck); `scripts/verify/pre_push_check.sh` for safety contract |
| `nuri/mcp/` (read-model MCP server, no scoped CLAUDE.md) | `nuri/mcp/server.py` + `readmodels.py` 모듈 독스트링 — stdio 전용 · 전 쿼리 `readonly=True` · `ALLOWED` 컬럼 dict 가 곧 SQL · `decisions` 전체 제외(보유 오라클). 잠금: `tests/mcp_server/test_readmodels_privacy.py` |
| DB migrations / schema changes | `nuri/core/CLAUDE.md` + `_MIGRATIONS` list in `nuri/core/db_migrations.py` (forward-only, never edit existing migration) |
| Investment-rule / strategy / regime decisions | `docs/STRATEGY.md` §2 (principles) + §3 (decisions) |
| Harness debugging (mock fail / phantom fix / scope creep) | `/nuri-harness-debug` skill + `docs/STRATEGY.md §5` |
| SIEGE predictivity audit / E4-0b methodology | `/nuri-siege-audit` skill + `docs/STRATEGY.md §3.8` |
| Pipeline backlog / next work | `docs/TODO.md` (gitignored, local-only — forward-only Tier 2/3) |
