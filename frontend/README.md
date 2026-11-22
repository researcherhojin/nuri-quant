# Nuri-Quant Frontend

The Nuri-Quant dashboard: Next.js 16, React 19, Tailwind CSS 4 and shadcn/ui,
with a dark-only theme. Development conventions, including Next.js 16 API
changes and testing pitfalls, are in [`CLAUDE.md`](CLAUDE.md).

## Setup

```bash
npm ci
```

The dashboard reads data from the FastAPI backend. Start it from the
repository root with `make api`, or start both with `make start`.
Open `http://localhost:3000` for the dashboard and check `http://localhost:8001/api/health`
for API liveness. [Fresh-clone walkthrough](../docs/FRESH_CLONE_SETUP.md)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend URL for the `/api/*` rewrite (default `http://localhost:8001`) |
| `DASHBOARD_PASSWORD` | Enables cookie authentication when set. Read from `frontend/.env.local`, not the repository-root `.env` |
| `AUTH_SECRET` | Cookie signing key (falls back to `DASHBOARD_PASSWORD`) |

## Architecture

![Dashboard page requests and API routes through Next.js to FastAPI and SQLite](../.github/assets/frontend-architecture.svg)

The production API binds to loopback. Browser API calls use relative URLs through Next.js. [Production processes](../docs/ARCHITECTURE.md#processes-and-deployment)

## Commands

```bash
npm run dev            # development server on :3000
npm run build          # production build
npm run start          # serve the production build
npm run lint           # eslint + oxlint
npm test               # vitest
npm run test:coverage  # vitest with coverage
npm run test:e2e       # Playwright
```

`npm run test:e2e` starts the backend from the repository-root `.venv` and the
Next.js dev server, or reuses them if they are already running
(`playwright.config.ts`). Run `make setup` first.
CI seeds a database before running the browser suite. For a manual check of a
production build, run `npm run build` and then `npm run start` with the backend
running. [CI and testing](../docs/ARCHITECTURE.md#cicd-pipeline-main-ci-cdyml)

## Structure

- Data pages generally use Server Components with `force-dynamic` and fetch
  through `fetchAPI()` in `src/lib/api.ts`. Interactive pages, including `/login`
  and `/portfolio`, use Client Components; see `CLAUDE.md` for the boundary.
- Next.js rewrites `/api/*` to the FastAPI backend (`next.config.ts`).
- UI strings are Korean constants in `src/lib/strings.ts`.
- Tests live in `src/__tests__/`, next to the code they cover, and in `e2e/`.
