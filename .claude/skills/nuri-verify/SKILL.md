---
name: nuri-verify
description: Pre-commit verification. Use when about to commit, asked to "verify", "검증", "커밋 전 확인", or before any git commit.
---

# Verify Before Commit

## Quick check (~10s, no network)

```bash
make verify-quick
```

## Full check (with network, before pushing)

```bash
make verify-all
```

## Manual checklist

- [ ] `make lint` passes (ruff check)
- [ ] `make test` passes (6,381 tests — integration 9건은 addopts 로 제외, xdist parallel)
- [ ] Numbers changed? → `grep -ri "old_value"` across CLAUDE.md, README.md, STRATEGY.md
- [ ] New rule or threshold? → Added to `config/rules.yaml` or `config/agents.yaml`, not hardcoded
- [ ] New feature? → "이 기능이 실패하면 어떻게 알 수 있는가?" 답할 것
- [ ] `datetime.now()` 사용? → `kst_now()` 또는 `today_kst()`로 교체
- [ ] DB 직접 접근? → `nuri/core/db/` 함수로 교체
- [ ] 스키마 변경? → `_MIGRATIONS` 리스트에 추가
- [ ] 커밋 메시지: conventional format `(feat|fix|docs|refactor|test|chore)(...): ...`
- [ ] PR 스코프: 이슈 1개 = PR 1개, 커밋 3개 이하
