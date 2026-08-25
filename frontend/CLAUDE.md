# frontend/ — Next.js 16 Dashboard

## CRITICAL: Next.js 16 Breaking Changes

APIs differ from LLM training data. **Always read `node_modules/next/dist/docs/` before writing any code.** Heed deprecation notices.

## Stack

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme (zinc-950 base).

## Commands

```bash
npm run dev            # Dev server (:3000)
npm run build          # Production build (type-check + compile)
npm run test           # vitest run (1600 tests, 134 files)
npm run test:e2e       # playwright (real backend — see "E2E (Playwright)" below)
npx vitest run src/__tests__/pages/dashboard.test.tsx  # single file
npx vitest run -t "renders verdict"                    # single test by name
```

## Server Components Pattern

All pages are **Server Components** with `force-dynamic`. Data fetched server-side via `fetchAPI()` (`src/lib/api.ts`).

Client Components: `/report` (LLM generation), `/pipeline` (ReactFlow DAG), `/portfolio` (holdings editor), `/login` (auth form), `<ActionItems>` (expand/collapse), `<OpportunityExplorer>` (10-Agent fetch), `<PriceChart>` (period selector).

**RSC boundary — never import a server util through a `"use client"` module.** next 16.2.9+ throws at *request time* (not build/vitest) when a Server Component calls a function re-exported from a `"use client"` module. The original trip: `composition-section-lazy.tsx` was `"use client"` and re-exported the pure `parseCompositionTab`; importing it there from `page.tsx` made the whole dashboard render the error boundary (#731). That wrapper was deleted in #1210 (donut → server-pure bar), but the rule stands for every remaining `"use client"` module: import pure utils from their **source server module** only. **Test:** `src/__tests__/pages/page-rsc-import-guard.test.tsx::page.tsx RSC import boundary` (asserts the import source — the runtime error is invisible to `next build` and jsdom render).

## Design System (3 shared components)

- `DataTable` — Universal table with column config, renderers, `rowClassName`, compact mode
- `StatusBadge` — BUY/SELL/HOLD/WATCH/LONG/SHORT + signal types
- `Metric` — Label + value + sub-text with color

**Conventions**: `async function Section()` in `<Suspense>`, `animate-pulse` skeletons, color semantics (emerald=BUY, red=SELL, amber=warning, blue=WATCH, zinc=HOLD), `text-[10px]` sub-labels.

## Dashboard Layout (#264 Action-First → U2b Evidence Terminal)

**VerdictBanner** (오늘의 답, 첫 픽셀 #1207) → Hero (4 stats) → RegimeShiftBanner(조건부) → **ActionItems 밀집 테이블 2/3 + SystemHealthRail·MacroEventsCard 1/3** (#1209) → market/events strips → CompositionSection (가로 스택 바 + tabs, #1210) → Holdings table (top 8) → **OpportunityExplorer** (상위 3개 + /scan 링크) → CoverageStatus (`<details>` 접힘, #1210) → footer.

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
should be **241**.

## E2E (Playwright) — runs against the real backend, gated by nothing

`npm run test:e2e` (`npx playwright test`). 10 spec files under `e2e/`, 89 tests. `playwright.config.ts` starts both servers itself (`uvicorn` :8001, `npm run dev` :3000) with `reuseExistingServer: true`.

- **No CI job, no Makefile target, no `scripts/verify/` step runs it.** It is the one suite in this repo that has never gated a merge, which is exactly how `410d385` (2026-05-04) renamed `CONTEXT.SIEGE` to `"Certification"`, updated the matching vitest files, and left three e2e assertions searching for `text=SIEGE` for 3.5 months. Wiring it into a gate is a separate decision (needs a runtime/stability budget); until then, run it by hand before touching the dashboard.
- **Never inline a user-facing string literal in a spec — import it from `src/lib/strings.ts`.** That file is the single source of truth and specs can import across the directory boundary (`import { ACTION, CONTEXT } from "../src/lib/strings"`). The contrast is on record: `dashboard.spec.ts:19` survived the same rename only because it OR'd several candidate strings, while the three brittle single-literal assertions all broke.
- **Scope assertions to `main`.** The sidebar carries a "Certification Engine" link, so a `body`-wide `includes("Certification")` passes even when the health card is gone. A spec that can pass with the feature deleted is worse than no spec.
- **Don't assert live portfolio values.** `action-first.spec.ts:28` hardcoded `TSLA` at `15.4%` in the `urgent` bucket, captured 2026-04-13; by 2026-08-20 the same holding was 14.3% and in `check`. Read what the API actually returned and assert the UI matches it.
- **`workers` is capped at 2 on purpose.** The default (cores/2 = 8 here) fires 8 spec files at one `next dev` and one uvicorn; every page is a `force-dynamic` Server Component issuing several API calls, so the backend saturates and unrelated specs time out. The cap is mitigation, not a fix — the real constraint is API concurrency (#1119). Do not raise a timeout to turn a red spec green without checking which side is actually slow.
- **Per-assertion `{ timeout: N }` overrides `expect.timeout` from the config.** Two explore-search specs stayed red after the config budget was raised to 15 s because they carried an inline `5000`. Keep the waiting budget in one place.
- **The `request` fixture goes through `baseURL`, i.e. the Next proxy** — which aborts at 30 s. A cold heavy endpoint makes the fixture see a non-ok response while the API logs `200 OK`. Warm the endpoint with a `page.goto` before asserting on it.

## Testing Gotchas

- **vi.mock("recharts") hoisting**: Affects ALL dynamic imports in same vitest worker. Keep recharts-dependent and recharts-free tests in **separate files**. Use `vi.doMock` for per-test control. (#1210 이후 대시보드 트리는 recharts 무관 — price/equity/siege/gate 차트 테스트에만 해당.)
- Mock `@/lib/api` + `next/navigation` in all page tests.
- **`window.localStorage` 는 환경 의존**: 로컬 Node 26 jsdom 엔 **없고**(실험적 webstorage 게터가 `--localstorage-file` 없이 undefined), CI Node 22 jsdom 은 **실동작 스토리지**를 제공해 같은 파일 내 테스트 간 상태가 지속된다. 로컬 초록 ≠ CI 초록 — storage 를 쓰는 테스트는 인메모리 스텁 + `beforeEach` 초기화로 결정론화할 것 (CI run 32814106230, #1212). **Test:** `src/__tests__/components/action-items.test.tsx::NEW badge + ack (#1212)` — describe 레벨 스텁이 빠지면 CI 에서 ack 누수로 FAIL.
- Test files: 98 in `src/__tests__/` (`components/lib/pages/coverage` subdirs + root `api-auth`/`middleware` tests) + 36 co-located next to sources (`src/app/**`, `src/components/ui/**`, `src/lib/**` — `*.coverage.test.tsx` / `*.branchcov.test.tsx`).
