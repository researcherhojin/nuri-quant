# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commands

```bash
npm run dev       # Dev server (:3000)
npm run build     # Production build (type-check + compile)
npm run lint      # ESLint
```

Requires backend API running at `http://localhost:8001` (see parent `make api`).

## Architecture

Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui. Dark-only theme (zinc-950 base).

### Data flow

All pages are **Server Components** with `force-dynamic`. Data is fetched server-side via `fetchAPI()` (`src/lib/api.ts`) which calls the FastAPI backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8001`). The only Client Component is `/report` (user-triggered LLM generation, imports `API_BASE` from `lib/api.ts`).

### Pages (14 routes)

| Route | Data source | Purpose |
|-------|------------|---------|
| `/` | `/api/dashboard` | Action-oriented overview: verdict, allocation bar, BUY/SELL/WATCH actions |
| `/signals` | `/api/scorecard`, `/api/cross-analysis` | Signal scorecard + regime cross-analysis |
| `/consensus` | `/api/consensus` | 7-agent verdicts table + dissent + price targets |
| `/scan` | `/api/scan`, `/api/swing/entries` | Market scanner + swing trade entries |
| `/strategy` | `/api/strategy/status`, `/api/backtest` | L/S strategy + backtest + stress test |
| `/rebalance` | `/api/rebalance?method=rp` | Regime-aware Risk Parity rebalancing |
| `/engine` | `/api/gate`, `/api/conflicts`, `/api/memory` | SIEGE engine status (gate, conflicts, drift) |
| `/report` | `/api/report`, `/api/report/context` | Client-side LLM report generation |
| `/evidence` | `/api/evidence` | Plotly 증거 차트 뷰어 (iframe embeds) |
| `/portfolio` | `/api/portfolio`, `/api/risk` | 포트폴리오 보유 현황 + 리스크 지표 |
| `/targets` | `/api/targets` | 전 종목 가격 타겟 (매수가/손절가/익절가/목표가) |
| `/advisor` | `/api/rebalance-advisor` | 리밸런스 어드바이저 (규칙 위반 + 매도 수량) |
| `/login` | `/api/auth` | 대시보드 로그인 (DASHBOARD_PASSWORD 설정 시) |
| `/ticker/[symbol]` | `/api/ticker/{symbol}` | Single ticker deep-dive (agents, ratings, earnings, insiders, fundamentals) |

### Design system (custom components)

Three shared components enforce visual consistency across all pages:

- **`DataTable`** (`src/components/ui/data-table.tsx`) — Universal table with column config, alignment, custom renderers, compact mode, optional row click. **Client Component** (`"use client"`) because of `onRowClick`.
- **`StatusBadge`** (`src/components/ui/status-badge.tsx`) — Colored badge for BUY/SELL/HOLD/WATCH/LONG/SHORT/READY/BLOCKED/REDUCE/AGGRESSIVE/NEUTRAL/CAUTIOUS/DEFENSIVE and signal types (breakout, momentum, bounce, volume_spike).
- **`Metric`** (`src/components/ui/metric.tsx`) — Label + value + optional sub-text with color (green/red/default) and size (sm/lg).

Use these instead of raw `<table>` or shadcn `Badge`. The shadcn `Badge`, `Card`, `Button`, `Separator`, `Tabs`, `Table` are available but prefer the design system components for data display.

### Type definitions

`src/lib/types.ts` has Zod schemas + TypeScript types for API responses: `Regime`, `Macro`, `Candidate`, `Scorecard`, `RebalanceAction`, `Strategy`.

## Conventions

- Korean comments, English code
- Every data page uses the pattern: `async function Section()` wrapped in `<Suspense fallback={<Loading />}>`
- Loading skeletons use `animate-pulse` with `bg-zinc-900 rounded-xl border border-zinc-800`
- Color semantics: emerald = positive/BUY, red = negative/SELL, amber = warning/REDUCE, blue = WATCH, zinc = neutral/HOLD
- Text sizes: `text-[10px]` for sub-labels, `text-xs` for secondary, `text-sm` for body
- Card pattern: `<Card className="bg-zinc-900 border-zinc-800">` → `<CardContent className="pt-5">` → description `<p className="text-xs text-zinc-500 mb-3">` → content
