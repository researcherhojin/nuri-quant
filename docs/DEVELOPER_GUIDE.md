# Developer Experience Guide

세션 시간 낭비 패턴을 차단하는 5개 script + PR template. ~120분 누적 낭비를 막은 도구.

## TL;DR — 매 push 전

```bash
bash scripts/verify/pre_push_check.sh           # full (~2 min)
bash scripts/verify/pre_push_check.sh --quick   # smoke (~30 s)
```

이 한 명령이 4 패턴을 잡는다:

| 패턴 | Detection | 미감지 시 비용 |
|---|---|---|
| Drift bug (working tree ≠ committed) | `check_drift.py --strict` | CI roundtrip 1회 ≈ 3 min |
| Lint stale config | `ruff check` against committed pyproject | CI roundtrip 1회 ≈ 3 min |
| Test isolation flake | `pytest -n auto` (CI parity) | CI roundtrip 1+ 회 |
| Atomicity violation | `check_atomic.sh` (multi-commit) | reset + re-stage cycle |

## 5 scripts

| Script | 역할 | Quick mode |
|---|---|---|
| `scripts/dev/ci_local.sh` | CI parity (`pytest -n auto`, Linux-only flake catch) | `--quick` (~30s), `--lint` (~5s) |
| `scripts/verify/check_drift.py` | uncommitted vs committed 의존성 분석. 0/1-5/6-20/>20 severity band. | `--strict` (exit 1), `--silent` |
| `scripts/verify/pre_push_check.sh` | drift + lint + tests + commit format 일괄 | `--quick`, `--skip-tests` |
| `scripts/verify/check_atomic.sh` | multi-commit branch 각 commit 독립 검증 | `HEAD~3..HEAD` range |
| `.github/pull_request_template.md` | PR 생성 시 자동 채움 — 패턴 checkbox 강제 | — |

## Optional: git hook 설치

```bash
# .git/hooks/pre-push
#!/bin/bash
bash scripts/verify/pre_push_check.sh --quick || {
    echo "Pre-push failed. To bypass: git push --no-verify"
    exit 1
}
```

```bash
chmod +x .git/hooks/pre-push
```

## Anti-patterns (5)

1. **Working tree drift accumulation** — 20+ uncommitted across sessions → CI 가 commit 만 보고 fail. **Fix**: `python scripts/verify/check_drift.py` 매 세션 시작.
2. **Atomic commit violation** — commit 1 alone breaks suite (commit 2-3 가 missing piece) → bisect 깨짐. **Fix**: `bash scripts/verify/check_atomic.sh` 최종 push 전.
3. **CI roundtrip debugging** — push → 3min wait → fail → fix 반복. **Fix**: `bash scripts/dev/ci_local.sh` 푸시 전.
4. **Scope creep** — "fix X" → "fix X + refactor Y + cleanup Z". **Fix**: 1 PR = 1 issue ≤ 3 commits. 새 발견 → 새 branch.
5. **Environment-only failures** (Linux CI vs macOS local) — **Mitigation**: `pytest -n auto` 로컬 + `tests/conftest.py` `journal_mode=MEMORY` (PR #93) + integration test 는 explicit fixture 사용.

## 이전 세션 ~120 min 낭비 매핑

| Category | Wasted | Tool |
|---|---|---|
| Drift bugs (2× hits) | ~30 min | `check_drift.py` + `pre_push_check.sh` |
| Linux-only test pollution | ~25 min | `ci_local.sh` (parallelism parity) |
| CI roundtrip waiting | ~15 min | `ci_local.sh` (catches locally) |
| Atomicity reset | ~10 min | `check_atomic.sh` |
| Scope accumulation | ~40 min | PR template + `check_drift.py` |
| **Total addressable** | **~120 min** | **5 scripts + 1 PR template** |
