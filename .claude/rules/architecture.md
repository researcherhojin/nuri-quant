# Architecture + Commands

## Code layout

**Pipeline** (5 stages; crossing imports deferred-only and allowlist-frozen — see Cross-stage imports in `invariants.md`): `collect → analyze → consensus → certify → track`.

⚠️ **화살표는 읽는 순서지 실행 순서가 아니다.** 스테이지를 이어 붙이는 주체가 없다 — `scheduler.py` 는 독립 cron job 을 등록할 뿐이고, 스테이지 job 은 `run_step(..., warn_only=True)` 로 감싸이지만 그건 lifecycle 이벤트 기록용이라 의존성이 안 맞아도 **경고만 남기고 그대로 실행**한다(관측이 본 작업을 게이트하면 안 된다 — #894). `analyze` 와 `certify` 는 **자기 cron job 이 아예 없고**(certify=consensus job 안에서 in-memory, `certifications` 는 `premarket_brief` 가 씀), cron 시각도 읽는 순서와 다르다 — outcome tracking 07:02 가 그걸 소비하는 consensus 07:05 **앞**에 있다(전날 것을 읽는다). 공개 서술은 `README.md` 스테이지 표.

디렉터리 구성과 모듈 개수는 `ls` 로 확인한다 — 여기 적지 않는다(드리프트만 만든다). 상세 지도(DB schema, migrations, env vars, CI/CD)는 `docs/ARCHITECTURE.md`, 스테이지별 규약은 `load-triggers.md` 가 가리키는 scoped CLAUDE.md.

## Commands

`make help` for full target inventory. Daily essentials:
- Setup: `make setup` (1회) — venv + deps + DB init + portfolio import
- Daily: `make quick-scan` (~2분 4-step) / `make full-scan` (8-phase + SIEGE) / `make consensus`
- Reactive: `make recommend` (BUY candidates + tracker) / `/nuri-thesis <T>` skill (`nuri/llm/thesis_query.py`) / `make earnings-preview ticker=<T>`
- LLM consult dual-archive: `make llm-consult slug=<kebab> prompt=<file>`
- Lint+Test: `make lint` / `make test-fast` / `.venv/bin/python -m pytest <path>::<test> -v`
- Gates: `make verify-quick` (~10s pre-commit smoke) / `make verify-all` (~30s pre-push: tests + lint + frontend)
- Deploy: `make start` (API :8001 + Dashboard :3000) / `make deploy-mini` (MBP → Mac mini 7단계 동기화)

Frontend-only commands → `frontend/CLAUDE.md`.

## API Access Pattern (frontend)

- **Server Components**: `fetchAPI("/api/...")` from `@/lib/api` (absolute, server-to-server)
- **Client Components**: `fetch("/api/...")` (relative, proxied by Next.js `rewrites` in `next.config.ts`)
- **Never** `${API_BASE}/api/...` in Client Components — breaks on network access (CORS/CSP)

Backend: FastAPI on `:8001`. Frontend: Next.js on `:3000`. Next.js proxies `/api/*` to backend.
