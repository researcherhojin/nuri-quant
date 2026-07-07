# frontend/ — Next.js 16 Dashboard

## CRITICAL: Next.js 16 Breaking Changes

APIs differ from LLM training data. **Always read `node_modules/next/dist/docs/` before writing any code.** Heed deprecation notices.

## Stack

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme (zinc-950 base).

## Commands

```bash
npm run dev            # Dev server (:3000)
npm run build          # Production build (type-check + compile)
npm run test           # vitest run (1383 tests, 126 files)
npx vitest run src/__tests__/pages/dashboard.test.tsx  # single file
npx vitest run -t "renders verdict"                    # single test by name
```

## Server Components Pattern

All pages are **Server Components** with `force-dynamic`. Data fetched server-side via `fetchAPI()` (`src/lib/api.ts`).

Client Components: `/report` (LLM generation), `/pipeline` (ReactFlow DAG), `<CompositionDonut>` (Recharts pie), `<ActionItems>` (expand/collapse), `<OpportunityExplorer>` (10-Agent fetch), `<PriceChart>` (period selector).

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

`src/middleware.ts` — HMAC-SHA256 keyed cookie auth (Edge Runtime compatible). Active only when `DASHBOARD_PASSWORD` env is set.

## Testing Gotchas

- **vi.mock("recharts") hoisting**: Affects ALL dynamic imports in same vitest worker. Keep recharts-dependent and recharts-free tests in **separate files**. Use `vi.doMock` for per-test control.
- Dashboard tests mock recharts at file level to avoid jsdom suspense on `CompositionDonut`.
- Mock `@/lib/api` + `next/navigation` in all page tests.
- Test files: 89 in `src/__tests__/` (`components/lib/pages/coverage` subdirs + root `api-auth`/`middleware` tests) + 37 co-located next to sources (`src/app/**`, `src/components/ui/**`, `src/lib/**` — `*.coverage.test.tsx` / `*.branchcov.test.tsx`).
