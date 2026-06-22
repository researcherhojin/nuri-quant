# Architecture + Commands

## Code layout

`nuri/core` (sole sqlite3 importer) / `nuri/collectors` (27 collector modules) / `analysis` / `quant` / `trading` (agents · engine · strategy · recommend · swing · execution) / `api` (72 endpoints, routes/) / `alerts` / `llm`. Plus `tests/` mirror + `scripts/` automation + `frontend/` (Next.js). Detailed map (DB schema, migrations, env vars, CI/CD): `docs/ARCHITECTURE.md`.

## Commands

`make help` for full target inventory. Daily essentials:
- Setup: `make setup` (1회) — venv + deps + DB init + portfolio import
- Daily: `make quick-scan` (~2분 4-step) / `make full-scan` (8-phase + SIEGE) / `make consensus`
- Reactive: `make buy-candidates` / `make thesis ticker=<T>` / `make earnings-preview ticker=<T>`
- LLM consult dual-archive: `make llm-consult slug=<kebab> prompt=<file>`
- Lint+Test: `make lint` / `make test-fast` / `.venv/bin/python -m pytest <path>::<test> -v`
- Deploy: `make start` (API :8001 + Dashboard :3000) / `make deploy-mini` (MBP → Mac mini 6단계 동기화)

Frontend-only commands → `frontend/CLAUDE.md`.

## API Access Pattern (frontend)

- **Server Components**: `fetchAPI("/api/...")` from `@/lib/api` (absolute, server-to-server)
- **Client Components**: `fetch("/api/...")` (relative, proxied by Next.js `rewrites` in `next.config.ts`)
- **Never** `${API_BASE}/api/...` in Client Components — breaks on network access (CORS/CSP)

Backend: FastAPI on `:8001`. Frontend: Next.js on `:3000`. Next.js proxies `/api/*` to backend.
