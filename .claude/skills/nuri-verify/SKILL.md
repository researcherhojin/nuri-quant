---
name: nuri-verify
description: Pre-commit verification. Use when about to commit, asked to "verify", "검증", "커밋 전 확인", or before any git commit.
---

# Verify Before Commit

## Quick check (84.9s, no network — M5 Max 2026-08-14)

```bash
make verify-quick
```

## Full check (requires a populated development DB and frontend dependencies)

```bash
make verify-all
```

This also exercises live handlers and backtests against the local DB. Unlike the mocked unit suite, it is not an isolated offline test: a handler may reach a configured fallback source. Use `bash scripts/verify/pre_push_check.sh --skip-tests` plus affected tests for the ordinary pre-push gate.

## Manual checklist

- [ ] `make lint` passes (ruff check)
- [ ] `make typecheck` passes (pyright with the CI pin; CI `Backend Lint` blocks on any error)
- [ ] `make test` passes (integration 테스트는 addopts 로 제외, xdist parallel)
- [ ] Numbers changed? → `grep -ri "old_value"` across CLAUDE.md, README.md, STRATEGY.md
- [ ] New rule or threshold? → Added to `config/rules.yaml` or `config/agents.yaml`, not hardcoded
- [ ] New feature? → "이 기능이 실패하면 어떻게 알 수 있는가?" 답할 것
- [ ] `datetime.now()` 사용? → `kst_now()` 또는 `today_kst()`로 교체
- [ ] DB 직접 접근? → `nuri/core/db/` 함수로 교체
- [ ] 스키마 변경? → `_MIGRATIONS` 리스트에 추가
- [ ] 커밋 메시지: conventional format `(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(...): ...`
- [ ] PR 스코프: 이슈 1개 = PR 1개, 커밋 3개 이하
