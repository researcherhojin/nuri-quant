# Nuri-Quant Frontend

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme.

## Commands

```bash
npm run dev            # Dev server (:3000)
npm run build          # Production build
npm run test           # vitest (1571 tests, 133 files)
npx playwright test    # E2E (87 tests, 9 specs)
```

## Architecture

See [`CLAUDE.md`](CLAUDE.md) for full details. Key points:

- **18 routes** — Server Components with `force-dynamic`
- **Action-First dashboard** — SystemHealth, ActionItems, OpportunityExplorer, MarketContext
- **API proxy** — Next.js rewrites `/api/*` to FastAPI `:8001`
- **i18n** — `src/lib/strings.ts` (Korean UI constants, not next-intl)
- **Tests** — `src/__tests__/{components,lib,pages,coverage}/` (95 files) + 36 co-located (`src/app` / `src/components/ui` / `src/lib`) + `e2e/`
