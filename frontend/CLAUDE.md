# frontend/ — Next.js 16 Dashboard

## CRITICAL: Next.js 16 Breaking Changes

APIs differ from LLM training data. **Always read `node_modules/next/dist/docs/` before writing any code.** Heed deprecation notices.

## Stack

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme (zinc-950 base).

## Commands

```bash
npm run dev            # Dev server (:3000)
npm run build          # Production build (type-check + compile)
npm run test           # vitest run (812 tests, 55 files)
npx vitest run src/__tests__/pages/dashboard.test.tsx  # single file
npx vitest run -t "renders verdict"                    # single test by name
```

## Server Components Pattern

All pages are **Server Components** with `force-dynamic`. Data fetched server-side via `fetchAPI()` (`src/lib/api.ts`).

Three Client Components only: `/report` (LLM generation), `/pipeline` (ReactFlow DAG), `<CompositionDonut>` (Recharts pie).

## 16 Routes

`/` (dashboard), `/signals`, `/consensus`, `/scan`, `/strategy`, `/rebalance`, `/engine`, `/pipeline`, `/report`, `/evidence`, `/portfolio`, `/targets`, `/advisor`, `/decisions`, `/login`, `/ticker/[symbol]`.

## Design System (3 shared components)

- `DataTable` — Universal table with column config, renderers, `rowClassName`, compact mode
- `StatusBadge` — BUY/SELL/HOLD/WATCH/LONG/SHORT + signal types
- `Metric` — Label + value + sub-text with color

**Conventions**: `async function Section()` in `<Suspense>`, `animate-pulse` skeletons, color semantics (emerald=BUY, red=SELL, amber=warning, blue=WATCH, zinc=HOLD), `text-[10px]` sub-labels.

## Dashboard Layout (#224)

Hero (4 stats) → market context strip → CollapsibleStrips (alerts/events/candidates) → CompositionSection (320px Recharts donut + tabs `?comp=ticker|sector|account`) → mini cards strip (Movers + concentration) → Holdings table (top 8 + `?holdings=expanded`) → footer.

Data flows through `summarizeHoldings()` in `src/lib/holdings-summary.ts`.

## Auth

`src/middleware.ts` — HMAC-SHA256 keyed cookie auth (Edge Runtime compatible). Active only when `DASHBOARD_PASSWORD` env is set.

## Testing Gotchas

- **vi.mock("recharts") hoisting**: Affects ALL dynamic imports in same vitest worker. Keep recharts-dependent and recharts-free tests in **separate files**. Use `vi.doMock` for per-test control.
- Dashboard tests mock recharts at file level to avoid jsdom suspense on `CompositionDonut`.
- Mock `@/lib/api` + `next/navigation` in all page tests.
- Test files: `__tests__/{components,lib,pages,coverage}/` subdirs.
