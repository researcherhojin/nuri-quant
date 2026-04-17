# Developer Experience Guide

How to avoid the failure modes that waste session time.

## TL;DR — Before every push

```bash
bash scripts/pre_push_check.sh           # full (~2 min)
bash scripts/pre_push_check.sh --quick   # smoke (~30 s)
```

This single command catches the 4 patterns that wasted ~120 minutes in the
previous session:

| Pattern | Detection | Cost when missed |
|---|---|---|
| Drift bug (working tree ≠ committed) | `check_drift.py --strict` | 1 CI roundtrip = ~3 min |
| Lint stale config | `ruff check` against committed pyproject | 1 CI roundtrip = ~3 min |
| Test isolation flake | `pytest -n auto` (CI-parity flags) | 1+ CI roundtrips |
| Atomicity violation | `check_atomic.sh` (multi-commit branches) | reset + re-stage cycle |

## The 4 scripts + 1 PR template

### 1. `scripts/ci_local.sh` — exact CI parity

Runs the same `pytest` command CI runs, with the same flags and parallelism.
Catches Linux-only or `-n auto` parallelism failures locally where possible.

```bash
bash scripts/ci_local.sh           # full (~2 min)
bash scripts/ci_local.sh --quick   # smoke (~30 s)
bash scripts/ci_local.sh --lint    # ruff only (~5 s)
```

### 2. `scripts/check_drift.py` — drift analyzer

Lists uncommitted files (modified + untracked) and finds committed files that
reference them. Warns if a committed file imports a module from an uncommitted
file — that's the recipe for "passes locally / fails CI".

```bash
python scripts/check_drift.py            # report
python scripts/check_drift.py --strict   # exit 1 on drift
python scripts/check_drift.py --silent   # 1-line summary
```

**Drift severity bands**:
- **0 files** → clean, no risk
- **1-5 files** → low risk, normal during active development
- **6-20 files** → moderate, consider committing related work
- **>20 files** → **high risk**, every new commit is exposed to invisible deps

### 3. `scripts/pre_push_check.sh` — orchestrator

Runs drift check + lint + tests + commit message format in one command.
Exit non-zero blocks the push (if used as a git hook).

```bash
bash scripts/pre_push_check.sh                # full (~2 min)
bash scripts/pre_push_check.sh --quick        # smoke (~30 s)
bash scripts/pre_push_check.sh --skip-tests   # lint + drift only (~10 s)
```

### 4. `scripts/check_atomic.sh` — multi-commit verification

For multi-commit branches: checks each commit independently to catch the
"commit 1 alone breaks the suite" pattern. Runs lint + test collection per
commit (skips full test run for speed).

```bash
bash scripts/check_atomic.sh                # since origin/main
bash scripts/check_atomic.sh HEAD~3..HEAD   # custom range
```

### 5. PR template (`.github/pull_request_template.md`)

GitHub auto-fills this when creating a PR. Forces explicit checkboxes for
the patterns above. If a checkbox is unchecked, the reviewer should ask why.

## Optional: install as a git hook

```bash
# .git/hooks/pre-push
#!/bin/bash
bash scripts/pre_push_check.sh --quick || {
    echo ""
    echo "Pre-push check failed. To bypass (not recommended):"
    echo "  git push --no-verify"
    exit 1
}
```

```bash
chmod +x .git/hooks/pre-push
```

## Anti-patterns to avoid

### 1. Working tree drift accumulation

**Symptom**: 20+ uncommitted files sitting in working tree across sessions.

**Cost**: every new commit is exposed to invisible dependencies. Local
checks pass because they see the working tree. CI sees only committed state
and fails with confusing errors.

**Fix**: commit related work in categorized PRs *before* starting new work.
Run `python scripts/check_drift.py` at the start of every session.

### 2. Atomic commit violation

**Symptom**: 3-commit branch where commit 1 alone breaks the test suite
because commit 2 and 3 add the missing pieces.

**Cost**: bisect doesn't work, rebase becomes painful.

**Fix**: `bash scripts/check_atomic.sh` before final push. If a commit
fails standalone, restructure (squash or reorder).

### 3. CI roundtrip debugging

**Symptom**: push → wait 3 min → fail → fix → push → wait 3 min → fail again.

**Cost**: 5 roundtrips = 15 min lost to pure waiting.

**Fix**: `bash scripts/ci_local.sh` before push. Each roundtrip caught locally
saves ~3 min.

### 4. Scope creep

**Symptom**: PR starts as "fix X" and grows to "fix X + refactor Y + cleanup Z".

**Cost**: PR review becomes opaque. Atomicity violations multiply. Conflicts
with parallel PRs increase.

**Fix**: 1 PR = 1 issue. Max 3 commits per PR (per session memory). New
unrelated discoveries → new branch + new PR.

### 5. Environment-only test failures

**Symptom**: 3 tests fail on Linux CI but pass on macOS local.

**Cost**: blind debugging without reproduction.

**Mitigation**:
- Use `pytest -n auto` locally (same parallelism as CI)
- `tests/conftest.py` should use `journal_mode=MEMORY` (not `OFF`) for
  cross-connection visibility on tmpfs (fixed in PR #93)
- Prefer integration tests with explicit fixtures over relying on
  module-level state

## Time budget rationale

These optimizations target ~120 min of waste observed in the previous session:

| Category | Wasted | Tool |
|---|---|---|
| Drift bugs (2× hits) | ~30 min | `check_drift.py` + `pre_push_check.sh` |
| Linux-only test pollution | ~25 min | `ci_local.sh` (parallelism parity) |
| CI roundtrip waiting | ~15 min | `ci_local.sh` (catches locally) |
| Atomicity reset | ~10 min | `check_atomic.sh` |
| Scope accumulation | ~40 min | PR template + scripts/check_drift.py |
| **Total addressable** | **~120 min** | **5 scripts + 1 PR template** |
