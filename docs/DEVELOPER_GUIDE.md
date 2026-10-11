# Developer Experience Guide

*Korean edition: [ko/DEVELOPER_GUIDE.md](ko/DEVELOPER_GUIDE.md)*

This guide describes 4 scripts and a PR template that reduce the time-wasting patterns that kept recurring during sessions. The tools were built around the roughly 120 minutes of accumulated waste at the time they were introduced.

## TL;DR — before every push

```bash
bash scripts/verify/pre_push_check.sh           # full (106s)
bash scripts/verify/pre_push_check.sh --quick   # smoke (6s)
```

`pre_push_check.sh` checks drift, lint (ruff · shellcheck), doc counts, spellcheck, pyright (changed lines), tests, the privacy scan and the commit message format in one run. This command catches the first 3 of the 4 patterns below; for atomicity, run `check_atomic.sh` separately.

| Pattern | Detection | Cost if undetected |
|---|---|---|
| Drift bug (working tree ≠ committed) | `check_drift.py --strict` | 1 CI roundtrip ≈ 3 min |
| Lint stale config | `ruff check` (the drift check detects an uncommitted `pyproject.toml`) | 1 CI roundtrip ≈ 3 min |
| Test isolation flake | `pytest -n auto` (CI uses `-n 8` on the fast shard, #1414) | 1+ CI roundtrips |
| Atomicity violation | `check_atomic.sh` (multi-commit, run separately) | reset + re-stage cycle |

## 4 scripts + 1 PR template

| Script | Role | Quick mode |
|---|---|---|
| `scripts/dev/ci_local.sh` | CI parity (`ruff check` + `pytest -n auto --cov`) | `--quick` (6.4s), `--lint` (0.05s) |
| `scripts/verify/check_drift.py` | Analyzes dependencies between uncommitted and committed files. 0 / 1-5 / 6-20 / >20 severity bands. | `--strict` (exit 1), `--silent` |
| `scripts/verify/pre_push_check.sh` | drift + lint + doc count + tests + privacy + commit format in one run | `--quick`, `--skip-tests` |
| `scripts/verify/check_atomic.sh` | Verifies each commit of a multi-commit branch on its own (default range `origin/main..HEAD`) | a range argument such as `HEAD~3..HEAD` |
| `.github/pull_request_template.md` | Checklist filled in automatically when a PR is created (drift · atomicity · scope) | — |

## Installing the git hooks

```bash
make setup-hooks     # included in `make setup` — pre-commit + pre-push symlinks
```

This installs `scripts/hooks/*` into `.git/hooks/` as symbolic links (`scripts/dev/install_hooks.sh`). The hook bodies live in the repo, so `git pull` brings in their updates. To bypass the hooks, use `git push --no-verify`.

Do not create `.git/hooks/pre-push` by hand. A manual install does not carry over to a new clone (#1070).

## Anti-patterns (5)

1. **Working tree drift accumulation**: when 20 or more uncommitted files pile up across several sessions, CI sees only the commits and fails. **Fix**: run `python scripts/verify/check_drift.py` at the start of each session.
2. **Atomic commit violation**: if commit 1 alone breaks the suite and commits 2-3 fill in the missing parts, bisect breaks. **Fix**: run `bash scripts/verify/check_atomic.sh` before the final push.
3. **CI roundtrip debugging**: a loop of push → wait 3 min → fail → fix. **Fix**: run `bash scripts/dev/ci_local.sh` before pushing.
4. **Scope creep**: "fix X" grows into "fix X + refactor Y + cleanup Z". **Fix**: 1 PR = 1 issue, ≤ 3 commits. New findings go on a new branch.
5. **Environment-only failures** (Linux CI vs macOS local): **Mitigation**: run `pytest -n auto` locally too, use `journal_mode=MEMORY` in `tests/conftest.py` (PR #93), and give integration tests explicit fixtures.

## Mapping the ~120 min wasted in earlier sessions

| Category | Wasted | Tool |
|---|---|---|
| Drift bugs (2× hits) | ~30 min | `check_drift.py` + `pre_push_check.sh` |
| Linux-only test pollution | ~25 min | `ci_local.sh` (parallelism parity) |
| CI roundtrip waiting | ~15 min | `ci_local.sh` (catches locally) |
| Atomicity reset | ~10 min | `check_atomic.sh` |
| Scope accumulation | ~40 min | PR template + `check_drift.py` |
| **Total addressable** | **~120 min** | **4 scripts + 1 PR template** |

## Overview maintenance

The [Overview implementation and operations guide](OVERVIEW.md) documents the home-screen Overview (`/`, formerly `/dashboard-next`): its layout, API contract, data refresh method, portfolio valuation and responsive-layout checks. The new data refresh API runs background collection and recalculation, and does not run adjudication ledger jobs.
