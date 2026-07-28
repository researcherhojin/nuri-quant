# frontend/ — Next.js 16 Dashboard

## CRITICAL: Next.js 16 Breaking Changes

APIs differ from LLM training data. **Always read `node_modules/next/dist/docs/` before writing any code.** Heed deprecation notices.

## Stack

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme (zinc-950 base).

## Commands

```bash
npm run dev            # Dev server (:3000)
npm run build          # Production build (type-check + compile)
npm run test           # vitest run (1449 tests, 127 files)
npx vitest run src/__tests__/pages/dashboard.test.tsx  # single file
npx vitest run -t "renders verdict"                    # single test by name
```

## Server Components Pattern

All pages are **Server Components** with `force-dynamic`. Data fetched server-side via `fetchAPI()` (`src/lib/api.ts`).

Client Components: `/report` (LLM generation), `/pipeline` (ReactFlow DAG), `/portfolio` (holdings editor), `/login` (auth form), `<CompositionDonut>` (Recharts pie), `<ActionItems>` (expand/collapse), `<OpportunityExplorer>` (10-Agent fetch), `<PriceChart>` (period selector).

**RSC boundary — never import a server util through a `"use client"` module.** next 16.2.9+ throws at *request time* (not build/vitest) when a Server Component calls a function re-exported from a `"use client"` module. `composition-section-lazy.tsx` is `"use client"` and re-exports the pure `parseCompositionTab`; importing it there from `page.tsx` made the whole dashboard render the error boundary. Import pure utils from their **source server module** (`composition-section`), take only the lazy wrapper component from the `-lazy` file. **Test:** `src/__tests__/pages/page-rsc-import-guard.test.tsx::page.tsx RSC import boundary` (asserts the import source — the runtime error is invisible to `next build` and jsdom render). (#731)

## 18 Routes

`/` (dashboard), `/signals`, `/consensus`, `/scan`, `/strategy`, `/rebalance`, `/engine`, `/pipeline`, `/report`, `/evidence`, `/portfolio`, `/targets`, `/advisor`, `/decisions`, `/decisions/[id]`, `/explore`, `/login`, `/ticker/[symbol]`.

## Design System (3 shared components)

- `DataTable` — Universal table with column config, renderers, `rowClassName`, compact mode
- `StatusBadge` — BUY/SELL/HOLD/WATCH/LONG/SHORT + signal types
- `Metric` — Label + value + sub-text with color

**Conventions**: `async function Section()` in `<Suspense>`, `animate-pulse` skeletons, color semantics (emerald=BUY, red=SELL, amber=warning, blue=WATCH, zinc=HOLD), `text-[10px]` sub-labels.

## Dashboard Layout (#264 Action-First)

Hero (4 stats) → **SystemHealth 4-card** (SIEGE/regime/macro/freshness) → **MacroEvents** (한국어 카테고리) → **ActionItems** (🔴urgent/🟡check/✅hold, 연금 제외) → market context strip → CompositionSection (320px donut + tabs) → Holdings table (top 8) → **OpportunityExplorer** (상위 3개 + /scan 링크) → footer.

Data flows through `summarizeHoldings()` in `src/lib/holdings-summary.ts`. Action data from `/api/actions`, `/api/opportunities`, `/api/market-context`.

## Auth

`src/middleware.ts` — HMAC-SHA256 keyed cookie auth (Edge Runtime compatible). Active only when `DASHBOARD_PASSWORD` env is set. Reads `frontend/.env.local`, **not** the repo-root `.env` — `npm run start` runs with `frontend/` as cwd, so Next only loads env files from there. Cookie signing key is `AUTH_SECRET` (falls back to `DASHBOARD_PASSWORD`); set it explicitly so sessions survive a password change.

## The build is the deploy artifact — rebuild or nothing lands

**`next build` output is a deploy artifact, not a cache.** Two things bake in at build time and are invisible to `git pull`:

1. **`next.config.ts` `rewrites()`** → `.next/routes-manifest.json`. A build made before a rewrite was added serves **404 for every proxied path**, forever, no matter how current the source is.
2. **`NEXT_PUBLIC_*` env vars** → inlined into both server and client bundles. Editing `frontend/.env.local` after a build changes nothing until you rebuild.

This shipped: production ran an Apr-13 build for 3.5 months (108 `frontend/` commits behind) because `deploy_to_mini.sh` had no build step. Reads kept working (server components used the baked `http://localhost:8001`, correct on the API host), so nothing looked broken — but every client-side `/api/*` call 404'd, killing portfolio writes, pipeline runs, and both SSE hooks. `deploy_to_mini.sh` step 4 now rebuilds when `.next` is older than the newest `frontend/` commit.

**Never build absolute request URLs in `"use client"` code.** `API_BASE` is the build-time-inlined `NEXT_PUBLIC_API_URL` — a *server-side* address. A Server Component resolves it on the API host and it works; a browser resolves it on the *visitor's* machine and it dies. Client code uses relative paths so the `rewrites()` proxy forwards server-side. `next build` and jsdom both miss this (valid template string; jsdom stubs `EventSource`). **Test:** `src/__tests__/lib/client-absolute-url-guard.test.ts::"use client" modules never build request URLs from API_BASE` (scans every `"use client"` module's source text).

## `overrides` are load-bearing — `npm audit fix` will break lint

`package.json` has no comment syntax, so the reasoning lives here.

`overrides.eslint = { "minimatch": ">=10.2.5" }` is **not** cosmetic. The blanket
`overrides["brace-expansion"] = ">=5.0.8"` (GHSA-mh99-v99m-4gvg) is incompatible with
the `minimatch@3` that eslint 9 ships — v5 changed the export shape, so eslint dies at
startup with `TypeError: expand is not a function` and lints **zero** files. The advisory
range (`<=5.0.7`) covers the entire 1.x line by semver, so there is no v1 pin that both
satisfies the advisory and keeps eslint alive. Forcing minimatch ≥10 into eslint's subtree
is what makes both true at once.

Two things that do **not** work, already tried (#913):
- scoping `brace-expansion` to `>=1.1.16 <2` under eslint — lint runs, but the alert stays open forever
- upgrading to eslint 10 — `eslint-config-next`'s plugins cap their peer range at `^9`, and lint fails there too

Symptom if someone drops it: eslint prints `Oops! Something went wrong!` with a
`brace-expansion` stack trace and lints **nothing**. `npm run lint` is silent on success, so
confirm by file count rather than by absence of output — `npx eslint --format json | jq length`
should be **212**.

## Testing Gotchas

- **vi.mock("recharts") hoisting**: Affects ALL dynamic imports in same vitest worker. Keep recharts-dependent and recharts-free tests in **separate files**. Use `vi.doMock` for per-test control.
- Dashboard tests mock recharts at file level to avoid jsdom suspense on `CompositionDonut`.
- Mock `@/lib/api` + `next/navigation` in all page tests.
- Test files: 90 in `src/__tests__/` (`components/lib/pages/coverage` subdirs + root `api-auth`/`middleware` tests) + 37 co-located next to sources (`src/app/**`, `src/components/ui/**`, `src/lib/**` — `*.coverage.test.tsx` / `*.branchcov.test.tsx`).
